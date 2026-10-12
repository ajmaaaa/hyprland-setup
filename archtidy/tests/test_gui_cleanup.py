import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from archtidy.core.candidate import Candidate
from archtidy.core.confirm import execute_cleanup, undo_recent_batch
from archtidy.core import confirm
from datetime import datetime


class CleanupRepairsTest(unittest.TestCase):
    def test_restore_uses_metadata_not_filename_and_never_overwrites(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            trash = root / 'Trash'
            (trash / 'info').mkdir(parents=True)
            (trash / 'files').mkdir()
            original = root / 'notes.txt'
            (trash / 'files/notes.txt').write_text('restored data')
            stamp = datetime.now().isoformat()
            (trash / 'info/notes.txt.trashinfo').write_text('[Trash Info]\nPath=' + str(original) + '\nDeletionDate=' + stamp + '\n')
            logs = [{'action': 'dry_run', 'batch_id': 'new-simulation'}, {'action': 'trash', 'status': 'success', 'batch_id': 'real', 'path': str(original), 'timestamp': stamp}]
            with patch.dict(os.environ, {'XDG_DATA_HOME': folder}), patch.object(confirm, 'get_recent_actions', return_value=logs), patch.object(confirm, 'log_action'):
                self.assertIn('Restored:', undo_recent_batch()[0])
                self.assertEqual(original.read_text(), 'restored data')
                self.assertIn('destination exists', undo_recent_batch()[0])

    def test_gui_package_command_does_not_remove_unreviewed_dependencies(self):
        candidate = Candidate(Path('/var/lib/pacman/local/example'), 10, '', 95, 'package', True, {'pkg_name': 'example'})
        with patch.object(confirm.subprocess, 'run') as run, patch.object(confirm, 'log_action'):
            run.return_value.returncode = 0
            result = execute_cleanup([candidate], dry_run=False, create_btrfs_snapshot=False, admin_command=['pkexec'])
            self.assertEqual(run.call_args.args[0], ['pkexec', 'pacman', '-R', '--noconfirm', '--', 'example'])
            self.assertEqual(result.processed_count, 1)

    def test_system_archive_authentication_is_scoped_to_reviewed_file(self):
        candidate = Candidate(Path('/var/cache/pacman/pkg/example-1.pkg.tar.zst'), 10, '', 90, 'cache', True)
        with patch.object(Path, 'is_file', return_value=True), patch.object(Path, 'is_symlink', return_value=False), patch.object(confirm.subprocess, 'run') as run, patch.object(confirm, 'log_action'):
            run.return_value.returncode = 0
            result = execute_cleanup([candidate], dry_run=False, create_btrfs_snapshot=False, admin_command=['pkexec'])
            self.assertEqual(run.call_args.args[0], ['pkexec', '/usr/bin/rm', '--', str(candidate.path)])
            self.assertEqual(result.processed_count, 1)

    def test_system_archive_symlink_is_never_removed(self):
        candidate = Candidate(Path('/var/cache/pacman/pkg/example-1.pkg.tar.zst'), 10, '', 90, 'cache', True)
        with patch.object(confirm, 'is_blacklisted', return_value=False), patch.object(Path, 'is_symlink', return_value=True), patch.object(confirm.subprocess, 'run') as run:
            result = execute_cleanup([candidate], dry_run=False, create_btrfs_snapshot=False, admin_command=['pkexec'])
            run.assert_not_called()
            self.assertEqual(result.processed_count, 0)
            self.assertTrue(result.errors)


if __name__ == '__main__':
    unittest.main()
