#!/bin/sh
set -eu
command -v quickshell >/dev/null 2>&1 || {
    printf '%s\n' 'Workspace preview requires quickshell: sudo pacman -S --needed quickshell' >&2
    exit 1
}
: "${XDG_RUNTIME_DIR:?Run this from your Hyprland session}"
: "${HYPRLAND_INSTANCE_SIGNATURE:?Run this from your Hyprland session}"
export QT_QPA_PLATFORM=wayland
exec flock -n "$XDG_RUNTIME_DIR/workspace-preview-$HYPRLAND_INSTANCE_SIGNATURE.lock" \
    quickshell --no-duplicate -p "$HOME/.config/quickshell/workspace-preview"
