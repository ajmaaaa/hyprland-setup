#!/usr/bin/env bash
# Package transactions remain sequential; pacman owns its database lock.
installer_acquire_lock() {
  local directory="$HOME/.local/state/hyprland-setup"
  mkdir -p "$directory" || return
  exec {INSTALLER_LOCK_FD}>"$directory/installer.lock" || return
  if ! flock -n "$INSTALLER_LOCK_FD"; then
    warn "Another hyprland-setup installer is running. Finish that session first."
    return 1
  fi
}

installer_wait_for_pacman() {
  local lock="${INSTALLER_PACMAN_LOCK:-}" dbpath deadline
  if [[ -z "$lock" ]]; then
    dbpath=$(pacman-conf DBPath 2>/dev/null) || dbpath=/var/lib/pacman
    [[ -n "$dbpath" ]] || dbpath=/var/lib/pacman
    lock="${dbpath%/}/db.lck"
  fi
  deadline=$((SECONDS + ${INSTALLER_LOCK_TIMEOUT:-300}))
  if [[ -e "$lock" ]]; then
    info "Waiting for the package database lock: $lock"
  fi
  while [[ -e "$lock" ]]; do
    if (( SECONDS >= deadline )); then
      warn "Package database is still locked after ${INSTALLER_LOCK_TIMEOUT:-300}s. Finish other package managers and rerun setup."
      warn "The lock was kept intact. If a previous process crashed, inspect it before removing a stale lock."
      INSTALLER_DATABASE_BLOCKED=true
      return 73
    fi
    sleep "${INSTALLER_LOCK_INTERVAL:-2}"
  done
}

installer_package_command() {
  local log="$1" attempt status
  shift
  for attempt in 1 2 3; do
    installer_wait_for_pacman || return $?
    if installer_run_logged "$log" env LC_ALL=C "$@"; then
      return 0
    else
      status=$?
    fi
    if ! grep -qiE 'unable to lock database|could not lock database' "$log"; then
      return "$status"
    fi
    warn "Another package transaction acquired the lock. Retrying ($attempt/3)."
    if (( attempt < 3 )); then
      sleep "${INSTALLER_LOCK_INTERVAL:-2}"
    fi
  done
  return "$status"
}

installer_pacman() {
  local log status
  log=$(mktemp) || return
  if installer_package_command "$log" sudo pacman "$@"; then
    status=0
  else
    status=$?
  fi
  rm -f "$log"
  return "$status"
}

import_missing_pgp_key() {
  local output="$1" package="$2" cache key fingerprint found=false matched
  # Bad signatures and invalid keys require investigation, not key import.
  if printf '%s\n' "$output" | grep -qiE 'BAD signature|BADSIG|KEYREVOKED|KEYEXPIRED|revoked|expired|FAILED.*checksum|checksum.*(FAILED|mismatch)|integrity check failed'; then
    warn "Invalid, revoked, or expired signature for $package. Verification remains enabled; inspect the package source."
    return 1
  fi
  cache="${YAY_CACHE_DIR:-${XDG_CACHE_HOME:-$HOME/.cache}/yay}/$package/.SRCINFO"
  if [[ ! -f "$cache" ]]; then
    warn "Cannot confirm the signing fingerprint: $cache is missing."
    return 1
  fi
  while IFS= read -r key; do
    matched=false
    while IFS= read -r fingerprint; do
      fingerprint="${fingerprint^^}"
      [[ "$fingerprint" =~ ^([0-9A-F]{40}|[0-9A-F]{64})$ ]] || continue
      [[ "$fingerprint" == *"${key^^}" ]] || continue
      found=true
      matched=true
      info "Fetching the missing key declared by $package: $fingerprint"
      local server imported=false
      for server in hkps://keyserver.ubuntu.com hkps://keys.openpgp.org; do
        if timeout 45s gpg --batch --keyserver-options timeout=15 --keyserver "$server" --recv-keys "$fingerprint"; then
          if gpg --batch --with-colons --fingerprint "$fingerprint" | awk -F: -v expected="$fingerprint" '$1 == "fpr" && $10 == expected { found=1 } END { exit !found }'; then
            imported=true
            break
          fi
        fi
      done
      if [[ "$imported" != true ]]; then
        warn "Could not fetch verified key $fingerprint. Retry when the keyserver is reachable."
        return 1
      fi
      success "Signing key imported; the next build must still verify its source signature."
      break
    done < <(awk '$1 == "validpgpkeys" && $2 == "=" { print $3 }' "$cache")
    if [[ "$matched" != true ]]; then
      warn "Missing key $key is not declared by $package; no key was imported for it."
      return 1
    fi
  done < <(printf '%s\n' "$output" | grep -oiE '(unknown public key|NO_PUBKEY)[[:space:]]+[0-9a-f]{16,64}' | awk '{print $NF}' | sort -u)
  if [[ "$found" != true ]]; then
    warn "No missing key matched the full validpgpkeys fingerprint for $package. Review .SRCINFO and the build error."
    return 1
  fi
}
