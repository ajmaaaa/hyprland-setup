#!/bin/bash

# █▀▄ █ █▀ █▀█ █░░ ▄▀█ █▄█
# █▄▀ █ ▄█ █▀▀ █▄▄ █▀█ ░█░
# ============================================================
# Adaptasi dari sway display-monitor.sh → pakai hyprctl

# --- CONFIGURATION ---
LAPTOP="eDP-1"
EXTERNAL="HDMI-A-1"
ROFI_CMD="rofi -dmenu -i -p 'Display Mode' -theme-str 'window {width: 20%;}'"

NOTIF_ID="1005"
TIMEOUT="3000"

# --- NOTIFICATION ---
send_notif() {
    notify-send -r "$NOTIF_ID" -t "$TIMEOUT" \
    -h string:x-canonical-private-synchronous:display \
    -u low -i video-display "$1"
}

# --- MODES LOGIC ---
apply_mode() {
    case "$1" in
        "💻 Laptop Only")
            hyprctl keyword monitor "$EXTERNAL, disable"
            hyprctl keyword monitor "$LAPTOP, 1920x1080, 0x0, 1"
            send_notif "Mode: Laptop Only"
            ;;
        "📽️ Projector Only")
            hyprctl keyword monitor "$LAPTOP, disable"
            hyprctl keyword monitor "$EXTERNAL, 1920x1080, 0x0, 1"
            send_notif "Mode: Projector Only (1080p)"
            ;;
        "🖥️ Extend (Dual)")
            hyprctl keyword monitor "$LAPTOP, 1920x1080, 0x0, 1"
            hyprctl keyword monitor "$EXTERNAL, 1920x1080, 1920x0, 1"
            send_notif "Mode: Extended Display"
            ;;
        "🪞 Mirror (Clone)")
            # Hyprland mirror = sama posisi dengan mirror_of
            hyprctl keyword monitor "$LAPTOP, 1920x1080, 0x0, 1"
            hyprctl keyword monitor "$EXTERNAL, 1920x1080, 0x0, 1, mirror, $LAPTOP"
            send_notif "Mode: Mirror / Clone"
            ;;
        *)
            exit 0
            ;;
    esac
}

# --- MENU ---
options="💻 Laptop Only\n📽️ Projector Only\n🖥️ Extend (Dual)\n🪞 Mirror (Clone)"
choice=$(echo -e "$options" | eval "$ROFI_CMD")

apply_mode "$choice"
