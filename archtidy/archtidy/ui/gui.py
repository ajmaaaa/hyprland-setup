"""Mouse-first cleanup panel. Scans never select or remove anything automatically."""
import threading
import os
import sys
from pathlib import Path
import gi

gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
from gi.repository import Gdk, Gio, GLib, Gtk, Pango
from ..core.candidate import Candidate
from ..core.confirm import execute_cleanup, undo_recent_batch
from ..modules import OrphanDetector, PackageCleaner, BigFileFinder, DuplicateFinder, AndroidCleaner, JunkCleaner

CSS = b'''
* { font-family: Sans; font-size: 14px; }
window { background: #151c28; color: #e3ecfa; }
.title { font-size: 28px; font-weight: bold; }
.muted { color: #9bafc9; font-size: 13px; }
.section { font-size: 17px; font-weight: bold; }
button { background: #24354c; color: #e3ecfa; border: 1px solid #3a506d;
 border-radius: 9px; padding: 9px 14px; box-shadow: none; }
button:hover { background: #344c6a; }
button:disabled { opacity: .45; }
.primary { background: #306dc0; border-color: #5896eb; color: white; }
.danger { background: #933e49; color: white; }
entry { background: #202e42; color: #e3ecfa; border: 1px solid #3a506d; border-radius: 9px; padding: 9px; }
list, textview, textview text { background: #192435; color: #e3ecfa; }
row { padding: 12px; border-bottom: 1px solid #2c3b50; }
row:hover { background: #23344b; }
checkbutton check { min-width: 20px; min-height: 20px; border: 1px solid #7189a9; border-radius: 5px; }
checkbutton check:checked { background: #306dc0; color: white; }
separator { background: #334660; }
'''
CATEGORIES = [
    ('App leftovers', 'Possible app leftovers. Review the reason and path before selecting.'),
    ('Cache & packages', 'Build caches and unused dependencies. Removing packages requires authentication.'),
    ('Large files', 'Large files may still be needed. Select only files you recognize.'),
    ('Duplicates', 'Identical copies; the scanner keeps one original copy.'),
    ('Android & temp', 'Android caches and temporary files. Review each item before selecting.'),
    ('Junk only', 'Superseded package archives (keeping two versions) and thumbnail caches older than 30 days. No personal files or installed packages.'),
]


def label(text, style=None):
    out = Gtk.Label(label=text, xalign=0)
    if style:
        out.get_style_context().add_class(style)
    return out


class Panel(Gtk.ApplicationWindow):
    def __init__(self, app, config):
        super().__init__(application=app, title='ArchTidy')
        self.config = config
        self.data = [None] * len(CATEGORIES)
        self.scanning = set()
        self.category = 1
        self.busy = False
        self.closed = False
        self.review_items = []
        self.set_default_size(940, 640)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.set_decorated(False)
        self.set_border_width(24)
        self.connect('destroy', self.on_destroy)
        scripts = Path(__file__).resolve().parents[3] / 'config/scripts'
        if not scripts.exists():
            scripts = Path.home() / '.config/hypr/scripts'
        sys.path.insert(0, str(scripts))
        import panel_dismiss
        panel_dismiss.listen(self, 'archtidy', GLib)
        self.connect('key-press-event', self.keypress)
        css = Gtk.CssProvider()
        css.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        self.add(root)
        header = Gtk.Box(spacing=12)
        heading = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        heading.pack_start(label('ArchTidy', 'title'), False, False, 0)
        heading.pack_start(label('Select files → review selection → clean up', 'muted'), False, False, 0)
        header.pack_start(heading, True, True, 0)
        self.undo = Gtk.Button(label='Restore last cleanup')
        self.undo.connect('clicked', lambda *_: self.run_work(lambda: '\n'.join(undo_recent_batch())))
        header.pack_start(self.undo, False, False, 0)
        close = Gtk.Button.new_from_icon_name('window-close-symbolic', Gtk.IconSize.BUTTON)
        close.set_tooltip_text('Close · Esc')
        close.connect('clicked', lambda *_: self.close())
        header.pack_end(close, False, False, 0)
        root.pack_start(header, False, False, 0)
        self.stack = Gtk.Stack()
        root.pack_start(self.stack, True, True, 0)
        browse = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.stack.add_named(browse, 'browse')
        toolbar = Gtk.Box(spacing=8)
        self.tabs = Gtk.ComboBoxText()
        for name, _ in CATEGORIES:
            self.tabs.append_text(name)
        self.tabs.set_active(self.category)
        self.tabs.connect('changed', self.change_category)
        toolbar.pack_start(self.tabs, False, False, 0)
        self.search = Gtk.SearchEntry(placeholder_text='Search file name or path…')
        self.search.connect('search-changed', lambda *_: self.list.invalidate_filter())
        toolbar.pack_start(self.search, True, True, 0)
        self.rescan = Gtk.Button(label='Rescan')
        self.rescan.connect('clicked', lambda *_: self.scan(force=True))
        toolbar.pack_end(self.rescan, False, False, 0)
        browse.pack_start(toolbar, False, False, 0)
        self.hint = label(CATEGORIES[self.category][1], 'muted')
        self.hint.set_line_wrap(True)
        browse.pack_start(self.hint, False, False, 0)
        self.list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.list.set_filter_func(lambda row: self.search.get_text().casefold() in row.search_text)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.add(self.list)
        browse.pack_start(scroll, True, True, 0)
        bottom = Gtk.Box(spacing=10)
        self.select_all = Gtk.Button(label='Select visible items')
        self.select_all.connect('clicked', self.toggle_visible)
        bottom.pack_start(self.select_all, False, False, 0)
        clear = Gtk.Button(label='Clear selection')
        clear.connect('clicked', self.clear_selection)
        bottom.pack_start(clear, False, False, 0)
        self.summary = label('', 'muted')
        bottom.pack_start(self.summary, True, True, 0)
        self.review = Gtk.Button(label='Review & clean…')
        self.review.get_style_context().add_class('primary')
        self.review.connect('clicked', self.show_review)
        bottom.pack_end(self.review, False, False, 0)
        browse.pack_start(bottom, False, False, 0)
        review = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        self.review_title = label('', 'section')
        review.pack_start(self.review_title, False, False, 0)
        explanation = label('User files are moved to Trash; disk space is freed after emptying Trash.\nPackages and system cache archives are removed with authentication and cannot be restored from Trash.', 'muted')
        explanation.set_line_wrap(True)
        review.pack_start(explanation, False, False, 0)
        self.review_text = Gtk.TextView(editable=False, cursor_visible=False, wrap_mode=Gtk.WrapMode.WORD_CHAR)
        self.review_text.set_left_margin(14)
        self.review_text.set_right_margin(14)
        scroll = Gtk.ScrolledWindow()
        scroll.add(self.review_text)
        review.pack_start(scroll, True, True, 0)
        actions = Gtk.Box(spacing=10)
        cancel = Gtk.Button(label='Back to selection')
        cancel.connect('clicked', lambda *_: self.stack.set_visible_child_name('browse'))
        actions.pack_start(cancel, False, False, 0)
        simulate = Gtk.Button(label='Preview cleanup')
        simulate.connect('clicked', lambda *_: self.cleanup(True))
        actions.pack_end(simulate, False, False, 0)
        delete = Gtk.Button(label='Delete selected items')
        delete.get_style_context().add_class('danger')
        delete.connect('clicked', lambda *_: self.cleanup(False))
        actions.pack_end(delete, False, False, 0)
        review.pack_start(actions, False, False, 0)
        self.stack.add_named(review, 'review')
        self.notice = label('Scanning…', 'muted')
        self.notice.set_line_wrap(True)
        self.notice.set_selectable(True)
        self.notice.set_max_width_chars(100)
        root.pack_start(self.notice, False, False, 0)
        self.show_all()
        self.update_summary()
        self.scan()

    def on_destroy(self, *_):
        self.closed = True

    def keypress(self, _, event):
        if event.keyval == Gdk.KEY_Escape:
            if self.stack.get_visible_child_name() == 'review' and not self.busy:
                self.stack.set_visible_child_name('browse')
            else:
                self.close()
            return True
        return False

    def change_category(self, combo):
        self.category = combo.get_active()
        self.hint.set_text(CATEGORIES[self.category][1])
        self.render()
        if self.data[self.category] is None:
            self.scan()

    def scan(self, force=False):
        index = self.category
        if index in self.scanning or self.busy:
            return
        self.scanning.add(index)
        self.notice.set_text('Scanning ' + CATEGORIES[index][0].lower() + '…')
        self.rescan.set_sensitive(False)
        self.render()
        def work():
            items, error = [], None
            try:
                bl = self.config.get('blacklist', {}).get('paths', [])
                pkg = PackageCleaner(custom_blacklist=bl)
                if index == 0:
                    cfg = self.config.get('orphans', {})
                    items = OrphanDetector(scan_dirs=cfg.get('scan_directories'), min_confidence=cfg.get('min_confidence_score', 70), custom_blacklist=bl).scan()
                elif index == 1:
                    items = pkg.get_orphan_packages() + pkg.get_aur_cache_candidates() + pkg.get_pacman_cache_candidates()
                elif index in (2, 3):
                    cfg = self.config.get('bigfiles' if index == 2 else 'duplicates', {})
                    detector = BigFileFinder if index == 2 else DuplicateFinder
                    items = detector(scan_dir=cfg.get('scan_directories'), min_size_mb=cfg.get('min_size_mb', 100 if index == 2 else 1), custom_blacklist=bl).scan()
                elif index == 4:
                    items = AndroidCleaner(custom_blacklist=bl).scan()
                else:
                    items = JunkCleaner(custom_blacklist=bl).scan()
                for item in items:
                    item.selected = False
                items.sort(key=lambda c: c.size_bytes, reverse=True)
            except Exception as exc:
                error = str(exc)
            GLib.idle_add(self.finish_scan, index, items, error)
        threading.Thread(target=work, daemon=True).start()

    def finish_scan(self, index, items, error):
        if self.closed:
            return False
        self.scanning.discard(index)
        self.data[index] = items
        self.rescan.set_sensitive(self.category not in self.scanning)
        self.notice.set_text('Scan failed: ' + error if error else f'{CATEGORIES[index][0]}: {len(items)} items found. Nothing is selected automatically.')
        if self.category == index:
            self.render()
        return False

    def render(self):
        for row in self.list.get_children():
            self.list.remove(row)
        items = self.data[self.category] or []
        if not items:
            row = Gtk.ListBoxRow()
            row.search_text = ''
            row.add(label('Scanning…' if self.category in self.scanning or self.data[self.category] is None else 'No candidates in this category.', 'muted'))
            self.list.add(row)
        for item in items:
            row = Gtk.ListBoxRow()
            row.search_text = (str(item.path) + ' ' + item.reason).casefold()
            row.item = item
            box = Gtk.Box(spacing=14)
            check = Gtk.CheckButton()
            system_cache = item.source == "cache" and item.path.parent == Path("/var/cache/pacman/pkg")
            writable = item.source == "package" or system_cache or os.access(item.path.parent, os.W_OK)
            check.set_sensitive(writable)
            if not writable:
                check.set_tooltip_text("This location is not writable by the current user.")
            check.set_active(item.selected)
            check.set_valign(Gtk.Align.CENTER)
            check.connect('toggled', self.toggle_item, item)
            row.check = check
            box.pack_start(check, False, False, 0)
            details = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            details.pack_start(label(item.details.get('pkg_name') or item.path.name, 'section'), False, False, 0)
            path = label(str(item.path), 'muted')
            path.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
            path.set_max_width_chars(65)
            path.set_selectable(True)
            path.set_tooltip_text(str(item.path))
            details.pack_start(path, False, False, 0)
            reason = label(item.reason, 'muted')
            reason.set_line_wrap(True)
            reason.set_max_width_chars(70)
            details.pack_start(reason, False, False, 0)
            box.pack_start(details, True, True, 0)
            right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            right.pack_start(label(item.human_size, 'section'), False, False, 0)
            right.pack_start(label('Remove package' if item.source == 'package' else 'Delete archive' if system_cache else 'Move to Trash' if writable else 'Unavailable', 'muted'), False, False, 0)
            box.pack_end(right, False, False, 0)
            row.add(box)
            self.list.add(row)
        self.list.show_all()
        self.update_summary()

    def toggle_item(self, check, item):
        item.selected = check.get_active()
        self.update_summary()

    def selected(self):
        # Scanners can report the same path in more than one category.
        return list({(c.source == 'package', str(c.path)): c for items in self.data if items for c in items if c.selected}.values())

    def update_summary(self):
        items = self.selected()
        size = Candidate(Path('.'), sum(c.size_bytes for c in items), '', 0, '').human_size
        self.summary.set_text(f'{len(items)} selected · {size}')
        self.review.set_sensitive(bool(items) and not self.busy)

    def toggle_visible(self, *_):
        rows = [r for r in self.list.get_children() if hasattr(r, 'check') and r.check.get_sensitive() and self.search.get_text().casefold() in r.search_text]
        active = any(not r.check.get_active() for r in rows)
        for row in rows:
            row.check.set_active(active)

    def clear_selection(self, *_):
        for items in self.data:
            for item in items or []:
                item.selected = False
        self.render()

    def show_review(self, *_):
        self.review_items = self.selected()
        self.review_title.set_text(f'Review {len(self.review_items)} items before deleting')
        self.review_text.get_buffer().set_text('\n\n'.join(f'{c.path}\n{c.human_size} · {"Remove package" if c.source == "package" else "Permanently delete archive (admin)" if c.path.parent == Path("/var/cache/pacman/pkg") else "Move to Trash"}\n{c.reason}' for c in self.review_items))
        self.stack.set_visible_child_name('review')

    def cleanup(self, dry_run):
        items = list(self.review_items)
        def work():
            result = execute_cleanup(items, dry_run=dry_run, custom_blacklist=self.config.get('blacklist', {}).get('paths', []), admin_command=['pkexec'])
            if not dry_run:
                for category in self.data:
                    if category:
                        category[:] = [c for c in category if str(c.path) not in result.items_trashed and f'Package: {c.details.get("pkg_name", c.path.name)}' not in result.items_trashed]
            msg = f'{"Preview" if dry_run else "Done"}: {result.processed_count} item. '
            if not dry_run:
                msg += 'User files were moved to Trash. Packages and system archives cannot be restored. '
            if result.errors:
                msg += '\n' + '\n'.join(result.errors[:8])
            return msg
        self.run_work(work)

    def run_work(self, callback):
        if self.busy:
            return
        self.busy = True
        self.stack.set_sensitive(False)
        self.undo.set_sensitive(False)
        self.notice.set_text('Processing…')
        app = self.get_application()
        app.hold()
        def work():
            try:
                message = callback()
            except Exception as exc:
                message = 'Failed: ' + str(exc)
            GLib.idle_add(self.finish_work, app, message)
        threading.Thread(target=work, daemon=True).start()

    def finish_work(self, app, message):
        self.busy = False
        if not self.closed:
            self.stack.set_sensitive(True)
            self.undo.set_sensitive(True)
            self.stack.set_visible_child_name('browse')
            self.render()
            self.notice.set_text(message)
        app.release()
        return False


class App(Gtk.Application):
    def __init__(self, config):
        super().__init__(application_id='local.hyprland.ArchTidy', flags=Gio.ApplicationFlags.FLAGS_NONE)
        self.config = config

    def do_activate(self):
        window = self.get_active_window()
        if window:
            window.close()
        else:
            Panel(self, self.config)


def run(config):
    GLib.set_prgname('archtidy')
    App(config).run([])
