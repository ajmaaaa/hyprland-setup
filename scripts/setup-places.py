#!/usr/bin/env python3
"""Configure folder shortcuts, newest-first sorting, and Dolphin Places."""
import argparse
import configparser
import datetime
import io
from pathlib import Path
import shutil
import subprocess
import uuid
import xml.etree.ElementTree as ET


FOLDERS = (
    ('Downloads', 'folder-downloads'),
    ('Documents', 'folder-documents'),
    ('Pictures', 'folder-pictures'),
    ('Videos', 'folder-videos'),
    ('Projects', 'folder-development'),
    ('Git', 'folder-development'),
)
BOOKMARK_NS = 'http://www.freedesktop.org/standards/desktop-bookmarks'
ET.register_namespace('bookmark', BOOKMARK_NS)
ET.register_namespace('kdepriv', 'http://www.kde.org/kdepriv')
ET.register_namespace('mime', 'http://www.freedesktop.org/standards/shared-mime-info')


def write_changed(path, content):
    if path.exists() and path.read_text() == content:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        shutil.copy2(path, path.with_name(path.name + '.backup-' + stamp))
    path.write_text(content)


def merge_ini(path, sections):
    settings = configparser.ConfigParser(interpolation=None)
    settings.optionxform = str
    settings.read(path)
    changed = False
    for section, values in sections.items():
        if not settings.has_section(section):
            settings.add_section(section)
        for key, value in values.items():
            if settings.get(section, key, fallback=None) != value:
                settings[section][key] = value
                changed = True
    if changed:
        output = io.StringIO()
        settings.write(output, space_around_delimiters=False)
        write_changed(path, output.getvalue())


def configure_sorting(home, apply_gsettings):
    merge_ini(home / '.config/dolphinrc', {'General': {'GlobalViewProps': 'true'}})
    merge_ini(home / '.local/share/dolphin/view_properties/global/.directory', {
        'Dolphin': {'Version': '4', 'SortRole': 'modificationtime',
            'SortOrder': '1', 'SortFoldersFirst': 'false'},
    })
    # KIO uses QDir::Time: newest first unless QDir::Reversed is set.
    merge_ini(home / '.config/kdeglobals', {'KFileDialog Settings': {
        'Sort by': 'Date', 'Sort reversed': 'false', 'Sort directories first': 'false',
    }})
    if apply_gsettings and shutil.which('gsettings'):
        schemas = subprocess.check_output(['gsettings', 'list-schemas'], text=True).splitlines()
        for schema in ('org.gtk.Settings.FileChooser', 'org.gtk.gtk4.Settings.FileChooser'):
            if schema in schemas:
                for key, value in (('sort-column', 'modified'), ('sort-order', 'descending'),
                        ('sort-directories-first', 'false')):
                    subprocess.run(['gsettings', 'set', schema, key, value], check=True)


def configure(home, apply_gsettings=True):
    home = home.expanduser().resolve()
    entries = []
    for name, icon in FOLDERS:
        folder = home / name
        folder.mkdir(parents=True, exist_ok=True)
        entries.append((folder.as_uri(), name, icon))

    for version in ('gtk-3.0', 'gtk-4.0'):
        path = home / '.config' / version / 'bookmarks'
        lines = path.read_text().splitlines() if path.exists() else []
        existing = {line.split(' ', 1)[0] for line in lines}
        for uri, name, _ in entries:
            if uri not in existing:
                lines.append(f'{uri} {name}')
        write_changed(path, '\n'.join(lines) + '\n')

    path = home / '.local/share/user-places.xbel'
    root = ET.parse(path).getroot() if path.exists() else ET.Element('xbel', {'version': '1.0'})
    before = ET.tostring(root)
    for uri, name, icon in entries:
        bookmark = next((b for b in root.findall('bookmark') if b.get('href') == uri), None)
        if bookmark is None:
            bookmark = ET.SubElement(root, 'bookmark', {'href': uri})
            ET.SubElement(bookmark, 'title').text = name
            info = ET.SubElement(bookmark, 'info')
            metadata = ET.SubElement(info, 'metadata', {'owner': 'http://freedesktop.org'})
            ET.SubElement(metadata, f'{{{BOOKMARK_NS}}}icon', {'name': icon})
            metadata = ET.SubElement(info, 'metadata', {'owner': 'http://www.kde.org'})
            ET.SubElement(metadata, 'ID').text = str(uuid.uuid4())
        # Ensure these shortcuts are visible in Dolphin and KDE file dialogs.
        for metadata in bookmark.findall('info/metadata'):
            for child in list(metadata):
                if child.tag == 'OnlyInApp':
                    metadata.remove(child)
                elif child.tag == 'isHidden':
                    child.text = 'false'
    info = root.find('info')
    if info is None:
        info = ET.SubElement(root, 'info')
    metadata = next((m for m in info.findall('metadata') if m.get('owner') == 'http://www.kde.org'), None)
    if metadata is None:
        metadata = ET.SubElement(info, 'metadata', {'owner': 'http://www.kde.org'})
    for group, hidden in (('Places', 'false'), ('Remote', 'true'),
            ('SearchFor', 'true'), ('RecentlySaved', 'true')):
        tag = f'GroupState-{group}-IsHidden'
        node = metadata.find(tag)
        if node is None:
            node = ET.SubElement(metadata, tag)
        node.text = hidden
    if not path.exists() or ET.tostring(root) != before:
        ET.indent(root, space=' ')
        content = '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xbel>\n'
        write_changed(path, content + ET.tostring(root, encoding='unicode') + '\n')
    configure_sorting(home, apply_gsettings)
    print('Dolphin and GTK bookmarks: ' + ', '.join(name for _, name, _ in entries))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--home', type=Path, default=Path.home())
    parser.add_argument('--skip-gsettings', action='store_true', help='Only update file-based settings')
    args = parser.parse_args()
    configure(args.home, apply_gsettings=not args.skip_gsettings)
