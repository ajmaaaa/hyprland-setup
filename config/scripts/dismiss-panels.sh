#!/bin/sh
[ -d "$XDG_RUNTIME_DIR/hypr-panels" ] || exit 0
exec /usr/bin/python3 "$(dirname "$0")/panel_dismiss.py"
