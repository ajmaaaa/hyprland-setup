import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
PRELUDE = '''
source "$1/scripts/installer-ui.sh"
source "$1/scripts/installer-packages.sh"
info() { printf '%s\\n' "$1"; }
warn() { printf '%s\\n' "$1"; }
success() { printf '%s\\n' "$1"; }
'''


class PackageTransactionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.lock = self.folder / 'db.lck'
        self.env = {**os.environ, 'HOME': str(self.folder),
            'INSTALLER_PACMAN_LOCK': str(self.lock), 'INSTALLER_LOCK_INTERVAL': '0.02',
            'INSTALLER_LOCK_TIMEOUT': '2', 'YAY_CACHE_DIR': str(self.folder / 'yay')}

    def run_shell(self, code, **kwargs):
        return subprocess.run(['bash', '-c', PRELUDE + code, 'test', str(ROOT)],
            env=self.env, capture_output=True, text=True, timeout=10, **kwargs)

    def test_waits_for_owner_to_release_database_before_running_command(self):
        self.lock.touch()
        result = self.run_shell('''
(sleep 0.1; rm "$INSTALLER_PACMAN_LOCK") &
installer_package_command "$HOME/log" bash -c 'test ! -e "$INSTALLER_PACMAN_LOCK" && echo installed'
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Waiting for', result.stdout)
        self.assertIn('installed', result.stdout)

    def test_lock_timeout_preserves_lock_and_never_runs_package_command(self):
        self.lock.touch()
        self.env['INSTALLER_LOCK_TIMEOUT'] = '0'
        result = self.run_shell('installer_package_command "$HOME/log" touch "$HOME/unexpected"; status=$?; '
            '[[ "$INSTALLER_DATABASE_BLOCKED" == true ]] || exit 9; exit "$status"')
        self.assertEqual(result.returncode, 73)
        self.assertTrue(self.lock.exists())
        self.assertFalse((self.folder / 'unexpected').exists())

    def test_retries_lock_race_but_does_not_retry_unrelated_failure(self):
        command = self.folder / 'transaction'
        command.write_text('''#!/bin/bash
if [[ ! -e "$HOME/attempted" ]]; then
  touch "$HOME/attempted"
  echo 'error: could not lock database: File exists'
  exit 1
fi
echo installed
''')
        command.chmod(0o755)
        result = self.run_shell('installer_package_command "$HOME/log" "$HOME/transaction"')
        self.assertEqual(result.returncode, 0)
        self.assertIn('installed', result.stdout)
        result = self.run_shell('installer_package_command "$HOME/log" bash -c \'echo "download failed"; exit 7\'')
        self.assertEqual(result.returncode, 7)
        self.assertEqual(result.stdout.count('download failed'), 1)

    def test_second_installer_is_rejected_without_removing_any_lock(self):
        result = self.run_shell('''
installer_acquire_lock || exit 8
bash -c 'source "$1/scripts/installer-packages.sh"; warn() { echo "$1"; }; installer_acquire_lock' test "$1"
''')
        self.assertEqual(result.returncode, 1)
        self.assertIn('Another hyprland-setup', result.stdout)

    def signing_fixture(self):
        self.fingerprint = '1234567890ABCDEF1234567890ABCDEF12345678'
        cache = self.folder / 'yay/example'
        cache.mkdir(parents=True)
        (cache / '.SRCINFO').write_text(f'pkgbase = example\n\tvalidpgpkeys = {self.fingerprint}\n')
        return '''
timeout() { shift; "$@"; }
gpg() {
  printf '%s\\n' "$*" >> "$HOME/gpg-calls"
  if [[ " $* " == *" --fingerprint "* ]]; then
    printf 'fpr:::::::::1234567890ABCDEF1234567890ABCDEF12345678:\\n'
  fi
}
'''

    def test_missing_key_import_uses_declared_full_fingerprint(self):
        mock = self.signing_fixture()
        result = self.run_shell(mock + 'import_missing_pgp_key "unknown public key 90ABCDEF12345678" example')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        calls = (self.folder / 'gpg-calls').read_text()
        self.assertIn('--recv-keys ' + self.fingerprint, calls)
        self.assertNotIn('--recv-keys 90ABCDEF12345678', calls)

    def test_bad_signatures_and_unlisted_keys_never_trigger_import(self):
        mock = self.signing_fixture()
        for output in ('unknown public key AAAAAAAAAAAAAAAA', 'One or more PGP signatures could not be verified!',
                'BAD signature unknown public key 90ABCDEF12345678', 'KEYREVOKED 90ABCDEF12345678',
                'KEYEXPIRED 90ABCDEF12345678', 'FAILED checksum 90ABCDEF12345678'):
            with self.subTest(output=output):
                self.env['ERROR_TEXT'] = output
                result = self.run_shell(mock + 'import_missing_pgp_key "$ERROR_TEXT" example')
                self.assertEqual(result.returncode, 1)
                self.assertFalse((self.folder / 'gpg-calls').exists())

    def test_downloaded_key_with_wrong_fingerprint_is_rejected(self):
        mock = self.signing_fixture()
        # The declared fingerprint still matches the error; the fetched key does not.
        mock = mock.replace("printf 'fpr:::::::::1234567890ABCDEF1234567890ABCDEF12345678:",
            "printf 'fpr:::::::::AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA:")
        result = self.run_shell(mock + 'import_missing_pgp_key "unknown public key 90ABCDEF12345678" example')
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
