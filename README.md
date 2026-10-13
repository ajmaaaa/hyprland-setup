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

Recommended AUR packages include `ttf-wps-fonts` for WPS Office's Symbol,
Wingdings, and formula fonts, alongside `ttf-ms-fonts`. The installer refreshes
the font cache when WPS is installed and warns if its symbol-font package is
missing. Restart an already-running WPS instance after installing the fonts.

The installer uses one full-screen terminal for package selection, downloads,
builds, and configuration. In an existing Hyprland session it expands only the
terminal running setup and restores that window when the installer exits.
On a TTY or another desktop it uses the available terminal size. Package
checklists fill the terminal; retry output remains visible and records the
actual command exit status. Cancelling a checklist selects no packages.

The installer needs `sudo`, `pacman`, `curl`, and `git`. Network checks do not
rewrite or lock your DNS configuration. Existing Zsh/Powerlevel10k and Neovim
configuration is backed up when replaced. Snapper setup runs only on Btrfs and
preserves an existing root configuration.

The recommended package selection includes the viewers and Quickshell. If an
application is deselected or fails to install, its file associations are skipped.

Antigravity IDE stays in the AUR checklist but starts unchecked. It is excluded
from **all recommended AUR packages**; choose the interactive checklist and
enable it explicitly to install it. An existing installation is not removed.
Default-off packages are listed in `packages/default-off.txt`.

## AI coding tools

The recommended npm packages include `@anthropic-ai/claude-code` and
`@openai/codex`. They are installed as the current user with the npm prefix
`~/.local`, so no `sudo npm` is used. Installation methods are documented by
[Claude Code](https://code.claude.com/docs/en/setup#install-with-npm) and
[OpenAI](https://developers.openai.com/cookbook/examples/codex/using_goals_in_codex).

After installation:

```bash
claude           # Normal Claude Code; sign in to your Claude account
codex            # Codex CLI; complete its sign-in flow
claude-deepseek   # Claude Code with the separate custom DeepSeek profile
```

DeepSeek configuration is stored in `~/.config/claude-deepseek/config.json`.
The default custom model is `deepseek-flash[1m]`; change `model`, `small_model`,
`pro_model`, or `base_url` in this file to customize it. The DeepSeek `/model`
menu shows **DeepSeek V4.1 Flash** (`deepseek-flash`) and **DeepSeek V4 Pro**
(`deepseek-v4-pro`) instead of duplicated Claude family labels. **Default** is
the launcher's selected model, normally Flash, rather than a third model.
The `[1m]` suffix configures the context window; it is not a different model.
Version labels follow the [DeepSeek release notes](https://api-docs.deepseek.com/updates/)
and the model names returned by its API. The Default row resolves to the chosen
DeepSeek model without a separate ANTHROPIC_DEFAULT_MODEL override.
Custom labels use Claude Code's `modelPicker` setting (v2.1.242 or later).
The launcher uses the
[DeepSeek Anthropic-compatible integration](https://api-docs.deepseek.com/quick_start/agent_integrations/claude_code/).
To change the saved API key, API endpoint, or default model, run:

```bash
claude-deepseek --configure
```

The key prompt hides input. Leave a field blank to keep its current value. The
updated profile is saved atomically with permissions `0600`. If you previously
exported `DEEPSEEK_API_KEY`, run `unset DEEPSEEK_API_KEY` to use the saved new key.
`--help` describes the profile commands without requesting a key.

Set `DEEPSEEK_API_KEY`, or enter the key at the hidden prompt when launching;
prompted keys apply only to that session and are not saved. `DEEPSEEK_MODEL`
and `DEEPSEEK_BASE_URL` can override the custom profile for one session.

The custom launcher scopes provider variables to its child process and keeps
its state separately. It does not modify normal Claude settings, Codex settings,
or `.zshrc` provider variables. Existing keys in `~/.claude-deepseek.env` are
imported into the private custom profile without executing that file.
To use actual Claude models again, run `claude`;
switching Claude model aliases inside the DeepSeek session still uses DeepSeek.

Zsh loads `~/.config/hyprland-setup/ai-tools.zsh`. As requested, `claude` and
`claude-deepseek` use `--dangerously-skip-permissions`, while `codex` uses
`--dangerously-bypass-approvals-and-sandbox`. These commands run without tool
approval prompts; Codex also disables its sandbox. Login and API authentication
still apply. The old `claude-ds-auto` command forwards to the custom launcher.
The flags are documented by [Claude Code](https://code.claude.com/docs/en/permissions)
and [OpenAI](https://developers.openai.com/codex/security/).

Apply these Zsh functions and the custom launcher to an existing installation:

```bash
python3 scripts/setup-ai-tools.py
source ~/.zshrc
```

This preserves other Zsh customizations and creates a backup before appending the
managed source block. Repeated setup adds that block only once.

## Desktop defaults

When Zen is selected, the installer sets `zen.window-sync.enabled` to `false`
using a dedicated application default in
`/opt/zen-browser-bin/defaults/pref/hyprland-setup.js`. This applies before a new
profile is first opened and remains editable in `about:config`. Existing profile
preferences, bookmarks, and sessions are preserved; a saved user value can
override this factory default. Other browser defaults and policies are retained.

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

New Zsh terminals include `status`, an alias for `fastfetch -l arch2` when
fastfetch is installed. Startup tolerates missing optional themes/plugins,
uses standard `ls` aliases when eza is absent, and adds `~/.local/bin` only once.
Syntax highlighting loads last, after completion and key bindings.

`Mod + I` opens an 860×520 connection panel with a clean list of connections:
Wi-Fi, Bluetooth, Ethernet, Hotspot, VPN, Airplane Mode, and Wireless Debugging.
Hotspot and Wireless Debugging pages become compact when no QR is active and
expand when a QR is ready. Content uses a single scrollbar. Action buttons (Rescan, Saved, Settings,
Pairing) appear in the relevant toolbar or page card. Cancel is shown while an
operation is running, and details use Back/Esc.

- Wi-Fi: radio toggle, signal indicators, top toolbar actions (rescan, saved profiles,
  settings), password prompt with eye toggle, lock badges on Wi-Fi icons, a browser Login
  button when a connected network is detected as a captive portal, and QR Code
  sharing for phone scanning, clean disconnect, and connection details.
- Bluetooth: radio toggle, paired devices list, top toolbar rescan/settings icons,
  automatic device trust for headsets and TWS earbuds, and battery level reporting.
- Ethernet: clean disconnect/reconnect controls and IP/DNS details.
- VPN: connect/disconnect through Proton VPN CLI using Automatic, or select a free
  server (Singapore, Netherlands, Japan, United States) or custom WireGuard configs.
- Airplane mode: Enable or Disable all wireless hardware via rfkill and radio controls.
- Hotspot: Status toggle and credentials editor, with a large QR shown only when
  the hotspot is active and credentials match. Preserves the existing Wi-Fi
  connection with a separate AP interface when the radio supports concurrency.
  Same-radio sharing uses hostapd, dnsmasq, and isolated firewall rules. Starting
  and stopping requires system authentication with the laptop account password.
  **Use 2.4 GHz Wi-Fi** appears only when the current channel is restricted;
  **Sync hotspot password** appears only when old session credentials mismatch.
- Wireless debugging: A unified pairing card and live connected-device list.
  QR appears only during an active, ready pairing attempt. Pairing, connection,
  timeout, and error are separate states. Scan from Developer options → Wireless
  debugging → Pair device with QR code on the same network. Code pairing and
  direct IP:port are also available. Arch builds without ADB mDNS use native
  discovery. Already configured discovery does not request a password; a new
  firewall zone can require a one-time setup authorization. Connection success
  requires an ADB shell response. The panel checks again before opening scrcpy
  and displays failures, with logs in `~/.local/state/hypr-connections/`.

The installer includes NetworkManager, BlueZ, Blueman, nm-connection-editor, the
official Proton VPN CLI, and Android tools,
and enables NetworkManager/bluetooth services for the next boot. UI and styling: `config/scripts/connections-ui.py`; connection actions:
`config/scripts/connections.py`. GTK 3, python-gobject and android-tools are included.
Hotspot availability is checked against the adapter's NetworkManager AP capability;
sharing internet requires a reachable upstream connection (Wi-Fi, LAN, or USB tethering).

`Mod + U` or `Mod + Alt + C` opens the graphical ArchTidy panel. Choose a
category, search or check individual items, then click **Review & clean**.
The review screen lists every selected path and offers simulation or deletion.
Nothing is preselected. User files go to Trash; packages and system package
archives require authentication and are permanently removed. Moving files to
Trash does not free disk space until Trash is emptied. **Restore last cleanup**
restores user files from the latest cleanup without overwriting existing files.
The **Junk only** category includes superseded package archives (keeping two
versions) and thumbnail caches older than 30 days. It excludes personal files,
installed packages, and application configuration. All panel text is in English.
The installer puts ArchTidy in `~/.local/share/archtidy/` with a launcher in
`~/.local/bin/archtidy`; it works after the checkout is moved or removed.
Existing `~/.config/archtidy/config.toml` is preserved. The terminal interface
remains available with `archtidy tui`.

Idle panels close on outside mouse clicks, through non-consuming Hyprland mouse
bindings and per-panel runtime sockets. Hovering outside does not close them.
Connections stays open during authentication so a click outside cannot hide a
running operation. Esc and the close button are also available. See [repair audit](docs/panel-repair-audit.md)
for validation and hardware limitations.

On a fresh OBS install, the installer creates a **Hyprland Recording** profile:
1920×1080, 30 FPS, Indistinguishable quality using x264, MKV recordings saved to
`~/Videos/OBS`. Adjust resolution for a different monitor. Existing OBS profiles
also have their Simple, Advanced, and FFmpeg recording paths set to `~/Videos/OBS`,
with a backup before changes; their other settings are preserved. A running OBS
instance is skipped. To apply this to an existing install, close OBS and run
`python3 scripts/setup-obs.py`. Screen/audio sources must be
selected in OBS because they depend on the current session and hardware.

The installer adds Downloads, Documents, Pictures, Videos, Projects, and Git
to Dolphin/KDE Places and GTK 3/4 file chooser bookmarks. Existing custom
shortcuts are kept; changed files are backed up. Run
`python3 scripts/setup-places.py` to apply this to an existing install.
Close Dolphin before running the script. Dolphin and GTK/KDE file dialogs
default to modification time, newest first, including folders. Dolphin defaults
to Details view with Name, Size, and Modified columns and uses
shared view settings; only the generic Network shortcut and Recent/search groups
in KDE Places are hidden. Remote locations, devices, and removable devices stay
visible so connected phone storage and network mounts can still appear.
Ark adds Extract actions to Dolphin, with ZIP, TAR, TAR.GZ, TAR.BZ2, TAR.XZ,
TAR.ZST, 7Z, RAR, ARJ, LRZ, and LZO support through the installed backends.
File upload/open/save dialogs float at 60% of the monitor width and height,
centered on the monitor even above split windows, with an 85% size limit.

## Validation

```bash
python3 -m unittest discover -s tests -v
PYTHONPATH=archtidy python3 -m unittest discover -s archtidy/tests -v
bash -n install.sh
bash -n scripts/installer-ui.sh
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
| `Mod + U` / `Mod + Alt + C` | Graphical ArchTidy cleaner |
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
