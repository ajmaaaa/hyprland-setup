#!/bin/bash

# █▀█ █▀ █▀▄
# █▄█ ▄█ █▄▀
# ==========================================
#  ON-SCREEN DISPLAY (VOLUME & BRIGHTNESS)
# ==========================================

# --- HELPERS ---
get_vol()    { pactl get-sink-volume @DEFAULT_SINK@ | grep -Po '\d+%' | head -n1; }
get_bright() { brightnessctl -m | cut -d, -f4; }

# --- CONFIG ---
ID_VOL="1001"
ID_BRI="1001"
TIMEOUT="3000"

# --- LOGIC ---
case "$1" in
    vol_up)
        pactl set-sink-volume @DEFAULT_SINK@ +5%
        notify-send -r "$ID_VOL" -t "$TIMEOUT" \
        -h string:x-canonical-private-synchronous:volume \
        -u low -i audio-volume-high "Volume: $(get_vol)"
        ;;
    vol_down)
        pactl set-sink-volume @DEFAULT_SINK@ -5%
        notify-send -r "$ID_VOL" -t "$TIMEOUT" \
        -h string:x-canonical-private-synchronous:volume \
        -u low -i audio-volume-low "Volume: $(get_vol)"
        ;;
    vol_mute)
        pactl set-sink-mute @DEFAULT_SINK@ toggle
        MUTE=$(pactl get-sink-mute @DEFAULT_SINK@)
        if [[ $MUTE == *"yes"* ]]; then
            notify-send -r "$ID_VOL" -t "$TIMEOUT" \
            -h string:x-canonical-private-synchronous:volume \
            -u low "Muted"
        else
            notify-send -r "$ID_VOL" -t "$TIMEOUT" \
            -h string:x-canonical-private-synchronous:volume \
            -u low -i audio-volume-high "Unmuted"
        fi
        ;;
    bright_up)
        brightnessctl set 5%+
        notify-send -r "$ID_BRI" -t "$TIMEOUT" \
        -h string:x-canonical-private-synchronous:brightness \
        -u low -i display-brightness-symbolic "Brightness: $(get_bright)"
        ;;
    bright_down)
        brightnessctl set 5%-
        notify-send -r "$ID_BRI" -t "$TIMEOUT" \
        -h string:x-canonical-private-synchronous:brightness \
        -u low -i display-brightness-symbolic "Brightness: $(get_bright)"
        ;;
esac
