"""Main CLI entry point for ArchTidy.

Supports a graphical panel, optional TUI, and command-line subcommands:
  archtidy                        Launch graphical panel
  archtidy tui                    Launch terminal interface
  archtidy scan [category]        Scan for cleanup candidates
  archtidy clean [category]       Clean selected items (--dry-run default)
  archtidy uninstall <pkg>        Clean uninstallation with residual config purge
  archtidy undo [batch_id]        Restore items from recent batch
  archtidy info                   Show system cleaning status
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tomllib
from typing import Dict, Any, List

from .core.candidate import Candidate
from .core.confirm import execute_cleanup, undo_recent_batch
from .core.safety import is_btrfs_root, expand_path
from .core.log import LOG_FILE, get_recent_actions
from .modules import (
    OrphanDetector,
    PackageCleaner,
    BigFileFinder,
    DuplicateFinder,
    AndroidCleaner,
)
from .ui.theme import color, BOX
from .ui.app import ArchTidyTUI


CONFIG_DEFAULT_PATH = Path.home() / ".config/archtidy/config.toml"


def load_config(config_path: Path = CONFIG_DEFAULT_PATH) -> Dict[str, Any]:
    """Load configuration TOML if it exists, otherwise fall back to defaults."""
    # Also check local repo config.toml
    local_cfg = Path(__file__).resolve().parent.parent / "config.toml"
    for candidate in [config_path, local_cfg]:
        if candidate.exists():
            try:
                with open(candidate, "rb") as f:
                    return tomllib.load(f)
            except Exception:
                pass
    return {}


def print_banner() -> None:
    """Print ASCII logo banner."""
    print(color("  󰃢  ArchTidy — Unified System Cleaner for Arch Linux", "primary", bold=True))
    print(color("  ─────────────────────────────────────────────────────", "muted"))


def cmd_info(args: argparse.Namespace) -> None:
    """Display system cleanup status and diagnostics."""
    print_banner()

    btrfs = is_btrfs_root()
    snapper_avail = shutil.which("snapper") is not None
    gio_avail = shutil.which("gio") is not None
    aur_helper = "yay" if shutil.which("yay") else ("paru" if shutil.which("paru") else "none")

    print(f" {color('Filesystem   :', 'bold')} {'Btrfs' if btrfs else 'ext4/other'}")
    print(f" {color('Snapper Hook :', 'bold')} {'Active (Automatic snapshots enabled)' if (btrfs and snapper_avail) else 'Not configured / skipped'}")
    print(f" {color('Trash Backend:', 'bold')} {'gio trash (Compliant)' if gio_avail else 'local Trash'}")
    print(f" {color('AUR Helper   :', 'bold')} {aur_helper}")
    print(f" {color('Audit Log    :', 'bold')} {LOG_FILE}")
    print()

    # Quick cache stats
    pkg_cleaner = PackageCleaner()
    aur_cache = pkg_cleaner.get_aur_cache_candidates()
    aur_size = sum(c.size_bytes for c in aur_cache)
    print(f" {color('AUR Cache Size    :', 'bold')} {Candidate(Path('~/.cache/yay'), aur_size, '', 0, '').human_size} ({len(aur_cache)} packages)")

    pkg_orphans = pkg_cleaner.get_orphan_packages()
    pkg_orphans_size = sum(c.size_bytes for c in pkg_orphans)
    print(f" {color('Orphan Packages   :', 'bold')} {len(pkg_orphans)} packages ({Candidate(Path('/var'), pkg_orphans_size, '', 0, '').human_size})")

    recent = get_recent_actions(limit=5)
    print(f"\n {color('Recent Actions (last 5):', 'accent', bold=True)}")
    if not recent:
        print("  No recent actions recorded.")
    else:
        for r in recent:
            print(f"  {r.get('timestamp', '')[:19]} │ {r.get('action', ''):<14} │ {r.get('status', ''):<8} │ {r.get('path', '')}")
    print()


def cmd_scan(args: argparse.Namespace) -> None:
    """Scan categories and output candidates."""
    cat = args.category.lower() if args.category else "all"
    candidates: List[Candidate] = []

    print_banner()
    print(f" Scanning category: {color(cat, 'accent', bold=True)} ...\n")

    cfg = load_config()
    custom_bl = cfg.get("blacklist", {}).get("paths", [])

    if cat in ("orphans", "all"):
        min_conf = cfg.get("orphans", {}).get("min_confidence_score", 70)
        cands = OrphanDetector(min_confidence=min_conf, custom_blacklist=custom_bl).scan()
        candidates.extend(cands)

    if cat in ("packages", "cache", "all"):
        cleaner = PackageCleaner(custom_blacklist=custom_bl)
        candidates.extend(cleaner.get_orphan_packages())
        candidates.extend(cleaner.get_aur_cache_candidates())
        candidates.extend(cleaner.get_pacman_cache_candidates())

    if cat in ("bigfiles", "all"):
        min_mb = cfg.get("bigfiles", {}).get("min_size_mb", 100)
        scan_dirs = cfg.get("bigfiles", {}).get("scan_directories")
        candidates.extend(BigFileFinder(scan_dir=scan_dirs, min_size_mb=min_mb, custom_blacklist=custom_bl).scan())

    if cat in ("duplicates", "all"):
        min_dup_mb = cfg.get("duplicates", {}).get("min_size_mb", 1)
        dup_dirs = cfg.get("duplicates", {}).get("scan_directories")
        candidates.extend(DuplicateFinder(scan_dir=dup_dirs, min_size_mb=min_dup_mb, custom_blacklist=custom_bl).scan())


    if cat in ("android", "all"):
        candidates.extend(AndroidCleaner(custom_blacklist=custom_bl).scan())

    if getattr(args, "json", False):
        print(json.dumps([c.to_dict() for c in candidates], indent=2))
        return

    if not candidates:
        print(color("  ✔ System is clean! No cleanup candidates identified.", "success", bold=True))
        return

    total_bytes = sum(c.size_bytes for c in candidates)
    size_f = float(total_bytes)
    hsize = f"{int(size_f)} B"
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if abs(size_f) < 1024.0 or unit == "TB":
            hsize = f"{size_f:.1f} {unit}" if unit != "B" else f"{int(size_f)} B"
            break
        size_f /= 1024.0

    print(f" Found {color(str(len(candidates)), 'warning', bold=True)} candidates ({color(hsize, 'success', bold=True)} potential space):\n")
    print(f"  {'SCORE':<7} {'SIZE':<11} {'SOURCE':<11} {'PATH / TARGET':<40} {'REASON'}")
    print("  " + "─" * 100)

    for c in candidates[:args.limit]:
        path_str = c.path.name or str(c.path)
        if len(path_str) > 38:
            path_str = path_str[:35] + "..."
        score_color = "success" if c.score >= 80 else ("warning" if c.score >= 50 else "muted")
        print(f"  {color(f'{c.score}%', score_color):<16} {c.human_size:<11} {c.source:<11} {path_str:<40} {c.reason}")

    if len(candidates) > args.limit:
        print(f"\n  ... and {len(candidates) - args.limit} more items. (Use --limit to display more)")

    print(f"\n To simulate cleanup, run: {color('archtidy clean', 'primary')} {cat}")
    print(f" To execute cleanup, run : {color('archtidy clean --apply', 'danger')} {cat}\n")


def cmd_clean(args: argparse.Namespace) -> None:
    """Clean candidates with dry-run safety by default."""
    dry_run = not args.apply

    cfg = load_config()
    custom_bl = cfg.get("blacklist", {}).get("paths", [])
    cat = args.category.lower() if args.category else "all"

    candidates: List[Candidate] = []
    if cat in ("orphans", "all"):
        candidates.extend(OrphanDetector(custom_blacklist=custom_bl).scan())
    if cat in ("packages", "cache", "all"):
        cleaner = PackageCleaner(custom_blacklist=custom_bl)
        candidates.extend(cleaner.get_orphan_packages())
        candidates.extend(cleaner.get_aur_cache_candidates())
    if cat in ("android", "all"):
        candidates.extend(AndroidCleaner(custom_blacklist=custom_bl).scan())

    for c in candidates:
        c.selected = True

    if not candidates:
        print(color("No candidates found to clean.", "success"))
        return

    print_banner()
    if dry_run:
        print(color(" [DRY-RUN SIMULATION] No files will be modified or removed.", "warning", bold=True))
    else:
        print(color(" [LIVE EXECUTION] Moving files to Trash & removing packages.", "danger", bold=True))

    res = execute_cleanup(candidates, dry_run=dry_run, custom_blacklist=custom_bl)

    size_f = float(res.freed_bytes)
    hsize = f"{int(size_f)} B"
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if abs(size_f) < 1024.0 or unit == "TB":
            hsize = f"{size_f:.1f} {unit}" if unit != "B" else f"{int(size_f)} B"
            break
        size_f /= 1024.0

    print(f"\n Batch ID : {res.batch_id}")
    print(f" Items    : {res.processed_count} processed")
    print(f" Space    : {hsize} {'would be freed' if dry_run else 'freed'}")

    if res.errors:
        print(color("\n Errors encountered:", "danger", bold=True))
        for err in res.errors:
            print(f"  ✖ {err}")
    else:
        print(color("\n ✔ Completed successfully without errors.", "success", bold=True))

    if dry_run:
        print(f"\n Run with {color('--apply', 'danger', bold=True)} to perform actual deletion.")
    print()


def cmd_uninstall(args: argparse.Namespace) -> None:
    """Cleanly uninstall a package and purge leftover configs."""
    pkg = args.package
    dry_run = not args.apply

    print_banner()
    print(f" Clean uninstall target: {color(pkg, 'accent', bold=True)}")

    cleaner = PackageCleaner()
    leftovers = cleaner.find_package_leftovers(pkg)

    if dry_run:
        print(color("\n [DRY-RUN SIMULATION] Would run:", "warning", bold=True))
        print(f"   pacman -Rns {pkg}")
        if leftovers:
            print(f"   Move residual folders to Trash:")
            for lo in leftovers:
                print(f"     - {lo.path} ({lo.human_size})")
        else:
            print("   No residual configuration folders detected.")
        print(f"\n Use {color('--apply', 'danger', bold=True)} to execute clean uninstallation.")
        return

    # Live execution
    print(f" Removing package {pkg} via pacman...")
    res = subprocess.run(["sudo", "pacman", "-Rns", "--noconfirm", pkg])
    if res.returncode != 0:
        print(color(f"✖ Failed to uninstall package {pkg}", "danger", bold=True))
        return

    print(color(f"✔ Package {pkg} removed.", "success"))

    if leftovers:
        for lo in leftovers:
            lo.selected = True
        exec_res = execute_cleanup(leftovers, dry_run=False)
        print(f"✔ Moved {exec_res.processed_count} residual folders to Trash.")


def cmd_undo(args: argparse.Namespace) -> None:
    """Restore trashed items from recent cleanup batch."""
    print_banner()
    batch_id = args.batch_id if hasattr(args, "batch_id") else None
    results = undo_recent_batch(batch_id)
    for r in results:
        print(f" {r}")
    print()


def cli() -> None:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="archtidy",
        description="ArchTidy: Unified System Cleaner for Arch Linux",
    )
    subparsers = parser.add_subparsers(dest="subcommand", help="Subcommand to execute")

    subparsers.add_parser("tui", help="Open the terminal interface")
    subparsers.add_parser("gui", help="Open the graphical cleanup panel")

    # scan
    p_scan = subparsers.add_parser("scan", help="Scan categories for cleanup candidates")
    p_scan.add_argument("category", nargs="?", default="all", choices=["orphans", "packages", "cache", "bigfiles", "duplicates", "android", "all"])
    p_scan.add_argument("--limit", type=int, default=30, help="Max candidates to display")
    p_scan.add_argument("--json", action="store_true", help="Output in JSON format")

    # clean
    p_clean = subparsers.add_parser("clean", help="Clean identified candidates")
    p_clean.add_argument("category", nargs="?", default="all", choices=["orphans", "packages", "cache", "android", "all"])
    p_clean.add_argument("--apply", action="store_true", help="Execute live cleanup (default is dry-run)")

    # uninstall
    p_uninstall = subparsers.add_parser("uninstall", help="Clean uninstall package and remove residual configs")
    p_uninstall.add_argument("package", help="Name of package to cleanly uninstall")
    p_uninstall.add_argument("--apply", action="store_true", help="Execute uninstallation")

    # undo
    p_undo = subparsers.add_parser("undo", help="Restore items from last cleanup batch")
    p_undo.add_argument("batch_id", nargs="?", default=None, help="Optional batch ID to undo")

    # info
    subparsers.add_parser("info", help="Show system cleanup diagnostics and status")

    # Parse args
    args = parser.parse_args()

    if not args.subcommand or args.subcommand == "gui":
        from .ui.gui import run
        run(load_config())
        return
    if args.subcommand == "tui":
        ArchTidyTUI(load_config()).run()
        return

    if args.subcommand == "info":
        cmd_info(args)
    elif args.subcommand == "scan":
        cmd_scan(args)
    elif args.subcommand == "clean":
        cmd_clean(args)
    elif args.subcommand == "uninstall":
        cmd_uninstall(args)
    elif args.subcommand == "undo":
        cmd_undo(args)


if __name__ == "__main__":
    cli()
