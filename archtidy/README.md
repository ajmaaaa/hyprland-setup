# ArchTidy

Arch Linux cleanup panel with an English GTK interface and a terminal interface.
The main Hyprland installer installs it for the current user. To install only
this panel, run `python3 scripts/setup-archtidy.py` from the repository root.

Launch `~/.local/bin/archtidy` for the graphical panel or `archtidy tui` for the
terminal interface. The graphical panel requires GTK 3 and python-gobject.

Choose a category, search, select items, and review before cleaning. Nothing in
the graphical panel is selected automatically. Junk only includes superseded
package archives (keeping two versions) and thumbnail caches older than 30 days.
Large files, duplicates, installed packages, and application configuration are
separate categories that require their own review.

User files move to Trash. Packages and system cache archives require
authentication and are permanently removed. Restore last cleanup restores
eligible user files without overwriting existing files. Moving files to Trash
frees disk space only after Trash is emptied.

Settings live in `~/.config/archtidy/config.toml`. Reinstalling preserves this
configuration and backs up the previous installed package and launcher.

Run tests from the repository root:

```bash
PYTHONPATH=archtidy python3 -m unittest discover -s archtidy/tests
```
