#!/usr/bin/env python3
"""Set the Zen package's default window-sync preference before first launch."""
import argparse
from datetime import datetime
from pathlib import Path
import shutil

PREFERENCE = 'pref("zen.window-sync.enabled", false);\n'


def configure(installation):
    installation = Path(installation)
    if not (installation / 'application.ini').is_file():
        return None
    directory = installation / 'defaults/pref'
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / 'hyprland-setup.js'
    if target.exists() and target.read_text() == PREFERENCE:
        return target
    if target.exists():
        backup = target.with_name(target.name + '.backup-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
        shutil.copy2(target, backup)
    target.write_text(PREFERENCE)
    target.chmod(0o644)
    return target


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--installation-dir', type=Path, default=Path('/opt/zen-browser-bin'))
    result = configure(parser.parse_args().installation_dir)
    print('Zen window-sync default disabled:', result) if result else print('Zen is not installed; defaults skipped.')
