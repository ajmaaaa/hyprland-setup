#!/usr/bin/env python3
"""Add shared folder shortcuts to Dolphin and GTK file chooser sidebars."""
import argparse
import datetime
from pathlib import Path
import shutil
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


def configure(home):
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
    for hidden in root.findall('info/metadata/GroupState-Places-IsHidden'):
        hidden.text = 'false'
    if not path.exists() or ET.tostring(root) != before:
        ET.indent(root, space=' ')
        content = '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xbel>\n'
        write_changed(path, content + ET.tostring(root, encoding='unicode') + '\n')
    print('Dolphin and GTK bookmarks: ' + ', '.join(name for _, name, _ in entries))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--home', type=Path, default=Path.home())
    configure(parser.parse_args().home)
