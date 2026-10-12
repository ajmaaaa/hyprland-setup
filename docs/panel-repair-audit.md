# Audit panel — 12 Oktober 2026

Konfigurasi aktif dibandingkan dengan working tree `~/Git/hyprland-setup`, termasuk
perubahan lokal yang sudah ada. Backup sebelum perbaikan:
`~/.local/state/hyprland-repair/20261012-154313/`.
Lampiran gambar tidak tersedia di sesi audit; pemeriksaan dilakukan dari kode dan
panel yang dijalankan pada desktop.

## Temuan dan perubahan

- Hyprland aktif berbeda pada screenshot binding, autostart workspace preview,
  dan konfigurasi idle. File dari repo dipulihkan; tambahan panel grafis dan
  outside-click disimpan pada repo serta konfigurasi aktif.
- ArchTidy menggunakan curses dan pilihan otomatis dari scanner. GUI GTK 3
  sekarang tidak memilih apa pun otomatis; tombol checkbox, pencarian, rincian
  path, tinjauan pilihan lintas kategori, simulasi, dan penghapusan tersedia.
  Scanner menghormati config TOML dan blacklist pengguna. Scan berlangsung pada
  worker, dimulai dari cache/paket, dan kategori lain dipindai saat dibuka.
- Ukuran file di Trash tidak berarti ruang sudah kosong. GUI menjelaskan ini.
  Paket di GUI dihapus dengan `pacman -R` agar dependensi lain tidak ikut dihapus
  di luar daftar tinjauan. Arsip pacman sistem menggunakan autentikasi dan
  penghapusan permanen hanya terhadap file arsip yang ditinjau.
- Undo sebelumnya menebak nama `file.*`, sehingga tidak cocok dengan nama Trash
  dari GIO. Pemulihan kini memakai `.trashinfo`, path asli, timestamp batch,
  serta menolak menimpa file tujuan. Simulasi tidak menggantikan batch nyata.
  Pemulihan saat ini mendukung Trash pengguna; Trash pada volume lain dapat
  perlu dipulihkan melalui file manager.
- Hotspot sebelumnya mengubah adaptor utama menjadi AP. Sekarang AP memakai
  adaptor bebas atau interface `hypr-hotspot`, dan pada radio yang sama mengikuti
  kanal uplink. Wi-Fi client dan AP tidak lagi dilaporkan sebagai koneksi yang
  sama. Radio tanpa kombinasi AP + managed akan menolak aktivasi sambil
  mempertahankan koneksi utama. Interface virtual dipertahankan untuk pemakaian
  berikutnya, tanpa autoconnect hotspot.
- `iw list` pada laptop ini menyatakan kombinasi managed + AP dengan satu kanal.
  Pembuatan interface virtual memerlukan autentikasi melalui pkexec; kemampuan
  driver/kanal DFS tetap menentukan apakah AP bisa diaktifkan.
- ADB lokal (`android-tools 37.0.0-5`) melaporkan mDNS tidak didukung; Avahi tidak
  aktif. Fallback mDNS langsung membaca nama record DNS, SRV, serta alamat A/AAAA,
  termasuk DNS compression dan record terpisah. QR memiliki session unik
  `studio-*`; pairing hanya memakai service session tersebut. Koneksi selanjutnya
  memakai port `_adb-tls-connect._tcp`, bukan IP tanpa port/port legacy 5555.
  QR memiliki quiet zone empat modul dan ditampilkan tanpa interpolasi blur.
  Tombol fallback pairing kode sekarang berjalan setelah operasi QR berakhir.
- Focus-out bukan sinyal klik pada `follow_mouse=1`. Binding mouse non-consuming
  mengirim permintaan tutup melalui socket hanya ketika cursor berada di luar
  persegi panel. Klik tetap diteruskan ke aplikasi tujuan. Klik pada dialog
  autentikasi tidak menutup panel. Worker operasi yang sudah berjalan tetap
  ditahan oleh GTK Application sampai selesai bila panel ditutup.

## Validasi

- Unit tests repository dan ArchTidy lulus, termasuk pencocokan session QR,
  port koneksi, DNS compression, hotspot pada kanal uplink, proteksi koneksi
  utama, pemulihan Trash, dan penghapusan paket yang hanya ditinjau.
- GUI smoke pada desktop: checkbox, pencarian, tinjauan, pilihan awal kosong,
  klik di dalam tetap terbuka, klik di luar menutup, dan socket dibersihkan.
  Panel Connections juga diuji peluncuran dan outside-click.
- Socket mDNS multicast berhasil dijalankan pada laptop; tidak ada service ADB
  yang ditemukan saat audit. Hyprland reload berhasil tanpa config errors.
- Tidak ada file pengguna atau paket yang dibersihkan pada sesi ini. Pengujian
  GUI memakai kandidat contoh; eksekusi paket hanya diuji dengan mock.
- Aktivasi hotspot sesungguhnya dan pairing ponsel belum diuji ujung ke ujung,
  karena memerlukan autentikasi sistem dan ponsel yang melakukan scan. Router
  harus mengizinkan multicast mDNS serta komunikasi antar perangkat.

Referensi protokol ADB:
https://android.googlesource.com/platform/packages/modules/adb/+/HEAD/docs/dev/adb_wifi.md

## Tindak lanjut error hotspot

Pengujian pengguna menunjukkan interface `hypr-hotspot` unavailable. Log kernel
dan wpa_supplicant mengungkap bahwa NetworkManager menginisialisasi interface
sebagai managed, menyebabkan pelanggaran batas satu managed interface.
Perbaikan selanjutnya memakai hostapd pada interface AP unmanaged, DNS/DHCP
dnsmasq, serta aturan NAT/FORWARD yang hanya diberi tag `hypr-hotspot`. Backend
ini memerlukan autentikasi saat start/stop dan memasang hostapd pada penggunaan
pertama jika belum tersedia. Kegagalan start membersihkan service, alamat IP,
interface, serta aturan firewall milik hotspot. Wi-Fi utama tidak diubah oleh
helper. IP forwarding global dipertahankan agar tidak mengganggu Docker/VPN.

Kanal Wi-Fi utama saat error adalah 64 (5320 MHz), berstatus no IR dan radar
detection pada driver. AP pada kanal ini ditolak sebelum autentikasi. SSID utama
yang sama tersedia di kanal 11, 2.4 GHz. Tombol **Gunakan Wi-Fi 2.4 GHz** memilih
BSSID 2.4 GHz pada SSID yang sama; perpindahan ini menyambungkan ulang Wi-Fi dan
dapat memutus koneksi sesaat. Setelah itu, tombol **Turn On Hotspot** memulai
backend AP. Interface lama yang gagal sudah dibuat unmanaged agar wpa_supplicant
tidak terus mencoba menginisialisasi client kedua.

Aktivasi AP hostapd dan koneksi ponsel masih memerlukan pengujian pengguna; tidak
ada klaim bahwa hotspot berhasil aktif pada kanal 64. Unit test tambahan mencakup
penolakan kanal terbatas sebelum perubahan sistem, lifecycle AP terisolasi, dan
pembersihan saat startup gagal.

## Tindak lanjut QR hotspot tidak tersambung

Output nmcli `FREQ` mencantumkan unit, misalnya `2462 MHz`. Filter frekuensi
sebelumnya memakai isdigit sehingga melewatkan jaringan 2.4 GHz yang ada. Filter
kini menerima angka dengan unit MHz. Wi-Fi yang sudah berada di 2.4 GHz tidak
disambungkan ulang oleh tombol pemindahan band.

Saat AP hostapd pertama aktif, kredensial berasal dari profil NetworkManager
lama, tetapi panel kemudian membaca file preferensi yang berbeda. Ditemukan
SSID AP `Hyprland-Hotspot`, sedangkan preferensi panel bernama `Arch`. Setelah
start berhasil, kredensial persis yang dikirim ke AP sekarang disimpan sebagai
state panel. Profil NM nonaktif tidak lagi menimpa preferensi tersimpan.

Untuk sesi lama yang sudah telanjur berbeda, status memeriksa SSID aktual dari
iw. Password lama tidak ditampilkan dan QR disembunyikan saat mismatch; tombol
sinkronisasi membaca konfigurasi AP aktif melalui helper dengan autentikasi
sistem, lalu menyimpan hasilnya pada file pengguna dengan mode 0600. Penyimpanan
perubahan kredensial AP aktif dilakukan setelah restart berhasil.

Pada pemeriksaan ini service AP dan DHCP telah aktif pada kanal 6. Belum ada
station yang terhubung atau pertukaran DHCP dari ponsel dalam log. Karena itu
koneksi ponsel belum diklaim berhasil, dan ketidakcocokan SSID/kredensial adalah
temuan terkonfirmasi yang diperbaiki sebelum menguji sambungan lagi.

## Tindak lanjut perangkat terus connecting

Log sesi 19:31 menunjukkan autentikasi WPA berhasil, lalu perangkat terputus
sekitar 18 detik kemudian tanpa lease DHCP. AP dan dnsmasq aktif, dengan alamat
gateway 10.42.88.1/24 dan socket DHCP pada interface hotspot. Firewalld aktif;
interface hotspot tidak memiliki zona eksplisit sehingga masuk zona public
yang tidak mengizinkan DHCP/DNS. Aturan ACCEPT iptables helper tidak mengatasi
penolakan dari hook nftables firewalld.

Helper kini menempatkan interface hotspot saja pada zona runtime `nm-shared`,
zona bawaan untuk berbagi jaringan. Zona sebelumnya disimpan sebelum perubahan
dan dipulihkan saat stop atau cleanup startup gagal. Zona yang kemudian diubah
pengguna tidak ditimpa saat cleanup. Firewalld nonaktif tetap memakai jalur
iptables sebelumnya. Aksi `repair-firewall` menerapkan perubahan pada sesi aktif
tanpa restart AP atau koneksi Wi-Fi utama. Tidak ada reload firewall global.

Perbaikan diterapkan pada konfigurasi aktif dan repo; tujuh tes helper dan
seluruh 49 tes repository lulus pada sesi desktop. Zona runtime terverifikasi
`nm-shared` dan uplink tetap connected. Pada pengujian ulang pukul 19:39:17,
dnsmasq mencatat DHCPACK 10.42.88.167 untuk ponsel A13; neighbor interface juga
menampilkan MAC perangkat itu. Koneksi dan pemberian IP terverifikasi. Akses
internet di ponsel belum dikonfirmasi; ada satu log upstream DNS menolak query
rekursif. Tes GTK dalam sandbox sebelumnya crash; pengulangan dengan akses sesi
desktop lulus. `git diff --check` melaporkan blank line EOF pada file
windowrules.conf yang sudah berubah sebelum perbaikan ini.

Referensi pengelolaan zona runtime:
https://firewalld.org/documentation/man-pages/firewall-cmd.html

## Penyederhanaan panel dan pembatalan operasi

Pengguna mengonfirmasi hotspot berhasil tersambung setelah perbaikan firewall.
QR hotspot kini hanya dibuat saat AP aktif dan kredensial sesuai. Tombol
sinkronisasi hanya muncul ketika panel mendeteksi ketidakcocokan SSID aktif;
tombol 2.4 GHz hanya muncul saat kanal uplink ditolak driver. Kanal yang sudah
mendukung AP tidak membutuhkan perpindahan band. Sinkronisasi sebelumnya
merupakan pemulihan sesi lama, bukan langkah wajib menyalakan hotspot.

Header menyediakan Batalkan dan Esc untuk operasi aktif. Klik luar tidak
menutup panel saat operasi sedang berjalan. Pembatalan menyelesaikan prompt
internal, menghentikan subprocess pengguna, dan mencegah langkah berikutnya.
Helper privileged start membaca marker pembatalan, lalu membersihkan AP, DHCP,
dan aturan hotspot jika startup dibatalkan. Cleanup tidak dibatalkan. Instalasi
paket yang sudah berjalan dibiarkan selesai agar transaksi pacman tetap utuh.
Pembatalan tidak memutus koneksi Wi-Fi yang sudah berhasil; aktivasi Wi-Fi yang
masih pending pada adaptor tujuan dihentikan. Error autentikasi pkexec diberi
pesan singkat, dan worker selesai mengaktifkan kembali kontrol.

Daftar Wi-Fi menampilkan ikon kunci untuk jaringan yang memerlukan kredensial.
OWE tidak ditandai membutuhkan password. Tombol Login membuka browser lewat
HTTP saat konektivitas perangkat aktif berstatus portal; kebutuhan login tidak
dapat ditentukan hanya dari hasil scan SSID. Deteksi memakai status per adaptor
NetworkManager, dan tombol hilang ketika status portal berakhir. Jaringan full,
limited, dan unknown tidak otomatis dianggap portal.

Suite repository berisi 59 tes lulus pada desktop; sesudah itu pengujian tambahan
pemulihan kontrol setelah pembatalan juga lulus dalam 10 tes usability. Pengujian
meliputi proses nyata yang tidur 30 detik dibatalkan dalam kurang dari 3 detik,
prompt yang terlepas, QR mati/aktif, ikon kunci dan tombol Login bersamaan,
kondisi kanal, cleanup helper, serta preservasi koneksi Wi-Fi yang sudah aktif.
Portal sesungguhnya dan dialog password salah belum diuji pada jaringan nyata.
Empat script dipasang ke konfigurasi aktif dengan backup. Panel yang sudah
terbuka memakai perubahan pada peluncuran berikutnya; AP aktif tidak direstart.

Referensi status portal NetworkManager:
https://networkmanager.dev/docs/api/latest/nmcli.html

## Wireless debugging: halaman terpadu dan pairing terbatas

Halaman ADB sekarang mengikuti layout hotspot: kartu kontrol dan daftar perangkat
terhubung, tanpa kolom QR kosong. QR baru ditampilkan ketika penemuan perangkat
siap pada sesi pairing aktif. QR hilang saat paired, connected, timeout, error,
atau cancelled; ukuran jendela kembali ringkas. Pairing QR tidak lagi menahan
panel dalam modal Future. Detail perangkat memakai Back/Esc, tanpa Batalkan pada
header. Tombol Hentikan pairing berada di kartu sesi yang sedang berlangsung.
Daftar perangkat diperbarui otomatis dan menampilkan nama serta status aktual.

ADB laptop menyatakan mDNS tidak didukung; penemuan native tetap diperlukan.
Firewalld public sebelumnya tidak mengizinkan mDNS. Helper baru mengizinkan
service mdns saja pada zona Wi-Fi aktif, runtime dan permanent tanpa reload.
Izin public berhasil diterapkan melalui autentikasi sistem pada sesi ini.
Pemakaian berikutnya hanya meminta autentikasi jika zona Wi-Fi belum mengizinkan
mDNS. Native discovery juga mengikuti interface hotspot, dan Avahi hanya dipakai
ketika daemon benar-benar aktif agar polling tidak tertahan oleh daemon mati.

Session QR memakai nama studio unik serta membedakan waiting, pairing, connecting,
dan terminal states. Scan dibatasi 90 detik, pairing client 15 detik, pencarian
port koneksi 20 detik, dan connect client 5 detik. Pairing hanya menuju instance QR
sesi tersebut; port connect berasal dari service TLS pada host perangkat yang
dipasangkan. Connected memerlukan transport state device, bukan sekadar sukses
pairing. Error menutup sesi dan menyembunyikan QR; secret tidak masuk pesan error.
Pembatalan menjangkau subprocess pairing melalui Operation pada thread sesi.

Seluruh 65 tes repository lulus, termasuk QR idle/aktif/selesai, daftar nama
perangkat, detail tanpa Batalkan, timeout, error tanpa secret, pembatalan, serta
port pairing/connect yang berbeda. Script dipasang dengan backup. Pairing HP
sesungguhnya masih menunggu pengujian ulang pengguna. Router yang mengisolasi
client tetap dapat menghalangi komunikasi antar laptop dan HP.

Referensi protokol pairing/penemuan:
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
