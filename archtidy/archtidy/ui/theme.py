"""Theme and styling module for ArchTidy.

Adapts to Tokyo Night / terminal colors and provides ANSI formatting & box drawing characters.
"""
import os
from pathlib import Path
import tomllib
from typing import Dict, Any


DEFAULT_PALETTE = {
    "bg": "\033[48;2;26;27;38m",
    "fg": "\033[38;2;192;202;245m",
    "primary": "\033[38;2;122;162;247m",    # Soft blue
    "accent": "\033[38;2;187;154;247m",     # Purple
    "success": "\033[38;2;158;206;106m",    # Matcha green
    "warning": "\033[38;2;224;175;104m",    # Warm yellow
    "danger": "\033[38;2;247;118;142m",     # Soft coral red
    "muted": "\033[38;2;86;95;137m",        # Gray
    "bold": "\033[1m",
    "dim": "\033[2m",
    "underline": "\033[4m",
    "reverse": "\033[7m",
    "reset": "\033[0m",
}

# Rounded box-drawing characters for clean UI
BOX = {
    "top_left": "╭",
    "top_right": "╮",
    "bottom_left": "╰",
    "bottom_right": "╯",
    "horizontal": "─",
    "vertical": "│",
    "t_down": "┬",
    "t_up": "┴",
    "t_right": "├",
    "t_left": "┤",
    "cross": "┼",
    "check": "✔",
    "cross_mark": "✖",
    "warn": "⚠",
    "arrow": "➜",
    "bullet": "•",
}


def load_theme() -> Dict[str, str]:
    """Load theme palette with terminal/alacritty awareness."""
    # Check if terminal supports truecolor
    colorterm = os.environ.get("COLORTERM", "").lower()
    if colorterm not in ("truecolor", "24bit"):
        # Fallback to standard 16 ANSI colors
        return {
            "bg": "",
            "fg": "\033[37m",
            "primary": "\033[34m",
            "accent": "\033[35m",
            "success": "\033[32m",
            "warning": "\033[33m",
            "danger": "\033[31m",
            "muted": "\033[90m",
            "bold": "\033[1m",
            "dim": "\033[2m",
            "underline": "\033[4m",
            "reverse": "\033[7m",
            "reset": "\033[0m",
        }
    return DEFAULT_PALETTE


THEME = load_theme()


def color(text: str, color_key: str, bold: bool = False) -> str:
    """Format text with ANSI escape codes."""
    prefix = THEME.get(color_key, "")
    if bold:
        prefix += THEME["bold"]
    return f"{prefix}{text}{THEME['reset']}"
