"""Package cleanup and clean uninstall module (F2, F5).

Manages pacman orphan packages (pacman -Qtdq), pacman cache (/var/cache/pacman/pkg),
AUR build cache (~/.cache/yay), and clean uninstallation with residual config detection.
"""
from datetime import datetime
import os
from pathlib import Path
import re
import shutil
import subprocess
from typing import Dict, List, Optional, Tuple

from ..core.candidate import Candidate
from ..core.safety import is_blacklisted, expand_path


class PackageCleaner:
    """Manages orphan packages, package caches, and uninstallation."""

    def __init__(self, aur_helper: str = "yay", custom_blacklist: Optional[List[str]] = None):
        self.aur_helper = aur_helper if shutil.which(aur_helper) else "pacman"
        self.custom_blacklist = custom_blacklist or []

    def get_orphan_packages(self) -> List[Candidate]:
        """Detect unneeded dependencies using pacman -Qtdq."""
        candidates: List[Candidate] = []
        try:
            res = subprocess.run(
                ["pacman", "-Qtdq"], capture_output=True, text=True, timeout=10
            )
            if res.returncode != 0 or not res.stdout.strip():
                return []

            pkg_names = [line.strip() for line in res.stdout.splitlines() if line.strip()]
        except Exception:
            return []

        # Batch query package info using a single pacman -Qi call
        try:
            info_res = subprocess.run(
                ["pacman", "-Qi"] + pkg_names, capture_output=True, text=True, timeout=10
            )
            if info_res.returncode == 0:
                blocks = info_res.stdout.split("\n\n")
                for block in blocks:
                    cur_pkg = ""
                    size_bytes = 0
                    desc = "Orphan dependency"
                    version = ""
                    for line in block.splitlines():
                        if line.startswith("Name"):
                            cur_pkg = line.split(":", 1)[1].strip()
                        elif line.startswith("Installed Size"):
                            size_str = line.split(":", 1)[1].strip()
                            size_bytes = self._parse_pacman_size(size_str)
                        elif line.startswith("Description"):
                            desc = line.split(":", 1)[1].strip()
                        elif line.startswith("Version"):
                            version = line.split(":", 1)[1].strip()

                    if cur_pkg:
                        cand = Candidate(
                            path=Path(f"/var/lib/pacman/local/{cur_pkg}"),
                            size_bytes=size_bytes,
                            reason=f"Unneeded orphan dependency: {desc}",
                            score=95,
                            source="package",
                            selected=True,
                            details={
                                "pkg_name": cur_pkg,
                                "version": version,
                                "description": desc,
                            },
                        )
                        candidates.append(cand)
        except Exception:
            pass

        return candidates


    def get_pacman_cache_candidates(self, keep_versions: int = 2) -> List[Candidate]:
        """Find old package archive files in pacman cache."""
        cache_dir = Path("/var/cache/pacman/pkg")
        if not cache_dir.exists() or not cache_dir.is_dir():
            return []

        candidates: List[Candidate] = []

        # If paccache is available, we can parse dry-run
        if shutil.which("paccache"):
            try:
                res = subprocess.run(
                    ["paccache", "-d", "-k", str(keep_versions), "-v"],
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                if res.returncode == 0:
                    for line in res.stdout.splitlines():
                        line = line.strip()
                        if line.startswith("/") and os.path.isfile(line):
                            p = Path(line)
                            try:
                                sz = p.stat().st_size
                            except OSError:
                                sz = 0
                            candidates.append(
                                Candidate(
                                    path=p,
                                    size_bytes=sz,
                                    reason=f"Old cached package (keeping {keep_versions})",
                                    score=90,
                                    source="cache",
                                    selected=True,
                                    details={"pkg_file": p.name},
                                )
                            )
                    if candidates:
                        return candidates
            except Exception:
                pass

        # Native fallback: group package versions in /var/cache/pacman/pkg
        try:
            pkg_groups: Dict[str, List[Path]] = {}
            pkg_pattern = re.compile(r"^(.+)-([^-]+-[^-]+)-(any|x86_64|aarch64)\.pkg\.tar\.(zst|xz|gz)$")

            for entry in cache_dir.iterdir():
                if not entry.is_file():
                    continue
                m = pkg_pattern.match(entry.name)
                if m:
                    base_name = m.group(1)
                    pkg_groups.setdefault(base_name, []).append(entry)

            for base_name, files in pkg_groups.items():
                if len(files) > keep_versions:
                    # Sort by modification time ascending (oldest first)
                    files.sort(key=lambda p: p.stat().st_mtime)
                    # Mark candidates exceeding keep_versions
                    excess = files[:-keep_versions]
                    for old_file in excess:
                        try:
                            sz = old_file.stat().st_size
                        except OSError:
                            sz = 0
                        candidates.append(
                            Candidate(
                                path=old_file,
                                size_bytes=sz,
                                reason=f"Superseded package cache for {base_name}",
                                score=90,
                                source="cache",
                                selected=True,
                                details={"pkg_file": old_file.name},
                            )
                        )
        except (PermissionError, OSError):
            pass

        return candidates

    def get_aur_cache_candidates(self) -> List[Candidate]:
        """Detect AUR build cache files and leftovers in ~/.cache/yay."""
        aur_cache_dir = expand_path("~/.cache/yay")
        if not aur_cache_dir.exists() or not aur_cache_dir.is_dir():
            return []

        candidates: List[Candidate] = []

        try:
            for entry in aur_cache_dir.iterdir():
                if not entry.is_dir() or is_blacklisted(entry, self.custom_blacklist):
                    continue

                total_sz = 0
                has_pkg_tar = False
                has_src_dir = False

                for root, dirs, files in os.walk(entry):
                    if "src" in dirs or "pkg" in dirs:
                        has_src_dir = True
                    for f in files:
                        fp = os.path.join(root, f)
                        if f.endswith((".pkg.tar.zst", ".pkg.tar.xz")):
                            has_pkg_tar = True
                        try:
                            total_sz += os.lstat(fp).st_size
                        except OSError:
                            continue

                if total_sz > 0:
                    reason = "AUR build artifacts"
                    if has_pkg_tar:
                        reason += " (includes built .pkg.tar)"
                    elif has_src_dir:
                        reason += " (compiled source tree)"

                    candidates.append(
                        Candidate(
                            path=entry,
                            size_bytes=total_sz,
                            reason=reason,
                            score=85,
                            source="cache",
                            selected=True,
                            details={"aur_package": entry.name},
                        )
                    )
        except Exception:
            pass

        return candidates

    def find_package_leftovers(self, pkg_name: str) -> List[Candidate]:
        """Find leftover configuration and cache directories for a given package."""
        leftovers: List[Candidate] = []
        user_dirs = ["~/.config", "~/.cache", "~/.local/share", "~/.local/state"]

        for d in user_dirs:
            base = expand_path(d)
            target = base / pkg_name
            if target.exists() and not is_blacklisted(target, self.custom_blacklist):
                sz = 0
                if target.is_file():
                    sz = target.stat().st_size
                else:
                    for root, _, files in os.walk(target):
                        for f in files:
                            try:
                                sz += os.lstat(os.path.join(root, f)).st_size
                            except OSError:
                                pass
                leftovers.append(
                    Candidate(
                        path=target,
                        size_bytes=sz,
                        reason=f"Residual configuration/cache for {pkg_name}",
                        score=95,
                        source="orphan",
                        selected=True,
                        details={"pkg_name": pkg_name},
                    )
                )

        return leftovers

    def _parse_pacman_size(self, size_str: str) -> int:
        """Parse pacman size string like '12.34 MiB' or '567 KiB' to integer bytes."""
        units = {
            "b": 1,
            "bytes": 1,
            "kib": 1024,
            "kb": 1000,
            "mib": 1024 * 1024,
            "mb": 1000 * 1000,
            "gib": 1024 * 1024 * 1024,
            "gb": 1000 * 1000 * 1000,
        }
        parts = size_str.strip().lower().split()
        if not parts:
            return 0
        try:
            val = float(parts[0])
            unit = parts[1] if len(parts) > 1 else "bytes"
            mult = units.get(unit, 1)
            return int(val * mult)
        except Exception:
            return 0
