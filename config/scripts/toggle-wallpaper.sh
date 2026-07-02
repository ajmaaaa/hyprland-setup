#!/bin/bash

# █░█░█ ▄▀█ █░░ █░░ █▀█ ▄▀█ █▀█ █▀▀ █▀█
# ▀▄▀▄▀ █▀█ █▄▄ █▄▄ █▀▀ █▀█ █▀▀ ██▄ █▀▄
# ============================================================
# Adapted from sway toggle-wallpaper.sh → use swww

# --- CONFIG ---
WALL_A="$HOME/Pictures/"
WALL_B="$HOME/Pictures/"
STATE_FILE="$HOME/.config/hypr/scripts/state/state_wallpaper"

mkdir -p "$(dirname "$STATE_FILE")"

# --- FUNCTIONS ---
set_wall_a() {
    swww img "$WALL_A" --transition-type wipe --transition-duration 1
    notify-send -r 1001 -t 2000 "Wallpaper" "Mode A Active"
    echo "A" > "$STATE_FILE"
}

set_wall_b() {
    swww img "$WALL_B" --transition-type wipe --transition-duration 1
    notify-send -r 1001 -t 2000 "Wallpaper" "Mode B Active"
    echo "B" > "$STATE_FILE"
}

# --- LOGIC ---
if [ "$1" == "restore" ]; then
    if [ -f "$STATE_FILE" ]; then
        CURRENT=$(cat "$STATE_FILE")
        [ "$CURRENT" == "B" ] && swww img "$WALL_B" || swww img "$WALL_A"
    else
        swww img "$WALL_A"
    fi
    exit 0
fi

if [ -f "$STATE_FILE" ]; then
    CURRENT=$(cat "$STATE_FILE")
    [ "$CURRENT" == "A" ] && set_wall_b || set_wall_a
else
    set_wall_b
fi
