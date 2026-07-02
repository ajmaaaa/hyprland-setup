#!/bin/bash

# ▀█▀ █░█ █▀▀ █▀▄▀█ █▀▀
# ░█░ █▀█ ██▄ █░▀░█ ██▄
# ==========================================
#  SYSTEM THEME & WALLPAPER TOGGLER
# ==========================================

# --- CONFIGURATION ---
STATE_FILE="$HOME/.config/hypr/scripts/state/state_theme"
GTK_CONFIG="$HOME/.config/gtk-3.0/settings.ini"

mkdir -p "$(dirname "$STATE_FILE")"

WALL_LIGHT="$HOME/Pictures/Wallpapers/Hinata.png"
WALL_DARK="$HOME/Pictures/Wallpapers/muichiro-tokito.png"

GTK_THEME_LIGHT="Adwaita"
GTK_THEME_DARK="Adwaita-dark"

# --- HELPER ---
update_gtk_file() {
    local theme="$1"
    local dark_int="$2"
    if [ -f "$GTK_CONFIG" ]; then
        sed -i "s/^gtk-theme-name=.*/gtk-theme-name=$theme/" "$GTK_CONFIG"
        sed -i "s/^gtk-application-prefer-dark-theme=.*/gtk-application-prefer-dark-theme=$dark_int/" "$GTK_CONFIG"
    fi
}

# --- LIGHT MODE ---
set_light() {
    # Wallpaper via swww
    swww img "$WALL_LIGHT" --transition-type wipe --transition-duration 1

    pkill wlsunset 2>/dev/null || true

    gsettings set org.gnome.desktop.interface gtk-theme "$GTK_THEME_LIGHT"
    gsettings set org.gnome.desktop.interface color-scheme 'default'

    update_gtk_file "$GTK_THEME_LIGHT" 0

    echo "light" > "$STATE_FILE"
    if [ "$SILENT" != "true" ]; then
        notify-send -r 1001 -t 2000 -i weather-clear "System Theme" "Light Mode Active"
    fi
}

# --- DARK MODE ---
set_dark() {
    # Wallpaper via swww
    swww img "$WALL_DARK" --transition-type wipe --transition-duration 1

    if ! pgrep -x "wlsunset" > /dev/null; then
        wlsunset -t 4000 &
    fi

    gsettings set org.gnome.desktop.interface gtk-theme "$GTK_THEME_DARK"
    gsettings set org.gnome.desktop.interface color-scheme 'prefer-dark'

    update_gtk_file "$GTK_THEME_DARK" 1

    echo "dark" > "$STATE_FILE"
    if [ "$SILENT" != "true" ]; then
        notify-send -r 1001 -t 2000 -i weather-clear-night "System Theme" "Dark Mode Active"
    fi
}

# --- EXECUTION ---
if [ "$1" == "restore" ]; then
    SILENT="true"
    if [ -f "$STATE_FILE" ]; then
        CURRENT=$(cat "$STATE_FILE")
        if [ "$CURRENT" == "dark" ]; then
            set_dark
        else
            set_light
        fi
    else
        set_dark
    fi
    exit 0
fi

if [ -f "$STATE_FILE" ]; then
    CURRENT=$(cat "$STATE_FILE")
    [ "$CURRENT" == "dark" ] && set_light || set_dark
else
    set_dark
fi
