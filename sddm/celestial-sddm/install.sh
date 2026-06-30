#!/bin/bash

# =============================================================================
# CELESTIAL SDDM INSTALLER
# =============================================================================

set -e

# =============================================================================
# COLORS
# =============================================================================

RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RESET='\033[0m'

info() {
  echo -e "${BLUE}[INFO]${RESET} $1"
}

success() {
  echo -e "${GREEN}[OK]${RESET} $1"
}

warn() {
  echo -e "${YELLOW}[WARN]${RESET} $1"
}

error() {
  echo -e "${RED}[ERROR]${RESET} $1"
  exit 1
}

# =============================================================================
# ROOT CHECK
# =============================================================================

if [[ "$EUID" -eq 0 ]]; then
  error "Do not run this script as root."
fi

# =============================================================================
# PATHS
# =============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

THEME_NAME="celestial"

SDDM_THEME_DIR="/usr/share/sddm/themes/$THEME_NAME"

CONFIG_DIR="$SCRIPT_DIR/configs"

# =============================================================================
# CHECK SDDM
# =============================================================================

if ! command -v sddm &>/dev/null; then
  error "SDDM is not installed."
fi

# =============================================================================
# INSTALL THEME
# =============================================================================

info "Installing celestial SDDM theme..."

sudo rm -rf "$SDDM_THEME_DIR"

sudo mkdir -p "$SDDM_THEME_DIR"

sudo cp -r "$SCRIPT_DIR/." "$SDDM_THEME_DIR/"

success "Theme files copied successfully."

# =============================================================================
# APPLY CONFIG
# =============================================================================

info "Applying SDDM configuration..."

sudo mkdir -p /etc/sddm.conf.d

# Create SDDM system config to use celestial theme
sudo tee /etc/sddm.conf.d/theme.conf > /dev/null << 'EOF'
[Theme]
Current=celestial
EOF

success "SDDM configured to use the celestial theme."

# =============================================================================
# PERMISSIONS
# =============================================================================

info "Setting permissions..."

sudo chmod -R 755 "$SDDM_THEME_DIR"

success "Permissions set successfully."

# =============================================================================
# DONE
# =============================================================================

echo ""
success "CELESTIAL SDDM INSTALLED!"
echo ""
