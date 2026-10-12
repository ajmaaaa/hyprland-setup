"""Candidate data model representing an item identified for cleanup."""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Any


@dataclass
class Candidate:
    """Represents a potential file, directory, or package to be cleaned."""
    path: Path
    size_bytes: int
    reason: str
    score: int          # Confidence score 0 - 100
    source: str         # 'orphan', 'package', 'bigfile', 'duplicate', 'cache'
    selected: bool = False
    details: Dict[str, Any] = field(default_factory=dict)

    @property
    def human_size(self) -> str:
        """Return human-readable file size string."""
        size = float(self.size_bytes)
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if abs(size) < 1024.0 or unit == 'TB':
                return f"{size:.1f} {unit}" if unit != 'B' else f"{int(size)} B"
            size /= 1024.0
        return f"{size:.1f} TB"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging or serialization."""
        return {
            "path": str(self.path),
            "size_bytes": self.size_bytes,
            "human_size": self.human_size,
            "reason": self.reason,
            "score": self.score,
            "source": self.source,
            "selected": self.selected,
            "details": self.details,
        }
