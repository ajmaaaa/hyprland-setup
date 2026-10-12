"""Interactive TUI for ArchTidy.

Provides a full curses-based terminal user interface with multi-tab browsing,
candidate selection, real-time calculation, dry-run simulation, and live cleanup execution.
Optimized with lazy/background loading and zero-CPU idle event loop.
"""
import curses
import os
from pathlib import Path
import shutil
import subprocess
import threading
import time
from typing import Dict, List, Optional

from ..core.candidate import Candidate
from ..core.confirm import execute_cleanup, undo_recent_batch
from ..core.safety import is_btrfs_root
from ..modules import (
    OrphanDetector,
    PackageCleaner,
    BigFileFinder,
    DuplicateFinder,
    AndroidCleaner,
)


def safe_addstr(win: curses.window, y: int, x: int, text: str, attr: int = 0) -> None:
    """Safely write string to curses window without crashing on boundary overflow."""
    try:
        max_y, max_x = win.getmaxyx()
        if y < 0 or y >= max_y or x < 0 or x >= max_x:
            return
        avail = max_x - x
        if y == max_y - 1:
            avail = max(0, avail - 1)  # Avoid bottom-right corner scroll/ERR in curses
        if avail <= 0:
            return
        win.addstr(y, x, text[:avail], attr)
    except curses.error:
        pass


class ArchTidyTUI:
    """Curses-based interactive TUI for ArchTidy."""

    TAB_NAMES = [
        "Orphans",
        "Packages & Cache",
        "Big Files",
        "Duplicates",
        "Android & Temp",
    ]

    TAB_DESCRIPTIONS = [
        "Configuration and cache left behind by uninstalled apps",
        "Pacman/AUR caches and unused dependencies",
        "Large files (> 100 MB) in user folders",
        "Identical duplicate files (matching SHA-256 checksums)",
        "Android tool caches (Waydroid, ADB, Gradle transforms, temporary files)",
    ]

    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        self.current_tab = 0
        self.tab_data: List[List[Candidate]] = [[], [], [], [], []]
        self.cursor_index: List[int] = [0, 0, 0, 0, 0]
        self.scroll_offset: List[int] = [0, 0, 0, 0, 0]
        self.status_msg = "[Space] Select item | [a] Select all | [x] Delete selected | [?] Help"
        self.status_color = 2
        self.tab_scanning = [False, False, False, False, False]
        self.lock = threading.Lock()

        # Cache system status strings once at startup (avoids findmnt/which in render loop)
        btrfs = is_btrfs_root()
        snapper_avail = shutil.which("snapper") is not None
        self.btrfs_status = "Btrfs: Snapper Active" if (btrfs and snapper_avail) else ("Btrfs" if btrfs else "ext4/other")
        self.trash_status = "Trash: gio" if shutil.which("gio") else "Trash: local"

    def scan_tab(self, tab_idx: int) -> None:
        """Scan data for a specific category tab."""
        data: List[Candidate] = []
        if tab_idx == 0:
            try:
                data = OrphanDetector().scan()
            except Exception:
                data = []
        elif tab_idx == 1:
            try:
                pkg_cleaner = PackageCleaner()
                data = (
                    pkg_cleaner.get_orphan_packages()
                    + pkg_cleaner.get_aur_cache_candidates()
                    + pkg_cleaner.get_pacman_cache_candidates()
                )
            except Exception:
                data = []
        elif tab_idx == 2:
            try:
                data = BigFileFinder().scan()
            except Exception:
                data = []
        elif tab_idx == 3:
            try:
                data = DuplicateFinder().scan()
            except Exception:
                data = []
        elif tab_idx == 4:
            try:
                data = AndroidCleaner().scan()
            except Exception:
                data = []

        with self.lock:
            self.tab_data[tab_idx] = data

    def load_initial_data(self, stdscr: Optional[curses.window] = None) -> None:
        """Load ultra-fast categories synchronously and heavy categories in parallel background threads."""
        # Ultra-fast categories (< 0.2s total)
        self.scan_tab(0)
        self.scan_tab(1)
        self.scan_tab(4)

        with self.lock:
            self.tab_scanning[2] = True
            self.tab_scanning[3] = True
            total_initial = sum(len(self.tab_data[i]) for i in [0, 1, 4])
            self.status_msg = f"Ready. {total_initial} candidates detected. Scanning deep files in background..."

        def _bg_scan_big():
            self.scan_tab(2)
            with self.lock:
                self.tab_scanning[2] = False
            self._check_bg_complete()

        def _bg_scan_dup():
            self.scan_tab(3)
            with self.lock:
                self.tab_scanning[3] = False
            self._check_bg_complete()

        # Run heavy scans in parallel background threads for maximum speed
        threading.Thread(target=_bg_scan_big, daemon=True).start()
        threading.Thread(target=_bg_scan_dup, daemon=True).start()

    def _check_bg_complete(self) -> None:
        with self.lock:
            if not any(self.tab_scanning):
                total = sum(len(t) for t in self.tab_data)
                self.status_msg = f"System scan complete. Found {total} cleanup candidates."

    def run(self) -> None:
        """Launch the curses wrapper."""
        curses.wrapper(self._main_loop)

    def _init_colors(self) -> None:
        """Set up curses color pairs."""
        try:
            curses.start_color()
        except curses.error:
            pass

        try:
            curses.use_default_colors()
        except curses.error:
            pass

        try:
            curses.curs_set(0)
        except Exception:
            pass

        # Color pairs: fg, bg
        try:
            curses.init_pair(1, curses.COLOR_WHITE, -1)         # Regular
            curses.init_pair(2, curses.COLOR_CYAN, -1)          # Primary
            curses.init_pair(3, curses.COLOR_MAGENTA, -1)       # Accent
            curses.init_pair(4, curses.COLOR_GREEN, -1)         # Success
            curses.init_pair(5, curses.COLOR_YELLOW, -1)        # Warning
            curses.init_pair(6, curses.COLOR_RED, -1)           # Danger
            curses.init_pair(7, curses.COLOR_BLACK, curses.COLOR_CYAN) # Inverted Highlight
            curses.init_pair(8, curses.COLOR_BLACK, curses.COLOR_WHITE) # Light Inverted
        except curses.error:
            pass

    def _main_loop(self, stdscr: curses.window) -> None:
        self._init_colors()
        stdscr.keypad(True)

        self.load_initial_data(stdscr)

        needs_render = True
        last_bg_done = False

        while True:
            # Poll every 100ms only while background threads are scanning; block completely (-1) when done
            is_scanning = any(self.tab_scanning)
            if is_scanning:
                stdscr.timeout(100)
            else:
                if not last_bg_done:
                    last_bg_done = True
                    needs_render = True
                stdscr.timeout(-1)  # 0% CPU usage while idle!

            max_y, max_x = stdscr.getmaxyx()
            if max_y < 12 or max_x < 50:
                stdscr.clear()
                safe_addstr(stdscr, 0, 0, f"Window too small ({max_x}x{max_y}). Min 50x12.", curses.A_BOLD)
                try:
                    stdscr.refresh()
                except curses.error:
                    pass
                time.sleep(0.2)
                needs_render = True
                continue

            if needs_render:
                with self.lock:
                    self._render(stdscr, max_y, max_x)
                needs_render = False

            try:
                ch = stdscr.getch()
            except curses.error:
                continue

            if ch == -1:
                # Timer tick while background scanning
                needs_render = True
                continue

            needs_render = True

            # Navigation
            if ch in (curses.KEY_UP, ord("k")):
                if self.cursor_index[self.current_tab] > 0:
                    self.cursor_index[self.current_tab] -= 1
                    if self.cursor_index[self.current_tab] < self.scroll_offset[self.current_tab]:
                        self.scroll_offset[self.current_tab] = self.cursor_index[self.current_tab]

            elif ch in (curses.KEY_DOWN, ord("j")):
                current_items = self.tab_data[self.current_tab]
                if self.cursor_index[self.current_tab] < len(current_items) - 1:
                    self.cursor_index[self.current_tab] += 1
                    visible_height = max(1, max_y - 13)
                    if self.cursor_index[self.current_tab] >= self.scroll_offset[self.current_tab] + visible_height:
                        self.scroll_offset[self.current_tab] += 1

            elif ch in (curses.KEY_LEFT, ord("h")):
                self.current_tab = (self.current_tab - 1) % len(self.TAB_NAMES)

            elif ch in (curses.KEY_RIGHT, ord("l"), 9):  # 9 is Tab
                self.current_tab = (self.current_tab + 1) % len(self.TAB_NAMES)

            elif ch in (ord("1"), ord("2"), ord("3"), ord("4"), ord("5")):
                self.current_tab = int(chr(ch)) - 1

            # Selection
            elif ch == ord(" "):
                current_items = self.tab_data[self.current_tab]
                idx = self.cursor_index[self.current_tab]
                if 0 <= idx < len(current_items):
                    current_items[idx].selected = not current_items[idx].selected

            # Select / Deselect All in Tab
            elif ch == ord("a"):
                current_items = self.tab_data[self.current_tab]
                any_unselected = any(not c.selected for c in current_items)
                for c in current_items:
                    c.selected = any_unselected

            # Dry-run execution
            elif ch == ord("d"):
                self._run_cleanup(stdscr, dry_run=True)

            # Live clean execution
            elif ch == ord("x"):
                self._confirm_and_run_clean(stdscr)

            # Undo
            elif ch == ord("u"):
                self._run_undo(stdscr)

            # Rescan
            elif ch == ord("r"):
                self.load_initial_data(stdscr)

            # Help
            elif ch == ord("?"):
                self._show_help(stdscr)

            # Resize
            elif ch == curses.KEY_RESIZE:
                needs_render = True

            # Quit
            elif ch in (ord("q"), 27):  # 27 is Esc
                break

    def _render(self, stdscr: curses.window, max_y: int, max_x: int) -> None:
        stdscr.erase()

        # Header bar
        header_text = " 󰃢  ArchTidy v1.0 — Unified System Cleaner "
        if max_x < 85:
            header_text = " 󰃢  ArchTidy "
        safe_addstr(stdscr, 0, 2, header_text, curses.color_pair(2) | curses.A_BOLD)

        sys_info = f"[{self.btrfs_status} │ {self.trash_status}]"
        sys_info_x = max_x - len(sys_info) - 2
        if sys_info_x > len(header_text) + 4:
            safe_addstr(stdscr, 0, sys_info_x, sys_info, curses.color_pair(1) | curses.A_DIM)

        # Tab bar (compact & responsive so [5] Android is never truncated)
        tab_y = 2
        col_x = 2

        if max_x < 92:
            tab_names = ["Orphan", "Pkg", "Big", "Dup", "Android"]
            compact = True
        elif max_x < 115:
            tab_names = ["Orphans", "Packages", "Big Files", "Duplicates", "Android"]
            compact = False
        else:
            tab_names = self.TAB_NAMES
            compact = False

        for i, name in enumerate(tab_names):
            count = len(self.tab_data[i])
            sel_count = sum(1 for c in self.tab_data[i] if c.selected)
            if self.tab_scanning[i]:
                sel_tag = "(...)"
            elif compact:
                sel_tag = f"({sel_count}/{count})" if sel_count > 0 else f"({count})"
            else:
                sel_tag = f" ({sel_count}/{count})" if sel_count > 0 else f" ({count})"

            tab_label = f"[{i+1}]{name}{sel_tag}" if compact else f" [{i+1}] {name}{sel_tag} "

            attr = (
                curses.color_pair(7) | curses.A_BOLD
                if i == self.current_tab
                else curses.color_pair(1)
            )
            safe_addstr(stdscr, tab_y, col_x, tab_label, attr)
            col_x += len(tab_label) + 1

        # Active Category Info Banner
        desc_text = f"󰋖 {self.TAB_DESCRIPTIONS[self.current_tab]}"
        safe_addstr(stdscr, 3, 2, desc_text, curses.color_pair(3) | curses.A_DIM)

        # Table Header
        table_top_y = 5
        if max_x < 90:
            name_w = max(18, max_x - 38)
            table_header = f"  {'SEL':<4} {'SCORE':<5} {'SIZE':<9} {'NAME / PATH':<{name_w}} {'REASON'}"
        else:
            name_w = 34
            table_header = f"  {'SEL':<5} {'SCORE':<7} {'SIZE':<11} {'NAME / PATH':<36} {'REASON'}"

        safe_addstr(stdscr, table_top_y, 2, table_header, curses.color_pair(3) | curses.A_BOLD)
        safe_addstr(stdscr, table_top_y + 1, 2, "─" * max(0, max_x - 4), curses.color_pair(1) | curses.A_DIM)

        # Table Items
        list_y_start = table_top_y + 2
        visible_height = max(1, max_y - 13)
        current_items = self.tab_data[self.current_tab]
        offset = self.scroll_offset[self.current_tab]
        cursor = self.cursor_index[self.current_tab]

        if not current_items:
            if self.tab_scanning[self.current_tab]:
                empty_msg = "󰃢 Scanning in the background... please wait."
            else:
                empty_msg = "✔ No cleanup candidates in this category."
            safe_addstr(stdscr, list_y_start + 2, 4, empty_msg, curses.color_pair(4) | curses.A_BOLD)
        else:
            for row in range(visible_height):
                item_idx = offset + row
                if item_idx >= len(current_items):
                    break

                cand = current_items[item_idx]
                is_selected_row = (item_idx == cursor)

                sel_mark = "[✔]" if cand.selected else "[ ]"
                score_str = f"{cand.score}%"
                size_str = cand.human_size
                path_str = cand.path.name or str(cand.path)
                if len(path_str) > (name_w - 2):
                    path_str = path_str[: max(0, name_w - 5)] + "..."
                reason_str = cand.reason

                if max_x < 90:
                    row_str = f" {sel_mark:<4} {score_str:<5} {size_str:<9} {path_str:<{name_w}} {reason_str}"
                else:
                    row_str = f" {sel_mark:<5} {score_str:<7} {size_str:<11} {path_str:<36} {reason_str}"

                attr = curses.color_pair(7) | curses.A_BOLD if is_selected_row else (
                    curses.color_pair(4) if cand.selected else curses.color_pair(1)
                )

                safe_addstr(stdscr, list_y_start + row, 2, row_str, attr)

        # Details Panel
        details_y = max_y - 5
        safe_addstr(stdscr, details_y - 1, 2, "─" * max(0, max_x - 4), curses.color_pair(1) | curses.A_DIM)

        if current_items and 0 <= cursor < len(current_items):
            cur_cand = current_items[cursor]
            detail_line1 = f"Path: {cur_cand.path} ({cur_cand.human_size}, {cur_cand.size_bytes:,} bytes)"
            detail_line2 = f"Score: {cur_cand.score}/100 | Source: {cur_cand.source} | Rationale: {cur_cand.reason}"
            safe_addstr(stdscr, details_y, 2, detail_line1, curses.color_pair(2))
            safe_addstr(stdscr, details_y + 1, 2, detail_line2, curses.color_pair(1) | curses.A_DIM)
        else:
            safe_addstr(stdscr, details_y, 2, "Select an item to view detailed info.", curses.color_pair(1) | curses.A_DIM)

        # Bottom Bar: Summary & Keybinds
        bottom_y = max_y - 2
        total_selected = sum(c.size_bytes for tab in self.tab_data for c in tab if c.selected)
        total_selected_items = sum(1 for tab in self.tab_data for c in tab if c.selected)

        # Convert bytes to human
        size_f = float(total_selected)
        hsize = f"{int(size_f)} B"
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if abs(size_f) < 1024.0 or unit == "TB":
                hsize = f"{size_f:.1f} {unit}" if unit != "B" else f"{int(size_f)} B"
                break
            size_f /= 1024.0

        summary_text = f" Selected [✔]: {total_selected_items} item ({hsize}) "
        safe_addstr(stdscr, bottom_y, 2, summary_text, curses.color_pair(5) | curses.A_BOLD)

        if max_x >= 110:
            shortcuts = "[Space] Select  [a] Select all  [d] Preview  [x] Delete [✔]  [u] Undo  [?] Help  [q] Quit"
        elif max_x >= 85:
            shortcuts = "[Space] Select  [a] All  [x] Delete [✔]  [d] Preview  [u] Undo  [?] Help"
        elif max_x >= 65:
            shortcuts = "[Space] Select  [a] All  [x] Delete  [?] Help"
        else:
            shortcuts = "[x] Delete [✔]  [q] Quit"

        sc_x = max_x - len(shortcuts) - 2
        if sc_x > len(summary_text) + 2:
            safe_addstr(stdscr, bottom_y, sc_x, shortcuts, curses.color_pair(1) | curses.A_BOLD)

        # Status Line
        safe_addstr(stdscr, max_y - 1, 2, self.status_msg, curses.color_pair(self.status_color))

        try:
            stdscr.refresh()
        except curses.error:
            pass

    def _show_modal(self, stdscr: curses.window, title: str, lines: List[str]) -> None:
        """Display a modal dialog with lines and wait for any key."""
        max_y, max_x = stdscr.getmaxyx()
        h = max(5, min(len(lines) + 6, max_y - 2))
        w = max(20, min(max_x - 4, 80))
        start_y = max(0, (max_y - h) // 2)
        start_x = max(0, (max_x - w) // 2)

        try:
            win = curses.newwin(h, w, start_y, start_x)
            win.box()
            safe_addstr(win, 1, 2, f" {title} ", curses.color_pair(2) | curses.A_BOLD)

            for i, line in enumerate(lines[: max(0, h - 4)]):
                safe_addstr(win, 3 + i, 3, line, curses.color_pair(1))

            safe_addstr(win, h - 2, 3, "Press any key to close...", curses.color_pair(5) | curses.A_BOLD)
            win.refresh()

            win.nodelay(False)
            win.getch()
        except curses.error:
            pass

    def _show_help(self, stdscr: curses.window) -> None:
        help_text = [
            "ArchTidy Keyboard Shortcuts & Help:",
            "",
            "  SELECTING & DELETING:",
            "  • [Space]   : Select/deselect the highlighted item [✔] / [ ]",
            "  • [a]       : Toggle all items in the current category",
            "  • [x]       : Delete selected items [✔]",
            "  • [d]       : Preview cleanup without changing files",
            "  • [u]       : Restore items from Trash",
            "",
            "  NAVIGATION & TABS:",
            "  • 1 - 5     : Jump to tabs 1 - 5",
            "  • Tab / Left: Switch to the next/previous tab",
            "  • j / k / Up: Move the highlighted item up/down",
            "  • r         : Rescan the system",
            "  • q / Esc   : Quit the application",
            "",
            "  CLEANUP BEHAVIOR:",
            "  • Only items marked [✔] are deleted when you press [x].",
            "  • User files go to Trash; a Btrfs snapshot is attempted when available.",
        ]
        self._show_modal(stdscr, "󰋖 ArchTidy Help", help_text)

    def _run_cleanup(self, stdscr: curses.window, dry_run: bool = True) -> None:
        selected_candidates = [c for tab in self.tab_data for c in tab if c.selected]
        if not selected_candidates:
            self.status_msg = "No items selected. Press [Space] or [a] to select items first."
            self.status_color = 5
            return

        res = execute_cleanup(selected_candidates, dry_run=dry_run)

        size_f = float(res.freed_bytes)
        hsize = f"{int(size_f)} B"
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if abs(size_f) < 1024.0 or unit == "TB":
                hsize = f"{size_f:.1f} {unit}" if unit != "B" else f"{int(size_f)} B"
                break
            size_f /= 1024.0

        lines = [
            f"Batch ID : {res.batch_id}",
            f"Mode     : {'SIMULATION (Dry-Run)' if dry_run else 'LIVE EXECUTION'}",
            f"Items    : {res.processed_count} processed of {res.total_candidates} selected",
            f"Space    : {hsize} {'would be freed' if dry_run else 'freed'}",
            "",
        ]
        if res.errors:
            lines.append("Errors encountered:")
            for err in res.errors[:5]:
                lines.append(f"  ✖ {err}")
        else:
            lines.append("✔ All operations completed successfully without errors.")

        self._show_modal(stdscr, "Dry-Run Simulation Results" if dry_run else "Cleanup Execution Complete", lines)

        if not dry_run:
            self.load_initial_data(stdscr)

    def _confirm_and_run_clean(self, stdscr: curses.window) -> None:
        selected_candidates = [c for tab in self.tab_data for c in tab if c.selected]
        if not selected_candidates:
            self.status_msg = "No items selected. Press [Space] to select an item or [a] to select all."
            self.status_color = 5
            return

        total_bytes = sum(c.size_bytes for c in selected_candidates)
        size_f = float(total_bytes)
        hsize = f"{int(size_f)} B"
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if abs(size_f) < 1024.0 or unit == "TB":
                hsize = f"{size_f:.1f} {unit}" if unit != "B" else f"{int(size_f)} B"
                break
            size_f /= 1024.0

        max_y, max_x = stdscr.getmaxyx()
        h = min(12, max_y - 2)
        w = min(max_x - 4, 74)
        if h < 8 or w < 30:
            return

        start_y = max(0, (max_y - h) // 2)
        start_x = max(0, (max_x - w) // 2)

        try:
            win = curses.newwin(h, w, start_y, start_x)
            win.box()
            safe_addstr(win, 1, 2, " ⚠ CONFIRM DELETION ", curses.color_pair(6) | curses.A_BOLD)
            safe_addstr(win, 3, 3, f"Delete {len(selected_candidates)} selected items [✔] ({hsize})?", curses.color_pair(1))
            safe_addstr(win, 4, 3, "• User files are moved to Trash and can be restored", curses.color_pair(5))
            safe_addstr(win, 5, 3, "• Unselected items [ ] are left unchanged", curses.color_pair(4))

            prompt_str = "Type \'yes\' to continue: "
            safe_addstr(win, 7, 3, prompt_str, curses.color_pair(6) | curses.A_BOLD)
            win.refresh()

            curses.echo()
            curses.curs_set(1)
            win.nodelay(False)
            try:
                input_x = min(3 + len(prompt_str), max(0, w - 8))
                user_input = win.getstr(7, input_x, 6).decode("utf-8").strip()
            except Exception:
                user_input = ""
            finally:
                curses.noecho()
                curses.curs_set(0)

            if user_input.lower() == "yes":
                self._run_cleanup(stdscr, dry_run=False)
            else:
                self.status_msg = "Deletion cancelled by the user."
                self.status_color = 5
        except curses.error:
            pass

    def _run_undo(self, stdscr: curses.window) -> None:
        restored = undo_recent_batch()
        self._show_modal(stdscr, "Undo Recent Batch", restored)
        self.load_initial_data(stdscr)
