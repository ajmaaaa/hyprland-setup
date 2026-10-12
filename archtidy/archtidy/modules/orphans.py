"""Orphan configuration and cache detector (F1).

Scans ~/.config, ~/.cache, ~/.local/share, ~/.local/state for residual files left behind
by uninstalled applications and scores confidence (0-100) based on mtime, PATH,
desktop files, and running processes.
"""
from datetime import datetime, timezone
import os
from pathlib import Path
import subprocess
import time
from typing import Dict, List, Set, Optional

from ..core.candidate import Candidate
from ..core.safety import is_blacklisted, expand_path


class OrphanDetector:
    """Detects leftover configuration and cache folders from uninstalled apps."""

    def __init__(
        self,
        scan_dirs: Optional[List[str]] = None,
        min_confidence: int = 70,
        custom_blacklist: Optional[List[str]] = None,
    ):
        self.scan_dirs = scan_dirs or [
            "~/.config",
            "~/.cache",
            "~/.local/share",
            "~/.local/state",
        ]
        self.min_confidence = min_confidence
        self.custom_blacklist = custom_blacklist or []

        # Caches
        self._installed_pkgs: Set[str] = set()
        self._path_binaries: Set[str] = set()
        self._desktop_apps: Set[str] = set()
        self._running_procs: Set[str] = set()
        self._indexed = False

    def build_system_index(self) -> None:
        """Build sets of installed packages, PATH executables, desktop files, and running processes."""
        # 1. Pacman packages
        try:
            res = subprocess.run(
                ["pacman", "-Qq"], capture_output=True, text=True, timeout=10
            )
            if res.returncode == 0:
                self._installed_pkgs = {
                    line.strip().lower() for line in res.stdout.splitlines() if line.strip()
                }
        except Exception:
            self._installed_pkgs = set()

        # 2. Executables in PATH
        self._path_binaries = set()
        for p in os.environ.get("PATH", "").split(":"):
            if p and os.path.isdir(p):
                try:
                    for entry in os.listdir(p):
                        self._path_binaries.add(entry.lower())
                except (PermissionError, OSError):
                    continue

        # 3. Desktop files and their Exec entries
        self._desktop_apps = set()
        desktop_dirs = [
            Path("/usr/share/applications"),
            Path("/usr/local/share/applications"),
            expand_path("~/.local/share/applications"),
        ]
        for ddir in desktop_dirs:
            if ddir.exists():
                for dfile in ddir.glob("*.desktop"):
                    self._desktop_apps.add(dfile.stem.lower())
                    try:
                        content = dfile.read_text(encoding="utf-8", errors="ignore")
                        for line in content.splitlines():
                            if line.startswith("Exec="):
                                cmd = line[5:].strip().split()[0]
                                self._desktop_apps.add(Path(cmd).name.lower())
                    except Exception:
                        pass

        # 4. Running processes
        self._running_procs = set()
        try:
            res = subprocess.run(
                ["ps", "-eo", "comm="], capture_output=True, text=True, timeout=5
            )
            if res.returncode == 0:
                self._running_procs = {
                    line.strip().lower() for line in res.stdout.splitlines() if line.strip()
                }
        except Exception:
            # Fallback to /proc
            try:
                for pid_dir in Path("/proc").iterdir():
                    if pid_dir.is_dir() and pid_dir.name.isdigit():
                        comm_file = pid_dir / "comm"
                        if comm_file.exists():
                            self._running_procs.add(comm_file.read_text().strip().lower())
            except Exception:
                pass

        self._indexed = True

    def _get_dir_size_and_mtime(self, path: Path) -> tuple[int, float]:
        """Compute total size in bytes and latest modification time."""
        total_size = 0
        latest_mtime = 0.0

        if path.is_file():
            stat = path.stat()
            return stat.st_size, stat.st_mtime

        try:
            stat = path.stat()
            latest_mtime = stat.st_mtime
        except OSError:
            pass

        try:
            for root, dirs, files in os.walk(path):
                for f in files:
                    fp = os.path.join(root, f)
                    try:
                        st = os.lstat(fp)
                        total_size += st.st_size
                        if st.st_mtime > latest_mtime:
                            latest_mtime = st.st_mtime
                    except OSError:
                        continue
        except OSError:
            pass

        return total_size, latest_mtime

    def is_known_entity(self, name: str) -> bool:
        """Check if an entity name is recognized in packages, binaries, or desktop files."""
        lower_name = name.lower()
        if lower_name in self._installed_pkgs:
            return True
        if lower_name in self._path_binaries:
            return True
        if lower_name in self._desktop_apps:
            return True

        # Strip common prefixes/suffixes (e.g. -bin, -git, org.gnome., io.github.)
        clean_name = lower_name.split(".")[-1]
        if clean_name in self._installed_pkgs or clean_name in self._path_binaries:
            return True

        return False

    def score_orphan(self, path: Path, mtime: float) -> tuple[int, str]:
        """Calculate confidence score (0-100) and rationale for an orphan directory."""
        name = path.name.lower()

        # If a running process matches exactly, definitely NOT orphan
        if name in self._running_procs:
            return 0, "Active process currently running"

        # If known installed package or binary
        if self.is_known_entity(name):
            return 0, "Matches installed package, binary, or desktop app"

        # Base confidence for unowned item
        score = 50
        reason_parts = ["No installed package or binary found"]

        # Modification time evaluation
        now = time.time()
        age_days = (now - mtime) / 86400.0 if mtime > 0 else 999.0

        if age_days > 180:
            score += 25
            reason_parts.append(f"Untouched for >180 days ({int(age_days)}d)")
        elif age_days > 30:
            score += 10
            reason_parts.append(f"Untouched for >30 days ({int(age_days)}d)")
        elif age_days < 7:
            score -= 40
            reason_parts.append(f"Recently modified ({int(age_days)}d)")

        # Cap score between 0 and 100
        score = max(0, min(100, score))
        return score, "; ".join(reason_parts)

    def scan(self) -> List[Candidate]:
        """Scan configured directories and return list of orphan candidates."""
        if not self._indexed:
            self.build_system_index()

        candidates: List[Candidate] = []

        for dir_str in self.scan_dirs:
            base_dir = expand_path(dir_str)
            if not base_dir.exists() or not base_dir.is_dir():
                continue

            try:
                entries = list(base_dir.iterdir())
            except PermissionError:
                continue

            for entry in entries:
                if is_blacklisted(entry, self.custom_blacklist):
                    continue

                name = entry.name.lower()
                if name in self._running_procs or self.is_known_entity(name):
                    continue

                try:
                    st = entry.stat()
                    mtime = st.st_mtime
                except OSError:
                    mtime = 0.0

                score, reason = self.score_orphan(entry, mtime)
                if score < self.min_confidence:
                    continue

                # Only compute expensive recursive directory size for true orphan candidates
                size_bytes, mtime = self._get_dir_size_and_mtime(entry)
                if size_bytes == 0:
                    continue

                age_days = int((time.time() - mtime) / 86400.0) if mtime > 0 else 0
                mtime_dt = datetime.fromtimestamp(mtime, tz=timezone.utc).strftime("%Y-%m-%d") if mtime > 0 else "unknown"

                cand = Candidate(
                    path=entry,
                    size_bytes=size_bytes,
                    reason=reason,
                    score=score,
                    source="orphan",
                    selected=False,
                    details={
                        "scan_dir": str(base_dir),
                        "last_modified": mtime_dt,
                        "age_days": age_days,
                    },
                )
                candidates.append(cand)

        # Sort candidates descending by confidence score, then by size
        candidates.sort(key=lambda c: (c.score, c.size_bytes), reverse=True)
        return candidates
