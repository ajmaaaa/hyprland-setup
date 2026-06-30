# Arch Hyprland Setup

Simple automated Arch Linux setup using:

- Hyprland
- Alacritty
- Swappy
- Rofi
- Celestial SDDM
- Powerlevel10k
- swww (wallpaper daemon)
- hypridle + hyprlock

---

# Installation

```bash
git clone https://github.com/ajmaaaa/hyprland-setup.git
cd hyprland-setup
chmod +x install.sh
./install.sh
```

> Do not run the script as root.

---

# Keybindings

| Shortcut | Action |
|----------|--------|
| `Mod + Enter` | Terminal |
| `Mod + Q` | Kill window |
| `Mod + Space` | App launcher |
| `Mod + F` | File manager |
| `Mod + Z/B/X` | Browser (Zen/Brave/Librewolf) |
| `Mod + C` | Antigravity IDE |
| `Mod + N` | Neovim |
| `Mod + V` | ProtonVPN |
| `Mod + P` | Display/Monitor setup |
| `Mod + ↑` | Fullscreen |
| `Mod + ↓` | Unfullscreen |
| `Mod + ← / →` | Move window |
| `Mod + H/J/K/L` | Focus window (Vim-style) |
| `Mod + Shift + Space` | Toggle floating |
| `Mod + R` | Resize mode |
| `Mod + 1-0` | Switch workspace |
| `Mod + Shift + 1-0` | Move to workspace |
| `Mod + Shift + E` | Power menu |
| `Mod + Shift + W` | Toggle wallpaper |
| `Mod + Shift + N` | Toggle dark/light |
| `Mod + Shift + C` | Reload config |
| `Print` | Screenshot (region) |
| `Shift + Print` | Screenshot (full) |
| `F1/F2/F3` | Mute/Vol-/Vol+ |
| `F5/F6` | Brightness-/+ |

---

# Repository Structure

```bash
hyprland-setup/
├── install.sh
├── packages/
│   ├── pacman.txt
│   ├── aur.txt
│   ├── npm.txt
│   └── services.txt
├── config/
│   ├── hypr/
│   │   ├── hyprland.conf
│   │   └── conf.d/
│   │       ├── variables.conf
│   │       ├── monitor.conf
│   │       ├── input.conf
│   │       ├── theme.conf
│   │       ├── keybinds.conf
│   │       ├── autostart.conf
│   │       ├── windowrules.conf
│   │       ├── hypridle.conf
│   │       └── hyprlock.conf
│   ├── scripts/
│   ├── alacritty/
│   └── swappy/
├── sddm/
│   └── celestial-sddm/
├── dotfiles/
└── powerlevel10k/
```

---

# Notes

- Arch Linux only
- Internet connection required
- Reboot recommended after installation
- Popup/floating windows (Zoom, etc.) handled automatically via `windowrulev2`
