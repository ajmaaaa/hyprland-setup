"""Audit logging module for ArchTidy actions."""
from datetime import datetime
import json
import os
from pathlib import Path
from typing import Dict, Any, List, Optional


LOG_DIR = Path(os.environ.get("XDG_STATE_HOME") or (Path.home() / ".local/state")) / "archtidy"
LOG_FILE = LOG_DIR / "actions.log"


def init_log_dir() -> Path:
    """Ensure the state log directory exists with secure permissions (0o700)."""
    LOG_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    return LOG_FILE


def log_action(
    action: str,
    path: Path,
    size_bytes: int,
    status: str,
    trash_destination: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
    batch_id: Optional[str] = None
) -> None:
    """Append a structured log record to actions.log."""
    init_log_dir()
    record = {
        "timestamp": datetime.now().isoformat(),
        "batch_id": batch_id or "",
        "action": action,
        "path": str(path),
        "size_bytes": size_bytes,
        "status": status,
        "trash_destination": trash_destination or "",
        "extra": extra or {},
    }
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
        os.chmod(LOG_FILE, 0o600)
    except Exception:
        pass


def get_recent_actions(limit: Optional[int] = 50) -> List[Dict[str, Any]]:
    """Retrieve recent action records from actions.log in reverse chronological order."""
    if not LOG_FILE.exists():
        return []
    records = []
    try:
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except Exception:
                        pass
    except Exception:
        return []
    return list(reversed(records))[:limit]
