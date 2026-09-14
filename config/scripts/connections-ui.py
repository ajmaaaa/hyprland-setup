#!/usr/bin/env python3
"""On-demand connection panel with live network and device lists."""
import re
import subprocess
import threading
from concurrent.futures import Future

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
from gi.repository import Gdk, Gio, GLib, Gtk, Pango
import connections as backend


CSS = b'''
window, dialog { background: #151c28; color: #dbe5f5; }
* { font-family: "Sans"; font-size: 14px; }
.title { font-size: 25px; font-weight: bold; color: #eef5ff; }
.subtitle { color: #8ea3bd; font-size: 12px; }
.section { font-size: 16px; font-weight: bold; }
button { background: #233247; color: #dbe5f5; border: 1px solid #354961;
    border-radius: 8px; padding: 8px 13px; box-shadow: none; }
button:hover { background: #304761; }
button:checked, .primary { background: #365b81; color: #ffffff; }
button:disabled { opacity: 0.45; }
.details-arrow { font-size: 24px; padding: 2px 10px; }
button.connection-icon { border-radius: 28px; min-width: 54px; min-height: 54px;
    padding: 0; border: none; background: #243448; }
button.connection-icon:hover { background: #365371; }
button.connection-icon:focus { border: 2px solid #82b5eb; }
entry { background: #1b2738; color: #dbe5f5; border: 1px solid #354961;
    border-radius: 8px; padding: 9px; }
list { background: transparent; }
row { background: #1c293b; border-radius: 10px; margin-bottom: 6px; padding: 5px; }
row:hover { background: #263b54; }
row:selected { background: #2d4664; }
separator { background: #304258; min-height: 1px; }
switch { border-radius: 12px; }
scrollbar.vertical { margin: 5px 0 5px 8px; }
scrollbar.vertical slider { min-width: 8px; border-radius: 5px; }
'''


def label(text, style=None):
    widget = Gtk.Label(label=text, xalign=0)
    if style:
        widget.get_style_context().add_class(style)
    return widget


class Panel(Gtk.ApplicationWindow):
    def __init__(self, application):
        super().__init__(application=application, title='Connections')
        self.set_default_size(320, 380)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.set_resizable(False)
        self.set_decorated(False)
        self.set_border_width(16)
        self.set_keep_above(True)
        self.page = 'home'
        self.closed = False
        self.loading = False
        self.busy = False
        self.discovery = None
        self.discovery_lock = threading.Lock()
        self.snapshot = None
        self.connect('destroy', self.cleanup)
        self.connect('key-press-event', self.keypress)
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        # Bound the window's minimum height independently of each page's content.
        # Long content scrolls instead of changing the popup's geometry.
        viewport = Gtk.ScrolledWindow()
        viewport.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        viewport.set_propagate_natural_width(False)
        viewport.set_propagate_natural_height(False)
        viewport.add(box)
        self.add(viewport)
        header = Gtk.Box(spacing=10)
        self.home_header = header
        headings = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        headings.pack_start(label('Connections', 'title'), False, False, 0)
        header.pack_start(headings, True, True, 0)
        box.pack_start(header, False, False, 0)

        self.back = Gtk.Button(label='‹  All connections')
        self.back.set_halign(Gtk.Align.START)
        self.back.connect('clicked', lambda *_: self.go_back())
        box.pack_start(self.back, False, False, 0)

        tools = Gtk.Box(spacing=8)
        self.page_tools = tools
        self.heading = label('Choose a connection', 'section')
        tools.pack_start(self.heading, True, True, 0)
        self.power = Gtk.Switch()
        self.power.set_valign(Gtk.Align.CENTER)
        self.power.connect('state-set', self.toggle_power)
        tools.pack_end(self.power, False, False, 0)
        box.pack_start(tools, False, False, 0)
        self.search = Gtk.SearchEntry(placeholder_text='Search networks…')
        self.search.connect('search-changed', lambda *_: self.listbox.invalidate_filter())
        box.pack_start(self.search, False, False, 0)
        self.state = label('Loading…', 'subtitle')
        self.state.set_line_wrap(True)
        self.state.set_lines(1)
        self.state.set_ellipsize(Pango.EllipsizeMode.END)
        self.state.connect('notify::label', lambda widget, *_: widget.set_tooltip_text(widget.get_text()))
        box.pack_start(self.state, False, False, 0)
        self.listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.listbox.set_filter_func(lambda row: self.search.get_text().casefold() in row.search_text)
        self.listbox.connect('row-activated', self.activate_row)
        scroll = Gtk.ScrolledWindow()
        scroll.set_overlay_scrolling(False)
        self.listbox.set_margin_end(10)
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_min_content_height(80)
        scroll.set_max_content_height(80)
        scroll.set_propagate_natural_height(False)
        scroll.set_size_request(-1, 80)
        scroll.set_vexpand(True)
        scroll.add(self.listbox)
        self.stack = Gtk.Stack()
        self.stack.set_homogeneous(False)
        self.stack.add_named(scroll, 'list')
        self.tiles = Gtk.Grid(column_spacing=8, row_spacing=14, column_homogeneous=True)
        self.tiles.set_halign(Gtk.Align.CENTER)
        self.tiles.set_margin_top(12)
        self.tiles.set_valign(Gtk.Align.START)
        self.stack.add_named(self.tiles, 'home')
        self.prompt_scroll = Gtk.ScrolledWindow()
        self.prompt_scroll.set_overlay_scrolling(False)
        self.prompt_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.prompt_scroll.set_min_content_height(190)
        self.prompt_scroll.set_max_content_height(190)
        self.prompt_scroll.set_propagate_natural_height(False)
        self.prompt_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.prompt_box.set_margin_end(12)
        self.prompt_scroll.add(self.prompt_box)
        self.stack.add_named(self.prompt_scroll, 'prompt')
        self.pending = None
        box.pack_start(self.stack, True, True, 0)
        self.footer = Gtk.Box(spacing=8)
        box.pack_start(self.footer, False, False, 0)
        self.notice = label('', 'subtitle')
        self.notice.set_line_wrap(True)
        self.notice.set_max_width_chars(30)
        self.notice.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
        box.pack_start(self.notice, False, False, 0)
        backend.menu = self.menu
        backend.entry = self.entry
        backend.notify = lambda message: GLib.idle_add(self.set_notice, message)
        self.show_all()
        self.rebuild_footer()
        self.timer = GLib.timeout_add_seconds(4, self.refresh)
        self.refresh()

    def keypress(self, _, event):
        if event.keyval == Gdk.KEY_Escape:
            if self.pending:
                self.resolve_prompt(None)
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
        if row.target:
            self.select_page(row.target)
        elif row.callback:
            self.perform(row.callback)

    def select_page(self, page):
        if page == self.page:
            return
        self.page = page
        if page != 'bluetooth':
            self.stop_discovery()
        self.snapshot = None
        self.search.set_text('')
        self.search.set_placeholder_text('Search devices…' if page == 'bluetooth' else 'Search networks…')
        self.heading.set_text({'home': 'Choose a connection', 'wifi': 'Wi-Fi networks', 'bluetooth': 'Bluetooth devices', 'adb': 'Wireless debugging'}[page])
        self.state.set_text('Loading…')
        self.clear_rows()
        self.rebuild_footer()
        self.refresh()

    def rebuild_footer(self):
        for child in self.footer.get_children():
            self.footer.remove(child)
        self.heading.set_text({'home': 'Connections', 'wifi': 'Wi-Fi networks', 'bluetooth': 'Bluetooth devices', 'adb': 'Wireless debugging'}[self.page])
        self.home_header.set_visible(self.page == 'home')
        self.stack.set_visible_child_name('home' if self.page == 'home' else 'list')
        self.back.set_label('‹  All connections')
        self.back.set_visible(self.page != 'home')
        self.heading.set_visible(self.page != 'home')
        self.page_tools.set_visible(self.page != 'home')
        self.state.set_visible(self.page != 'home')
        self.set_notice('')
        self.power.set_visible(self.page in ('wifi', 'bluetooth'))
        self.power.set_sensitive(False)
        self.search.set_visible(self.page in ('wifi', 'bluetooth'))
        if self.page == 'wifi':
            buttons = [('Rescan', lambda: backend.nm('device', 'wifi', 'rescan')),
                       ('Saved', backend.saved_wifi), ('Settings', lambda: backend.launch('nm-connection-editor'))]
        elif self.page == 'bluetooth':
            buttons = [('Rescan', self.restart_discovery), ('Settings', lambda: backend.launch('blueman-manager'))]
        elif self.page == 'adb':
            buttons = [('Pairing code', backend.adb_pair), ('Connect IP:port', backend.adb_connect)]
        else:
            buttons = []
        for title, callback in buttons:
            button = Gtk.Button(label=title)
            button.connect('clicked', lambda _, callback=callback: self.perform(callback))
            self.footer.pack_start(button, True, True, 0)
        self.footer.show_all()
        self.footer.set_visible(bool(buttons))

    def toggle_power(self, switch, state):
        if getattr(self, 'updating_power', False):
            return False
        if self.page == 'wifi':
            self.perform(lambda: backend.nm('radio', 'wifi', 'on' if state else 'off'))
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
            adapters = [r for r in backend.devices() if r[1] == 'wifi']
            if not adapters:
                return (False, [], 'No Wi-Fi adapter available.', False)
            enabled = backend.nm('radio', 'wifi') == 'enabled'
            networks = backend.rows('IN-USE,SSID,SIGNAL,SECURITY,BSSID,DEVICE', 'device', 'wifi', 'list', '--rescan', 'auto') if enabled else []
            unique = {}
            for row in sorted((r for r in networks if len(r) == 6 and r[1]), key=lambda r: (r[0] != '*', -int(r[2] or 0))):
                unique.setdefault((row[1], row[3], row[5]), row)
            networks = list(unique.values())
            message = f'{len(networks)} networks · updates automatically' if networks else 'No networks found. Try Rescan.'
            return (enabled, networks, message if enabled else 'Wi-Fi is off. Turn it on to see networks.', True)
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
            message = f'{len(devices)} devices · scanning nearby devices…' if scanning else f'{len(devices)} devices · preparing scan…'
            if not devices:
                message += '\nPut the target device into pairing mode first.'
            return (powered, devices, message if powered else 'Bluetooth is off. Turn it on to scan.', True)
        if page == 'adb':
            return backend.adb_devices()
        try:
            adapters = backend.devices()
            aps = [r[0] for r in adapters if r[1] == 'wifi' and backend.nm('-g', 'WIFI-PROPERTIES.AP', 'device', 'show', r[0]) == 'yes']
            wired = [r for r in adapters if r[1] == 'ethernet']
            active = next((r[3] for r in adapters if r[1] == 'wifi' and r[2] == 'connected'), '')
            connected_bt = backend.run(['bluetoothctl', 'devices', 'Connected'], timeout=5)
            bt_name = ', '.join(line.split(' ', 2)[2] for line in connected_bt.stdout.splitlines() if line.startswith('Device ') and len(line.split(' ', 2)) == 3)
            return (aps, wired, active, '', bt_name)
        except RuntimeError as error:
            return ([], [], '', str(error), '')

    def clear_rows(self):
        for row in self.listbox.get_children():
            self.listbox.remove(row)

    def add_row(self, title, subtitle, icon, callback=None, badge='', target=None, detail=None):
        row = Gtk.ListBoxRow(activatable=callback is not None or target is not None)
        row.target = target
        row.callback = callback
        row.search_text = (title + ' ' + subtitle).casefold()
        box = Gtk.Box(spacing=8)
        box.set_border_width(3)
        image = Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.LARGE_TOOLBAR)
        box.pack_start(image, False, False, 0)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        name = label(backend.clean(title), 'section')
        name.set_ellipsize(Pango.EllipsizeMode.END)
        name.set_max_width_chars(16)
        name.set_tooltip_text(backend.clean(title))
        text.pack_start(name, False, False, 0)
        description = label(subtitle, 'subtitle')
        description.set_line_wrap(True)
        description.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
        description.set_max_width_chars(16)
        text.pack_start(description, False, False, 0)
        box.pack_start(text, True, True, 0)
        side = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        side.set_valign(Gtk.Align.CENTER)
        if badge and not detail:
            side.pack_start(label(badge, 'subtitle'), False, False, 0)
        if detail:
            arrow = Gtk.Button(label='›')
            arrow.get_style_context().add_class('details-arrow')
            arrow.set_size_request(40, 40)
            arrow.set_margin_start(4)
            arrow.set_margin_end(2)
            arrow.set_tooltip_text('Open details')
            arrow.connect('clicked', lambda *_: self.perform(detail))
            side.pack_start(arrow, False, False, 0)
        box.pack_end(side, False, False, 0)
        row.add(box)
        self.listbox.add(row)

    def render(self, page, data, error):
        self.loading = False
        if self.closed:
            return False
        if self.busy:
            return False
        if page != self.page:
            self.refresh()
            return False
        if error:
            self.state.set_text(error)
            self.power.set_sensitive(False)
            return False
        if data == self.snapshot:
            return False
        self.snapshot = data
        self.clear_rows()
        if page in ('wifi', 'bluetooth'):
            powered, items, message, available = data
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
                    level = 'excellent' if int(strength) >= 80 else 'good' if int(strength) >= 55 else 'ok' if int(strength) >= 30 else 'weak'
                    self.add_row(ssid, subtitle, f'network-wireless-signal-{level}-symbolic', lambda item=item: backend.connect_wifi(item), '●' if active == '*' else '', detail=lambda item=item: backend.wifi_details(item))
                else:
                    address, name, connected, paired, status = item
                    self.add_row(name, status, 'bluetooth-symbolic', lambda item=item: backend.connect_bluetooth(item), '●' if connected else '', detail=lambda item=item: backend.bluetooth_details(item))
            if not items:
                self.add_row('No networks found' if page == 'wifi' else 'No devices found',
                             'Turn Wi-Fi on or run Rescan.' if page == 'wifi' else 'Turn Bluetooth on and put the device in pairing mode.',
                             'network-wireless-symbolic' if page == 'wifi' else 'bluetooth-symbolic', None)
        elif page == 'adb':
            self.state.set_text('Android 11+ · enable Wireless debugging on the phone. Use Pairing code for a new device.')
            for item in data:
                serial, name, state, wireless = item
                status = {'device': 'Connected', 'offline': 'Offline', 'unauthorized': 'Waiting for phone approval'}[state]
                self.add_row(name, status + (' · Wireless' if wireless else ' · USB'), 'phone-symbolic', lambda item=item: backend.adb_device_action(item))
            if not data:
                self.add_row('No Android device connected', 'Pair with a code, then connect using the phone IP:port.', 'phone-symbolic', badge='')
        else:
            aps, wired, active, error, bt_name = data
            for child in self.tiles.get_children():
                self.tiles.remove(child)
            cable = next((r[3] for r in wired if r[2] == 'connected' and r[3] != '--'), '')
            features = [
                ('Wi-Fi', active, 'network-wireless-symbolic', lambda: self.select_page('wifi')),
                ('Bluetooth', bt_name, 'bluetooth-symbolic', lambda: self.select_page('bluetooth')),
                ('Ethernet', cable, 'network-wired-symbolic', lambda: self.perform(backend.ethernet)),
                ('Hotspot', '', 'network-wireless-hotspot-symbolic', lambda: self.perform(backend.hotspot)),
                ('VPN', '', 'network-vpn-symbolic', lambda: self.perform(backend.vpn)),
                ('Wireless', '', 'phone-symbolic', lambda: self.select_page('adb')),
                ('Airplane', '', 'airplane-mode-symbolic', lambda: self.perform(backend.airplane))]
            for index, (title, detail, icon, callback) in enumerate(features):
                button = Gtk.Button()
                button.get_style_context().add_class('connection-icon')
                button.set_halign(Gtk.Align.CENTER)
                button.set_valign(Gtk.Align.CENTER)
                button.set_size_request(56, 56)
                button.set_tooltip_text(title)
                button.get_accessible().set_name(title)
                contents = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
                contents.set_valign(Gtk.Align.START)
                icon_widget = Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.DIALOG)
                icon_widget.set_pixel_size(26)
                button.add(icon_widget)
                contents.pack_start(button, False, False, 0)
                name = Gtk.Label(label=title)
                name.set_line_wrap(True)
                name.set_justify(Gtk.Justification.CENTER)
                contents.pack_start(name, False, False, 0)
                if detail:
                    subtitle = label(backend.clean(detail), 'subtitle')
                    subtitle.set_xalign(0.5)
                    subtitle.set_max_width_chars(10)
                    subtitle.set_ellipsize(Pango.EllipsizeMode.END)
                    contents.pack_start(subtitle, False, False, 0)
                button.connect('clicked', lambda _, callback=callback: callback())
                self.tiles.attach(contents, index % 3 if index < 6 else 1, index // 3, 1, 1)
            self.tiles.show_all()
            if error:
                self.set_notice(error)
        self.listbox.show_all()
        return False

    def perform(self, callback):
        if self.busy or self.closed:
            return
        self.busy = True
        self.listbox.set_sensitive(False)
        self.footer.set_sensitive(False)
        self.power.set_sensitive(False)
        self.tiles.set_sensitive(False)
        self.back.set_sensitive(False)
        self.set_notice('Working…')
        def work():
            error = None
            try:
                callback()
            except Exception as exc:
                error = str(exc)
            GLib.idle_add(self.finish_action, error)
        threading.Thread(target=work, daemon=True).start()

    def finish_action(self, error):
        if self.closed:
            return False
        self.busy = False
        self.snapshot = None
        self.listbox.set_sensitive(True)
        self.footer.set_sensitive(True)
        self.tiles.set_sensitive(True)
        self.back.set_sensitive(True)
        self.rebuild_footer()
        self.set_notice(error or '')
        self.refresh()
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
            future.set_result(value)

    def show_prompt(self, future, title, message, options=None, password=False):
        if self.closed:
            future.set_result(None)
            return False
        self.pending = future
        for child in self.prompt_box.get_children():
            self.prompt_box.remove(child)
        self.heading.set_text(backend.clean(title))
        self.home_header.hide()
        self.page_tools.show()
        self.heading.set_visible(True)
        self.heading.set_ellipsize(Pango.EllipsizeMode.END)
        self.heading.set_max_width_chars(24)
        self.back.set_label('‹  Back')
        self.back.set_visible(True)
        self.back.set_sensitive(True)
        self.power.hide()
        self.search.hide()
        self.state.hide()
        self.footer.hide()
        self.set_notice('')
        for line in message.splitlines():
            if not line.strip():
                continue
            if ': ' in line:
                key, value = line.split(': ', 1)
                row = Gtk.Box(spacing=10)
                key_label = label(key, 'subtitle')
                key_label.set_size_request(86, -1)
                key_label.set_valign(Gtk.Align.START)
                row.pack_start(key_label, False, False, 0)
                value_label = label(backend.clean(value))
                value_label.set_line_wrap(True)
                value_label.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
                value_label.set_max_width_chars(18)
                value_label.set_selectable(True)
                row.pack_start(value_label, True, True, 0)
            else:
                row = label(backend.clean(line), 'subtitle')
                row.set_line_wrap(True)
                row.set_max_width_chars(28)
                row.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
            self.prompt_box.pack_start(row, False, False, 0)
            self.prompt_box.pack_start(Gtk.Separator(), False, False, 0)
        field = None
        if options is None:
            field = Gtk.Entry(visibility=not password)
            field.connect('activate', lambda *_: self.resolve_prompt(field.get_text()))
            self.prompt_box.pack_start(field, False, False, 0)
            button = Gtk.Button(label='Continue')
            button.connect('clicked', lambda *_: self.resolve_prompt(field.get_text()))
            self.prompt_box.pack_start(button, False, False, 0)
        else:
            for index, option in enumerate(options):
                if option in ('Back', 'Cancel'):
                    continue
                button = Gtk.Button(label=backend.clean(option))
                button.get_child().set_line_wrap(True)
                button.get_child().set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
                button.get_child().set_max_width_chars(26)
                button.connect('clicked', lambda _, index=index: self.resolve_prompt(index))
                self.prompt_box.pack_start(button, False, False, 0)
        self.prompt_box.set_sensitive(True)
        self.prompt_box.show_all()
        self.stack.set_visible_child_name('prompt')
        self.prompt_scroll.get_vadjustment().set_value(0)
        if field:
            field.grab_focus()
        return False

    def menu(self, title, options, message=''):
        future = Future()
        GLib.idle_add(self.show_prompt, future, title, message, options)
        return future.result()

    def entry(self, title, message, password=False):
        future = Future()
        GLib.idle_add(self.show_prompt, future, title, message, None, password)
        return future.result()

    def cleanup(self, *_):
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
