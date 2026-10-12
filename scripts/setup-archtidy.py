#!/usr/bin/env python3
"""Install ArchTidy for the current user without depending on the git checkout."""
import argparse
from datetime import datetime
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]


def configure(home):
    home = Path(home)
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    backup = home / '.local/state/hyprland-setup/archtidy' / stamp
    target = home / '.local/share/archtidy'
    launcher = home / '.local/bin/archtidy'
    desktop = home / '.local/share/applications/archtidy.desktop'
    for path in (target, launcher, desktop):
        if path.exists():
            destination = backup / path.relative_to(home)
            destination.parent.mkdir(parents=True, exist_ok=True)
            if path.is_dir():
                shutil.copytree(path, destination)
            else:
                shutil.copy2(path, destination)
    target.mkdir(parents=True, exist_ok=True)
    shutil.copytree(ROOT / 'archtidy/archtidy', target / 'archtidy', dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    config = home / '.config/archtidy/config.toml'
    config.parent.mkdir(parents=True, exist_ok=True)
    if not config.exists():
        shutil.copy2(ROOT / 'archtidy/config.toml', config)
    launcher.parent.mkdir(parents=True, exist_ok=True)
    launcher.write_text('#!/usr/bin/env bash\n'
        'export PYTHONPATH="$HOME/.local/share/archtidy${PYTHONPATH:+:$PYTHONPATH}"\n'
        'exec /usr/bin/python3 -m archtidy.main "$@"\n')
    launcher.chmod(0o755)
    desktop.parent.mkdir(parents=True, exist_ok=True)
    executable = str(launcher).replace('\\', '\\\\').replace('"', '\\"').replace('`', '\\`').replace('$', '\\$')
    desktop.write_text((ROOT / 'archtidy/packaging/archtidy.desktop').read_text().replace('Exec=archtidy', f'Exec="{executable}"'))
    return target


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--home', type=Path, default=Path.home())
    args = parser.parse_args()
    print('ArchTidy installed:', configure(args.home))
