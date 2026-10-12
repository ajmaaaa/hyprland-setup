"""Comprehensive test suite for ArchTidy."""
import os
from pathlib import Path
import tempfile
import unittest

from archtidy.core.candidate import Candidate
from archtidy.core.safety import is_blacklisted, DEFAULT_BLACKLIST
from archtidy.core.log import log_action, get_recent_actions
from archtidy.core.confirm import execute_cleanup, move_to_trash
from archtidy.modules.orphans import OrphanDetector
from archtidy.modules.packages import PackageCleaner
from archtidy.modules.duplicates import DuplicateFinder
from archtidy.modules.bigfiles import BigFileFinder


class TestCandidate(unittest.TestCase):
    def test_human_size(self):
        c1 = Candidate(Path("/test"), 500, "reason", 80, "test")
        self.assertEqual(c1.human_size, "500 B")

        c2 = Candidate(Path("/test"), 2048, "reason", 80, "test")
        self.assertEqual(c2.human_size, "2.0 KB")

        c3 = Candidate(Path("/test"), 1048576 * 15, "reason", 80, "test")
        self.assertEqual(c3.human_size, "15.0 MB")

        c4 = Candidate(Path("/test"), 1073741824 * 3, "reason", 80, "test")
        self.assertEqual(c4.human_size, "3.0 GB")

    def test_to_dict(self):
        c = Candidate(Path("/home/user/cache"), 1024, "Old cache", 75, "cache", True, {"foo": "bar"})
        d = c.to_dict()
        self.assertEqual(d["path"], "/home/user/cache")
        self.assertEqual(d["size_bytes"], 1024)
        self.assertEqual(d["score"], 75)
        self.assertEqual(d["selected"], True)
        self.assertEqual(d["details"]["foo"], "bar")


class TestSafety(unittest.TestCase):
    def test_blacklist_critical_paths(self):
        self.assertTrue(is_blacklisted(Path("/")))
        self.assertTrue(is_blacklisted(Path.home()))
        self.assertTrue(is_blacklisted(Path.home() / ".ssh"))
        self.assertTrue(is_blacklisted(Path.home() / ".ssh/id_rsa"))
        self.assertTrue(is_blacklisted(Path.home() / ".gnupg"))
        self.assertTrue(is_blacklisted(Path.home() / ".config/hypr"))
        self.assertTrue(is_blacklisted(Path("/etc")))
        self.assertTrue(is_blacklisted(Path("/etc/fstab")))

    def test_non_blacklisted_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            p = Path(tmpdir) / "safe_to_clean_cache"
            p.mkdir()
            self.assertFalse(is_blacklisted(p))

    def test_custom_blacklist(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            p = Path(tmpdir) / "custom_protected"
            p.mkdir()
            self.assertFalse(is_blacklisted(p))
            self.assertTrue(is_blacklisted(p, custom_blacklist=[str(p)]))


class TestConfirmPipeline(unittest.TestCase):
    def test_dry_run_does_not_delete(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "file_to_clean.txt"
            test_file.write_text("sample content")
            self.assertTrue(test_file.exists())

            cand = Candidate(test_file, 14, "Test reason", 90, "test", selected=True)
            res = execute_cleanup([cand], dry_run=True, create_btrfs_snapshot=False)

            self.assertTrue(test_file.exists())  # File still exists
            self.assertEqual(res.processed_count, 1)
            self.assertEqual(res.freed_bytes, 14)
            self.assertEqual(len(res.errors), 0)

    def test_blacklisted_candidate_is_blocked(self):
        ssh_dir = Path.home() / ".ssh"
        cand = Candidate(ssh_dir, 1024, "Accidental target", 100, "test", selected=True)
        res = execute_cleanup([cand], dry_run=False, create_btrfs_snapshot=False)

        self.assertEqual(res.processed_count, 0)
        self.assertEqual(len(res.errors), 1)
        self.assertIn("Blocked by safety blacklist", res.errors[0])


class TestDuplicateFinder(unittest.TestCase):
    def test_three_stage_duplicate_detection(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            dir_path = Path(tmpdir)
            f1 = dir_path / "original.txt"
            f2 = dir_path / "duplicate.txt"
            f3 = dir_path / "unique.txt"

            content = b"A" * 5000  # > 4KB prefix test
            f1.write_bytes(content)
            f2.write_bytes(content)
            f3.write_bytes(b"B" * 5000)

            finder = DuplicateFinder(scan_dir=str(dir_path), min_size_mb=0)
            finder.min_size_bytes = 100  # low threshold for unit test
            duplicates = finder.scan(target_dir=str(dir_path))

            self.assertEqual(len(duplicates), 1)
            self.assertEqual(duplicates[0].size_bytes, 5000)
            self.assertIn("Duplicate of original.txt", duplicates[0].reason)


class TestBigFileFinder(unittest.TestCase):
    def test_finds_only_large_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            dir_path = Path(tmpdir)
            small_file = dir_path / "small.dat"
            large_file = dir_path / "large.dat"

            small_file.write_bytes(b"1" * 100)
            large_file.write_bytes(b"2" * 10000)

            finder = BigFileFinder(scan_dir=str(dir_path), min_size_mb=0)
            finder.min_size_bytes = 5000  # 5KB threshold
            cands = finder.scan(target_dir=str(dir_path))

            self.assertEqual(len(cands), 1)
            self.assertEqual(cands[0].path.name, "large.dat")


class TestPackageCleaner(unittest.TestCase):
    def test_parse_pacman_size(self):
        cleaner = PackageCleaner()
        self.assertEqual(cleaner._parse_pacman_size("1024 B"), 1024)
        self.assertEqual(cleaner._parse_pacman_size("10.0 KiB"), 10240)
        self.assertEqual(cleaner._parse_pacman_size("2.5 MiB"), int(2.5 * 1024 * 1024))
        self.assertEqual(cleaner._parse_pacman_size("1 GiB"), 1024 * 1024 * 1024)


class TestOrphanScoring(unittest.TestCase):
    def test_orphan_confidence_scores(self):
        detector = OrphanDetector()
        detector._indexed = True
        detector._installed_pkgs = {"active-app"}
        detector._path_binaries = {"active-bin"}
        detector._desktop_apps = set()
        detector._running_procs = {"running-daemon"}

        # Running process -> score 0
        score, _ = detector.score_orphan(Path("running-daemon"), mtime=100.0)
        self.assertEqual(score, 0)

        # Installed package -> score 0
        score, _ = detector.score_orphan(Path("active-app"), mtime=100.0)
        self.assertEqual(score, 0)

        # Unknown app with old mtime (> 180 days)
        old_mtime = 1000000.0
        score, _ = detector.score_orphan(Path("old-deleted-app"), mtime=old_mtime)
        self.assertGreaterEqual(score, 75)


if __name__ == "__main__":
    unittest.main()
