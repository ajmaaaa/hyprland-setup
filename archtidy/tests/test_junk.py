import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from archtidy.core.candidate import Candidate
from archtidy.modules.junk import JunkCleaner


class JunkTests(unittest.TestCase):
    def test_only_stale_thumbnails_are_included_and_nothing_is_selected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            cache = root / 'thumbnails'
            normal = cache / 'normal'
            normal.mkdir(parents=True)
            old = normal / 'old.png'
            recent = normal / 'recent.png'
            unrelated = normal / 'notes.txt'
            personal = root / 'photo.png'
            for path in (old, recent, unrelated, personal):
                path.write_bytes(b'data')
            stale = time.time() - 40 * 86400
            for path in (old, unrelated, personal):
                os.utime(path, (stale, stale))
            (normal / 'linked.png').symlink_to(personal)
            with patch('archtidy.modules.junk.PackageCleaner.get_pacman_cache_candidates', return_value=[]):
                items = JunkCleaner(thumbnail_dir=cache).scan()
            self.assertEqual([item.path for item in items], [old])
            self.assertFalse(items[0].selected)
            self.assertTrue(personal.exists())
            self.assertTrue(old.exists())

    def test_blacklist_applies_to_thumbnails_and_package_archives(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            cache = root / 'thumbnails'
            (cache / 'normal').mkdir(parents=True)
            thumbnail = cache / 'normal' / 'old.png'
            archive = root / 'example-1.pkg.tar.zst'
            for path in (thumbnail, archive):
                path.write_bytes(b'data')
                stale = time.time() - 40 * 86400
                os.utime(path, (stale, stale))
            item = Candidate(archive, 4, 'Old cached package', 90, 'cache', True)
            with patch('archtidy.modules.junk.PackageCleaner.get_pacman_cache_candidates', return_value=[item]):
                items = JunkCleaner(thumbnail_dir=cache, custom_blacklist=[str(cache), str(archive)]).scan()
            self.assertEqual(items, [])

    def test_archive_scan_keeps_two_versions_and_does_not_select_packages(self):
        with tempfile.TemporaryDirectory() as folder:
            archive = Path(folder) / 'example-1.pkg.tar.zst'
            archive.write_bytes(b'data')
            candidate = Candidate(archive, 4, 'Old cached package', 90, 'cache', True)
            with patch('archtidy.modules.junk.PackageCleaner.get_pacman_cache_candidates', return_value=[candidate]) as scan:
                items = JunkCleaner(thumbnail_dir=Path(folder) / 'missing').scan()
            scan.assert_called_once_with(keep_versions=2)
            self.assertFalse(items[0].selected)
            self.assertEqual(items[0].details['junk_kind'], 'superseded_package_archive')
            self.assertTrue(archive.exists())


if __name__ == '__main__':
    unittest.main()
