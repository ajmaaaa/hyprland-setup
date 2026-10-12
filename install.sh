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
source "$SCRIPT_DIR/scripts/installer-ui.sh"
installer_ui_start
trap installer_ui_restore EXIT

PACMAN_FILE="$SCRIPT_DIR/packages/pacman.txt"
AUR_FILE="$SCRIPT_DIR/packages/aur.txt"
NPM_FILE="$SCRIPT_DIR/packages/npm.txt"
SERVICES_FILE="$SCRIPT_DIR/packages/services.txt"
DEFAULT_OFF_FILE="$SCRIPT_DIR/packages/default-off.txt"

for file in "$PACMAN_FILE" "$AUR_FILE" "$NPM_FILE" "$SERVICES_FILE" "$DEFAULT_OFF_FILE"; do
  if [[ ! -f "$file" ]]; then
    error "Missing required file: $file"
  fi
done

# =============================================================================
# PRE-CHECK: INTERNET & DNS
# =============================================================================

installer_stage "Network checks"
for prerequisite in sudo pacman curl git; do
  command -v "$prerequisite" >/dev/null || error "Missing prerequisite: $prerequisite. Install it before running setup."
done
info "Checking internet connection..."

MAX_RETRY=5
ATTEMPT=0
CONNECTED=false

while [[ $ATTEMPT -lt $MAX_RETRY ]]; do
  ATTEMPT=$((ATTEMPT + 1))
  if curl --silent --fail --location --max-time 10 --output /dev/null https://github.com; then
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

source "$SCRIPT_DIR/scripts/package-selection.sh"

# Load all installed packages into a map for fast lookup
declare -A INSTALLED_PKGS
if command -v pacman &>/dev/null; then
  while read -r pkg; do
    INSTALLED_PKGS["$pkg"]=1
  done < <(pacman -Qq)
fi

# --- PROMPT USER FOR PACMAN PACKAGES ---
installer_stage "Choose Pacman packages"
printf '  [Y] Install all recommended Pacman packages\n  [N] Choose packages with the full-screen checklist\n\n'
read -rp "  Proceed with all recommended Pacman packages? [Y/n]: " INSTALL_ALL_PACMAN
INSTALL_ALL_PACMAN="${INSTALL_ALL_PACMAN:-Y}"

# Initialize arrays with all recommended packages (default)
mapfile -t FINAL_PACMAN_PACKAGES < <(recommended_packages "$PACMAN_FILE")
mapfile -t FINAL_AUR_PACKAGES    < <(recommended_packages "$AUR_FILE")

PACMAN_INTERACTIVE=false
if [[ "${INSTALL_ALL_PACMAN,,}" == "n" ]]; then
  ensure_dialog
  if show_checklist "Pacman Packages" "$PACMAN_FILE" FINAL_PACMAN_PACKAGES; then
    PACMAN_INTERACTIVE=true
  fi
fi

info "Installing ${#FINAL_PACMAN_PACKAGES[@]} pacman packages."

# =============================================================================
# CONFIGURE PACMAN FOR BETTER DOWNLOAD RELIABILITY
# =============================================================================

installer_stage "Prepare package downloads"
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

installer_stage "System update"
info "Updating system packages..."
sudo pacman -Syu --noconfirm

# =============================================================================
# INSTALL PACMAN PACKAGES
# =============================================================================

installer_stage "Install Pacman packages"
info "Installing pacman packages..."

if [[ ${#FINAL_PACMAN_PACKAGES[@]} -gt 0 ]]; then
  set +e
  PACMAN_FAILED=()
  needed_flag="--needed"
  if [[ "$PACMAN_INTERACTIVE" == "true" ]]; then
    needed_flag=""
  fi
  # Attempt to install all pacman packages in one command (batch)
  if ! sudo pacman -S $needed_flag --noconfirm "${FINAL_PACMAN_PACKAGES[@]}"; then
    warn "Batch pacman installation failed. Retrying packages individually..."
    for pkg in "${FINAL_PACMAN_PACKAGES[@]}"; do
      if ! sudo pacman -S $needed_flag --noconfirm "$pkg"; then
        warn "Failed to install '$pkg' — retrying once..."
        sleep 3
        if ! sudo pacman -S $needed_flag --noconfirm "$pkg"; then
          warn "Skipping '$pkg' after retry failure."
          PACMAN_FAILED+=("$pkg")
        fi
      fi
    done
  fi
  set -e
  if [[ ${#PACMAN_FAILED[@]} -gt 0 ]]; then
    warn "The following pacman packages failed: ${PACMAN_FAILED[*]}"
  fi
fi
success "Pacman packages installed."

# =============================================================================
# INSTALL YAY (AUR HELPER)
# =============================================================================

installer_stage "Set up the AUR helper"
if ! command -v yay &>/dev/null; then
  info "Installing yay AUR helper..."
  sudo pacman -S --needed --noconfirm base-devel git
  # Add curl retry flag to makepkg config
  if ! grep -qF -- "--retry 5" /etc/makepkg.conf; then
    sudo sed -i '/curl/s/-o %o %u/--retry 5 --retry-delay 5 -o %o %u/' /etc/makepkg.conf
  fi

  YAY_BUILD_DIR=$(mktemp -d)
  YAY_CLONED=false
  for i in $(seq 1 5); do
    if git clone --depth=1 https://aur.archlinux.org/yay.git "$YAY_BUILD_DIR/yay"; then
      YAY_CLONED=true
      break
    fi
    warn "git clone failed, retrying... ($i/5)"
    rm -rf "$YAY_BUILD_DIR/yay"
    sleep 3
  done

  if [[ "$YAY_CLONED" == false ]]; then
    rm -rf "$YAY_BUILD_DIR"
    error "Failed to clone yay repository after 5 attempts. Check your internet connection."
  fi

  cd "$YAY_BUILD_DIR/yay"
  makepkg -si --noconfirm
  cd "$SCRIPT_DIR"
  rm -rf "$YAY_BUILD_DIR"
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

# --- PROMPT USER FOR AUR PACKAGES ---
installer_stage "Choose AUR packages"
# Parse aur.txt to display categories and packages nicely
while IFS= read -r line; do
  # Skip empty lines
  [[ -z "${line// }" ]] && continue
  # Skip separator lines
  [[ "$line" =~ ^[[:space:]]*#[[:space:]]*[=\-]+[[:space:]]*$ ]] && continue
  # Category header
  if [[ "$line" =~ ^[[:space:]]*#[[:space:]]+([A-Za-z][A-Za-z0-9\ /\&\.\-]+)[[:space:]]*$ ]]; then
    echo -e "${YELLOW}  Category: ${BASH_REMATCH[1]}${RESET}"
  elif [[ ! "$line" =~ ^[[:space:]]*# ]]; then
    pkg="$(echo "$line" | tr -d '[:space:]')"
    if [[ -n "$pkg" ]]; then
      if package_default_enabled "$pkg"; then
        echo -e "    • $pkg"
      else
        echo -e "    • $pkg (optional; default off)"
      fi
    fi
  fi
done < "$AUR_FILE"

printf '  [Y] Install all recommended AUR packages\n  [N] Choose packages with the full-screen checklist\n\n'
read -rp "  Proceed with all recommended AUR packages? [Y/n]: " INSTALL_ALL_AUR
INSTALL_ALL_AUR="${INSTALL_ALL_AUR:-Y}"

AUR_INTERACTIVE=false
if [[ "${INSTALL_ALL_AUR,,}" == "n" ]]; then
  ensure_dialog
  if show_checklist "AUR Packages" "$AUR_FILE" FINAL_AUR_PACKAGES; then
    AUR_INTERACTIVE=true
  fi
fi

# Print beautiful installation header
installer_stage "Download and build AUR packages"
if [[ ${#FINAL_AUR_PACKAGES[@]} -gt 0 ]]; then
  echo -e "Installing the following AUR packages:"
  for pkg in "${FINAL_AUR_PACKAGES[@]}"; do
    echo -e "  • ${GREEN}$pkg${RESET}"
  done
  echo ""
else
  echo -e "${YELLOW}No AUR packages selected for installation.${RESET}\n"
fi

AUR_MAX_RETRY=3

if [[ ${#FINAL_AUR_PACKAGES[@]} -gt 0 ]]; then
  sudo pacman -S --needed --noconfirm base-devel
  set +e
  AUR_FAILED=()
  aur_needed_flag="--needed"
  if [[ "$AUR_INTERACTIVE" == "true" ]]; then
    aur_needed_flag=""
  fi
  # Attempt to install all AUR packages in one command (batch)
  info "Running batch installation via yay..."
  if ! yay -S --noconfirm $aur_needed_flag --answerdiff None --answerclean None --pgpfetch "${FINAL_AUR_PACKAGES[@]}"; then
    warn "Batch AUR installation failed. Retrying packages individually..."
    for pkg in "${FINAL_AUR_PACKAGES[@]}"; do
      echo -e "${BLUE}[AUR]${RESET} Installing: ${YELLOW}$pkg${RESET}..."
      PKG_INSTALLED=false

      for attempt in $(seq 1 $AUR_MAX_RETRY); do
        aur_attempt_log=$(mktemp)
        installer_run_logged "$aur_attempt_log" yay -S --noconfirm $aur_needed_flag --answerdiff None --answerclean None --pgpfetch "$pkg"
        install_status=$?
        install_output=$(cat "$aur_attempt_log")
        rm -f "$aur_attempt_log"

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
  else
    success "Batch AUR package installation completed successfully."
  fi
  set +e # Disable exit-on-error for remaining non-critical setup steps to ensure config copying runs

  if [[ ${#AUR_FAILED[@]} -gt 0 ]]; then
    warn "The following AUR packages failed to install: ${AUR_FAILED[*]}"
    warn "Install them manually later with: yay -S ${AUR_FAILED[*]}"
  fi
fi

# =============================================================================
# INSTALL NPM PACKAGES
# =============================================================================

installer_stage "Install npm packages"
info "Installing global npm packages..."
mapfile -t NPM_PACKAGES < <(recommended_packages "$NPM_FILE")

if [[ ${#NPM_PACKAGES[@]} -gt 0 ]] && command -v npm >/dev/null; then
  if ! npm install --global --prefix "$HOME/.local" "${NPM_PACKAGES[@]}"; then
    warn "Failed to install global npm packages."
  else
    success "Global npm packages installed."
  fi
elif [[ ${#NPM_PACKAGES[@]} -gt 0 ]]; then
  warn "npm is unavailable. Install nodejs and npm to add the selected CLI tools."
fi

# =============================================================================
# ENABLE SYSTEM SERVICES
# =============================================================================

python3 "$SCRIPT_DIR/scripts/setup-ai-tools.py" || warn "AI tool profile setup failed. Rerun scripts/setup-ai-tools.py."

installer_stage "Enable system services"
info "Enabling system services..."
while read -r service; do
  [[ -z "$service" || "$service" =~ ^# ]] && continue
  if ! sudo systemctl enable "$service"; then
    warn "Failed to enable service: $service"
  else
    success "$service enabled."
  fi
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

installer_stage "Configure the desktop and utility panels"
info "Copying configuration files..."

# Hyprland main config
if [[ -d "$HOME/.config/hypr" ]]; then
  hypr_backup="$HOME/.local/state/hyprland-setup/hyprland/$(date +%Y%m%d-%H%M%S)"
  mkdir -p "$hypr_backup"
  cp -a "$HOME/.config/hypr" "$hypr_backup/"
fi
mkdir -p "$HOME/.config/hypr"
if [[ -d "$SCRIPT_DIR/config/hypr" ]]; then
  cp -r "$SCRIPT_DIR/config/hypr/." "$HOME/.config/hypr/"
  # The repository retains a legacy example, but new installs use Lua.
  rm -f "$HOME/.config/hypr/hyprland.conf"
  success "Hyprland configuration copied."
fi

# Hyprland scripts
mkdir -p "$HOME/.config/hypr/scripts/state"
echo "dark" > "$HOME/.config/hypr/scripts/state/state_theme"
if [[ -d "$SCRIPT_DIR/config/scripts" ]]; then
  cp -r "$SCRIPT_DIR/config/scripts/." "$HOME/.config/hypr/scripts/"
  chmod +x "$HOME"/.config/hypr/scripts/*.sh 2>/dev/null || true
  success "Hyprland scripts copied and made executable."
fi

# Workspace preview (only copy this shell, preserving other Quickshell configs)
PREVIEW_TARGET="$HOME/.config/quickshell/workspace-preview"
if [[ -d "$PREVIEW_TARGET" ]]; then
  cp -a "$PREVIEW_TARGET" "${PREVIEW_TARGET}.backup-$(date +%Y%m%d-%H%M%S)"
fi
mkdir -p "$PREVIEW_TARGET"
cp "$SCRIPT_DIR/config/quickshell/workspace-preview/"{shell.qml,start.sh,README.md} "$PREVIEW_TARGET/"
chmod +x "$PREVIEW_TARGET/start.sh"
if command -v quickshell &>/dev/null; then
  success "Workspace preview configured (starts with Hyprland)."
else
  warn "Workspace preview requires quickshell; install it if it was deselected."
fi

# Default viewers and Open With entries; skip applications that were not installed.
if [[ -f /opt/zen-browser-bin/application.ini ]]; then
  sudo /usr/bin/python3 "$SCRIPT_DIR/scripts/setup-zen.py" || warn "Could not apply Zen browser defaults."
fi
python3 "$SCRIPT_DIR/scripts/setup-archtidy.py" || warn "ArchTidy setup failed. Rerun scripts/setup-archtidy.py."
if ! python3 "$SCRIPT_DIR/scripts/setup-viewers.py"; then
  warn "Viewer setup failed. Rerun: python3 $SCRIPT_DIR/scripts/setup-viewers.py"
fi
if command -v obs &>/dev/null; then
  if ! python3 "$SCRIPT_DIR/scripts/setup-obs.py"; then
    warn "OBS preset setup failed. Rerun: python3 $SCRIPT_DIR/scripts/setup-obs.py"
  fi
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

installer_stage "Configure snapshots"
if [[ "$(findmnt -n -o FSTYPE /)" != btrfs ]]; then
  info "Skipping Snapper: the root filesystem is not Btrfs."
elif [[ -f /etc/snapper/configs/root ]]; then
  info "Keeping the existing Snapper root configuration."
elif sudo snapper -c root create-config /; then
  sudo snapper -c root set-config NUMBER_LIMIT=50 NUMBER_LIMIT_IMPORTANT=10 TIMELINE_CREATE=no
  success "Snapper root configuration created."
else
  warn "Snapper setup failed; existing files were preserved."
fi

# =============================================================================
# NVCHAD SETUP
# =============================================================================

installer_stage "Set up Neovim"
info "Setting up NvChad..."
nvchad_staging=$(mktemp -d)
if git clone --depth=1 https://github.com/NvChad/starter "$nvchad_staging/nvim"; then
  if [[ -e "$HOME/.config/nvim" ]]; then
    nvim_backup="$HOME/.local/state/hyprland-setup/neovim/$(date +%Y%m%d-%H%M%S)"
    mkdir -p "$nvim_backup"
    mv "$HOME/.config/nvim" "$nvim_backup/nvim"
  fi
  mkdir -p "$HOME/.config"
  mv "$nvchad_staging/nvim" "$HOME/.config/nvim"
  cat > "$HOME/.config/nvim/lua/chadrc.lua" << 'LUAEOF'
local M = {}
M.ui = { theme = "horizon" }
return M
LUAEOF
  success "NvChad installed. Existing Neovim configuration was backed up."
else
  warn "NvChad download failed; the existing Neovim configuration was preserved."
fi
rm -rf "$nvchad_staging"

# =============================================================================
# ROFI THEMES
# =============================================================================

installer_stage "Configure application menus"
info "Installing Rofi themes..."
YAY_BUILD_DIR=$(mktemp -d)
git clone --depth=1 https://github.com/adi1090x/rofi.git "$YAY_BUILD_DIR/rofi"
cd "$YAY_BUILD_DIR/rofi"
chmod +x setup.sh
./setup.sh
cd "$SCRIPT_DIR"
rm -rf "$YAY_BUILD_DIR"

ln -sf ~/.config/rofi/launchers/type-6/launcher.sh ~/.config/rofi/launcher_active.sh
sed -i "s/theme=.*/theme='style-7'/g" ~/.config/rofi/launchers/type-6/launcher.sh
ln -sf ~/.config/rofi/powermenu/type-1/powermenu.sh ~/.config/rofi/powermenu_active.sh
cp "$SCRIPT_DIR/config/rofi/connections.rasi" "$HOME/.config/rofi/connections.rasi"
  # Patch Rofi powermenus to use instant-off, lock, suspend, and logout for Hyprland
  for powermenu in ~/.config/rofi/powermenu/type-*/powermenu.sh; do
    if [[ -f "$powermenu" ]]; then
      sed -i "s|betterlockscreen -l|hyprctl dispatch 'hl.dsp.dpms({ action = \"off\" })' \&\& loginctl lock-session \&\& systemctl suspend|g" "$powermenu"
      sed -i 's/betterlockscreen/hyprlock/g' "$powermenu"
      # Use uname -n instead of hostname command which might be missing
      sed -i 's/`hostname`/$(uname -n)/g' "$powermenu"
      # Patch logout for Hyprland if not already present
      if ! grep -q "hl.dsp.exit()" "$powermenu"; then
        sed -i 's/openbox --exit/openbox --exit\n\t\t\telif [[ "$DESKTOP_SESSION" == '\''hyprland'\'' || "$DESKTOP_SESSION" == '\''Hyprland'\'' || -n "$HYPRLAND_INSTANCE_SIGNATURE" ]]; then\n\t\t\t\thyprctl dispatch '\''hl.dsp.exit()'\''/g' "$powermenu"
      fi
    fi
  done
  if [[ -f ~/.config/rofi/applets/bin/powermenu.sh ]]; then
    sed -i 's/`hostname`/$(uname -n)/g' ~/.config/rofi/applets/bin/powermenu.sh
  fi
  success "Rofi themes installed, symlinked, and patched for Hyprland."

# =============================================================================
# POWERLEVEL10K & ZSH
# =============================================================================

installer_stage "Configure Zsh and Powerlevel10k"
info "Setting up Powerlevel10k and ZSH..."
if [[ -f "$SCRIPT_DIR/powerlevel10k/powerlevel10k.zsh-theme" ]]; then
  mkdir -p "$HOME/powerlevel10k"
  cp -r "$SCRIPT_DIR/powerlevel10k/." "$HOME/powerlevel10k/"
elif [[ -f "$HOME/powerlevel10k/powerlevel10k.zsh-theme" ]]; then
  info "Using the existing Powerlevel10k theme."
else
  p10k_staging=$(mktemp -d)
  if git clone --depth=1 https://github.com/romkatv/powerlevel10k.git "$p10k_staging/theme"; then
    if [[ -e "$HOME/powerlevel10k" ]]; then
      mv "$HOME/powerlevel10k" "$HOME/powerlevel10k.backup-$(date +%Y%m%d-%H%M%S)"
    fi
    mv "$p10k_staging/theme" "$HOME/powerlevel10k"
    success "Powerlevel10k downloaded."
  else
    warn "Powerlevel10k download failed; Zsh will use its default prompt."
  fi
  rm -rf "$p10k_staging"
fi

zsh_backup="$HOME/.local/state/hyprland-setup/zsh/$(date +%Y%m%d-%H%M%S)"
mkdir -p "$zsh_backup"
for dotfile in .zshrc .p10k.zsh; do
  if [[ -f "$SCRIPT_DIR/dotfiles/$dotfile" ]]; then
    [[ ! -e "$HOME/$dotfile" ]] || cp -a "$HOME/$dotfile" "$zsh_backup/$dotfile"
    cp "$SCRIPT_DIR/dotfiles/$dotfile" "$HOME/$dotfile"
  fi
done

if command -v zsh >/dev/null; then
  zsh_path=$(command -v zsh)
  if [[ "${SHELL:-}" != "$zsh_path" ]]; then
    info "Changing the default shell to Zsh..."
    chsh -s "$zsh_path" || warn "Could not change the login shell. Run chsh manually after installation."
  fi
else
  warn "Zsh was not installed; the login shell was left unchanged."
fi

# =============================================================================
# INSTALL CELESTIAL SDDM THEME
# =============================================================================

installer_stage "Configure the login screen"
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
# BOOTLOADER, MKINITCPIO & PLYMOUTH SETUP
# =============================================================================

configure_bootloader_and_plymouth() {
  info "Configuring bootloader and Plymouth..."

  # 1. Install custom theme
  if [[ -d "$SCRIPT_DIR/plymouth/Arch-Plymouth" ]]; then
    info "Installing Arch-Plymouth theme..."
    sudo mkdir -p /usr/share/plymouth/themes/Arch-Plymouth
    sudo cp -r "$SCRIPT_DIR/plymouth/Arch-Plymouth/." /usr/share/plymouth/themes/Arch-Plymouth/
    success "Arch-Plymouth theme installed."
  else
    warn "Custom Arch-Plymouth theme directory not found. Skipping theme install."
  fi

  # 2. Plymouth configuration
  info "Configuring /etc/plymouth/plymouthd.conf..."
  sudo mkdir -p /etc/plymouth
  sudo tee /etc/plymouth/plymouthd.conf > /dev/null << 'EOF'
[Daemon]
Theme=Arch-Plymouth
ShowDelay=0
DeviceTimeout=8
UseFirmwareBackground=false
EOF
  success "Plymouth configuration written."

  # Set default theme using plymouth tool
  if command -v plymouth-set-default-theme &>/dev/null; then
    info "Setting default theme to Arch-Plymouth..."
    sudo plymouth-set-default-theme Arch-Plymouth || true
  fi

  # Disable systemd-stub splash in mkinitcpio preset to prevent duplicate boot screens
  if [[ -f "/etc/mkinitcpio.d/linux.preset" ]]; then
    info "Disabling systemd-stub splash screen in mkinitcpio preset..."
    sudo sed -i 's/--splash [^"]*//g' /etc/mkinitcpio.d/linux.preset
    success "Systemd-stub splash disabled."
  fi

  # 3. Configure Loader options for UKI systems (via /etc/kernel/cmdline)
  if [[ -f "/etc/kernel/cmdline" ]]; then
    info "Found UKI configuration at /etc/kernel/cmdline. Applying silent boot parameters..."
    sudo sed -i 's/\b\(quiet\|splash\|loglevel=3\|systemd.show_status=[a-z]*\|rd.systemd.show_status=[a-z]*\|rd.udev.log_level=3\|udev.log_priority=3\|vt.global_cursor_default=0\|bgrt_disable\)\b//g' /etc/kernel/cmdline
    sudo sed -i 's/ *$/ quiet splash loglevel=3 systemd.show_status=false rd.systemd.show_status=false rd.udev.log_level=3 udev.log_priority=3 vt.global_cursor_default=0 bgrt_disable/' /etc/kernel/cmdline
    success "Updated /etc/kernel/cmdline"
  fi

  # 4. Add plymouth to mkinitcpio hooks & configure Early KMS if present
  if [[ -f "/etc/mkinitcpio.conf" ]]; then
    info "Configuring mkinitcpio..."

    # Detect GPU and add matching module for Early KMS (hybrid-compatible)
    local gpu_drivers=()
    if lspci | grep -iq "intel"; then
      gpu_drivers+=("i915")
    fi
    if lspci | grep -iq "amd"; then
      gpu_drivers+=("amdgpu")
    fi
    if lspci | grep -iq "nvidia"; then
      gpu_drivers+=("nvidia" "nvidia_modeset" "nvidia_uvm" "nvidia_drm")
    fi

    if [[ ${#gpu_drivers[@]} -gt 0 ]]; then
      info "Detected GPU(s). Configuring Early KMS modules (${gpu_drivers[*]}) in mkinitcpio..."
      for mod in "${gpu_drivers[@]}"; do
        if ! grep -q "^MODULES=.*$mod" /etc/mkinitcpio.conf; then
          sudo sed -i "s/\(MODULES=(\)/\1$mod /" /etc/mkinitcpio.conf
        fi
      done
      success "Configured Early KMS modules."
    fi

    # Add plymouth hook at the correct place (after kms if present, else after udev)
    if ! grep -q "^HOOKS=.*plymouth" /etc/mkinitcpio.conf; then
      if grep -q "^HOOKS=.*kms" /etc/mkinitcpio.conf; then
        sudo sed -i 's/\(kms\)/\1 plymouth/' /etc/mkinitcpio.conf
      else
        sudo sed -i 's/\(udev\)/\1 plymouth/' /etc/mkinitcpio.conf
      fi
      success "Added plymouth hook to /etc/mkinitcpio.conf"
    else
      info "plymouth hook already present in /etc/mkinitcpio.conf"
    fi

    info "Regenerating initramfs..."
    sudo mkinitcpio -P || true
  fi

  # 5. Configure Loader Timeout & Plymouth parameters (quiet splash)
  # Auto-detect whether /boot (ESP) requires sudo to access.
  # Some systems mount it with fmask=0077,dmask=0077 (only root can access),
  # while others allow normal user read access. Handle both cases.
  BOOT_NEEDS_SUDO=false
  for boot_path in "/boot" "/efi" "/boot/efi"; do
    if [[ -d "$boot_path" ]] 2>/dev/null; then
      # /boot exists and is accessible without sudo
      break
    elif sudo test -d "$boot_path" 2>/dev/null; then
      # /boot exists but requires sudo to access
      BOOT_NEEDS_SUDO=true
      info "ESP at $boot_path requires elevated access (fmask=0077). Using sudo for boot configuration."
      break
    fi
  done

  # Helper: run a command with sudo only if /boot requires it
  boot_run() {
    if [[ "$BOOT_NEEDS_SUDO" == true ]]; then
      sudo "$@"
    else
      "$@"
    fi
  }

  # For systemd-boot config (timeout)
  for loader_conf in "/boot/loader/loader.conf" "/efi/loader/loader.conf" "/boot/efi/loader/loader.conf"; do
    if boot_run test -f "$loader_conf"; then
      info "Found systemd-boot config at $loader_conf. Setting timeout to 0..."
      # Replace existing timeout line, or append if missing
      if boot_run grep -q '^timeout' "$loader_conf"; then
        sudo sed -i 's/^timeout.*/timeout 0/' "$loader_conf"
      else
        echo "timeout 0" | sudo tee -a "$loader_conf" > /dev/null
      fi
      # Set console-mode to auto for cleaner boot
      if boot_run grep -q '^console-mode' "$loader_conf"; then
        sudo sed -i 's/^console-mode.*/console-mode auto/' "$loader_conf"
      else
        echo "console-mode auto" | sudo tee -a "$loader_conf" > /dev/null
      fi
      success "systemd-boot timeout set to 0 at $loader_conf"
    fi
  done

  # For systemd-boot entries (quiet splash)
  for entry_dir in "/boot/loader/entries" "/efi/loader/entries" "/boot/efi/loader/entries"; do
    if boot_run test -d "$entry_dir"; then
      info "Found systemd-boot entries directory at $entry_dir. Adjusting entries for Plymouth..."
      boot_run find "$entry_dir" -type f -name "*.conf" | while read -r entry_file; do
        if boot_run grep -q "^options " "$entry_file"; then
          local options_line
          options_line=$(boot_run grep "^options " "$entry_file")
          [[ ! "$options_line" =~ "quiet" ]] && options_line="$options_line quiet"
          [[ ! "$options_line" =~ "splash" ]] && options_line="$options_line splash"
          [[ ! "$options_line" =~ "loglevel=3" ]] && options_line="$options_line loglevel=3"
          if [[ "$options_line" =~ "systemd.show_status=auto" ]]; then
            options_line=${options_line//systemd.show_status=auto/systemd.show_status=false}
          elif [[ ! "$options_line" =~ "systemd.show_status=false" ]]; then
            options_line="$options_line systemd.show_status=false"
          fi
          [[ ! "$options_line" =~ "rd.systemd.show_status=false" ]] && options_line="$options_line rd.systemd.show_status=false"
          [[ ! "$options_line" =~ "rd.udev.log_level=3" ]] && options_line="$options_line rd.udev.log_level=3"
          [[ ! "$options_line" =~ "udev.log_priority=3" ]] && options_line="$options_line udev.log_priority=3"
          [[ ! "$options_line" =~ "vt.global_cursor_default=0" ]] && options_line="$options_line vt.global_cursor_default=0"
          [[ ! "$options_line" =~ "bgrt_disable" ]] && options_line="$options_line bgrt_disable"
          sudo sed -i "s|^options .*|$options_line|" "$entry_file"
          success "Updated systemd-boot entry: $(basename "$entry_file")"
        fi
      done
    fi
  done

  # GRUB configuration removed as the user uses systemd-boot
}

installer_stage "Configure the boot screen"
configure_bootloader_and_plymouth

# =============================================================================
# INSTALLATION COMPLETE
# =============================================================================

installer_stage "Installation complete"
echo ""
success "Hyprland setup finished. Review any warnings above before rebooting."
echo ""
read -rp "  Do you want to reboot the system now? [Y/n]: " REBOOT_CHOICE
REBOOT_CHOICE="${REBOOT_CHOICE:-Y}"
if [[ "${REBOOT_CHOICE,,}" == "y" ]]; then
  info "Rebooting..."
  sudo reboot
else
  info "Please reboot your system manually to apply all changes."
fi
