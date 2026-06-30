#!/bin/bash

# =============================================================================
# ARCH HYPRLAND SETUP INSTALLER
# Automated Arch Linux post-install setup script for Hyprland
# =============================================================================

set -e

# =============================================================================
# COLORS & HELPERS
# =============================================================================

RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
RESET='\033[0m'

info()    { echo -e "${BLUE}[INFO]${RESET} $1"; }
success() { echo -e "${GREEN}[OK]${RESET} $1"; }
warn()    { echo -e "${YELLOW}[WARN]${RESET} $1"; }
error()   { echo -e "${RED}[ERROR]${RESET} $1"; exit 1; }

# =============================================================================
# ROOT CHECK
# =============================================================================

if [[ "$EUID" -eq 0 ]]; then
  error "Do not run this script as root. Run as a standard user."
fi

# =============================================================================
# PATHS & REQUIREMENT CHECK
# =============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PACMAN_FILE="$SCRIPT_DIR/packages/pacman.txt"
AUR_FILE="$SCRIPT_DIR/packages/aur.txt"
NPM_FILE="$SCRIPT_DIR/packages/npm.txt"
SERVICES_FILE="$SCRIPT_DIR/packages/services.txt"

for file in "$PACMAN_FILE" "$AUR_FILE" "$NPM_FILE" "$SERVICES_FILE"; do
  if [[ ! -f "$file" ]]; then
    error "Missing required file: $file"
  fi
done

# =============================================================================
# PRE-CHECK: INTERNET & DNS
# =============================================================================

info "Checking internet connection..."
if ! ping -c 1 -W 3 8.8.8.8 &>/dev/null; then
  warn "Connection issues detected. Setting DNS to Google & Cloudflare..."
  sudo tee /etc/resolv.conf > /dev/null << 'EOF'
nameserver 8.8.8.8
nameserver 8.8.4.4
nameserver 1.1.1.1
EOF
  sudo chattr +i /etc/resolv.conf 2>/dev/null || true
  sleep 2
fi

MAX_RETRY=5
ATTEMPT=0
CONNECTED=false

while [[ $ATTEMPT -lt $MAX_RETRY ]]; do
  ATTEMPT=$((ATTEMPT + 1))
  if ping -c 1 -W 3 github.com &>/dev/null; then
    CONNECTED=true
    break
  fi
  warn "Waiting for network... ($ATTEMPT/$MAX_RETRY)"
  sleep 5
done

if [[ "$CONNECTED" == false ]]; then
  error "No internet connection after $MAX_RETRY attempts. Please check your network."
fi
success "Internet connection is stable."

# =============================================================================
# INTERACTIVE PACKAGE SELECTION
# =============================================================================

# Ensure 'dialog' is available for the interactive TUI checklist
ensure_dialog() {
  if ! command -v dialog &>/dev/null; then
    info "Installing 'dialog' for interactive package selection..."
    sudo pacman -S --noconfirm dialog
  fi
}

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

# Show an interactive dialog checklist for the given package file.
# Stores selected packages into the given array variable name.
show_checklist() {
  local title="$1"
  local file="$2"
  local -n result_ref="$3"   # nameref to output array

  local TMPFILE
  TMPFILE=$(mktemp)

  # Determine dialog dimensions based on terminal size
  local H W LH
  H=$(( $(tput lines) - 4 ))
  W=$(( $(tput cols) - 6 ))
  [[ $H -lt 20 ]] && H=20
  [[ $W -lt 60 ]] && W=60
  LH=$(( H - 8 ))

  # Build checklist items: ("pkg" "[CATEGORY]" "on") ...
  local ITEMS=()
  while IFS='|' read -r pkg category; do
    ITEMS+=("$pkg" "[$category]" "on")
  done < <(parse_packages "$file")

  dialog \
    --title " $title " \
    --backtitle "Arch Hyprland Setup — Package Selection" \
    --checklist "\nSelect packages to install.\n\n  SPACE = toggle on/off   ENTER = confirm   TAB = switch buttons\n" \
    "$H" "$W" "$LH" \
    "${ITEMS[@]}" 2>"$TMPFILE"

  local EXIT_CODE=$?

  if [[ $EXIT_CODE -ne 0 ]]; then
    rm -f "$TMPFILE"
    clear
    warn "Selection cancelled for '$title'. Falling back to all recommended packages."
    # Fallback: load all packages from file
    mapfile -t result_ref < <(grep -vE '^\s*#|^\s*$' "$file")
    return 1
  fi

  # Parse dialog output: space-separated, possibly quoted
  mapfile -t result_ref < <(cat "$TMPFILE" | tr -d '"' | tr ' ' '\n' | grep -v '^$')
  rm -f "$TMPFILE"
  clear
  return 0
}

# Full interactive package selection flow (pacman + AUR)
select_packages_interactively() {
  ensure_dialog
  show_checklist "Pacman Packages" "$PACMAN_FILE" FINAL_PACMAN_PACKAGES
  show_checklist "AUR Packages"    "$AUR_FILE"    FINAL_AUR_PACKAGES
}

# --- PROMPT USER ---
echo ""
echo -e "${BLUE}╔══════════════════════════════════════════════════════╗${RESET}"
echo -e "${BLUE}║          PACKAGE INSTALLATION OPTIONS                ║${RESET}"
echo -e "${BLUE}╠══════════════════════════════════════════════════════╣${RESET}"
echo -e "${BLUE}║  ${GREEN}[Y]${RESET}  Install with all recommended packages          ${BLUE}║${RESET}"
echo -e "${BLUE}║  ${YELLOW}[N]${RESET}  Choose packages interactively (checklist)      ${BLUE}║${RESET}"
echo -e "${BLUE}╚══════════════════════════════════════════════════════╝${RESET}"
echo ""
read -rp "  Proceed with all recommended packages? [Y/n]: " INSTALL_ALL
INSTALL_ALL="${INSTALL_ALL:-Y}"

# Initialize arrays with all recommended packages (default)
mapfile -t FINAL_PACMAN_PACKAGES < <(grep -vE '^\s*#|^\s*$' "$PACMAN_FILE")
mapfile -t FINAL_AUR_PACKAGES    < <(grep -vE '^\s*#|^\s*$' "$AUR_FILE")

if [[ "${INSTALL_ALL,,}" == "n" ]]; then
  select_packages_interactively
fi

info "Installing ${#FINAL_PACMAN_PACKAGES[@]} pacman packages and ${#FINAL_AUR_PACKAGES[@]} AUR packages."

# =============================================================================
# CONFIGURE PACMAN FOR BETTER DOWNLOAD RELIABILITY
# =============================================================================

info "Configuring pacman for reliable downloads..."
# Enable parallel downloads
if ! grep -q '^ParallelDownloads' /etc/pacman.conf; then
  sudo sed -i '/^#ParallelDownloads/s/^#//' /etc/pacman.conf
fi
# Add curl retry to XferCommand
if ! grep -q 'XferCommand' /etc/pacman.conf; then
  echo -e '\nXferCommand = /usr/bin/curl --retry 5 --retry-delay 5 --connect-timeout 30 -L -o %o %u' \
    | sudo tee -a /etc/pacman.conf > /dev/null
fi
success "Pacman configured."

# =============================================================================
# SYSTEM UPDATE
# =============================================================================

info "Updating system packages..."
sudo pacman -Syu --noconfirm

# =============================================================================
# INSTALL PACMAN PACKAGES
# =============================================================================

info "Installing pacman packages..."

if [[ ${#FINAL_PACMAN_PACKAGES[@]} -gt 0 ]]; then
  set +e
  PACMAN_FAILED=()
  for pkg in "${FINAL_PACMAN_PACKAGES[@]}"; do
    if ! sudo pacman -S --needed --noconfirm "$pkg"; then
      warn "Failed to install '$pkg' — retrying once..."
      sleep 3
      if ! sudo pacman -S --needed --noconfirm "$pkg"; then
        warn "Skipping '$pkg' after retry failure."
        PACMAN_FAILED+=("$pkg")
      fi
    fi
  done
  set -e
  if [[ ${#PACMAN_FAILED[@]} -gt 0 ]]; then
    warn "The following pacman packages failed: ${PACMAN_FAILED[*]}"
  fi
fi
success "Pacman packages installed."

# =============================================================================
# INSTALL YAY (AUR HELPER)
# =============================================================================

if ! command -v yay &>/dev/null; then
  info "Installing yay AUR helper..."
  # Add curl retry flag to makepkg config
  if ! grep -qF -- "--retry 5" /etc/makepkg.conf; then
    sudo sed -i '/curl/s/-o %o %u/--retry 5 --retry-delay 5 -o %o %u/' /etc/makepkg.conf
  fi

  TMPDIR=$(mktemp -d)
  YAY_CLONED=false
  for i in $(seq 1 5); do
    if git clone --depth=1 https://aur.archlinux.org/yay.git "$TMPDIR/yay"; then
      YAY_CLONED=true
      break
    fi
    warn "git clone failed, retrying... ($i/5)"
    rm -rf "$TMPDIR/yay"
    sleep 3
  done

  if [[ "$YAY_CLONED" == false ]]; then
    rm -rf "$TMPDIR"
    error "Failed to clone yay repository after 5 attempts. Check your internet connection."
  fi

  cd "$TMPDIR/yay"
  makepkg -si --noconfirm
  cd "$SCRIPT_DIR"
  rm -rf "$TMPDIR"
  success "yay installed successfully."
else
  info "yay is already installed."
fi

# =============================================================================
# INSTALL AUR PACKAGES (WITH PGP ERROR HANDLING + RETRY)
# =============================================================================

# Configure GPG keyserver for reliable AUR builds
info "Configuring GPG keyserver..."
mkdir -p ~/.gnupg
chmod 700 ~/.gnupg
if ! grep -q 'keyserver hkps://keyserver.ubuntu.com' ~/.gnupg/gpg.conf 2>/dev/null; then
  echo 'keyserver hkps://keyserver.ubuntu.com' >> ~/.gnupg/gpg.conf
fi
gpgconf --kill dirmngr 2>/dev/null || true
success "GPG keyserver configured."

# Attempt to import a missing PGP key extracted from build error output
import_missing_pgp_key() {
  local output="$1"
  local key_id

  # Try to extract key ID from various GPG/makepkg error formats
  key_id=$(echo "$output" | grep -oP '(?<=key |NO_PUBKEY |unknown public key |KEYEXPIRED |KEYREVOKED |signature from ")[0-9A-Fa-f]{8,}' | tail -n1)

  # Fallback: scan lines mentioning key/gpg/pgp/signature for any 16+ char hex string
  if [[ -z "$key_id" ]]; then
    key_id=$(echo "$output" | grep -iE 'key|gpg|pgp|signature' | grep -oP '[0-9A-Fa-f]{16,}' | tail -n1)
  fi

  if [[ -z "$key_id" ]]; then
    warn "Could not extract PGP key ID from error output. Manual fix may be needed."
    warn "Relevant output: $(echo "$output" | grep -iE 'key|gpg|pgp|signature' | head -5)"
    return 1
  fi

  warn "PGP key not found: $key_id — attempting import via --recv-keys..."
  gpgconf --kill dirmngr 2>/dev/null || true

  local KEYSERVERS=(
    "hkps://keyserver.ubuntu.com"
    "hkps://keys.openpgp.org"
    "hkps://pgp.mit.edu"
    "hkp://keyserver.ubuntu.com:80"
  )

  for ks in "${KEYSERVERS[@]}"; do
    info "Trying keyserver: $ks"
    if gpg --keyserver "$ks" --recv-keys "$key_id"; then
      success "PGP key $key_id imported from $ks."
      return 0
    fi
    warn "Failed from $ks, trying next..."
  done

  warn "All keyservers failed for key $key_id."
  warn "You can try manually: gpg --recv-keys $key_id"
  return 1
}

info "Installing AUR packages..."

AUR_MAX_RETRY=3

if [[ ${#FINAL_AUR_PACKAGES[@]} -gt 0 ]]; then
  set +e
  AUR_FAILED=()
  for pkg in "${FINAL_AUR_PACKAGES[@]}"; do
    info "Installing: $pkg"
    PKG_INSTALLED=false

    for attempt in $(seq 1 $AUR_MAX_RETRY); do
      install_output=$(yay -S --noconfirm --needed --answerdiff None --answerclean None --pgpfetch "$pkg" 2>&1)
      install_status=$?

      if [[ $install_status -eq 0 ]]; then
        success "$pkg installed successfully."
        PKG_INSTALLED=true
        break
      fi

      warn "Attempt $attempt/$AUR_MAX_RETRY failed for $pkg."

      # Handle PGP/GPG key issues before retrying
      if echo "$install_output" | grep -qiE "pgp|gpg|signature|key|FAILED"; then
        warn "PGP issue detected — attempting key import..."
        import_missing_pgp_key "$install_output"
      fi

      if [[ $attempt -lt $AUR_MAX_RETRY ]]; then
        warn "Retrying $pkg in 5 seconds..."
        sleep 5
      fi
    done

    if [[ "$PKG_INSTALLED" == false ]]; then
      warn "Skipping $pkg after $AUR_MAX_RETRY failed attempts."
      AUR_FAILED+=("$pkg")
    fi
  done
  set -e

  if [[ ${#AUR_FAILED[@]} -gt 0 ]]; then
    warn "The following AUR packages failed to install: ${AUR_FAILED[*]}"
    warn "Install them manually later with: yay -S ${AUR_FAILED[*]}"
  fi
fi

# =============================================================================
# INSTALL NPM PACKAGES
# =============================================================================

info "Installing global npm packages..."
NPM_PACKAGES=$(grep -vE '^\s*#|^\s*$' "$NPM_FILE")

if [[ -n "$NPM_PACKAGES" ]]; then
  sudo npm install -g $NPM_PACKAGES
fi
success "Global npm packages installed."

# =============================================================================
# ENABLE SYSTEM SERVICES
# =============================================================================

info "Enabling system services..."
while read -r service; do
  [[ -z "$service" || "$service" =~ ^# ]] && continue
  sudo systemctl enable --now "$service"
  success "$service enabled."
done < "$SERVICES_FILE"

# Add user to libvirt/kvm groups if libvirtd is in the services list
if grep -q "libvirtd.service" "$SERVICES_FILE"; then
  info "Adding user to libvirt and kvm groups..."
  sudo usermod -aG libvirt,kvm "$USER"
  sudo virsh net-autostart default 2>/dev/null || true
  sudo virsh net-start default 2>/dev/null || true
  success "User added to QEMU/KVM groups."
fi

# =============================================================================
# COPY CONFIGURATION FILES
# =============================================================================

info "Copying configuration files..."

# Hyprland main config
mkdir -p "$HOME/.config/hypr"
if [[ -d "$SCRIPT_DIR/config/hypr" ]]; then
  cp -r "$SCRIPT_DIR/config/hypr/." "$HOME/.config/hypr/"
  success "Hyprland configuration copied."
fi

# Hyprland scripts
mkdir -p "$HOME/.config/hypr/scripts/state"
if [[ -d "$SCRIPT_DIR/config/scripts" ]]; then
  cp -r "$SCRIPT_DIR/config/scripts/." "$HOME/.config/hypr/scripts/"
  chmod +x "$HOME"/.config/hypr/scripts/*.sh 2>/dev/null || true
  success "Hyprland scripts copied and made executable."
fi

# Alacritty
mkdir -p "$HOME/.config/alacritty"
if [[ -d "$SCRIPT_DIR/config/alacritty" ]]; then
  cp -r "$SCRIPT_DIR/config/alacritty/." "$HOME/.config/alacritty/"
  success "Alacritty configuration copied."
fi

# Dunst
mkdir -p "$HOME/.config/dunst"
if [[ -d "$SCRIPT_DIR/config/dunst" ]]; then
  cp -r "$SCRIPT_DIR/config/dunst/." "$HOME/.config/dunst/"
  success "Dunst configuration copied."
fi

# Swappy
mkdir -p "$HOME/.config/swappy"
if [[ -d "$SCRIPT_DIR/config/swappy" ]]; then
  cp -r "$SCRIPT_DIR/config/swappy/." "$HOME/.config/swappy/"
  success "Swappy configuration copied."
fi

# Symlink hyprlock and hypridle configs to expected paths
if [[ -f "$HOME/.config/hypr/conf.d/hyprlock.conf" ]]; then
  ln -sf "$HOME/.config/hypr/conf.d/hyprlock.conf" "$HOME/.config/hypr/hyprlock.conf"
  success "Hyprlock config symlinked."
fi
if [[ -f "$HOME/.config/hypr/conf.d/hypridle.conf" ]]; then
  ln -sf "$HOME/.config/hypr/conf.d/hypridle.conf" "$HOME/.config/hypr/hypridle.conf"
  success "Hypridle config symlinked."
fi

# =============================================================================
# SNAPPER CONFIGURATION
# =============================================================================

info "Configuring Snapper for root..."
sudo mkdir -p /etc/snapper/configs
sudo tee /etc/snapper/configs/root > /dev/null << 'EOF'
SUBVOLUME="/"
FSTYPE="btrfs"
QGROUP=""
SPACE_LIMIT="0.5"
FREE_LIMIT="0.2"
ALLOW_USERS=""
ALLOW_GROUPS=""
SYNC_ACL="no"
BACKGROUND_COMPARISON="yes"
NUMBER_CLEANUP="yes"
NUMBER_MIN_AGE="3600"
NUMBER_LIMIT="50"
NUMBER_LIMIT_IMPORTANT="10"
TIMELINE_CREATE="no"
TIMELINE_CLEANUP="yes"
TIMELINE_LIMIT_HOURLY="3"
TIMELINE_LIMIT_DAILY="5"
TIMELINE_LIMIT_WEEKLY="2"
TIMELINE_LIMIT_MONTHLY="1"
TIMELINE_LIMIT_QUARTERLY="0"
TIMELINE_LIMIT_YEARLY="0"
EMPTY_PRE_POST_CLEANUP="yes"
EMPTY_PRE_POST_MIN_AGE="3600"
EOF
success "Snapper root configuration updated."

# =============================================================================
# NVCHAD SETUP
# =============================================================================

info "Setting up NvChad..."
rm -rf ~/.config/nvim ~/.local/share/nvim ~/.cache/nvim
git clone --depth=1 https://github.com/NvChad/starter ~/.config/nvim

mkdir -p ~/.config/nvim/lua
cat > ~/.config/nvim/lua/chadrc.lua << 'LUAEOF'
---@type ChadrcConfig
local M = {}
M.ui = { theme = "horizon" }
return M
LUAEOF
success "NvChad cloned and horizon theme applied."

# =============================================================================
# ROFI THEMES
# =============================================================================

info "Installing Rofi themes..."
TMPDIR=$(mktemp -d)
git clone --depth=1 https://github.com/adi1090x/rofi.git "$TMPDIR/rofi"
cd "$TMPDIR/rofi"
chmod +x setup.sh
./setup.sh
cd "$SCRIPT_DIR"
rm -rf "$TMPDIR"

ln -sf ~/.config/rofi/launchers/type-1/launcher.sh ~/.config/rofi/launcher_active.sh
ln -sf ~/.config/rofi/powermenu/type-1/powermenu.sh ~/.config/rofi/powermenu_active.sh
success "Rofi themes installed and symlinked."

# =============================================================================
# POWERLEVEL10K & ZSH
# =============================================================================

info "Setting up Powerlevel10k and ZSH..."
if [[ -d "$SCRIPT_DIR/powerlevel10k" && "$(ls -A "$SCRIPT_DIR/powerlevel10k" 2>/dev/null | grep -v '.gitkeep')" ]]; then
  cp -r "$SCRIPT_DIR/powerlevel10k/." ~/powerlevel10k/
else
  git clone --depth=1 https://github.com/romkatv/powerlevel10k.git ~/powerlevel10k
fi
success "Powerlevel10k configured."

if [[ -f "$SCRIPT_DIR/dotfiles/.zshrc" ]]; then
  cp "$SCRIPT_DIR/dotfiles/.zshrc" ~/.zshrc
fi
if [[ -f "$SCRIPT_DIR/dotfiles/.p10k.zsh" ]]; then
  cp "$SCRIPT_DIR/dotfiles/.p10k.zsh" ~/.p10k.zsh
fi

if [[ "$SHELL" != "$(which zsh)" ]]; then
  info "Changing default shell to ZSH..."
  chsh -s "$(which zsh)"
  success "Default shell changed to ZSH. Will take effect upon next login."
fi

# =============================================================================
# INSTALL CELESTIAL SDDM THEME
# =============================================================================

info "Setting up celestial-sddm..."
mkdir -p ~/Projects/sddm
SDDM_SOURCE="$SCRIPT_DIR/sddm/celestial-sddm"
SDDM_TARGET="$HOME/Projects/sddm/celestial-sddm"

if [[ -d "$SDDM_SOURCE" ]]; then
  rm -rf "$SDDM_TARGET"
  mkdir -p "$SDDM_TARGET"
  cp -r "$SDDM_SOURCE/." "$SDDM_TARGET/"

  info "Setting executable permissions for SDDM scripts..."
  find "$SDDM_TARGET" -type f -name "*.sh" -exec chmod +x {} \;

  # Ensure qt6-virtualkeyboard is installed — required by the celestial theme
  if ! pacman -Qi qt6-virtualkeyboard &>/dev/null; then
    info "Installing qt6-virtualkeyboard (required for celestial theme)..."
    sudo pacman -S --noconfirm --needed qt6-virtualkeyboard
  fi

  if [[ -f "$SDDM_TARGET/install.sh" ]]; then
    info "Running celestial-sddm installer..."
    cd "$SDDM_TARGET"
    bash install.sh
    cd "$SCRIPT_DIR"
    success "celestial-sddm installed successfully."
  else
    warn "install.sh not found inside celestial-sddm."
  fi
else
  warn "sddm/celestial-sddm directory not found. Skipping SDDM setup."
fi

# Verify SDDM theme installation
if [[ -d "/usr/share/sddm/themes/celestial" ]]; then
  success "SDDM celestial theme verified at /usr/share/sddm/themes/celestial."
else
  warn "SDDM theme directory not found — theme may not have been installed correctly."
fi

# =============================================================================
# INSTALLATION COMPLETE
# =============================================================================

echo ""
echo -e "${GREEN}${BOLD}======================================================${RESET}"
echo -e "${GREEN}${BOLD}     HYPRLAND INSTALLATION COMPLETED SUCCESSFULLY!   ${RESET}"
echo -e "${GREEN}${BOLD}======================================================${RESET}"
echo ""
echo -e "  ${YELLOW}The system will reboot in 5 seconds...${RESET}"
echo -e "  ${YELLOW}Press Ctrl+C to cancel the reboot.${RESET}"
echo ""
sleep 5
sudo reboot
