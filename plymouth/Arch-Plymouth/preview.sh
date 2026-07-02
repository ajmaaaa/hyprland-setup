#!/usr/bin/env bash

# Helper script to preview the custom Arch-Plymouth theme.

THEME_NAME="Arch-Plymouth"
THEME_DIR="/usr/share/plymouth/themes/$THEME_NAME"

echo "=== Installing/Updating theme to system directory ==="
sudo mkdir -p "$THEME_DIR"
sudo cp -v Arch-Plymouth.plymouth Arch-Plymouth.script logo.png "$THEME_DIR/"

# Allow root to access the user's graphical session (needed for X11 rendering under Wayland/sudo)
sudo plymouth-set-default-theme "$THEME_NAME"

XHOST_MODIFIED=false
if command -v xhost &>/dev/null; then
    xhost +si:localuser:root &>/dev/null
    XHOST_MODIFIED=true
fi

echo "=== Ensuring no existing Plymouth daemon is running ==="
sudo DISPLAY="$DISPLAY" XAUTHORITY="$XAUTHORITY" plymouth --quit 2>/dev/null || true
LOG_FILE="/home/ajmaaa/Git/hyprland-setup/plymouth/Arch-Plymouth/plymouthd-preview.log"

# Temporarily make the plymouthd window fullscreen and borderless in Hyprland
if command -v hyprctl &>/dev/null; then
    hyprctl keyword windowrulev2 "fullscreen, class:.*[Pp]lymouth.*" &>/dev/null
    hyprctl keyword windowrulev2 "noborder, class:.*[Pp]lymouth.*" &>/dev/null
    hyprctl keyword windowrulev2 "noshadow, class:.*[Pp]lymouth.*" &>/dev/null
    hyprctl keyword windowrulev2 "rounding 0, class:.*[Pp]lymouth.*" &>/dev/null
    hyprctl keyword windowrulev2 "bordersize 0, class:.*[Pp]lymouth.*" &>/dev/null
    hyprctl keyword windowrulev2 "fullscreen, title:.*[Pp]lymouth.*" &>/dev/null
    hyprctl keyword windowrulev2 "noborder, title:.*[Pp]lymouth.*" &>/dev/null
    hyprctl keyword windowrulev2 "rounding 0, title:.*[Pp]lymouth.*" &>/dev/null
    hyprctl keyword windowrulev2 "bordersize 0, title:.*[Pp]lymouth.*" &>/dev/null
fi

echo "=== Starting Plymouth daemon (X11 Window Mode) ==="
sudo GTK_CSD=0 GDK_BACKEND=x11 WAYLAND_DISPLAY="" DISPLAY="$DISPLAY" XAUTHORITY="$XAUTHORITY" plymouthd --debug --debug-file="$LOG_FILE" --no-daemon --kernel-command-line="quiet splash plymouth.debug" &
PLYMOUTH_PID=$!

# Give the daemon a second to initialize
sleep 1

echo "=== Showing Plymouth splash window ==="
echo "The preview should now be visible on your screen."
echo "Previewing for 10 seconds (auto-recovery)..."
sudo DISPLAY="$DISPLAY" XAUTHORITY="$XAUTHORITY" plymouth --show-splash

# Wait 10 seconds to automatically stop and recover
sleep 10

echo "=== Stopping Plymouth daemon ==="
sudo DISPLAY="$DISPLAY" XAUTHORITY="$XAUTHORITY" plymouth --quit
kill $PLYMOUTH_PID 2>/dev/null || true
sudo chmod 666 "$LOG_FILE" 2>/dev/null || true

# Reload Hyprland configuration to clean up temporary window rules
if command -v hyprctl &>/dev/null; then
    hyprctl reload &>/dev/null
fi

# Revoke display access for root
if [ "$XHOST_MODIFIED" = true ]; then
    xhost -si:localuser:root &>/dev/null
fi
