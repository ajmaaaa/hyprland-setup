#!/usr/bin/env python3
"""Install the optional DeepSeek launcher without changing Claude/Codex settings."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import shutil
import shlex

ROOT = Path(__file__).resolve().parents[1]
ZSH_BLOCK = '''# >>> hyprland-setup AI tools >>>
[[ ! -r "$HOME/.config/hyprland-setup/ai-tools.zsh" ]] || source "$HOME/.config/hyprland-setup/ai-tools.zsh"
# <<< hyprland-setup AI tools <<<'''


def legacy_key(home):
    legacy = home / '.claude-deepseek.env'
    if not legacy.exists():
        return None
    for line in legacy.read_text().splitlines():
        try:
            parts = shlex.split(line, comments=True)
        except ValueError:
            continue
        if parts and parts[0] == 'export':
            parts = parts[1:]
        if len(parts) == 1 and '=' in parts[0]:
            name, value = parts[0].split('=', 1)
            if name in ('DEEPSEEK_API_KEY', 'ANTHROPIC_AUTH_TOKEN', 'ANTHROPIC_API_KEY') and value and not any(c in value for c in '$`'):
                return value
    return None


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
                                     'model': 'deepseek-flash[1m]', 'small_model': 'deepseek-flash', 'always_proceed': True}, indent=2) + '\n')
        config.chmod(0o600)
    settings = json.loads(config.read_text())
    key = legacy_key(home)
    if key and not settings.get('api_key'):
        settings['api_key'] = key
        config.write_text(json.dumps(settings, indent=2) + '\n')
        config.chmod(0o600)
    zsh_helpers = home / '.config/hyprland-setup/ai-tools.zsh'
    zsh_helpers.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / 'config/zsh/ai-tools.zsh', zsh_helpers)
    zshrc = home / '.zshrc'
    current = zshrc.read_text() if zshrc.exists() else ''
    if '# >>> hyprland-setup AI tools >>>' not in current:
        if zshrc.exists():
            backup = home / '.local/state/hyprland-setup/ai-tools' / datetime.now().strftime('%Y%m%d-%H%M%S-%f')
            backup.mkdir(parents=True, exist_ok=True)
            shutil.copy2(zshrc, backup / '.zshrc')
        zshrc.write_text(current.rstrip() + '\n\n' + ZSH_BLOCK + '\n')
    return launcher


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--home', type=Path, default=Path.home())
    print('DeepSeek custom launcher installed:', configure(parser.parse_args().home))
