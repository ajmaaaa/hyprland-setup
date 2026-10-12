"""Android, Waydroid, and ADB cache cleanup module (F7).

Detects residual APKs, ADB pull dumps, temporary scrcpy caches, and Waydroid images.
"""
import glob
import os
from pathlib import Path
from typing import List, Optional

from ..core.candidate import Candidate
from ..core.safety import is_blacklisted, expand_path


class AndroidCleaner:
    """Detects temporary and cache files from Android tools (ADB, Scrcpy, Waydroid)."""

    def __init__(self, custom_blacklist: Optional[List[str]] = None):
        self.custom_blacklist = custom_blacklist or []

    def _get_dir_size(self, path: Path) -> int:
        """Calculate total directory or file size."""
        if path.is_file():
            try:
                return path.stat().st_size
            except OSError:
                return 0
        total = 0
        try:
            for root, _, files in os.walk(path):
                for f in files:
                    try:
                        total += os.lstat(os.path.join(root, f)).st_size
                    except OSError:
                        continue
        except OSError:
            pass
        return total

    def scan(self) -> List[Candidate]:
        """Scan system for Android-related cache candidates."""
        candidates: List[Candidate] = []

        targets = [
            ("~/.local/share/waydroid/cache", "Waydroid container cache", 80),
            ("~/.cache/waydroid", "Waydroid image cache", 85),
            ("~/.android/cache", "Android SDK / ADB download cache", 80),
            ("~/.android/build-cache", "Android legacy build cache", 85),
            ("~/.gradle/caches/transforms-3", "Android Gradle transforms cache", 75),
        ]

        for target_str, reason, score in targets:
            target_path = expand_path(target_str)
            if target_path.exists() and not is_blacklisted(target_path, self.custom_blacklist):
                sz = self._get_dir_size(target_path)
                if sz > 1024 * 1024:  # > 1 MB
                    candidates.append(
                        Candidate(
                            path=target_path,
                            size_bytes=sz,
                            reason=reason,
                            score=score,
                            source="android",
                            selected=False,
                            details={"type": "android_cache"},
                        )
                    )

        # Temporary files in /tmp (e.g. /tmp/scrcpy*, /tmp/adb*)
        for pattern, desc in [("/tmp/scrcpy*", "Scrcpy temporary dumps"), ("/tmp/adb.*", "ADB temporary socket dumps")]:
            for matched in glob.glob(pattern):
                mp = Path(matched)
                if mp.exists() and not is_blacklisted(mp, self.custom_blacklist):
                    sz = self._get_dir_size(mp)
                    if sz > 0:
                        candidates.append(
                            Candidate(
                                path=mp,
                                size_bytes=sz,
                                reason=desc,
                                score=90,
                                source="android",
                                selected=True,
                                details={"type": "temp_file"},
                            )
                        )

        return candidates
