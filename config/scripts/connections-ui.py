#!/usr/bin/env python3
"""On-demand connection panel with live network and device lists."""
import atexit
import json
import os
import re
import shutil
import subprocess
import threading
from concurrent.futures import Future

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
gi.require_version('GdkPixbuf', '2.0')
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk, Pango
import connections as backend
import panel_dismiss


CSS = b'''
window, dialog { background: #151c28; color: #dbe5f5; }
* { font-family: "Sans"; font-size: 15px; }
.title { font-size: 26px; font-weight: bold; color: #eef5ff; }
.subtitle { color: #8ea3bd; font-size: 13px; }
.section { font-size: 17px; font-weight: bold; color: #ffffff; }
button { background: #233247; color: #dbe5f5; border: 1px solid #354961;
    border-radius: 8px; padding: 7px 14px; box-shadow: none; font-size: 14px; }
button:hover { background: #304761; }
button:checked, .primary { background: #2f6cb3; color: #ffffff; border-color: #4b88d4; }
button:disabled { opacity: 0.45; }
.wifi-lock { background: transparent; padding: 1px; }
button.danger { background: #7c2d2d; border-color: #a83d3d; color: #ffffff; }
button.danger:hover { background: #963838; }
button.icon-btn { padding: 6px 10px; border-radius: 8px; min-width: 36px; min-height: 36px; }
.details-arrow { font-size: 20px; padding: 2px 8px; border: none; background: transparent; color: #8ea3bd; }
.details-arrow:hover { background: #2d4664; color: #ffffff; }
entry { background: #1b2738; color: #dbe5f5; border: 1px solid #354961;
    border-radius: 8px; padding: 8px 12px; font-size: 14px; }
entry image { color: #8ea3bd; }
entry image:hover { color: #eef5ff; }
.qr-frame { background: #ffffff; border-radius: 12px; padding: 10px; }
.card-box { background: #1b2636; border: 1px solid #2a3b50; border-radius: 12px; padding: 14px; }
.badge-active { background: #1b4d3e; color: #4ade80; border-radius: 6px; padding: 2px 8px; font-size: 12px; font-weight: bold; }
.badge-inactive { background: #374151; color: #9ca3af; border-radius: 6px; padding: 2px 8px; font-size: 12px; }
list { background: transparent; }
row { background: #1c293b; border-radius: 10px; margin-bottom: 6px; padding: 8px 12px; border: 1px solid transparent; }
row:hover { background: #263b54; border-color: #3b5577; }
row:selected { background: #2d4664; }
row.home-row { padding: 4px 10px; margin-bottom: 2px; }
separator { background: #304258; min-height: 1px; }
switch { border-radius: 14px; }
scrollbar.vertical { margin: 2px 0 2px 4px; }
scrollbar.vertical slider { min-width: 6px; border-radius: 4px; }
'''


def label(text, style=None):
    widget = Gtk.Label(label=text, xalign=0)
    if style:
        widget.get_style_context().add_class(style)
    return widget


def password_display(password):
    """A read-only secret looks like text; editing uses a separate entry."""
    box = Gtk.Box(spacing=8)
    text = label('••••••••••••' if password else 'Not synced yet')
    text.set_can_focus(False)
    text.set_ellipsize(Pango.EllipsizeMode.END)
    text.set_max_width_chars(22)
    box.pack_start(text, True, True, 0)
    eye = Gtk.ToggleButton()
    eye.set_sensitive(bool(password))
    eye.set_tooltip_text('Lihat password')
    icon = Gtk.Image.new_from_icon_name('view-reveal-symbolic', Gtk.IconSize.BUTTON)
    eye.add(icon)
    def toggle(button):
        shown = button.get_active()
        text.set_text(password if shown else '••••••••••••')
        icon.set_from_icon_name('view-conceal-symbolic' if shown else 'view-reveal-symbolic', Gtk.IconSize.BUTTON)
        button.set_tooltip_text('Sembunyikan password' if shown else 'Lihat password')
    eye.connect('toggled', toggle)
    box.pack_end(eye, False, False, 0)
    return box


def toggle_entry_password(entry, *_):
    visible = entry.get_visibility()
    entry.set_visibility(not visible)
    entry.set_icon_from_icon_name(Gtk.EntryIconPosition.SECONDARY,
                                 'view-conceal-symbolic' if not visible else 'view-reveal-symbolic')


def qr_icon_pixbuf(size=18):
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="#dbe5f5" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <rect x="3" y="3" width="7" height="7"/>
      <rect x="14" y="3" width="7" height="7"/>
      <rect x="14" y="14" width="7" height="7"/>
      <rect x="3" y="14" width="7" height="7"/>
      <rect x="6" y="6" width="1" height="1" fill="#dbe5f5"/>
      <rect x="17" y="6" width="1" height="1" fill="#dbe5f5"/>
      <rect x="6" y="17" width="1" height="1" fill="#dbe5f5"/>
      <path d="M14 17h3v3"/>
    </svg>'''
    loader = GdkPixbuf.PixbufLoader.new_with_mime_type('image/svg+xml')
    loader.write(svg.encode('utf-8'))
    loader.close()
    return loader.get_pixbuf()


class Panel(Gtk.ApplicationWindow):
    def __init__(self, application):
        super().__init__(application=application, title='Connections')
        self.set_default_size(860, 520)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.set_resizable(True)
        self.set_decorated(False)
        self.set_border_width(18)
        self.set_keep_above(True)
        self.page = 'home'
        self.closed = False
        self.loading = False
        self.busy = False
        self.operation = None
        self.adb_session = None
        self.adb_devices_snapshot = []
        self.discovery = None
        self.discovery_lock = threading.Lock()
        self.snapshot = None
        self.connect('destroy', self.cleanup)
        atexit.register(self.stop_discovery)
        self.connect('key-press-event', self.keypress)
        panel_dismiss.listen(self, 'connections', GLib)
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        # Main vertical box - directly inside window, no outer ScrolledWindow to prevent double scrollbars!
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.add(box)

        # Header bar
        header = Gtk.Box(spacing=12)
        self.home_title = label('Connections', 'title')
        header.pack_start(self.home_title, False, False, 0)
        close = Gtk.Button.new_from_icon_name('window-close-symbolic', Gtk.IconSize.BUTTON)
        close.set_tooltip_text('Close · Esc')
        close.connect('clicked', lambda *_: self.close())
        header.pack_end(close, False, False, 0)
        self.cancel_action_button = Gtk.Button(label='Cancel')
        self.cancel_action_button.set_no_show_all(True)
        self.cancel_action_button.set_tooltip_text('Cancel operation · Esc')
        self.cancel_action_button.connect('clicked', lambda *_: self.cancel_action())
        header.pack_end(self.cancel_action_button, False, False, 0)

        self.back = Gtk.Button(label='‹  All connections')
        self.back.set_halign(Gtk.Align.START)
        self.back.connect('clicked', lambda *_: self.go_back())
        header.pack_start(self.back, False, False, 0)

        self.notice = label('', 'subtitle')
        self.notice.set_line_wrap(True)
        self.notice.set_max_width_chars(50)
        self.notice.set_halign(Gtk.Align.END)
        header.pack_end(self.notice, False, False, 0)
        box.pack_start(header, False, False, 0)

        # Secondary toolbar (for subpages)
        tools = Gtk.Box(spacing=10)
        self.page_tools = tools
        title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.heading = label('Choose a connection', 'section')
        title_box.pack_start(self.heading, False, False, 0)
        self.state = label('Loading…', 'subtitle')
        self.state.set_ellipsize(Pango.EllipsizeMode.END)
        self.state.set_max_width_chars(35)
        title_box.pack_start(self.state, False, False, 0)
        tools.pack_start(title_box, True, True, 0)

        self.search = Gtk.SearchEntry(placeholder_text='Search…')
        self.search.set_width_chars(16)
        self.search.connect('search-changed', lambda *_: self.listbox.invalidate_filter())
        tools.pack_start(self.search, False, False, 0)

        self.toolbar_actions = Gtk.Box(spacing=6)
        tools.pack_start(self.toolbar_actions, False, False, 0)

        self.power = Gtk.Switch()
        self.power.set_valign(Gtk.Align.CENTER)
        self.power.connect('state-set', self.toggle_power)
        tools.pack_end(self.power, False, False, 0)
        box.pack_start(tools, False, False, 0)

        # Central Stack containing pages
        self.stack = Gtk.Stack()
        self.stack.set_homogeneous(False)

        # 'home' page: List of connection categories (no circular grid icons)
        home_scroll = Gtk.ScrolledWindow()
        home_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.home_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.home_list.connect('row-activated', self.activate_row)
        home_scroll.add(self.home_list)
        self.stack.add_named(home_scroll, 'home')

        # 'list' page: Wi-Fi, Bluetooth, ADB devices with a single clean scrollbar
        list_scroll = Gtk.ScrolledWindow()
        list_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.listbox.set_filter_func(lambda row: self.search.get_text().casefold() in getattr(row, 'search_text', ''))
        self.listbox.connect('row-activated', self.activate_row)
        list_scroll.add(self.listbox)
        self.stack.add_named(list_scroll, 'list')

        # 'hotspot' page: 2-pane side-by-side unified view
        hotspot_scroll = Gtk.ScrolledWindow()
        hotspot_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.hotspot_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=24)
        self.hotspot_box.set_border_width(4)
        self.hotspot_box.set_valign(Gtk.Align.START)
        hotspot_scroll.add(self.hotspot_box)
        self.stack.add_named(hotspot_scroll, 'hotspot')

        adb_scroll = Gtk.ScrolledWindow()
        adb_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.adb_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=24)
        self.adb_box.set_border_width(4)
        self.adb_box.set_valign(Gtk.Align.START)
        adb_scroll.add(self.adb_box)
        self.stack.add_named(adb_scroll, 'adb')

        # 'prompt' page: Interactive inputs, QR dialogs, and selections
        self.prompt_scroll = Gtk.ScrolledWindow()
        self.prompt_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.prompt_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.prompt_box.set_border_width(8)
        self.prompt_scroll.add(self.prompt_box)
        self.stack.add_named(self.prompt_scroll, 'prompt')

        self.pending = None
        box.pack_start(self.stack, True, True, 0)

        # Hooks to backend functions
        backend.menu = self.menu
        backend.entry = self.entry
        backend.show_qr = self.show_qr
        backend.notify = lambda message: GLib.idle_add(self.set_notice, message)

        self.show_all()
        self.update_toolbar_actions()
        self.timer = GLib.timeout_add_seconds(4, self.refresh)
        self.refresh()

    def keypress(self, _, event):
        if event.keyval == Gdk.KEY_Escape:
            if self.pending:
                self.resolve_prompt(None)
            elif self.busy:
                self.cancel_action()
            elif self.page == 'home':
                self.close()
            else:
                self.select_page('home')
            return True
        return False

    def set_notice(self, message):
        if not self.closed:
            self.notice.set_text(message)
            self.notice.set_visible(bool(message))
        return False

    def activate_row(self, _, row):
        if getattr(row, 'target', None):
            self.select_page(row.target)
        elif getattr(row, 'callback', None):
            self.perform(row.callback)

    def select_page(self, page):
        if page == self.page:
            return
        self.page = page
        if page != 'adb' and self.adb_session:
            self.adb_session.stop()
        if page != 'bluetooth':
            self.stop_discovery()
        self.snapshot = None
        self.clear_rows()
        self.update_toolbar_actions()
        if page == 'hotspot':
            self.render_hotspot_page()
        else:
            if page == 'adb':
                self.render_adb_page(self.adb_devices_snapshot)
            self.refresh()

    def update_toolbar_actions(self):
        for child in self.toolbar_actions.get_children():
            self.toolbar_actions.remove(child)

        is_home = (self.page == 'home')
        self.home_title.set_visible(is_home)
        self.back.set_visible(not is_home)
        self.back.set_label('‹  All connections')
        self.page_tools.set_visible(not is_home)
        self.power.set_visible(self.page in ('wifi', 'bluetooth'))
        self.power.set_sensitive(False)
        self.search.set_visible(self.page in ('wifi', 'bluetooth'))
        self.search.set_text('')

        titles = {
            'home': 'Connections',
            'wifi': 'Wi-Fi Networks',
            'bluetooth': 'Bluetooth Devices',
            'adb': 'Wireless Debugging',
            'hotspot': 'Wi-Fi Hotspot'
        }
        self.heading.set_text(titles.get(self.page, 'Connections'))
        self.state.set_text('Loading…' if self.page not in ('home', 'hotspot') else '')
        self.state.set_visible(self.page not in ('home', 'hotspot', 'adb'))
        if self.page not in ('hotspot', 'adb'):
            self.resize_panel(860, 520)

        if self.page == 'wifi':
            self.search.set_placeholder_text('Search networks…')
            items = [
                ('view-refresh-symbolic', 'Rescan networks', lambda: backend.nm('device', 'wifi', 'rescan')),
                ('folder-saved-search-symbolic', 'Saved networks', backend.saved_wifi),
                ('preferences-system-symbolic', 'Network settings', lambda: backend.launch('nm-connection-editor')),
            ]
        elif self.page == 'bluetooth':
            self.search.set_placeholder_text('Search devices…')
            items = [
                ('view-refresh-symbolic', 'Rescan devices', self.restart_discovery),
                ('preferences-system-symbolic', 'Bluetooth settings', lambda: backend.launch('blueman-manager')),
            ]
        else:
            items = []

        for icon_name, tooltip, callback in items:
            btn = Gtk.Button()
            btn.get_style_context().add_class('icon-btn')
            btn.set_tooltip_text(tooltip)
            if icon_name == 'qr-icon':
                img = Gtk.Image.new_from_pixbuf(qr_icon_pixbuf(18))
            else:
                img = Gtk.Image.new_from_icon_name(icon_name, Gtk.IconSize.BUTTON)
                img.set_pixel_size(18)
            btn.add(img)
            btn.connect('clicked', lambda _, cb=callback: self.perform(cb))
            self.toolbar_actions.pack_start(btn, False, False, 0)

        self.toolbar_actions.show_all()
        if self.page in ('home', 'hotspot', 'adb'):
            self.stack.set_visible_child_name(self.page)
        else:
            self.stack.set_visible_child_name('list')

    def toggle_power(self, switch, state):
        if getattr(self, 'updating_power', False):
            return False
        if self.page == 'wifi':
            def turn_wifi():
                if not state:
                    for r in backend.rows('UUID,TYPE', 'connection', 'show', '--active'):
                        if len(r) >= 2 and r[1] == '802-11-wireless':
                            backend.run(['nmcli', 'connection', 'down', 'uuid', r[0]], timeout=10)
                    backend.nm('radio', 'wifi', 'off')
                else:
                    backend.nm('radio', 'wifi', 'on')
            self.perform(turn_wifi)
        elif self.page == 'bluetooth':
            self.perform(lambda: backend.bt('power', 'on' if state else 'off'))
        return True

    def start_discovery(self):
        with self.discovery_lock:
            if self.closed or self.page != 'bluetooth':
                return
            if self.discovery is None or self.discovery.poll() is not None:
                self.discovery = subprocess.Popen(['bluetoothctl'], stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True, env=backend.ENV)
                self.discovery.stdin.write('scan on\n')
                self.discovery.stdin.flush()

    def stop_discovery(self):
        with self.discovery_lock:
            process, self.discovery = self.discovery, None
            if process and process.poll() is None:
                try:
                    process.communicate('scan off\nquit\n', timeout=1)
                except (subprocess.TimeoutExpired, BrokenPipeError):
                    process.terminate()
                    try:
                        process.wait(timeout=1)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()

    def restart_discovery(self):
        self.stop_discovery()
        if 'Powered: yes' not in backend.bt('show'):
            raise RuntimeError('Enable Bluetooth to scan for devices.')
        self.start_discovery()

    def refresh(self):
        if self.closed:
            return False
        if self.loading or self.busy:
            return True
        if self.page == 'hotspot':
            self.render_hotspot_page()
            return True
        self.loading = True
        page = self.page
        def read():
            try:
                data = self.read_data(page)
                GLib.idle_add(self.render, page, data, None)
            except Exception as error:
                GLib.idle_add(self.render, page, None, str(error))
        threading.Thread(target=read, daemon=True).start()
        return True

    def read_data(self, page):
        if page == 'wifi':
            adapters = backend.wifi_client_devices()
            if not adapters:
                return (False, [], 'No Wi-Fi adapter available.', False)
            enabled = backend.nm('radio', 'wifi') == 'enabled'
            networks = backend.rows('IN-USE,SSID,SIGNAL,SECURITY,BSSID,DEVICE', 'device', 'wifi', 'list', '--rescan', 'auto') if enabled else []
            client_names = {r[0] for r in adapters}
            networks = [r for r in networks if len(r) == 6 and r[5] in client_names]
            unique = {}
            for row in sorted((r for r in networks if len(r) == 6 and r[1]), key=lambda r: (r[0] != '*', -int(r[2] or 0))):
                unique.setdefault((row[1], row[3], row[5]), row)
            networks = list(unique.values())
            message = f'{len(networks)} networks · updates automatically' if networks else 'No networks found. Try Rescan.'
            portals = {row[5] for row in networks if row[0] == '*' and backend.wifi_needs_login(row[5])}
            return (enabled, networks, message if enabled else 'Wi-Fi is off. Turn it on to see networks.', True, portals)
        if page == 'bluetooth':
            controller = backend.bt('show')
            powered = 'Powered: yes' in controller
            if powered:
                self.start_discovery()
            else:
                self.stop_discovery()
            devices = []
            for line in backend.bt('devices').splitlines():
                match = re.match(r'Device ([0-9A-Fa-f:]{17}) (.*)', line)
                if not match:
                    continue
                address, name = match.groups()
                state = backend.bt('info', address)
                connected, paired = 'Connected: yes' in state, 'Paired: yes' in state
                status = 'Connected' if connected else 'Paired' if paired else 'Detected'
                battery = re.search(r'Battery Percentage:.*\((\d+)\)', state)
                if battery:
                    status += f' · Battery {battery[1]}%'
                devices.append((address, name, connected, paired, status))
            devices.sort(key=lambda r: (not r[2], not r[3],
                bool(re.fullmatch(r'(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}', r[1])), r[1].casefold()))
            scanning = 'Discovering: yes' in controller
            message = 'Connected' if any(r[2] for r in devices) else 'Scanning for devices…' if scanning else 'Ready to connect'
            return (powered, devices, message if powered else 'Bluetooth is off. Turn it on to see devices.', True)
        if page == 'adb':
            return backend.adb_devices()
        adapters = backend.devices()
        wired = [r for r in adapters if r[1] == 'ethernet']
        active = next((r[3] for r in backend.wifi_client_devices() if r[2] == 'connected'), '')
        connected_bt = backend.run(['bluetoothctl', 'devices', 'Connected'], timeout=5)
        bt_name = ', '.join(line.split(' ', 2)[2] for line in connected_bt.stdout.splitlines() if line.startswith('Device ') and len(line.split(' ', 2)) == 3)
        hotspot_info = backend.get_hotspot_status()
        hotspot_active = 'Active' if hotspot_info['active'] else ''
        return ([], wired, active, '', bt_name, hotspot_active)

    def clear_rows(self):
        for row in self.listbox.get_children():
            self.listbox.remove(row)
        for row in self.home_list.get_children():
            self.home_list.remove(row)

    def add_home_row(self, title, subtitle, icon, callback=None, target=None):
        row = Gtk.ListBoxRow(activatable=True)
        row.callback = callback
        row.target = target
        row.get_style_context().add_class('home-row')

        box = Gtk.Box(spacing=12)
        box.set_border_width(3)

        icon_img = Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.LARGE_TOOLBAR)
        icon_img.set_pixel_size(24)
        box.pack_start(icon_img, False, False, 2)

        text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        title_lbl = label(title, 'section')
        text_box.pack_start(title_lbl, False, False, 0)
        sub_lbl = label(subtitle, 'subtitle')
        text_box.pack_start(sub_lbl, False, False, 0)
        box.pack_start(text_box, True, True, 0)

        chevron = label('›', 'subtitle')
        chevron.set_valign(Gtk.Align.CENTER)
        box.pack_end(chevron, False, False, 4)

        row.add(box)
        self.home_list.add(row)

    def add_row(self, title, subtitle, icon, callback=None, badge='', target=None, detail=None, disconnect_callback=None, locked=False, login=False, container=None):
        row = Gtk.ListBoxRow(activatable=callback is not None or target is not None)
        row.target = target
        row.callback = callback
        row.search_text = (title + ' ' + subtitle).casefold()

        box = Gtk.Box(spacing=12)
        box.set_border_width(4)
        image = Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.LARGE_TOOLBAR)
        image.set_pixel_size(28)
        if locked:
            wifi_icon = Gtk.Overlay()
            wifi_icon.set_valign(Gtk.Align.CENTER)
            wifi_icon.set_size_request(34, -1)
            image.set_halign(Gtk.Align.START)
            wifi_icon.add(image)
            lock = Gtk.Image.new_from_icon_name('changes-prevent-symbolic', Gtk.IconSize.BUTTON)
            lock.set_pixel_size(12)
            lock.set_halign(Gtk.Align.END)
            lock.set_valign(Gtk.Align.END)
            lock.get_style_context().add_class('wifi-lock')
            lock.set_tooltip_text('Password-protected network')
            wifi_icon.add_overlay(lock)
            box.pack_start(wifi_icon, False, False, 0)
        else:
            box.pack_start(image, False, False, 0)

        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        name = label(backend.clean(title), 'section')
        name.set_ellipsize(Pango.EllipsizeMode.END)
        name.set_max_width_chars(35)
        name.set_tooltip_text(backend.clean(title))
        text.pack_start(name, False, False, 0)

        description = label(subtitle, 'subtitle')
        description.set_line_wrap(True)
        description.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
        description.set_max_width_chars(50)
        text.pack_start(description, False, False, 0)
        box.pack_start(text, True, True, 0)

        side = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        side.set_valign(Gtk.Align.CENTER)
        if login:
            login_button = Gtk.Button(label='Login')
            login_button.set_tooltip_text('Open the network login page in your browser')
            login_button.connect('clicked', lambda *_: backend.open_wifi_login())
            side.pack_start(login_button, False, False, 0)
        if badge and not detail:
            side.pack_start(label(badge, 'badge-active'), False, False, 0)

        if disconnect_callback:
            disconnect = Gtk.Button(label='Disconnect')
            disconnect.set_tooltip_text('Disconnect this device; keep its pairing')
            disconnect.connect('clicked', lambda *_: self.perform(disconnect_callback))
            side.pack_start(disconnect, False, False, 0)

        if detail:
            arrow = Gtk.Button(label='›')
            arrow.get_style_context().add_class('details-arrow')
            arrow.set_size_request(38, 38)
            arrow.set_tooltip_text('Open details')
            arrow.connect('clicked', lambda *_: self.perform(detail))
            side.pack_start(arrow, False, False, 0)

        box.pack_end(side, False, False, 0)
        row.add(box)
        (container if container is not None else self.listbox).add(row)

    def render(self, page, data, error):
        self.loading = False
        if self.closed or self.busy:
            return False
        if page != self.page:
            self.refresh()
            return False
        if error:
            self.state.set_text(error)
            if page == 'adb':
                self.set_notice(error)
            self.power.set_sensitive(False)
            return False
        if data == self.snapshot:
            return False
        self.snapshot = data
        self.clear_rows()

        if page in ('wifi', 'bluetooth'):
            powered, items, message, available = data[:4]
            portals = data[4] if len(data) > 4 else set()
            self.updating_power = True
            self.power.set_active(powered)
            self.power.set_state(powered)
            self.updating_power = False
            self.power.set_sensitive(available and not self.busy)
            self.state.set_text(message)
            for item in items:
                if page == 'wifi':
                    active, ssid, strength, security, _, device = item
                    subtitle = ('Connected' if active == '*' else 'Available') + ' · ' + (security or 'Open network')
                    login = active == '*' and device in portals
                    if login:
                        subtitle += ' · Login required'
                    level = 'excellent' if int(strength) >= 80 else 'good' if int(strength) >= 55 else 'ok' if int(strength) >= 30 else 'weak'
                    self.add_row(ssid, subtitle, f'network-wireless-signal-{level}-symbolic',
                                 callback=lambda item=item: backend.connect_wifi(item),
                                 badge='●' if active == '*' else '',
                                 detail=lambda item=item: backend.wifi_details(item),
                                 locked=backend.wifi_requires_password(security), login=login)
                else:
                    address, name, connected, paired, status = item
                    self.add_row(name, status, 'bluetooth-symbolic',
                                 callback=lambda item=item: backend.connect_bluetooth(item),
                                 badge='●' if connected else '',
                                 detail=lambda item=item: backend.bluetooth_details(item))
            if not items:
                self.add_row('No networks found' if page == 'wifi' else 'No devices found',
                             'Turn Wi-Fi on or run Rescan.' if page == 'wifi' else 'Turn Bluetooth on and put device in pairing mode.',
                             'network-wireless-symbolic' if page == 'wifi' else 'bluetooth-symbolic', None)
        elif page == 'adb':
            self.adb_devices_snapshot = data
            self.render_adb_page(data)
        else:
            # Home page - Clean list
            aps, wired, active, error, bt_name, *rest = data
            eth_status, eth_sub = backend.get_ethernet_status()
            hs_info = backend.get_hotspot_status()

            wifi_sub = f'Connected to "{active}"' if active else 'Available'
            bt_sub = f'Connected: {bt_name}' if bt_name else 'Ready to connect'
            hs_sub = f'Active · "{hs_info["ssid"]}"' if hs_info['active'] else 'Off'

            rows_def = [
                ('Wi-Fi', wifi_sub, 'network-wireless-symbolic', None, 'wifi'),
                ('Bluetooth', bt_sub, 'bluetooth-symbolic', None, 'bluetooth'),
                ('Ethernet', eth_sub, 'network-wired-symbolic', backend.ethernet, None),
                ('Hotspot', hs_sub, 'network-wireless-hotspot-symbolic', None, 'hotspot'),
                ('VPN', 'Proton VPN · Connect & choose servers', 'network-vpn-symbolic', backend.vpn, None),
                ('Airplane Mode', 'Toggle all wireless radios', 'airplane-mode-symbolic', backend.airplane, None),
                ('Wireless Debugging', 'Android ADB over Wi-Fi (QR code / pairing code)', 'phone-symbolic', None, 'adb'),
            ]

            for title, subtitle, icon, cb, target in rows_def:
                self.add_home_row(title, subtitle, icon, callback=cb, target=target)

            self.home_list.show_all()
            if error:
                self.set_notice(error)

        self.listbox.show_all()
        return False

    def start_adb_pairing(self):
        if self.busy or (self.adb_session and self.adb_session.snapshot()['active']):
            return
        try:
            self.adb_session = backend.AdbQrSession(on_change=lambda: GLib.idle_add(self.adb_pairing_changed))
            self.adb_session.start()
            self.render_adb_page(self.adb_devices_snapshot)
        except Exception as error:
            self.set_notice(str(error))

    def adb_pairing_changed(self):
        if not self.closed and self.page == 'adb' and not self.pending and not self.busy:
            if self.adb_session.snapshot()['state'] == 'connected':
                self.snapshot = None
                self.refresh()
            else:
                self.render_adb_page(self.adb_devices_snapshot)
        return False

    def render_adb_page(self, devices):
        session = self.adb_session.snapshot() if self.adb_session else {'active': False, 'svg': None, 'message': ''}
        if session.get('state') == 'connected' and not any(wireless and state == 'device' and
                (not session.get('serial') or serial == session['serial']) for serial, _, state, wireless in devices):
            session = {**session, 'state': 'disconnected', 'message': 'The previous device is no longer connected. Check Wireless debugging on your phone, then reconnect with its current IP:port.'}
        snapshot = (devices, session)
        if getattr(self, 'adb_snapshot', None) == snapshot and self.adb_box.get_children():
            return
        self.adb_snapshot = snapshot
        for child in self.adb_box.get_children():
            self.adb_box.remove(child)
        self.cancel_action_button.hide()
        svg = session['svg']
        if svg:
            loader = GdkPixbuf.PixbufLoader.new_with_mime_type('image/svg+xml')
            loader.write(svg.encode())
            loader.close()
            image = Gtk.Image.new_from_pixbuf(loader.get_pixbuf().scale_simple(240, 240, GdkPixbuf.InterpType.NEAREST))
            left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
            left.set_size_request(280, -1)
            left.set_valign(Gtk.Align.START)
            frame = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            frame.get_style_context().add_class('qr-frame')
            frame.set_size_request(260, 260)
            frame.pack_start(image, True, True, 0)
            left.pack_start(frame, False, False, 0)
            hint = label('Scan from Wireless debugging on your phone', 'subtitle')
            hint.set_xalign(.5)
            left.pack_start(hint, False, False, 0)
            self.adb_box.pack_start(left, False, False, 0)

        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        right.set_hexpand(True)
        status = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        status.get_style_context().add_class('card-box')
        status.pack_start(label('Pair an Android device', 'section'), False, False, 0)
        instructions = label(session['message'] or 'Connect your phone and laptop to the same Wi-Fi. Scan the QR code from Wireless debugging to pair and connect. Click a connected device when you want to open its screen.', 'subtitle')
        instructions.set_line_wrap(True)
        instructions.set_max_width_chars(46)
        status.pack_start(instructions, False, False, 0)
        pair = Gtk.Button(label='Stop pairing' if session['active'] else 'Start QR pairing')
        pair.get_style_context().add_class('danger' if session['active'] else 'primary')
        pair.connect('clicked', lambda *_: self.adb_session.stop() if session['active'] else self.start_adb_pairing())
        status.pack_start(pair, False, False, 0)
        if session.get('state') in ('paired', 'timeout', 'error', 'disconnected'):
            alternatives = Gtk.Box(spacing=8)
            for text, callback in [('Pair with code', backend.adb_pair), ('Connect IP:port', backend.adb_connect)]:
                button = Gtk.Button(label=text)
                button.connect('clicked', lambda _, cb=callback: self.perform(cb))
                alternatives.pack_start(button, True, True, 0)
            status.pack_start(alternatives, False, False, 0)
        right.pack_start(status, False, False, 0)

        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        card.get_style_context().add_class('card-box')
        card.pack_start(label('Connected devices', 'section'), False, False, 0)
        card.pack_start(label('Click a connected device to open its screen.', 'subtitle'), False, False, 0)
        listing = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        listing.connect('row-activated', self.activate_row)
        for item in devices:
            serial, name, state, wireless = item
            description = {'device': 'Connected', 'offline': 'Offline', 'unauthorized': 'Waiting for approval on your phone'}.get(state, state)
            self.add_row(name, description + (' · Wireless' if wireless else ' · USB'), 'phone-symbolic',
                         callback=(lambda serial=serial: backend.start_scrcpy(serial)) if state == 'device' else None,
                         disconnect_callback=(lambda serial=serial: backend.disconnect_adb_device(serial)) if wireless else None,
                         container=listing)
        if devices:
            card.pack_start(listing, False, False, 0)
        else:
            card.pack_start(label('No devices connected yet.', 'subtitle'), False, False, 0)
        right.pack_start(card, False, False, 0)
        self.adb_box.pack_start(right, True, True, 0)
        self.adb_box.show_all()
        self.resize_panel(860 if svg else 620, 430)

    def render_hotspot_page(self):
        info = backend.get_hotspot_status()
        info['needs_band_switch'] = backend.hotspot_needs_band_switch(info)
        if getattr(self, 'hotspot_snapshot', None) == info and self.hotspot_box.get_children():
            return
        self.hotspot_snapshot = dict(info)
        for child in self.hotspot_box.get_children():
            self.hotspot_box.remove(child)
        self.state.set_text('')
        ssid = info['ssid']
        pwd = info['password']
        is_active = info['active']

        # Left Pane: Crisp 1:1 Square QR code
        left_pane = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        left_pane.set_valign(Gtk.Align.CENTER)
        left_pane.set_halign(Gtk.Align.CENTER)
        left_pane.set_size_request(280, -1)

        svg = None
        if backend.hotspot_qr_available(info):
            svg = backend.qr_to_svg(backend.wifi_qr_text(ssid, pwd, 'WPA'))
        if is_active and info.get('credentials_mismatch'):
            left_pane.pack_start(label('The QR code is available after syncing credentials.', 'subtitle'), False, False, 0)
            self.set_notice('The panel credentials differ from the active hotspot. Sync before sharing its QR code.')
        if svg:
            try:
                loader = GdkPixbuf.PixbufLoader.new_with_mime_type('image/svg+xml')
                loader.write(svg.encode('utf-8'))
                loader.close()
                pixbuf = loader.get_pixbuf()
                if pixbuf:
                    pixbuf = pixbuf.scale_simple(240, 240, GdkPixbuf.InterpType.NEAREST)
                    img = Gtk.Image.new_from_pixbuf(pixbuf)
                    qr_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
                    qr_card.get_style_context().add_class('qr-frame')
                    qr_card.set_size_request(260, 260)
                    qr_card.set_valign(Gtk.Align.CENTER)
                    qr_card.set_halign(Gtk.Align.CENTER)
                    qr_card.pack_start(img, True, True, 0)
                    left_pane.pack_start(qr_card, False, False, 0)
            except Exception:
                pass

        if svg:
            qr_hint = label('Scan with phone to join Hotspot', 'subtitle')
            qr_hint.set_xalign(0.5)
            left_pane.pack_start(qr_hint, False, False, 0)
            self.hotspot_box.pack_start(left_pane, False, False, 0)

        # Right Pane: Status & Credentials
        right_pane = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        right_pane.set_hexpand(True)
        right_pane.set_valign(Gtk.Align.START)

        status_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        status_card.get_style_context().add_class('card-box')

        status_title = label('Wi-Fi Hotspot', 'section')
        status_card.pack_start(status_title, False, False, 0)

        note = label('Share your laptop\'s internet connection with other devices.', 'subtitle')
        note.set_line_wrap(True)
        note.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
        status_card.pack_start(note, False, False, 0)
        if is_active and info.get('credentials_mismatch'):
            sync = Gtk.Button(label='Sync hotspot password')
            sync.connect('clicked', lambda *_: self.perform(backend.sync_native_hotspot_credentials))
            status_card.pack_start(sync, False, False, 0)
        if info['needs_band_switch']:
            status_card.pack_start(label('The current Wi-Fi channel does not support hotspot mode. Switch to 2.4 GHz to continue.', 'subtitle'), False, False, 0)
            use24 = Gtk.Button(label='Use 2.4 GHz Wi-Fi')
            use24.set_tooltip_text('Reconnect to the same Wi-Fi network on 2.4 GHz. The connection will pause briefly.')
            use24.connect('clicked', lambda *_: self.perform(backend.use_24ghz_uplink))
            status_card.pack_start(use24, False, False, 0)

        toggle_btn = Gtk.Button(label='Turn Off Hotspot' if is_active else 'Turn On Hotspot')
        if is_active:
            toggle_btn.get_style_context().add_class('danger')
        else:
            toggle_btn.get_style_context().add_class('primary')

        def on_toggle_hotspot(*_):
            if is_active:
                self.perform(backend.turn_off_hotspot)
            else:
                self.perform(backend.turn_on_hotspot)
        toggle_btn.connect('clicked', on_toggle_hotspot)
        status_card.pack_start(toggle_btn, False, False, 4)
        right_pane.pack_start(status_card, False, False, 0)

        # Credentials card
        cred_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        cred_card.get_style_context().add_class('card-box')

        cred_header = Gtk.Box(spacing=10)
        cred_title = label('Hotspot Credentials', 'section')
        cred_header.pack_start(cred_title, True, True, 0)

        edit_icon_btn = Gtk.Button()
        edit_icon_btn.get_style_context().add_class('icon-btn')
        edit_icon_btn.set_tooltip_text('Edit name & password')
        edit_img = Gtk.Image.new_from_icon_name('document-edit-symbolic', Gtk.IconSize.BUTTON)
        edit_img.set_pixel_size(18)
        edit_icon_btn.add(edit_img)
        cred_header.pack_end(edit_icon_btn, False, False, 0)
        cred_card.pack_start(cred_header, False, False, 0)

        # View box
        view_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        ssid_row = Gtk.Box(spacing=10)
        ssid_lbl = label('Name (SSID):', 'subtitle')
        ssid_lbl.set_size_request(90, -1)
        ssid_row.pack_start(ssid_lbl, False, False, 0)
        ssid_val = label(ssid, 'section')
        ssid_val.set_selectable(True)
        ssid_row.pack_start(ssid_val, True, True, 0)
        view_box.pack_start(ssid_row, False, False, 0)

        pwd_row = Gtk.Box(spacing=10)
        pwd_lbl = label('Password:', 'subtitle')
        pwd_lbl.set_size_request(90, -1)
        pwd_row.pack_start(pwd_lbl, False, False, 0)
        pwd_row.pack_start(password_display(pwd), True, True, 0)

        copy_btn = Gtk.Button(label='Copy')
        copy_btn.set_sensitive(bool(pwd))
        def on_copy_pwd(*_):
            cb = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
            cb.set_text(pwd, -1)
            cb.store()
            if shutil.which('wl-copy'):
                backend.run(['wl-copy'], data=pwd)
            self.set_notice('Hotspot password copied.')
        copy_btn.connect('clicked', on_copy_pwd)
        pwd_row.pack_start(copy_btn, False, False, 0)
        view_box.pack_start(pwd_row, False, False, 0)
        cred_card.pack_start(view_box, False, False, 0)

        # Edit box (hidden initially, with Save and Cancel buttons)
        edit_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        edit_box.set_no_show_all(True)
        edit_box.hide()

        edit_title = label('Edit Hotspot Settings', 'section')
        edit_box.pack_start(edit_title, False, False, 0)

        edit_ssid_row = Gtk.Box(spacing=8)
        edit_ssid_lbl = label('Name:', 'subtitle')
        edit_ssid_lbl.set_size_request(70, -1)
        edit_ssid_row.pack_start(edit_ssid_lbl, False, False, 0)
        edit_ssid_entry = Gtk.Entry()
        edit_ssid_entry.set_text(ssid)
        edit_ssid_entry.set_max_length(32)
        edit_ssid_row.pack_start(edit_ssid_entry, True, True, 0)
        edit_box.pack_start(edit_ssid_row, False, False, 0)

        edit_pwd_row = Gtk.Box(spacing=8)
        edit_pwd_lbl = label('Password:', 'subtitle')
        edit_pwd_lbl.set_size_request(70, -1)
        edit_pwd_row.pack_start(edit_pwd_lbl, False, False, 0)
        edit_pwd_entry = Gtk.Entry()
        edit_pwd_entry.set_text(pwd)
        edit_pwd_entry.set_visibility(False)
        edit_pwd_entry.set_max_length(63)
        edit_pwd_entry.set_icon_from_icon_name(Gtk.EntryIconPosition.SECONDARY, 'view-reveal-symbolic')
        edit_pwd_entry.set_icon_activatable(Gtk.EntryIconPosition.SECONDARY, True)
        edit_pwd_entry.connect('icon-press', toggle_entry_password)
        edit_pwd_row.pack_start(edit_pwd_entry, True, True, 0)
        edit_box.pack_start(edit_pwd_row, False, False, 0)

        err_label = label('', 'subtitle')
        err_label.get_style_context().add_class('danger')
        edit_box.pack_start(err_label, False, False, 0)

        action_btns = Gtk.Box(spacing=8)
        save_btn = Gtk.Button(label='Save')
        save_btn.get_style_context().add_class('primary')
        cancel_btn = Gtk.Button(label='Cancel')

        def on_save_clicked(*_):
            new_s = edit_ssid_entry.get_text().strip()
            new_p = edit_pwd_entry.get_text()
            if not (1 <= len(new_s.encode()) <= 32):
                err_label.set_text('SSID must be 1–32 characters.')
                err_label.show()
                return
            if not (8 <= len(new_p) <= 63):
                err_label.set_text('Password must be 8–63 characters.')
                err_label.show()
                return
            err_label.hide()
            def do_save():
                backend.save_hotspot_config(new_s, new_p)
                GLib.idle_add(self.set_notice, f'Hotspot configured: "{new_s}".')
                GLib.idle_add(self.render_hotspot_page)
            self.perform(do_save)

        def on_cancel_clicked(*_):
            edit_ssid_entry.set_text(ssid)
            edit_pwd_entry.set_text(pwd)
            err_label.hide()
            edit_box.hide()
            cred_header.show()
            view_box.show()

        def on_edit_clicked(*_):
            cred_header.hide()
            view_box.hide()
            edit_box.show()
            edit_ssid_entry.grab_focus()

        edit_icon_btn.connect('clicked', on_edit_clicked)
        save_btn.connect('clicked', on_save_clicked)
        cancel_btn.connect('clicked', on_cancel_clicked)
        action_btns.pack_start(save_btn, True, True, 0)
        action_btns.pack_start(cancel_btn, True, True, 0)
        edit_box.pack_start(action_btns, False, False, 4)
        cred_card.pack_start(edit_box, False, False, 0)

        right_pane.pack_start(cred_card, False, False, 0)
        self.hotspot_box.pack_start(right_pane, True, True, 0)
        self.hotspot_box.show_all()
        width, height = (860, 400) if svg else (620, 360)
        self.resize_panel(width, height)

    def resize_panel(self, width, height):
        self.set_default_size(width, height)
        self.resize(width, height)
        previous = getattr(self, 'resize_timer', None)
        if previous:
            GLib.source_remove(previous)
        def apply_size():
            self.resize_timer = None
            if self.closed or not self.get_mapped() or not os.environ.get('HYPRLAND_INSTANCE_SIGNATURE'):
                return False
            try:
                result = subprocess.run(['hyprctl', '-j', 'clients'], capture_output=True, text=True, timeout=2)
                client = next((c for c in json.loads(result.stdout) if c.get('pid') == os.getpid() and c.get('title') == 'Connections'), None)
                if client:
                    if not client.get('floating'):
                        subprocess.run(['hyprctl', 'dispatch', f'hl.dsp.window.float({{action="enable", window="address:{client["address"]}"}})'],
                                       capture_output=True, timeout=2)
                    subprocess.run(['hyprctl', 'dispatch',
                                    f'hl.dsp.window.resize({{x={width}, y={height}, relative=false, window="address:{client["address"]}"}})'],
                                   capture_output=True, timeout=2)
                    subprocess.run(['hyprctl', 'dispatch', f'hl.dsp.window.center({{window="address:{client["address"]}"}})'],
                                   capture_output=True, timeout=2)
            except (OSError, ValueError, subprocess.TimeoutExpired):
                pass
            return False
        self.resize_timer = GLib.timeout_add(60, apply_size)

    def perform(self, callback):
        if self.busy or self.closed:
            return
        self.busy = True
        operation = self.operation = backend.Operation()
        self.cancel_action_button.set_sensitive(True)
        self.cancel_action_button.show()
        app = self.get_application()
        app.hold()
        self.listbox.set_sensitive(False)
        self.home_list.set_sensitive(False)
        self.hotspot_box.set_sensitive(False)
        self.adb_box.set_sensitive(False)
        self.power.set_sensitive(False)
        self.back.set_sensitive(False)
        self.set_notice('Working…')
        def work():
            error = None
            backend.OPERATION.current = operation
            try:
                callback()
            except Exception as exc:
                error = str(exc)
            finally:
                if operation.cancelled.is_set():
                    error = 'Operation cancelled.'
                backend.OPERATION.current = None
                operation.close()
            GLib.idle_add(self.finish_action, error, app)
        threading.Thread(target=work, daemon=True).start()

    def cancel_action(self):
        if self.operation and self.busy:
            self.operation.cancel()
            self.next_action = None
            self.resolve_prompt(None)
            self.cancel_action_button.set_sensitive(False)
            self.set_notice('Cancelling…')

    def dismiss_on_outside_click(self):
        if not self.busy:
            self.close()

    def finish_action(self, error, app):
        app.release()
        if self.closed:
            return False
        self.busy = False
        self.operation = None
        self.cancel_action_button.hide()
        self.snapshot = None
        self.listbox.set_sensitive(True)
        self.home_list.set_sensitive(True)
        self.hotspot_box.set_sensitive(True)
        self.adb_box.set_sensitive(True)
        self.back.set_sensitive(True)
        self.update_toolbar_actions()
        self.set_notice(error or '')
        self.refresh()
        next_action = getattr(self, 'next_action', None)
        self.next_action = None
        if next_action:
            GLib.idle_add(self.perform, next_action)
        return False

    def go_back(self):
        if self.pending:
            self.resolve_prompt(None)
        elif not self.busy:
            self.select_page('home')

    def resolve_prompt(self, value):
        future, self.pending = self.pending, None
        if future and not future.done():
            self.prompt_box.set_sensitive(False)
            self.back.set_sensitive(False)
            self.cancel_action_button.set_visible(bool(self.busy and self.operation and not self.operation.cancelled.is_set()))
            future.set_result(value)

    def show_prompt(self, future, title, message, options=None, password=False, qr_data=None):
        if self.closed or (self.operation and self.operation.cancelled.is_set()):
            future.set_result(None)
            return False
        self.pending = future
        # Details and forms already have Back/Cancel controls. The header's
        # cancel button is for work in progress, including live ADB pairing.
        self.cancel_action_button.hide()
        for child in self.prompt_box.get_children():
            self.prompt_box.remove(child)

        self.heading.set_text(backend.clean(title))
        self.home_title.hide()
        self.page_tools.show()
        self.heading.set_visible(True)
        self.heading.set_ellipsize(Pango.EllipsizeMode.END)
        self.heading.set_max_width_chars(45)
        self.back.set_label('‹  Back')
        self.back.set_visible(True)
        self.back.set_sensitive(True)
        self.power.hide()
        self.search.hide()
        self.state.hide()
        for child in self.toolbar_actions.get_children():
            self.toolbar_actions.remove(child)
        self.set_notice('')

        if qr_data:
            is_adb = (qr_data.get('security') == 'ADB')
            qr_layout = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=24)
            qr_layout.set_valign(Gtk.Align.CENTER)
            qr_layout.set_halign(Gtk.Align.CENTER)

            # Left side: Crisp 1:1 Square QR Card
            left_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
            left_box.set_valign(Gtk.Align.CENTER)
            left_box.set_halign(Gtk.Align.CENTER)
            left_box.set_size_request(280, -1)

            svg = qr_data.get('svg')
            if svg:
                try:
                    loader = GdkPixbuf.PixbufLoader.new_with_mime_type('image/svg+xml')
                    loader.write(svg.encode('utf-8'))
                    loader.close()
                    pixbuf = loader.get_pixbuf()
                    if pixbuf:
                        pixbuf = pixbuf.scale_simple(240, 240, GdkPixbuf.InterpType.NEAREST)
                        img = Gtk.Image.new_from_pixbuf(pixbuf)
                        qr_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
                        qr_card.get_style_context().add_class('qr-frame')
                        qr_card.set_size_request(260, 260)
                        qr_card.set_valign(Gtk.Align.CENTER)
                        qr_card.set_halign(Gtk.Align.CENTER)
                        qr_card.pack_start(img, True, True, 0)
                        left_box.pack_start(qr_card, False, False, 0)
                except Exception:
                    pass

            qr_hint = label('Pair with Developer Options' if is_adb else 'Scan with phone camera to connect', 'subtitle')
            qr_hint.set_xalign(0.5)
            left_box.pack_start(qr_hint, False, False, 0)
            qr_layout.pack_start(left_box, False, False, 0)

            # Right side: Details & instructions
            info_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
            info_box.set_valign(Gtk.Align.CENTER)
            info_box.set_hexpand(True)

            ssid_row = Gtk.Box(spacing=10)
            ssid_lbl = label('Service:' if is_adb else 'Network:', 'subtitle')
            ssid_lbl.set_size_request(80, -1)
            ssid_row.pack_start(ssid_lbl, False, False, 0)
            ssid_val = label(backend.clean(qr_data.get('ssid', '')))
            ssid_val.set_selectable(True)
            ssid_row.pack_start(ssid_val, True, True, 0)
            info_box.pack_start(ssid_row, False, False, 0)

            pwd = qr_data.get('password') or ''
            if pwd:
                pwd_row = Gtk.Box(spacing=10)
                pwd_lbl = label('QR secret:' if is_adb else 'Password:', 'subtitle')
                pwd_lbl.set_size_request(80, -1)
                pwd_row.pack_start(pwd_lbl, False, False, 0)

                pwd_row.pack_start(password_display(pwd), True, True, 0)

                copy_btn = Gtk.Button(label='Copy')
                def copy_pwd_clicked(*_):
                    cb = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
                    cb.set_text(pwd, -1)
                    cb.store()
                    if shutil.which('wl-copy'):
                        backend.run(['wl-copy'], data=pwd)
                    self.set_notice('Copied to clipboard.')
                copy_btn.connect('clicked', copy_pwd_clicked)
                pwd_row.pack_start(copy_btn, False, False, 0)
                info_box.pack_start(pwd_row, False, False, 0)
            else:
                open_row = label('Open network (no password required)', 'subtitle')
                info_box.pack_start(open_row, False, False, 0)

            if is_adb:
                warn_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
                warn_box.get_style_context().add_class('card-box')
                w_title = label('How to scan on phone:', 'section')
                warn_box.pack_start(w_title, False, False, 0)
                w_desc = label('1. Connect the phone and laptop to the same network.\n2. Open Developer options → Wireless debugging.\n3. Choose Pair device with QR code, then scan.\nWait for the Android connected message above.', 'subtitle')
                w_desc.set_line_wrap(True)
                w_desc.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
                warn_box.pack_start(w_desc, False, False, 0)
                info_box.pack_start(warn_box, False, False, 0)

                fallback_btn = Gtk.Button(label='Pair with code instead…')
                def on_fallback(*_):
                    self.next_action = backend.adb_pair
                    self.resolve_prompt(None)
                fallback_btn.connect('clicked', on_fallback)
                info_box.pack_start(fallback_btn, False, False, 0)

            done_btn = Gtk.Button(label='Done')
            done_btn.connect('clicked', lambda *_: self.resolve_prompt(None))
            info_box.pack_start(done_btn, False, False, 4)

            qr_layout.pack_start(info_box, True, True, 0)
            self.prompt_box.pack_start(qr_layout, True, True, 0)
        else:
            for line in message.splitlines():
                if not line.strip():
                    continue
                if ': ' in line:
                    key, value = line.split(': ', 1)
                    row = Gtk.Box(spacing=12)
                    key_label = label(key, 'subtitle')
                    key_label.set_size_request(120, -1)
                    key_label.set_valign(Gtk.Align.START)
                    row.pack_start(key_label, False, False, 0)
                    value_label = label(backend.clean(value))
                    value_label.set_line_wrap(True)
                    value_label.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
                    value_label.set_max_width_chars(45)
                    value_label.set_selectable(True)
                    row.pack_start(value_label, True, True, 0)
                else:
                    row = label(backend.clean(line), 'subtitle')
                    row.set_line_wrap(True)
                    row.set_max_width_chars(60)
                    row.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
                self.prompt_box.pack_start(row, False, False, 0)
                self.prompt_box.pack_start(Gtk.Separator(), False, False, 0)

            field = None
            if options is None:
                field = Gtk.Entry(visibility=not password)
                if password:
                    field.set_icon_from_icon_name(Gtk.EntryIconPosition.SECONDARY, 'view-reveal-symbolic')
                    field.set_icon_activatable(Gtk.EntryIconPosition.SECONDARY, True)
                    field.set_icon_tooltip_text(Gtk.EntryIconPosition.SECONDARY, 'Toggle password visibility')
                    def on_toggle_visibility(entry, *_):
                        vis = entry.get_visibility()
                        entry.set_visibility(not vis)
                        entry.set_icon_from_icon_name(
                            Gtk.EntryIconPosition.SECONDARY,
                            'view-conceal-symbolic' if not vis else 'view-reveal-symbolic'
                        )
                    field.connect('icon-press', on_toggle_visibility)
                field.connect('activate', lambda *_: self.resolve_prompt(field.get_text()))
                self.prompt_box.pack_start(field, False, False, 0)

                btn_box = Gtk.Box(spacing=8)
                save_btn = Gtk.Button(label='Save')
                save_btn.get_style_context().add_class('primary')
                save_btn.connect('clicked', lambda *_: self.resolve_prompt(field.get_text()))
                btn_box.pack_start(save_btn, True, True, 0)

                cancel_btn = Gtk.Button(label='Cancel')
                cancel_btn.connect('clicked', lambda *_: self.resolve_prompt(None))
                btn_box.pack_start(cancel_btn, True, True, 0)
                self.prompt_box.pack_start(btn_box, False, False, 0)
            else:
                for index, option in enumerate(options):
                    if option in ('Back', 'Cancel'):
                        continue
                    button = Gtk.Button(label=backend.clean(option))
                    button.get_child().set_line_wrap(True)
                    button.get_child().set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
                    button.get_child().set_max_width_chars(50)
                    button.connect('clicked', lambda _, index=index: self.resolve_prompt(index))
                    self.prompt_box.pack_start(button, False, False, 0)

        self.prompt_box.set_sensitive(True)
        self.prompt_box.show_all()
        self.stack.set_visible_child_name('prompt')
        self.prompt_scroll.get_vadjustment().set_value(0)
        if not qr_data and options is None and field:
            field.grab_focus()
        return False

    def show_qr(self, ssid, password, svg, security=None):
        future = Future()
        title = f'Wi-Fi: {ssid}' if security != 'ADB' else 'Wireless Debugging: Pair with QR'
        GLib.idle_add(self.show_prompt, future, title, '', None, False,
                      {'ssid': ssid, 'password': password, 'svg': svg, 'security': security})
        return future.result()

    def menu(self, title, options, message=''):
        future = Future()
        GLib.idle_add(self.show_prompt, future, title, message, options)
        return future.result()

    def entry(self, title, message, password=False):
        future = Future()
        GLib.idle_add(self.show_prompt, future, title, message, None, password)
        return future.result()

    def cleanup(self, *_):
        self.cancel_action()
        if self.adb_session:
            self.adb_session.stop()
        if getattr(self, 'resize_timer', None):
            GLib.source_remove(self.resize_timer)
            self.resize_timer = None
        self.closed = True
        self.resolve_prompt(None)
        GLib.source_remove(self.timer)
        self.stop_discovery()


class App(Gtk.Application):
    def __init__(self):
        super().__init__(application_id='local.hyprland.Connections', flags=Gio.ApplicationFlags.FLAGS_NONE)

    def do_activate(self):
        window = self.get_active_window()
        if window:
            window.close()
        else:
            Panel(self)


if __name__ == '__main__':
    GLib.set_prgname('hypr-connections')
    App().run()
