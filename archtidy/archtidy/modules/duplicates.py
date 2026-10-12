"""Duplicate file detector module (F4).

Implements high-performance 3-stage hashing:
Stage 1: Filter by exact file size.
Stage 2: 4KB prefix hash for collision pruning.
Stage 3: Full SHA-256 verification.
Prunes hidden dot-directories and dev build trees.
"""
from collections import defaultdict
import hashlib
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

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


class DuplicateFinder:
    """Finds duplicate files using 3-stage hashing."""

    def __init__(
        self,
        scan_dir: Optional[Union[str, List[str]]] = None,
        min_size_mb: int = 1,
        custom_blacklist: Optional[List[str]] = None,
    ):
        if scan_dir is None:
            self.scan_dirs = ["~/Downloads", "~/Videos", "~/Pictures"]
        elif isinstance(scan_dir, str):
            self.scan_dirs = [scan_dir]
        else:
            self.scan_dirs = list(scan_dir)

        self.min_size_bytes = min_size_mb * 1024 * 1024
        self.custom_blacklist = custom_blacklist or []

    def _is_ignored(self, name: str) -> bool:
        if name.startswith("."):
            return True
        return name in IGNORED_DIRS

    def _hash_prefix_suffix(self, path: Path, chunk_size: int = 4096) -> str:
        """Hash first 4KB and last 4KB of a file to quickly eliminate non-duplicates."""
        hasher = hashlib.md5()
        try:
            with open(path, "rb") as f:
                head = f.read(chunk_size)
                hasher.update(head)
                f.seek(0, os.SEEK_END)
                size = f.tell()
                if size > chunk_size * 2:
                    f.seek(-chunk_size, os.SEEK_END)
                    tail = f.read(chunk_size)
                    hasher.update(tail)
            return hasher.hexdigest()
        except OSError:
            return ""

    def _hash_full(self, path: Path, chunk_size: int = 262144) -> str:
        """Compute full SHA-256 hash with 256KB I/O buffer."""
        hasher = hashlib.sha256()
        try:
            with open(path, "rb") as f:
                while chunk := f.read(chunk_size):
                    hasher.update(chunk)
            return hasher.hexdigest()
        except OSError:
            return ""

    def scan(self, target_dir: Optional[str] = None) -> List[Candidate]:
        """Scan directories and return list of duplicate candidate files with high performance."""
        dirs_to_scan = [target_dir] if target_dir else self.scan_dirs

        # Stage 1: Group by exact size in bytes using fast os.scandir traversal
        size_map: Dict[int, List[Path]] = defaultdict(list)

        def _walk_dir(folder: Path):
            if is_blacklisted(folder, self.custom_blacklist):
                return
            try:
                with os.scandir(folder) as it:
                    for entry in it:
                        try:
                            if entry.is_dir(follow_symlinks=False):
                                if not self._is_ignored(entry.name):
                                    _walk_dir(Path(entry.path))
                            elif entry.is_file(follow_symlinks=False):
                                st = entry.stat()
                                if st.st_size >= self.min_size_bytes:
                                    p = Path(entry.path)
                                    if not is_blacklisted(p, self.custom_blacklist):
                                        size_map[st.st_size].append(p)
                        except (PermissionError, OSError):
                            continue
            except (PermissionError, OSError):
                return

        for d_str in dirs_to_scan:
            base_path = expand_path(d_str)
            if base_path.exists() and base_path.is_dir():
                _walk_dir(base_path)

        # Filter sizes with at least 2 files
        size_candidates = {sz: paths for sz, paths in size_map.items() if len(paths) > 1}

        # Stage 2: Fast Double-Ended Hash (First 4KB + Last 4KB) filtering
        prefix_map: Dict[Tuple[int, str], List[Path]] = defaultdict(list)
        for sz, paths in size_candidates.items():
            for p in paths:
                p_hash = self._hash_prefix_suffix(p)
                if p_hash:
                    prefix_map[(sz, p_hash)].append(p)

        prefix_candidates = {k: paths for k, paths in prefix_map.items() if len(paths) > 1}

        # Stage 3: Full SHA-256 hash verification (only for candidates matching size and double-end hashes)
        full_map: Dict[str, List[Path]] = defaultdict(list)
        for _, paths in prefix_candidates.items():
            for p in paths:
                f_hash = self._hash_full(p)
                if f_hash:
                    full_map[f_hash].append(p)

        candidates: List[Candidate] = []

        # Convert duplicate groups into Candidate objects
        for _, duplicates in full_map.items():
            if len(duplicates) > 1:
                # Primary is kept (oldest file)
                duplicates.sort(key=lambda p: p.stat().st_mtime)
                primary = duplicates[0]

                # Other duplicates are cleanup candidates
                for dup in duplicates[1:]:
                    try:
                        sz = dup.stat().st_size
                    except OSError:
                        sz = 0

                    cand = Candidate(
                        path=dup,
                        size_bytes=sz,
                        reason=f"Duplicate of {primary.name}",
                        score=90,
                        source="duplicate",
                        selected=False,
                        details={
                            "primary_file": str(primary),
                            "duplicate_count": len(duplicates),
                        },
                    )
                    candidates.append(cand)

        # Sort descending by size
        candidates.sort(key=lambda c: c.size_bytes, reverse=True)
        return candidates
