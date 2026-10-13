# Panel audit — October 12, 2026

The active configuration was compared with the working tree at
`~/Git/hyprland-setup`, including existing local changes. The backup made before
repairs is at `~/.local/state/hyprland-repair/20261012-154313/`.
Image attachments were unavailable during the audit; checks used the source code
and panels running on the desktop.

## Findings and changes

- The active Hyprland configuration differed in screenshot bindings, workspace
  preview autostart, and idle settings. Repository files were restored; the new
  graphical panels and outside-click handling were saved in both the repository
  and the active configuration.
- ArchTidy previously used curses and automatic scanner selections. The GTK 3
  GUI now selects nothing automatically and provides checkboxes, search, path
  details, cross-category selection review, dry runs, and cleanup. The scanner
  respects the user's TOML configuration and blacklist. Scanning runs on a
  worker, starting with caches/packages; other categories are scanned when opened.
- Files in Trash still occupy disk space, which the GUI explains. Packages are
  removed with `pacman -R` so dependencies outside the reviewed list are retained.
  System pacman archives require authentication; permanent deletion applies only
  to the archive files included in the review.
- Undo previously guessed `file.*` names, which did not match GIO Trash entries.
  Restore now uses `.trashinfo`, original paths, and the batch timestamp, and
  refuses to overwrite destination files. A dry run does not replace a real
  cleanup batch. Restore currently supports the user's Trash; files trashed on
  other volumes may need to be restored through a file manager.
- Hotspot previously converted the primary adapter into an AP. It now uses a
  free adapter or the `hypr-hotspot` interface, following the uplink channel when
  sharing one radio. Wi-Fi client and AP connections are reported separately.
  Radios without AP + managed support reject activation while preserving the
  primary connection. The virtual interface is retained for later use without
  enabling hotspot autoconnect.
- `iw list` on this laptop reports managed + AP support on one channel. Creating
  a virtual interface requires authentication through pkexec; driver support and
  DFS channel restrictions still determine whether the AP can start.
- Local ADB (`android-tools 37.0.0-5`) reports that mDNS is unsupported, and Avahi
  is inactive. The direct mDNS fallback reads DNS record names, SRV records, and
  A/AAAA addresses, including DNS compression and records spread across packets.
  Each QR session has a unique `studio-*` name; pairing uses only that session's
  service. Connection then uses the `_adb-tls-connect._tcp` port rather than an
  IP without a port or legacy port 5555. The QR code has a four-module quiet zone
  and is displayed without blur interpolation. Code-pairing fallback controls
  now work after the QR operation ends.
- Focus-out is not an outside-click signal with `follow_mouse=1`. Non-consuming
  mouse bindings send a close request over a socket only when the cursor is
  outside the panel rectangle. Clicks still reach their destination application.
  Clicking an authentication dialog does not close the panel. GTK Application
  retains workers for running operations until they finish if the panel closes.

## Validation

- Repository and ArchTidy unit tests passed, including QR session matching,
  connection ports, DNS compression, hotspot uplink channels, primary-connection
  protection, Trash restore, and removal of only the reviewed packages.
- Desktop GUI smoke checks covered checkboxes, search, selection review, empty
  initial selections, keeping the panel open on inside clicks, closing it on
  outside clicks, and socket cleanup. Connections panel launch and outside-click
  handling were also tested.
- The multicast mDNS socket started successfully on the laptop, but no ADB
  service was found during the audit. Hyprland reloaded without configuration errors.
- No user files or packages were cleaned during this session. GUI tests used
  sample candidates, and package execution was tested only with mocks.
- Actual hotspot activation and phone pairing were not tested end to end because
  they require system authentication and a phone scanning the QR code. The router
  must allow multicast mDNS and communication between devices.

ADB protocol reference:
https://android.googlesource.com/platform/packages/modules/adb/+/HEAD/docs/dev/adb_wifi.md

## Hotspot error follow-up

User testing showed that `hypr-hotspot` was unavailable. Kernel and
wpa_supplicant logs revealed that NetworkManager initialized the interface as
managed, violating the limit of one managed interface. The subsequent fix uses
hostapd on an unmanaged AP interface, dnsmasq for DNS/DHCP, and NAT/FORWARD rules
marked only with `hypr-hotspot`. This backend requires authentication on start/stop
and installs hostapd on first use if it is missing. A failed start cleans up its
services, IP address, interface, and firewall rules. The helper leaves the primary
Wi-Fi connection unchanged and preserves global IP forwarding to avoid disrupting
Docker/VPN networking.

The primary Wi-Fi channel at the time of the error was 64 (5320 MHz), marked
no IR and radar detection by the driver. AP activation on this channel is rejected
before authentication. The same SSID is available on channel 11 at 2.4 GHz.
**Use 2.4 GHz Wi-Fi** selects the 2.4 GHz BSSID for the same SSID; switching
reconnects Wi-Fi and may briefly interrupt the connection. **Turn On Hotspot**
then starts the AP backend. The old failed interface was made unmanaged so
wpa_supplicant would stop trying to initialize a second client.

hostapd AP activation and phone connectivity still require user testing. No claim
is made that hotspot activation succeeded on channel 64. Additional unit tests
cover rejecting restricted channels before system changes, the isolated AP
lifecycle, and cleanup after startup failure.

## Hotspot QR connection follow-up

nmcli `FREQ` output includes units, such as `2462 MHz`. The previous frequency
filter used isdigit and skipped available 2.4 GHz networks. The filter now accepts
numbers followed by MHz. The band-switch button does not reconnect Wi-Fi that
is already using 2.4 GHz.

When the hostapd AP first started, its credentials came from an old NetworkManager
profile, while the panel subsequently read a different preferences file. The
actual AP SSID was `Hyprland-Hotspot`, but the panel preferences used `Arch`.
After a successful start, the exact credentials sent to the AP are now saved as
panel state. Inactive NM profiles no longer overwrite saved preferences.

For older sessions with mismatched state, status checks read the actual SSID
from iw. The old password is not displayed, and the QR code is hidden on a
mismatch. The synchronization button reads the active AP configuration through
an authenticated helper and saves the result in a user file with mode 0600.
Changes to active AP credentials are saved only after a successful restart.

During this check, the AP and DHCP services were active on channel 6, but logs
showed no connected station or DHCP exchange with a phone. Phone connectivity
was therefore not claimed; the confirmed SSID/credential mismatch was repaired
before another connection test.

## Devices stuck connecting follow-up

The 19:31 session log showed successful WPA authentication followed by a
connection drop about 18 seconds later without a DHCP lease. AP and dnsmasq were
active, with gateway 10.42.88.1/24 and a DHCP socket on the hotspot interface.
Firewalld was active; the hotspot interface had no explicit zone and inherited
the public zone, which did not allow DHCP/DNS. The helper's iptables ACCEPT rules
did not override rejection from firewalld's nftables hook.

The helper now puts only the hotspot interface in the runtime `nm-shared` zone,
the built-in zone for network sharing. It saves the previous zone before changes
and restores it on stop or failed-start cleanup. Cleanup does not overwrite a
zone subsequently changed by the user. With firewalld inactive, the previous
iptables path remains in use. `repair-firewall` applies changes to an active
session without restarting the AP or primary Wi-Fi connection. No global
firewall reload is performed.

The fix was applied to the active configuration and repository. Seven helper
tests and all 49 repository tests passed in the desktop session. The runtime
zone was confirmed as `nm-shared`, and the uplink remained connected. During the
19:39:17 retest, dnsmasq logged DHCPACK 10.42.88.167 for an A13 phone; the interface
neighbor table also showed its MAC address. Connection and IP assignment were
verified. Internet access on the phone was not confirmed; one upstream DNS log
rejected a recursive query. Earlier GTK tests in the sandbox crashed, but reruns
with desktop-session access passed. `git diff --check` reported an EOF blank line
in windowrules.conf, which had already changed before this repair.

Runtime zone management reference:
https://firewalld.org/documentation/man-pages/firewall-cmd.html

## Panel simplification and operation cancellation

The user confirmed successful hotspot connectivity after the firewall fix.
Hotspot QR codes are now created only when the AP is active and credentials match.
The synchronization button appears only for an active SSID mismatch; the 2.4 GHz
button appears only when the driver rejects the uplink channel. Channels that
already support AP operation do not require a band switch. Synchronization was
recovery for an older session, not a required step for starting the hotspot.

The header offers Cancel and Esc for active operations. Outside clicks do not
close the panel during an operation. Cancellation resolves internal prompts,
stops user subprocesses, and prevents subsequent steps. The privileged start
helper reads a cancellation marker and cleans up AP, DHCP, and hotspot rules
if startup is cancelled. Cleanup itself is not cancelled. Package installations
already running are allowed to finish so pacman transactions remain intact.
Cancellation does not disconnect Wi-Fi that has already connected successfully;
pending activation on the target adapter is stopped. pkexec authentication errors
receive a short message, and workers re-enable controls when they finish.

The Wi-Fi list shows a lock icon for networks that require credentials. OWE is
not marked as requiring a password. Login opens a browser over HTTP when the
active device's connectivity state is portal; the need to log in cannot be
inferred from SSID scans alone. Detection uses NetworkManager state per adapter,
and the button disappears when portal state ends. Full, limited, and unknown
networks are not automatically treated as portals.

All 59 repository tests passed on the desktop. Ten usability tests, including
additional checks for restoring controls after cancellation, also passed.
Checks covered cancelling a real 30-second sleep process in under 3 seconds,
released prompts, inactive/active QR codes, lock icons and Login appearing
together, channel conditions, helper cleanup, and preserving connected Wi-Fi.
A real captive portal and incorrect-password dialog were not tested on a live
network. Four scripts were installed in the active configuration with backups.
Already-open panels use the changes on their next launch; the active AP was
not restarted.

NetworkManager portal state reference:
https://networkmanager.dev/docs/api/latest/nmcli.html

## Wireless debugging: unified page and bounded pairing

The ADB page now follows the hotspot layout: a control card and connected-device
list, with no empty QR column. QR appears only when discovery is ready in an
active pairing session. It disappears on paired, connected, timeout, error, or
cancelled states, and the window returns to its compact size. QR pairing no
longer blocks the panel in a modal Future. Device details use Back/Esc without
Cancel in the header. Stop pairing is on the active-session card. The device
list refreshes automatically and displays actual names and states.

The laptop's ADB reports no mDNS support, so native discovery remains necessary.
Firewalld's public zone previously did not allow mDNS. The new helper allows
only the mdns service on the active Wi-Fi zone, in both runtime and permanent
configuration, without a reload. Public-zone permission was applied successfully
through system authentication during this session. Later use requests
authentication only if the Wi-Fi zone does not allow mDNS. Native discovery also
follows the hotspot interface, and Avahi is used only when its daemon is actually
active so polling does not wait on a stopped daemon.

QR sessions use a unique studio name and distinguish waiting, pairing, connecting,
and terminal states. Scanning is limited to 90 seconds, the pairing client to
15 seconds, connect-port discovery to 20 seconds, and the connect client to
5 seconds. Pairing targets only that session's QR instance; the connect port comes
from the TLS service on the paired device's host. Connected requires transport
state device, not merely successful pairing. Errors close the session and hide
the QR code without including secrets in error messages. Cancellation reaches
the pairing subprocess through Operation on the session thread.

All 65 repository tests passed, including idle/active/completed QR states, device
names, details without Cancel, timeout, errors without secrets, cancellation, and
different pairing/connect ports. Scripts were installed with backups. Actual
phone pairing still awaits another user test. Routers that isolate clients can
still block communication between the laptop and phone.

Pairing/discovery protocol reference:
https://android.googlesource.com/platform/packages/modules/adb/+/HEAD/docs/dev/adb_wifi.md

## English panels and Junk only filter

Connections, hotspot, wireless debugging, and their helper messages now use
English. ArchTidy GUI, terminal UI, and the remaining restore message also use
English. Existing command names, state keys, and saved preferences are unchanged.
An AST string audit found no remaining Indonesian phrases in these modules.

ArchTidy adds Junk only to the category filter. It scans superseded package
archives while retaining two versions, plus standard thumbnail PNG caches older
than 30 days. It excludes installed packages, large personal files, duplicates,
application configuration, arbitrary temporary files, and active ADB sockets.
The scanner respects blacklists and skips symlinks. No candidate is selected or
deleted automatically; the existing review and cleanup workflow still applies.

65 Connections tests and 18 ArchTidy tests passed. A live, read-only scan found
one candidate (50,165,238 bytes), with zero items selected. A GTK smoke check
verified the English controls and Junk only category. No cleanup was performed.
Connections scripts were installed with a backup; the ArchTidy launcher already
references the updated repository package. Reopen both panels to load changes.

## Remove unnecessary wireless authentication prompts

User reported password dialogs while wireless pairing could already proceed.
The installed FirewallD server protects queryService with config.info; the CLI
client also initializes configuration access even for a status request. These
read-only CLI checks can request authentication or wait until the timeout. The
previous preflight treated an unsuccessful query as a missing service, causing
another helper authentication request.

Wireless discovery preflight now uses systemctl for daemon state and direct
busctl calls to the INFO-authorized getZoneOfInterface/getDefaultZone methods.
It reads the saved zone XML for mDNS, preferring /etc over package defaults. Our
setup helper already applies permissions to runtime and permanent state. No
firewall-cmd or pkexec is called when the zone is already configured. Deliberate
runtime-only changes can differ from the saved XML; the preflight assumes the
persisted setup installed by the helper is still in effect.

Authentication remains required for privileged hotspot start/stop and for a
genuinely unconfigured wireless discovery zone. Messages explain that this is
the laptop account password. Cancellation of required discovery setup prevents
pairing from starting. No PolicyKit rule or authorization requirement was
disabled. 68 repository tests pass, including configured discovery without
CLI queries/authentication, cancelled setup, and XML override priority. A live
preflight completed all checks without authentication-capable CLI commands.

## Verify ADB usability before reporting connection success

User reported a successful wireless status followed by scrcpy failing. Live
inspection found adb devices empty and no TLS services in native discovery.
NetworkManager also recorded a recent switch to Galaxy, which can invalidate a
previous transport. scrcpy 4.1 is installed. The previous session message stayed
connected even after the live device list became empty, and the generic launcher
discarded scrcpy stdout/stderr.

Both QR and manual IP connection now require device transport state plus a
successful shell getprop response before reporting connected. The status card
uses fresh device data and explains when the previous device has disconnected.
Opening scrcpy rechecks the selected transport, preserves its log in
~/.local/state/hypr-connections/scrcpy-last.log, and reports startup/runtime errors.
72 tests passed, including unusable transport, manual connection without false
success, stale status removal, and scrcpy startup error reporting. Scripts were
installed with backup. End-to-end phone connection and mirroring remain pending
the current IP:port from the phone's main Wireless debugging screen.

## Installer packaging and consistent terminal presentation

The installer now fullscreens only its own terminal in Hyprland and restores
the previous fullscreen/maximized state on exit. Package checklists use the
available screen and every major phase uses the same width-aware heading.
AUR retries stream progress while retaining output and the real exit status.
Cancelling a checklist selects no packages. Non-Hyprland/TTY operation uses the
existing terminal size without trying to resize another application.

ArchTidy is installed to the user's data directory with a standalone launcher
and desktop entry; no shortcut refers to this laptop's username. Reinstalling
preserves user settings and backs up the installed package. Zsh startup tolerates
missing optional dependencies, keeps PATH entries unique, avoids conflicting
history modes, and loads syntax highlighting last. Existing Zsh and Neovim files
are backed up; failed theme/editor downloads preserve the previous setup.
Snapper configuration is conditional on Btrfs and preserves an existing config.
Network checks no longer rewrite or make resolv.conf immutable. The Lua config
is selected after copying, without reintroducing the legacy main config.

Pacman metadata identified obsolete rofi-wayland, ttf-font-awesome, and
iptables-nft names; the manifest now uses rofi, otf-font-awesome, and iptables.
All recommended package names resolve in the local repository metadata.
77 repository tests and 18 ArchTidy tests passed, as did Bash/Zsh syntax checks
and whitespace validation. Fresh-user packaging and startup were tested in
temporary directories. A complete OS/package installation was not run on this
laptop during validation.
