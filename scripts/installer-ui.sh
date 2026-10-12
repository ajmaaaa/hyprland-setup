#!/usr/bin/env bash
# Shared terminal presentation; downloading/building keeps the full terminal.
installer_ui_start() {
  INSTALLER_WINDOW_STATE='{}'
  if [[ -t 1 && -n "${HYPRLAND_INSTANCE_SIGNATURE:-}" ]] && command -v python3 >/dev/null && command -v hyprctl >/dev/null; then
    INSTALLER_WINDOW_STATE=$(python3 "$SCRIPT_DIR/scripts/installer-screen.py" enter)
  fi
}

installer_ui_restore() {
  if [[ -n "${INSTALLER_WINDOW_STATE:-}" && "$INSTALLER_WINDOW_STATE" != '{}' ]]; then
    python3 "$SCRIPT_DIR/scripts/installer-screen.py" leave "$INSTALLER_WINDOW_STATE" || true
  fi
}

installer_stage() {
  local title="$1" width=80 line
  if [[ -t 1 && "${TERM:-dumb}" != dumb ]]; then
    width=$(tput cols 2>/dev/null) || width=80
    tput clear 2>/dev/null || true
  fi
  [[ "$width" =~ ^[0-9]+$ && "$width" -gt 0 ]] || width=80
  printf -v line '%*s' "$width" ''
  line=${line// /─}
  printf '%b%s%b\n%b  Arch Hyprland Setup — %s%b\n%b%s%b\n\n' \
    "${BLUE:-}" "$line" "${RESET:-}" "${BOLD:-}" "$title" "${RESET:-}" "${BLUE:-}" "$line" "${RESET:-}"
}

installer_run_logged() {
  local log="$1" command_text
  shift
  if [[ -t 1 ]] && command -v script >/dev/null; then
    printf -v command_text '%q ' "$@"
    script --quiet --return --flush --command "$command_text" "$log"
  else
    "$@" 2>&1 | tee "$log"
    return "${PIPESTATUS[0]}"
  fi
}
