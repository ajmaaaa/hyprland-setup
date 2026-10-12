#!/bin/sh
SCRIPT_DIR="$(dirname "$0")"

# Launch GTK 3 UI, fallback to Rofi UI if GTK encounters an error
if python3 "$SCRIPT_DIR/connections-ui.py" "$@"; then
    exit 0
fi

exec python3 "$SCRIPT_DIR/connections.py" "$@"
