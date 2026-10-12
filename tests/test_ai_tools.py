import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def load(path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


profiles = load(ROOT / 'scripts/setup-ai-tools.py')
deepseek = load(ROOT / 'config/scripts/claude-deepseek.py')


class AiToolTests(unittest.TestCase):
    def test_default_selection_keeps_antigravity_available_but_off(self):
        command = 'source "$1"; DEFAULT_OFF_FILE="$2"; recommended_packages "$3"'
        result = subprocess.run(['bash', '-c', command, 'test', str(ROOT / 'scripts/package-selection.sh'),
            str(ROOT / 'packages/default-off.txt'), str(ROOT / 'packages/aur.txt')], capture_output=True, text=True, check=True)
        self.assertNotIn('antigravity-ide', result.stdout.splitlines())
        self.assertIn('android-studio', result.stdout.splitlines())
        self.assertIn('antigravity-ide', (ROOT / 'packages/aur.txt').read_text().splitlines())

    def test_checklist_starts_antigravity_off_but_accepts_explicit_selection(self):
        with tempfile.TemporaryDirectory() as folder:
            capture = Path(folder) / 'dialog.args'
            command = '''source "$1"
DEFAULT_OFF_FILE="$2"
CAPTURE="$4"
declare -A INSTALLED_PKGS=()
dialog() { printf '%s\\n' "$@" > "$CAPTURE"; printf '"antigravity-ide"\\n' >&2; }
clear() { :; }
selected=()
show_checklist "AUR" "$3" selected
printf '%s\\n' "${selected[@]}"
'''
            result = subprocess.run(['bash', '-c', command, 'test', str(ROOT / 'scripts/package-selection.sh'),
                str(ROOT / 'packages/default-off.txt'), str(ROOT / 'packages/aur.txt'), str(capture)],
                capture_output=True, text=True, check=True)
            args = capture.read_text().splitlines()
            self.assertEqual(args[args.index('antigravity-ide') + 2], 'off')
            self.assertEqual(result.stdout.strip(), 'antigravity-ide')

    def test_deepseek_is_scoped_to_child_environment_and_key_is_not_in_arguments(self):
        original = {'HOME': '/home/test user', 'DEEPSEEK_API_KEY': 'test-deepseek-key',
                    'ANTHROPIC_API_KEY': 'test-claude-key', 'ANTHROPIC_MODEL': 'claude-sonnet'}
        saved = dict(original)
        args, env = deepseek.build_launch({'model': 'custom-deepseek'}, original, ['--continue'])
        self.assertEqual(original, saved)
        self.assertNotIn('ANTHROPIC_API_KEY', env)
        self.assertEqual(env['ANTHROPIC_AUTH_TOKEN'], 'test-deepseek-key')
        self.assertEqual(env['ANTHROPIC_MODEL'], 'custom-deepseek')
        self.assertNotIn('test-deepseek-key', ' '.join(args))
        self.assertTrue(env['CLAUDE_CONFIG_DIR'].endswith('claude-deepseek/state'))
        self.assertEqual(args[-1], '--continue')

    def test_missing_key_is_reported_without_using_claude_credentials(self):
        with self.assertRaisesRegex(ValueError, 'DEEPSEEK_API_KEY'):
            deepseek.build_launch({}, {'HOME': '/home/test', 'ANTHROPIC_API_KEY': 'test-claude-key'}, [])

    def test_profile_install_preserves_normal_and_custom_settings(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            original = home / '.claude/settings.json'
            original.parent.mkdir()
            original.write_text('{"model":"claude-sonnet"}')
            launcher = profiles.configure(home)
            self.assertTrue(os.access(launcher, os.X_OK))
            self.assertEqual(original.read_text(), '{"model":"claude-sonnet"}')
            config = home / '.config/claude-deepseek/config.json'
            self.assertEqual(config.stat().st_mode & 0o777, 0o600)
            settings = {'base_url': 'https://custom.example/anthropic', 'model': 'custom-model'}
            config.write_text(json.dumps(settings))
            profiles.configure(home)
            self.assertEqual(json.loads(config.read_text()), settings)


if __name__ == '__main__':
    unittest.main()
