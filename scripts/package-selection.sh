#!/usr/bin/env bash
# Parse a package file and output lines in "package|CATEGORY" format.
# Skips empty lines, separator lines (===), and inline comments.
parse_packages() {
  local file="$1"
  local current_category="General"
  while IFS= read -r line; do
    # Skip empty lines
    [[ -z "${line// }" ]] && continue
    # Skip separator lines (lines containing only #, =, -, spaces)
    [[ "$line" =~ ^[[:space:]]*#[[:space:]]*[=\-]+[[:space:]]*$ ]] && continue
    # Detect category header: "# CATEGORY NAME"
    if [[ "$line" =~ ^[[:space:]]*#[[:space:]]+([A-Za-z][A-Za-z0-9\ /\&\.\-]+)[[:space:]]*$ ]]; then
      current_category="$(echo "${BASH_REMATCH[1]}" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
    # Regular package line (not a comment)
    elif [[ ! "$line" =~ ^[[:space:]]*# ]]; then
      local pkg
      pkg="$(echo "$line" | tr -d '[:space:]')"
      [[ -n "$pkg" ]] && echo "$pkg|$current_category"
    fi
  done < "$file"
}

package_default_enabled() {
  local package="$1" line
  [[ -f "${DEFAULT_OFF_FILE:-}" ]] || return 0
  while IFS= read -r line; do
    [[ "$line" == "$package" ]] && return 1
  done < "$DEFAULT_OFF_FILE"
  return 0
}

recommended_packages() {
  local package category
  while IFS='|' read -r package category; do
    if package_default_enabled "$package"; then
      printf '%s\n' "$package"
    fi
  done < <(parse_packages "$1")
}

# Show an interactive dialog checklist for the given package file.
# Stores selected packages into the given array variable name.
show_checklist() {
  local title="$1"
  local file="$2"
  local -n result_ref="$3"   # nameref to output array

  local TMPFILE
  TMPFILE=$(mktemp)

  # Build checklist items: ("pkg" "[CATEGORY]" "on") ...
  local ITEMS=()
  while IFS='|' read -r pkg category; do
    local status="on"
    package_default_enabled "$pkg" || status="off"
    local disp_category="[$category]"
    if [[ -n "${INSTALLED_PKGS[$pkg]}" ]]; then
      status="off"
      disp_category="[Installed] $category"
    fi
    ITEMS+=("$pkg" "$disp_category" "$status")
  done < <(parse_packages "$file")

  dialog \
    --title " $title " \
    --backtitle "Arch Hyprland Setup — Package Selection" \
    --checklist "\nSelect packages to install.\n\n  SPACE = toggle on/off   ENTER = confirm   TAB = switch buttons\n" \
    0 0 0 \
    "${ITEMS[@]}" 2>"$TMPFILE"

  local EXIT_CODE=$?

  if [[ $EXIT_CODE -ne 0 ]]; then
    rm -f "$TMPFILE"
    clear
    warn "Selection cancelled for '$title'. No packages selected."
    result_ref=()
    return 1
  fi

  # Parse dialog output: space-separated, possibly quoted
  mapfile -t result_ref < <(cat "$TMPFILE" | tr -d '"' | tr ' ' '\n' | grep -v '^$')
  rm -f "$TMPFILE"
  clear
  return 0
}
