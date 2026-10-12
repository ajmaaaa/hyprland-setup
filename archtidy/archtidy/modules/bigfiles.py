"""Large file finder module (F3).

Scans directories for large files (default >= 100MB) with high-performance os.scandir
traversal, pruning hidden dot-directories and dev build trees.
"""
from datetime import datetime, timezone
import os
from pathlib import Path
from typing import List, Optional, Union

from ..core.candidate import Candidate
from ..core.safety import is_blacklisted, expand_path


IGNORED_DIRS = {
    "node_modules",
    "development",
    "Git",
    "venv",
    ".venv",
    "build",
    "target",
    "vendor",
    ".cache",
    ".local",
    ".cargo",
    ".rustup",
    ".gradle",
    ".android",
    ".gemini",
}


class BigFileFinder:
    """Finds large files exceeding size threshold."""

    def __init__(
        self,
        scan_dir: Optional[Union[str, List[str]]] = None,
        min_size_mb: int = 100,
        custom_blacklist: Optional[List[str]] = None,
        max_results: int = 100,
    ):
        if scan_dir is None:
            self.scan_dirs = ["~/Downloads", "~/Videos", "~/Pictures", "~/Documents"]
        elif isinstance(scan_dir, str):
            self.scan_dirs = [scan_dir]
        else:
            self.scan_dirs = list(scan_dir)

        self.min_size_bytes = min_size_mb * 1024 * 1024
        self.custom_blacklist = custom_blacklist or []
        self.max_results = max_results

    def _is_ignored(self, name: str) -> bool:
        if name.startswith("."):
            return True
        return name in IGNORED_DIRS

    def scan(self, target_dir: Optional[str] = None) -> List[Candidate]:
        """Scan target directories recursively for large files."""
        dirs_to_scan = [target_dir] if target_dir else self.scan_dirs
        candidates: List[Candidate] = []

        def _scan_folder(folder: Path, is_root: bool = False):
            if not is_root and is_blacklisted(folder, self.custom_blacklist):
                return

            try:
                with os.scandir(folder) as it:
                    for entry in it:
                        try:
                            if entry.is_dir(follow_symlinks=False):
                                if self._is_ignored(entry.name):
                                    continue
                                p = Path(entry.path)
                                if not is_blacklisted(p, self.custom_blacklist):
                                    _scan_folder(p, is_root=False)
                            elif entry.is_file(follow_symlinks=False):
                                st = entry.stat()
                                if st.st_size >= self.min_size_bytes:
                                    p = Path(entry.path)
                                    if not is_blacklisted(p, self.custom_blacklist):
                                        mtime_dt = datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).strftime("%Y-%m-%d")
                                        cand = Candidate(
                                            path=p,
                                            size_bytes=st.st_size,
                                            reason=f"Large file ({st.st_size / (1024*1024):.1f} MB)",
                                            score=60,
                                            source="bigfile",
                                            selected=False,
                                            details={
                                                "modified": mtime_dt,
                                                "filename": entry.name,
                                            },
                                        )
                                        candidates.append(cand)
                        except (PermissionError, OSError):
                            continue
            except (PermissionError, OSError):
                return

        for d_str in dirs_to_scan:
            base_path = expand_path(d_str)
            if base_path.exists():
                _scan_folder(base_path, is_root=True)

        # Sort descending by size
        candidates.sort(key=lambda c: c.size_bytes, reverse=True)
        return candidates[: self.max_results]
