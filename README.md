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
- Quickshell workspace previews
- Papers (PDF), Loupe (images), mpv (video/audio)

---

# Installation

```bash
git clone https://github.com/ajmaaaa/hyprland-setup.git
cd hyprland-setup
chmod +x install.sh
./install.sh
```

> Do not run the script as root.

The recommended package selection includes the viewers and Quickshell. If an
application is deselected or fails to install, its file associations are skipped.

## Desktop defaults

| File type | Default application | Open With alternative |
|-----------|---------------------|-----------------------|
| PDF | Papers | Existing choices are retained |
| Images supported by Loupe | Loupe | Existing choices are retained |
| Audio/video supported by mpv | mpv | Existing choices are retained |
| Source code, text, JSON, YAML, local HTML | Antigravity IDE | Neovim (Alacritty) |

The installer merges MIME associations, registers the editor launchers, and
refreshes the desktop databases for Dolphin and other apps. Web links keep their
browser association. A browser's internal PDF reader is a separate preference:
in Zen, set Settings → General → Applications → PDF to use the system default
if you also want PDF downloads to open externally. This installer does not edit
browser profiles or disable embedded web viewers.

To reapply associations after installing a previously skipped viewer:

```bash
python3 scripts/setup-viewers.py
```

Existing changed MIME lists and launchers are backed up under
`~/.local/state/hyprland-setup/viewers/`. Unrelated associations are preserved.

Alt+Tab cycles existing workspaces on the focused monitor (Alt+Shift+Tab reverses
direction) and shows real window miniatures at the right-center of the focused
monitor. The active workspace is larger, the adjacent existing workspaces are
smaller, and all cards align right. Labels overlay the lower left; the lower
preview is slightly dimmed. The carousel slides and disappears after **1 second**.
Mod+number and other workspace changes hide the preview without showing it.
Window capture stops while hidden. Wallpaper, panels and compositor effects are
not captured; small text remains limited by the thumbnail size. Quickshell 0.3.1
and Hyprland's toplevel export support are required.

Configuration: `config/quickshell/workspace-preview/shell.qml`. Both the Lua and
legacy Hyprland configs launch the preview automatically on login. It can also
be started with `~/.config/quickshell/workspace-preview/start.sh`.

New Zsh terminals include `status`, an alias for `fastfetch -l arch2`.

`Mod + I` opens a 320×380 popup with a compact grid of round icon buttons and names
below: Wi-Fi, Bluetooth, Ethernet, Hotspot, Wireless, VPN, and Airplane.
The window keeps the same size across the chooser, lists, and detail pages;
long content scrolls within the panel. Choose Wi-Fi or Bluetooth to
open its searchable list with automatic refresh and a radio switch. Wi-Fi signal
strength uses icons without percentages. Bluetooth discovery runs while its page
is open and stops when leaving it. Escape returns to the chooser, then closes it;
Mod + I toggles the popup. Details, action menus, and password prompts stay inside
the same window, with labeled detail rows and separators. The interface is English.
Mod + P still opens the monitor menu.

- Wi-Fi: radio toggle, signal/security indicators, rescan, password prompt,
  disconnect, saved profiles, and connection details.
- Bluetooth: radio toggle, paired devices, connect/disconnect, forget, and battery
  level when reported. Discovery runs in the panel; pairing/PIN confirmation opens
  the Blueman authentication agent when required.
- Ethernet: connection controls and IP/DNS details. VPN: connect/disconnect through
  the official Proton VPN CLI using Automatic, without opening the app. Select a
  saved server to connect through NetworkManager instead. Add server imports a
  [Proton WireGuard configuration](https://protonvpn.com/support/wireguard-configurations)
  downloaded from your account and labels it with your chosen server name.
  Proton Free does not allow manual server selection through its CLI; the manual
  list requires these configuration files. Imported servers do not auto-connect.
- Airplane mode: Enable or Disable Wi-Fi and Bluetooth together. Hotspot: supported
  adapters only, a custom SSID and password, stop/edit controls. An adapter already
  connected to Wi-Fi is not reused. Same-adapter Wi-Fi sharing needs a virtual AP
  interface, which the panel does not yet configure. Use another adapter or a LAN
  upstream connection. Existing profiles are preserved; passwords use stdin.
- Advanced and enterprise Wi-Fi settings open NetworkManager's connection editor.
- Wireless debugging: Android ADB pairing code, connect by IP/port, device status,
  disconnect, and launch scrcpy for a selected device. Pairing codes are passed
  through stdin, never command arguments. The pairing and connection ports can
  differ; use the addresses displayed on the corresponding Android screen.
  See [Android's wireless ADB guide](https://developer.android.com/tools/adb#wireless-android11-command-line).

The installer includes NetworkManager, BlueZ, Blueman, nm-connection-editor, the
official Proton VPN CLI, and Android tools,
and enables NetworkManager/bluetooth services for the next boot. UI and styling: `config/scripts/connections-ui.py`; connection actions:
`config/scripts/connections.py`. GTK 3, python-gobject and android-tools are included.
Hotspot availability is checked against the adapter's NetworkManager AP capability;
sharing internet requires a reachable upstream connection (Wi-Fi, LAN, or USB tethering).

On a fresh OBS install, the installer creates a **Hyprland Recording** profile:
1920×1080, 30 FPS, Indistinguishable quality using x264, MKV recordings saved to
`~/Videos/OBS`. Adjust resolution for a different monitor. Existing OBS profiles
are preserved; a running OBS instance is skipped. Screen/audio sources must be
selected in OBS because they depend on the current session and hardware.

## Validation

```bash
python3 -m unittest discover -s tests -v
bash -n install.sh
zsh -n dotfiles/.zshrc
```

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
| `Mod + I` | Connections popup (Wi-Fi, Bluetooth, Ethernet, VPN, hotspot) |
| `Mod + ↑` | Fullscreen |
| `Mod + ↓` | Unfullscreen |
| `Mod + ← / →` | Move window |
| `Mod + H/J/K/L` | Focus window (Vim-style) |
| `Mod + Shift + Space` | Toggle floating |
| `Mod + R` | Resize mode |
| `Mod + 1-0` | Switch workspace |
| `Alt + Tab` / `Alt + Shift + Tab` | Next / previous workspace with preview |
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
