"""Unified confirmation and execution pipeline for all deletions and cleanups."""
from dataclasses import dataclass, field
from datetime import datetime
import os
from pathlib import Path
import shutil
import subprocess
from typing import List, Dict, Any, Optional
import uuid
from urllib.parse import quote, unquote
import configparser

from .candidate import Candidate
from .safety import is_blacklisted, create_snapshot
from .log import log_action, get_recent_actions


@dataclass
class ExecutionResult:
    """Summary of cleanup execution."""
    batch_id: str
    dry_run: bool
    total_candidates: int
    processed_count: int
    freed_bytes: int
    errors: List[str] = field(default_factory=list)
    items_trashed: List[str] = field(default_factory=list)


def move_to_trash(target: Path) -> bool:
    """Move a file or directory to Trash using gio, trash-put, or atomic move."""
    target_str = str(target.absolute())

    # Strategy 1: gio trash (standard on GNOME/XDG/Wayland)
    if shutil.which("gio"):
        res = subprocess.run(["gio", "trash", target_str], capture_output=True, text=True)
        if res.returncode == 0:
            return True

    # Strategy 2: trash-put (trash-cli)
    if shutil.which("trash-put"):
        res = subprocess.run(["trash-put", target_str], capture_output=True, text=True)
        if res.returncode == 0:
            return True

    # Strategy 3: Local user trash directory ~/.local/share/Trash/files
    try:
        trash_root = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "Trash"
        trash_files = trash_root / "files"
        trash_info = trash_root / "info"
        trash_files.mkdir(parents=True, exist_ok=True)
        trash_info.mkdir(parents=True, exist_ok=True)

        dest_name = f"{target.name}.{uuid.uuid4().hex}"
        dest_path = trash_files / dest_name
        shutil.move(target_str, dest_path)

        info_content = (
            f"[Trash Info]\n"
            f"Path={quote(target_str, safe='/')}\n"
            f"DeletionDate={datetime.now().strftime('%Y-%m-%dT%H:%M:%S')}\n"
        )
        (trash_info / f"{dest_name}.trashinfo").write_text(info_content, encoding="utf-8")
        return True
    except Exception:
        return False


def execute_cleanup(
    candidates: List[Candidate],
    dry_run: bool = True,
    custom_blacklist: Optional[List[str]] = None,
    create_btrfs_snapshot: bool = True,
    admin_command: Optional[List[str]] = None
) -> ExecutionResult:
    """Execute cleanup on selected candidates through a strict safety pipeline."""
    batch_id = str(uuid.uuid4())[:8]
    result = ExecutionResult(
        batch_id=batch_id,
        dry_run=dry_run,
        total_candidates=len(candidates),
        processed_count=0,
        freed_bytes=0,
    )

    selected = [c for c in candidates if c.selected]
    if not selected:
        return result

    if not dry_run and create_btrfs_snapshot:
        create_snapshot(f"cleanup batch {batch_id} ({len(selected)} items)")

    for candidate in selected:
        target_path = candidate.path

        # 1. Permanent Blacklist Validation
        if is_blacklisted(target_path, custom_blacklist):
            result.errors.append(f"Blocked by safety blacklist: {target_path}")
            log_action("blocked", target_path, candidate.size_bytes, "blacklisted", batch_id=batch_id)
            continue

        if dry_run:
            result.processed_count += 1
            result.freed_bytes += candidate.size_bytes
            result.items_trashed.append(str(target_path))
            log_action("dry_run", target_path, candidate.size_bytes, "simulated", batch_id=batch_id)
            continue

        # 2. Execution (Live Mode)
        # Packages source handled via pacman if specified
        if candidate.source == "package":
            pkg_name = candidate.details.get("pkg_name", target_path.name)
            res = subprocess.run([*(admin_command or ["sudo"]), "pacman", "-R" if admin_command else "-Rns", "--noconfirm", "--", pkg_name], capture_output=True, text=True)
            if res.returncode == 0:
                result.processed_count += 1
                result.freed_bytes += candidate.size_bytes
                result.items_trashed.append(f"Package: {pkg_name}")
                log_action("package_remove", target_path, candidate.size_bytes, "success", batch_id=batch_id)
            else:
                err_msg = res.stderr.strip() or f"Failed to remove package {pkg_name}"
                result.errors.append(err_msg)
                log_action("package_remove", target_path, candidate.size_bytes, "error", extra={"error": err_msg}, batch_id=batch_id)
            continue

        # Protected pacman archives require GUI authentication and cannot use user Trash.
        if admin_command and candidate.source == "cache" and target_path.parent == Path("/var/cache/pacman/pkg"):
            if target_path.is_symlink() or not target_path.is_file() or ".pkg.tar." not in target_path.name:
                result.errors.append(f"Not a package archive: {target_path}")
                continue
            res = subprocess.run([*admin_command, "/usr/bin/rm", "--", str(target_path)], capture_output=True, text=True)
            if res.returncode == 0:
                result.processed_count += 1
                result.freed_bytes += candidate.size_bytes
                result.items_trashed.append(str(target_path))
                log_action("cache_remove", target_path, candidate.size_bytes, "success", batch_id=batch_id)
            else:
                result.errors.append(res.stderr.strip() or f"Failed to remove archive: {target_path}")
            continue

        # Files and directories: move to Trash
        if not target_path.exists():
            continue

        size = candidate.size_bytes
        success = move_to_trash(target_path)
        if success:
            result.processed_count += 1
            result.freed_bytes += size
            result.items_trashed.append(str(target_path))
            log_action("trash", target_path, size, "success", batch_id=batch_id)
        else:
            err = f"Failed to move to trash: {target_path}"
            result.errors.append(err)
            log_action("trash", target_path, size, "error", extra={"error": err}, batch_id=batch_id)

    return result


def undo_recent_batch(batch_id: Optional[str] = None) -> List[str]:
    """Attempt to restore trashed items from recent actions."""
    recent = get_recent_actions(limit=None)
    if not recent:
        return ["No recent actions found to undo."]

    target_batch = batch_id or next((a.get("batch_id") for a in recent
                                      if a.get("action") in ("trash", "package_remove", "cache_remove") and a.get("status") == "success"), None)
    actions_to_undo = [a for a in recent if a.get("batch_id") == target_batch
                       and a.get("action") == "trash" and a.get("status") == "success"]
    if not actions_to_undo:
        return ["No files from the last cleanup can be restored."]
    restored = []
    trash_root = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "Trash"
    for action in actions_to_undo:
        orig_path = Path(action["path"])
        if orig_path.exists() or orig_path.is_symlink():
            restored.append(f"Skipped (destination exists): {orig_path}")
            continue
        found = False
        for info_file in (trash_root / "info").glob("*.trashinfo"):
            try:
                meta = configparser.ConfigParser(interpolation=None)
                meta.read(info_file, encoding="utf-8")
                if unquote(meta["Trash Info"]["Path"]) != str(orig_path):
                    continue
                # Restrict to this cleanup's timestamp, avoiding older same-name items.
                deleted = datetime.fromisoformat(meta["Trash Info"]["DeletionDate"])
                logged = datetime.fromisoformat(action["timestamp"])
                if abs((deleted - logged.replace(tzinfo=None)).total_seconds()) > 10:
                    continue
                trash_item = trash_root / "files" / info_file.name.removesuffix(".trashinfo")
                if not trash_item.exists() and not trash_item.is_symlink():
                    continue
                orig_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(trash_item), str(orig_path))
                info_file.unlink()
                restored.append(f"Restored: {orig_path}")
                log_action("restore", orig_path, action.get("size_bytes", 0), "success", batch_id=target_batch)
                found = True
                break
            except Exception as exc:
                restored.append(f"Failed to restore {orig_path}: {exc}")
        if not found:
            restored.append(f"Item not found in user Trash: {orig_path}")
    return restored
