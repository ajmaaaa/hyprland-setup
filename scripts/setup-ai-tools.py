#!/usr/bin/env python3
"""Install the optional DeepSeek launcher without changing Claude/Codex settings."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]


def configure(home):
    home = Path(home)
    launcher = home / '.local/bin/claude-deepseek'
    if launcher.exists():
        backup = home / '.local/state/hyprland-setup/ai-tools' / datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        backup.mkdir(parents=True, exist_ok=True)
        shutil.copy2(launcher, backup / launcher.name)
    launcher.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / 'config/scripts/claude-deepseek.py', launcher)
    launcher.chmod(0o755)
    config = home / '.config/claude-deepseek/config.json'
    config.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not config.exists():
        config.write_text(json.dumps({'base_url': 'https://api.deepseek.com/anthropic',
                                     'model': 'deepseek-flash[1m]', 'small_model': 'deepseek-flash'}, indent=2) + '\n')
        config.chmod(0o600)
    return launcher


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--home', type=Path, default=Path.home())
    print('DeepSeek custom launcher installed:', configure(parser.parse_args().home))
