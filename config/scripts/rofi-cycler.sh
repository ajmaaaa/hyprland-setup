#!/bin/bash

# █▀█ █▀█ █▀▀ █
# █▀▄ █▄█ █▀░ █
# ==========================================
#  ROFI THEME CYCLER — identical to sway
# ==========================================

MODE=$1    # launcher / powermenu
ACTION=$2  # type / style
ROFI_DIR="$HOME/.config/rofi"

if [ "$MODE" == "launcher" ]; then
    ACTIVE_LINK="$ROFI_DIR/launcher_active.sh"
    BASE_PATH="$ROFI_DIR/launchers"
    FILE_NAME="launcher.sh"
    MAX_TYPE=7
elif [ "$MODE" == "powermenu" ]; then
    ACTIVE_LINK="$ROFI_DIR/powermenu_active.sh"
    BASE_PATH="$ROFI_DIR/powermenu"
    FILE_NAME="powermenu.sh"
    MAX_TYPE=6
else
    notify-send "Rofi Cycler" "Invalid mode! Use 'launcher' or 'powermenu'"
    exit 1
fi

REAL_FILE=$(readlink -f "$ACTIVE_LINK")
CURRENT_TYPE_DIR=$(dirname "$REAL_FILE")
CURRENT_TYPE=$(basename "$CURRENT_TYPE_DIR")
CURRENT_TYPE_NUM=${CURRENT_TYPE//type-/}

if [ "$ACTION" == "type" ]; then
    NEXT_NUM=$((CURRENT_TYPE_NUM + 1))
    [ "$NEXT_NUM" -gt "$MAX_TYPE" ] && NEXT_NUM=1

    NEW_TARGET="$BASE_PATH/type-${NEXT_NUM}/${FILE_NAME}"
    if [ -f "$NEW_TARGET" ]; then
        ln -sf "$NEW_TARGET" "$ACTIVE_LINK"
        notify-send -h string:x-canonical-private-synchronous:rofi_cycler \
            "Rofi $MODE" "Switched to Type-${NEXT_NUM}"
    else
        notify-send "Rofi Error" "Type-${NEXT_NUM} not found!"
    fi

elif [ "$ACTION" == "style" ]; then
    CURRENT_STYLE=$(grep "theme=" "$REAL_FILE" | head -1 | grep -o "style-[0-9]*")
    CURRENT_STYLE_NUM=${CURRENT_STYLE//style-/}

    MAX_STYLE=5
    [[ "$CURRENT_TYPE_NUM" -ge 6 ]] && MAX_STYLE=10

    NEXT_STYLE_NUM=$((CURRENT_STYLE_NUM + 1))
    [ "$NEXT_STYLE_NUM" -gt "$MAX_STYLE" ] && NEXT_STYLE_NUM=1

    NEW_STYLE="style-${NEXT_STYLE_NUM}"
    sed -i "s/$CURRENT_STYLE/$NEW_STYLE/g" "$REAL_FILE"

    notify-send -h string:x-canonical-private-synchronous:rofi_cycler \
        "Rofi $MODE ($CURRENT_TYPE)" "Switched to $NEW_STYLE"
fi
