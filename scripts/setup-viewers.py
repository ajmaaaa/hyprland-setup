#!/usr/bin/env python3
"""Merge desktop file associations, without selecting uninstalled viewers."""
import argparse
import configparser
import datetime
import io
from pathlib import Path
import shutil
import subprocess


def read_ini(path):
    result = configparser.ConfigParser(interpolation=None, strict=False)
    result.optionxform = str
    result.read(path)
    return result


def serialize(value):
    output = io.StringIO()
    value.write(output, space_around_delimiters=False)
    return output.getvalue()


def configure(home, system_apps=Path('/usr/share/applications'), refresh=True):
    apps = home / '.local/share/applications'
    backup = home / '.local/state/hyprland-setup/viewers' / datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')

    def write(path, content):
        if path.exists():
            if path.read_text() == content:
                return
            saved = backup / path.relative_to(home)
            saved.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, saved)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    def supported(name):
        desktop = read_ini(system_apps / name)
        return set(filter(None, desktop.get('Desktop Entry', 'MimeType', fallback='').split(';')))

    code = set(Path(__file__).with_name('code-mime-types.txt').read_text().split())
    aliases = Path('/usr/share/mime/aliases')
    if aliases.exists():
        for line in aliases.read_text().splitlines():
            parts = line.split()
            if len(parts) == 2 and parts[1] in code:
                code.add(parts[0])

    available = lambda name: (system_apps / name).is_file()
    has_editor = available('antigravity-ide.desktop')
    has_nvim = available('nvim.desktop') and available('Alacritty.desktop')
    if has_editor:
        desktop = read_ini(system_apps / 'antigravity-ide.desktop')
        desktop['Desktop Entry']['MimeType'] = ';'.join(sorted(code | supported('antigravity-ide.desktop'))) + ';'
        write(apps / 'antigravity-ide.desktop', serialize(desktop))
    if has_nvim:
        write(apps / 'nvim.desktop', '[Desktop Entry]\nName=Neovim (Alacritty)\nType=Application\n'
              'Exec=alacritty -e nvim -- %F\nTryExec=nvim\nIcon=nvim\nTerminal=false\n'
              'Categories=Utility;TextEditor;Development;\nMimeType=' + ';'.join(sorted(code)) + ';\n')

    expected = {}
    alternatives = {}
    if has_editor:
        expected.update(dict.fromkeys(code, 'antigravity-ide.desktop'))
    if has_nvim:
        alternatives.update({mime: ['nvim.desktop'] for mime in code})
    for name, predicate in (
        ('mpv.desktop', lambda m: m.startswith(('audio/', 'video/')) or m in {
            'application/ogg', 'application/x-ogg', 'application/x-matroska',
            'application/vnd.apple.mpegurl', 'application/x-mpegurl'}),
        ('org.gnome.Papers.desktop', lambda m: m == 'application/pdf'),
        ('org.gnome.Loupe.desktop', lambda m: m.startswith('image/')),
    ):
        if available(name):
            expected.update({mime: name for mime in supported(name) if predicate(mime)})
        else:
            print(f'Skipping unavailable viewer: {name}')

    # Existing desktop-specific lists take precedence over the generic list.
    paths = [home / '.config/mimeapps.list']
    paths += sorted((home / '.config').glob('*-mimeapps.list'))
    for path in paths:
        settings = read_ini(path)
        for section in ('Default Applications', 'Added Associations'):
            if not settings.has_section(section):
                settings.add_section(section)
        for mime in sorted(expected.keys() | alternatives.keys()):
            default = expected.get(mime)
            if default:
                settings['Default Applications'][mime] = default + ';'
            added = ([default] if default else []) + alternatives.get(mime, [])
            previous = settings['Added Associations'].get(mime, '').split(';')
            choices = list(dict.fromkeys(added + list(filter(None, previous))))
            settings['Added Associations'][mime] = ';'.join(choices) + ';'
            if settings.has_section('Removed Associations'):
                removed = settings['Removed Associations'].get(mime, '').split(';')
                remaining = [name for name in removed if name and name not in added]
                if remaining:
                    settings['Removed Associations'][mime] = ';'.join(remaining) + ';'
                else:
                    settings.remove_option('Removed Associations', mime)
        write(path, serialize(settings))
    if refresh:
        for command in (['update-desktop-database', str(apps)], ['kbuildsycoca6', '--noincremental']):
            if shutil.which(command[0]) and (command[0] != 'update-desktop-database' or apps.exists()):
                subprocess.run(command, check=True)
    print(f'Configured {len(expected)} default associations. Existing changed files backed up under {backup}')
    return expected


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--home', type=Path, default=Path.home())
    parser.add_argument('--applications', type=Path, default=Path('/usr/share/applications'))
    parser.add_argument('--skip-cache', action='store_true')
    args = parser.parse_args()
    configure(args.home, args.applications, not args.skip_cache)
