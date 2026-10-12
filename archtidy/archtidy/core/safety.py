"""Safety enforcement: blacklist verification, dry-run checks, and Btrfs snapshots."""
import os
from pathlib import Path
import shutil
import subprocess
from typing import List, Optional


DEFAULT_BLACKLIST: List[str] = [
    "~/.ssh",
    "~/.gnupg",
    "~/.config/Code/User",
    "~/.mozilla",
    "~/.local/share/keyrings",
    "~/Documents",
    "~/.password-store",
    "~/.config/hypr",
    "~/.git",
    "~/.local/state/hypr-connections",
    "~/.local/state/archtidy",
    "~/.local/state/hyprland-repair",
    "/etc",
    "/boot",
    "/usr",
    "/bin",
    "/sbin",
    "/lib",
    "/lib64",
    "/dev",
    "/proc",
    "/sys",
]


def expand_path(p: str) -> Path:
    """Safely expand user and environment variables to a normalized Path."""
    return Path(os.path.expandvars(os.path.expanduser(p))).resolve()


def is_blacklisted(target_path: Path, custom_blacklist: Optional[List[str]] = None) -> bool:
    """Check if target_path is within or matches any blacklisted paths."""
    resolved_target = target_path.resolve()

    # Critical root protection
    if resolved_target in (Path("/"), Path.home()):
        return True

    all_blacklists = list(DEFAULT_BLACKLIST)
    if custom_blacklist:
        all_blacklists.extend(custom_blacklist)

    for item in all_blacklists:
        try:
            bl_path = expand_path(item)
            if resolved_target == bl_path or bl_path in resolved_target.parents:
                return True
        except Exception:
            continue

    return False


import functools

@functools.lru_cache(maxsize=1)
def is_btrfs_root() -> bool:
    """Determine if root filesystem is Btrfs."""
    try:
        res = subprocess.run(
            ["findmnt", "-n", "-o", "FSTYPE", "/"],
            capture_output=True,
            text=True,
            timeout=5
        )
        return "btrfs" in res.stdout.lower()
    except Exception:
        return False


def create_snapshot(description: str = "ArchTidy pre-cleanup") -> Optional[str]:
    """Create a Btrfs snapshot using snapper if available."""
    if not is_btrfs_root():
        return None

    if not shutil.which("snapper"):
        return None

    try:
        cmd = ["snapper", "create", "-d", f"ArchTidy: {description}"]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if res.returncode == 0:
            return "Snapper snapshot created successfully."
        # If snapper requires sudo/privileges, try not to block user flow
        return f"Snapper snapshot skipped: {res.stderr.strip() or 'permissions'}"
    except Exception as exc:
        return f"Snapper snapshot skipped: {exc}"
