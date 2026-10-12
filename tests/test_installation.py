import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


archtidy = load('setup-archtidy')
screen = load('installer-screen')


class InstallationTests(unittest.TestCase):
    def test_fresh_archtidy_install_is_independent_of_checkout_and_preserves_config(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder) / 'another user'
            archtidy.configure(home)
            launcher = home / '.local/bin/archtidy'
            self.assertTrue(os.access(launcher, os.X_OK))
            self.assertNotIn(str(ROOT), launcher.read_text())
            self.assertTrue((home / '.local/share/archtidy/archtidy/modules/junk.py').exists())
            desktop = (home / '.local/share/applications/archtidy.desktop').read_text()
            self.assertIn(f'Exec="{launcher}"', desktop)
            config = home / '.config/archtidy/config.toml'
            config.write_text('[blacklist]\npaths = ["~/important"]\n')
            archtidy.configure(home)
            self.assertIn('important', config.read_text())
            result = subprocess.run([str(launcher), '--help'], cwd=folder,
                env={**os.environ, 'HOME': str(home), 'PYTHONPATH': ''}, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('ArchTidy', result.stdout)

    def test_fullscreen_targets_the_installing_terminal_and_restores_maximized_state(self):
        clients = [{'address': '0x111', 'pid': 12, 'fullscreen': 0},
                   {'address': '0x222', 'pid': 34, 'fullscreen': 1}]
        with patch.object(screen, 'ancestors', return_value={34}), patch.object(screen.subprocess, 'check_output', return_value=json.dumps(clients)), patch.object(screen, 'dispatch', return_value=True) as dispatch:
            state = screen.enter()
            self.assertEqual(state['address'], '0x222')
            screen.leave(state)
            self.assertEqual(dispatch.call_args.args, ('0x222', 'set', 'maximized'))

    def test_nonterminal_process_does_not_fullscreen_the_focused_window(self):
        with patch.object(screen, 'ancestors', return_value={34}), patch.object(screen.subprocess, 'check_output', return_value='[{"address":"0x111","pid":12,"fullscreen":0}]'), patch.object(screen, 'dispatch') as dispatch:
            self.assertEqual(screen.enter(), {})
            dispatch.assert_not_called()

    def test_retry_logs_are_visible_and_preserve_failure_status(self):
        with tempfile.TemporaryDirectory() as folder:
            log = Path(folder) / 'download.log'
            result = subprocess.run(['bash', '-c',
                'source "$1"; installer_run_logged "$2" bash -c \'printf "download progress\\n"; exit 7\'',
                'test', str(ROOT / 'scripts/installer-ui.sh'), str(log)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 7)
            self.assertIn('download progress', result.stdout)
            self.assertIn('download progress', log.read_text())

    def test_zsh_startup_without_optional_commands_and_theme_is_quiet_and_has_unique_path(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            commands = home / 'bin'
            commands.mkdir()
            (commands / 'mv').symlink_to('/usr/bin/mv')
            result = subprocess.run(['/usr/bin/zsh', '-dfc',
                'source "$1"; source "$1"; [[ "$EDITOR" == vi ]] || exit 2; '
                '[[ ${#path[(r)$HOME/.local/bin]} -gt 0 ]] || exit 3; '
                '[[ ${(M)#path:#$HOME/.local/bin} == 1 ]] || exit 4',
                'test', str(ROOT / 'dotfiles/.zshrc')],
                env={**os.environ, 'HOME': str(home), 'ZDOTDIR': str(home), 'PATH': str(commands), 'TERM': 'dumb'},
                capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stderr, '')


if __name__ == '__main__':
    unittest.main()
