"""A narrow set of redundant archives and regenerable, stale thumbnails."""
import os
import time
from pathlib import Path

from ..core.candidate import Candidate
from ..core.safety import is_blacklisted
from .packages import PackageCleaner


class JunkCleaner:
    def __init__(self, custom_blacklist=None, thumbnail_dir=None, min_age_days=30):
        self.custom_blacklist = custom_blacklist or []
        cache_home = Path(os.environ.get('XDG_CACHE_HOME') or Path.home() / '.cache')
        self.thumbnail_dir = Path(thumbnail_dir) if thumbnail_dir is not None else cache_home / 'thumbnails'
        self.min_age_days = min_age_days

    def scan(self):
        candidates = []
        # Keep the two newest package versions for reinstall/downgrade.
        for item in PackageCleaner(custom_blacklist=self.custom_blacklist).get_pacman_cache_candidates(keep_versions=2):
            if item.path.is_symlink() or not item.path.is_file() or is_blacklisted(item.path, self.custom_blacklist):
                continue
            item.selected = False
            item.details['junk_kind'] = 'superseded_package_archive'
            candidates.append(item)

        # Scan only the standard thumbnail cache, never arbitrary .tmp files,
        # personal files, application configuration, or active /tmp sockets.
        cutoff = time.time() - self.min_age_days * 86400
        root = self.thumbnail_dir
        if root.is_symlink() or not root.is_dir() or is_blacklisted(root, self.custom_blacklist):
            return candidates
        for folder in ('normal', 'large', 'x-large', 'xx-large', 'fail'):
            directory = root / folder
            if directory.is_symlink() or is_blacklisted(directory, self.custom_blacklist):
                continue
            for base, dirs, files in os.walk(directory, followlinks=False):
                dirs[:] = [name for name in dirs if not (Path(base) / name).is_symlink()
                           and not is_blacklisted(Path(base) / name, self.custom_blacklist)]
                for name in files:
                    path = Path(base) / name
                    if path.suffix.lower() != '.png' or path.is_symlink() or is_blacklisted(path, self.custom_blacklist):
                        continue
                    try:
                        stat = path.stat()
                        if not path.is_file() or stat.st_mtime > cutoff or stat.st_size == 0:
                            continue
                        candidates.append(Candidate(path, stat.st_size,
                            f'Thumbnail cache older than {self.min_age_days} days; recreated when needed',
                            95, 'cache', False, {'junk_kind': 'stale_thumbnail'}))
                    except OSError:
                        continue
        return candidates
