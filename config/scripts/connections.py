#!/usr/bin/env python3
"""Keyboard-driven connection popup. Network names are data, never shell code."""
import fcntl
import html
import ipaddress
import json
import os
from pathlib import Path
import random
import re
import secrets
import shutil
import socket
import string
import struct
import subprocess
import tempfile
import threading
import time
import uuid as uuidlib
import xml.etree.ElementTree as ET

ENV = dict(os.environ, LC_ALL='C')
THEME = Path.home() / '.config/rofi/connections.rasi'
XDG_STATE_HOME = Path(os.environ.get('XDG_STATE_HOME') or (Path.home() / '.local/state'))
STATE_DIR = XDG_STATE_HOME / 'hypr-connections'
ADB_ALIASES_FILE = STATE_DIR / 'adb_aliases.json'
PREVIOUS_WIFI_UUID_FILE = STATE_DIR / 'previous_wifi.txt'
AIRPLANE_STATE_FILE = STATE_DIR / 'airplane_state.json'
HOTSPOT_CONFIG_FILE = STATE_DIR / 'hotspot.json'
OPERATION = threading.local()


class OperationCancelled(RuntimeError):
    def __init__(self):
        super().__init__('Operation cancelled.')


class Operation:
    def __init__(self):
        self.cancelled = threading.Event()
        self.directory = tempfile.TemporaryDirectory(prefix='hypr-connection-')
        self.cancel_file = Path(self.directory.name) / 'cancel'

    def cancel(self):
        self.cancelled.set()
        try:
            self.cancel_file.touch()
        except FileNotFoundError:
            pass

    def close(self):
        self.directory.cleanup()


def check_cancelled():
    operation = getattr(OPERATION, 'current', None)
    if operation and operation.cancelled.is_set():
        raise OperationCancelled()


def cancel_pending_wifi(args):
    if args[0] != 'nmcli' or 'ifname' not in args or not any(word in args for word in ('connect', 'up')):
        return
    device = args[args.index('ifname') + 1]
    result = subprocess.run(['nmcli', '-g', 'GENERAL.STATE', 'device', 'show', device],
                            capture_output=True, text=True, timeout=3, env=ENV)
    if re.match(r'(40|50|60|70|80|90)\s', result.stdout):
        subprocess.run(['nmcli', '--wait', '2', 'device', 'disconnect', device],
                       capture_output=True, text=True, timeout=3, env=ENV)


def write_secure_state(filepath, content):
    STATE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    filepath.write_text(content)
    try:
        os.chmod(filepath, 0o600)
    except Exception:
        pass


def run(args, *, data=None, timeout=40):
    operation = getattr(OPERATION, 'current', None)
    if operation is None:
        try:
            return subprocess.run(args, input=data, text=True, capture_output=True,
                                  timeout=timeout, env=ENV)
        except subprocess.TimeoutExpired:
            return subprocess.CompletedProcess(args, 124, '', 'The operation timed out. Please try again.')
    check_cancelled()
    process = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True, env=ENV)
    deadline = time.monotonic() + timeout if timeout is not None else None
    first = True
    try:
        while True:
            if operation.cancelled.is_set():
                try:
                    process.terminate()
                except PermissionError:
                    # A privileged helper checks the cancellation file and cleans up.
                    pass
            if deadline is not None and time.monotonic() >= deadline:
                try:
                    process.kill()
                except PermissionError:
                    operation.cancel()
                else:
                    process.communicate()
                    return subprocess.CompletedProcess(args, 124, '', 'The operation timed out. Please try again.')
            try:
                stdout, stderr = process.communicate(input=data if first else None, timeout=.2)
                check_cancelled()
                if args[0] == 'pkexec' and process.returncode in (126, 127):
                    raise RuntimeError('Authentication cancelled or failed. Please try again.')
                return subprocess.CompletedProcess(args, process.returncode, stdout, stderr)
            except subprocess.TimeoutExpired:
                first = False
    finally:
        if process.poll() is None:
            try:
                process.kill()
                process.wait()
            except PermissionError:
                pass
        if operation.cancelled.is_set():
            try:
                cancel_pending_wifi(args)
            except (OSError, subprocess.TimeoutExpired):
                pass


def wifi_requires_password(security):
    return bool(security and security.strip() not in ('', '--', 'OWE'))


def hotspot_qr_available(info):
    return bool(info['active'] and info.get('password') and not info.get('credentials_mismatch'))


def wifi_needs_login(device):
    result = run(['nmcli', '-g', 'GENERAL.IP4-CONNECTIVITY,GENERAL.IP6-CONNECTIVITY',
                  'device', 'show', device], timeout=3)
    return result.returncode == 0 and any(re.match(r'2(?:\s|$)|.*\(portal\)', line)
                                        for line in result.stdout.splitlines())


def open_wifi_login():
    # Plain HTTP lets the network redirect the browser to its own login page.
    launch('xdg-open', 'http://neverssl.com/')


def clean(value):
    return re.sub(r'[\x00-\x1f\x7f]', ' ', value)


def fields(line):
    """Decode nmcli's escaped separators, including colons in SSIDs and MACs."""
    result, word, escaped = [], '', False
    for char in line:
        if escaped:
            word += char
            escaped = False
        elif char == '\\':
            escaped = True
        elif char == ':':
            result.append(word)
            word = ''
        else:
            word += char
    result.append(word)
    return result


def nm(*args):
    result = run(['nmcli', '--wait', '25', *args])
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or 'NetworkManager is unavailable.')
    return result.stdout.strip()


def rows(columns, *args):
    return [fields(line) for line in nm('-t', '-f', columns, *args).splitlines() if line]


def menu(title, options, message='Enter: choose · Esc: back'):
    args = ['rofi', '-dmenu', '-i', '-no-custom', '-format', 'i', '-p', title,
            '-mesg', html.escape(message), '-theme', str(THEME)]
    result = run(args, data='\n'.join(clean(option) for option in options), timeout=None)
    if result.returncode or not result.stdout.strip().isdigit():
        return None
    index = int(result.stdout.strip())
    return index if index < len(options) else None


def entry(title, message, password=False):
    args = ['rofi', '-dmenu', '-p', title, '-mesg', html.escape(message),
            '-theme', str(THEME), '-theme-str', 'listview { lines: 0; }']
    if password:
        args.append('-password')
    result = run(args, data='', timeout=None)
    return result.stdout.rstrip('\n') if result.returncode == 0 else None


def info(title, message):
    menu(title, ['Back'], message)


def confirm(message):
    return menu('Confirm', ['Cancel', 'Continue'], message) == 1


show_qr = None


def wifi_qr_text(ssid, password=None, security=None):
    def escape_val(val):
        return re.sub(r'([\\;,":])', r'\\\1', val or '')
    sec = 'nopass'
    if password:
        sec = 'WEP' if security and 'WEP' in security.upper() else 'WPA'
    parts = [f'WIFI:T:{sec}', f'S:{escape_val(ssid)}']
    if password:
        parts.append(f'P:{escape_val(password)}')
    return ';'.join(parts) + ';;'


def qr_to_svg(text, border=4):
    try:
        try:
            from qrcodegen import QrCode
        except ImportError:
            import sys
            script_dir = str(Path(__file__).resolve().parent)
            if script_dir not in sys.path:
                sys.path.insert(0, script_dir)
            from qrcodegen import QrCode
        qr = QrCode.encode_text(text, QrCode.Ecc.MEDIUM)
        size = qr.get_size()
        total = size + border * 2
        parts = [
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {total} {total}" width="{total * 12}" height="{total * 12}" shape-rendering="crispEdges">',
            f'<rect width="{total}" height="{total}" fill="#ffffff" rx="1"/>'
        ]
        for y in range(size):
            for x in range(size):
                if qr.get_module(x, y):
                    parts.append(f'<rect x="{x + border}" y="{y + border}" width="1" height="1" fill="#000000"/>')
        parts.append('</svg>')
        return ''.join(parts)
    except Exception:
        return ''


def get_wifi_password(uuid):
    try:
        psk = nm('--show-secrets', '-g', '802-11-wireless-security.psk', 'connection', 'show', 'uuid', uuid)
        if psk and psk != '--':
            return psk
    except Exception:
        pass
    try:
        wep = nm('--show-secrets', '-g', '802-11-wireless-security.wep-key0', 'connection', 'show', 'uuid', uuid)
        if wep and wep != '--':
            return wep
    except Exception:
        pass
    return ''


def show_qr_screen(ssid, password, security=None):
    svg = qr_to_svg(wifi_qr_text(ssid, password, security))
    if callable(show_qr):
        show_qr(ssid, password, svg, security)
    else:
        msg = f'SSID: {ssid}\nPassword: {password or "(None)"}'
        info('Wi-Fi QR & Password', msg)


def notify(message):
    if shutil.which('notify-send'):
        run(['notify-send', '-a', 'Connections', 'Connections', message])


def action(args, data=None):
    notify('Processing connection…')
    result = run(args, data=data)
    if result.returncode:
        error = result.stderr.strip() or result.stdout.strip() or 'Operation failed.'
        if data:
            error = error.replace(data.strip(), '••••')
        raise RuntimeError(error)
    notify('Done. Connection status updated.')


def launch(program, *args):
    if not shutil.which(program):
        raise RuntimeError(f'{program} is not installed. Run the installer to add connection support.')
    subprocess.Popen([program, *args], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def devices():
    return rows('DEVICE,TYPE,STATE,CONNECTION', 'device', 'status')


def network_details(device):
    names = {'GENERAL.DEVICE': 'Adapter', 'GENERAL.HWADDR': 'MAC address',
             'IP4.ADDRESS': 'IPv4 address', 'IP4.GATEWAY': 'Gateway',
             'IP4.DNS': 'DNS', 'IP6.ADDRESS': 'IPv6 address'}
    result = []
    for line in nm('-t', '-f', ','.join(names), 'device', 'show', device).splitlines():
        parts = fields(line)
        key = re.sub(r'\[\d+\]$', '', parts[0])
        value = ':'.join(parts[1:])
        if key in names and value and value != '--':
            result.append(f'{names[key]}: {value}')
    return '\n'.join(result)


def details(device):
    info('Connection details', network_details(device))


def saved_wifi():
    profiles = [r for r in rows('NAME,UUID,TYPE', 'connection', 'show') if r[2] == '802-11-wireless']
    index = menu('Saved Wi-Fi networks', [r[0] for r in profiles] + ['Back'])
    if index is None or index == len(profiles):
        return
    name, uuid, _ = profiles[index]
    options = ['Connect', 'Show password & QR Code', 'Edit settings', 'Forget network', 'Back']
    choice = menu(name, options)
    if choice is None or options[choice] == 'Back':
        return
    selected = options[choice]
    if selected == 'Connect':
        action(['nmcli', '--wait', '25', 'connection', 'up', 'uuid', uuid])
    elif selected == 'Show password & QR Code':
        pwd = get_wifi_password(uuid)
        show_qr_screen(name, pwd, 'WPA')
    elif selected == 'Edit settings':
        launch('nm-connection-editor', '--edit', uuid)
    elif selected == 'Forget network' and confirm(f'Forget saved network {name}?'):
        nm('connection', 'delete', 'uuid', uuid)
        notify(f'Network {name} removed.')


def wifi():
    while True:
        adapters = [r for r in devices() if r[1] == 'wifi']
        if not adapters:
            info('Wi-Fi', 'No Wi-Fi adapter found.'); return
        enabled = nm('radio', 'wifi') == 'enabled'
        networks = rows('IN-USE,SSID,SIGNAL,SECURITY,BSSID,DEVICE', 'device', 'wifi', 'list', '--rescan', 'no') if enabled else []
        networks = [r for r in networks if len(r) == 6 and r[1]]
        networks.sort(key=lambda r: (r[0] != '*', -int(r[2] or 0)))
        # Keep one access point per network/security/adapter, preferring the active AP.
        unique = {}
        for row in networks:
            unique.setdefault((row[1], row[3], row[5]), row)
        networks = list(unique.values())
        options = ['Turn Wi-Fi off' if enabled else 'Turn Wi-Fi on', 'Rescan',
                   'Saved networks', 'Hidden network / advanced settings']
        options += [f'{"●" if r[0] == "*" else "○"}  {r[1]}  ·  {r[2]}%  ·  {r[3] or "Open"}  ·  {r[5]}' for r in networks]
        index = menu('Wi-Fi', options, 'Choose a network to connect. Esc: back')
        if index is None:
            return
        if index == 0:
            nm('radio', 'wifi', 'off' if enabled else 'on')
        elif index == 1:
            notify('Scanning Wi-Fi networks…')
            nm('device', 'wifi', 'rescan')
        elif index == 2:
            saved_wifi()
        elif index == 3:
            launch('nm-connection-editor')
        else:
            connect_wifi(networks[index - 4])


def wifi_profiles(ssid):
    found = []
    for row in rows('NAME,UUID,TYPE', 'connection', 'show'):
        if len(row) < 3:
            continue
        name, uuid, kind = row[:3]
        if kind == '802-11-wireless' and nm('-g', '802-11-wireless.ssid', 'connection', 'show', 'uuid', uuid) == ssid:
            if nm('-g', '802-11-wireless.mode', 'connection', 'show', 'uuid', uuid) != 'ap':
                found.append((name, uuid))
    return found


def connect_wifi(network):
    active, ssid, signal, security, bssid, device = network
    if active == '*':
        notify(f'{ssid} is already connected. Use the arrow for details.')
    elif '802.1X' in security or 'EAP' in security:
        info('Enterprise Wi-Fi', 'Configure network identity and certificates in the settings dialog.')
        launch('nm-connection-editor')
    else:
        command = ['nmcli', '--wait', '25', 'device', 'wifi', 'connect', bssid, 'ifname', device]
        if not security or security == '--':
            action(command)
            return
        profiles = wifi_profiles(ssid)
        if profiles:
            result = run(['nmcli', '--wait', '25', 'connection', 'up', 'uuid', profiles[0][1], 'ifname', device, 'ap', bssid])
            if result.returncode == 0:
                return
        password = entry('Wi-Fi password', ssid, password=True)
        if password is not None:
            if not password:
                raise RuntimeError('Password cannot be empty.')
            action(['nmcli', '--ask', *command[1:]], password + '\n')


def wifi_details(network):
    active, ssid, _, security, bssid, device = network
    profiles = wifi_profiles(ssid)
    message = f'Network: {ssid}\nSecurity: {security or "Open"}\nBSSID: {bssid}'
    if active == '*':
        message += '\n' + network_details(device)
    else:
        message += f'\nAdapter: {device}'
    options = []
    if active == '*':
        options.append('Disconnect')
    if profiles:
        options.append('Show password & QR Code')
        options.append('Forget network')
    options.extend(['Network settings', 'Back'])
    choice = menu(ssid, options, message)
    if choice is None or options[choice] == 'Back':
        return
    selected = options[choice]
    if selected == 'Disconnect':
        if profiles:
            run(['nmcli', 'connection', 'down', 'uuid', profiles[0][1]])
        nm('device', 'disconnect', device)
        notify(f'Disconnected from {ssid}.')
    elif selected in ('Show password & QR Code', 'Show QR Code'):
        pwd = get_wifi_password(profiles[0][1]) if profiles else ''
        show_qr_screen(ssid, pwd, security)
    elif selected == 'Forget network':
        index = 0 if len(profiles) == 1 else menu('Choose a profile', [p[0] for p in profiles])
        if index is not None and confirm(f'Forget network {profiles[index][0]}?'):
            nm('connection', 'delete', 'uuid', profiles[index][1])
            notify(f'Network {profiles[index][0]} removed.')
    elif selected == 'Network settings':
        launch('nm-connection-editor', *(['--edit', profiles[0][1]] if profiles else []))

def bt(*args):
    command = ['bluetoothctl']
    if args[0] in ('connect', 'disconnect', 'pair'):
        command += ['--timeout', '45' if args[0] == 'pair' else '15']
    result = run([*command, *args], timeout=50 if args[0] == 'pair' else 20)
    output = re.sub(r'\x1b\[[0-9;]*m', '', result.stdout).strip()
    if result.returncode or 'Failed' in output or 'No default controller' in output:
        raise RuntimeError(output or result.stderr.strip() or 'Bluetooth is unavailable.')
    return output


def connect_bluetooth(device):
    address, name, connected, paired, _ = device
    if connected:
        notify(f'{name} is already connected. Use the arrow for details.')
        return
    try:
        if 'Powered: yes' not in bt('show'):
            bt('power', 'on')
        bt('pairable', 'on')
    except Exception:
        pass
    if not paired:
        # Activate Blueman's authentication agent; only PIN/confirmation needs a dialog.
        from gi.repository import Gio, GLib
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        bus.call_sync('org.freedesktop.DBus', '/org/freedesktop/DBus', 'org.freedesktop.DBus',
            'StartServiceByName', GLib.Variant('(su)', ('org.blueman.Applet', 0)),
            None, Gio.DBusCallFlags.NONE, 10000, None)
        bt('pair', address)
    try:
        bt('trust', address)
    except Exception:
        pass
    if 'Connected: yes' not in bt('info', address):
        bt('connect', address)


def bluetooth_details(device):
    address, name, connected, paired, _ = device
    if paired:
        try:
            bt('trust', address)
        except Exception:
            pass
    options = (['Disconnect'] if connected else ['Connect'] if paired else []) + (['Forget device'] if paired else []) + ['Bluetooth settings', 'Back']
    values = dict(line.strip().split(': ', 1) for line in bt('info', address).splitlines() if ': ' in line)
    message = f'Device: {name}\nAddress: {address}\nConnection: {"Connected" if connected else "Disconnected"}\nPaired: {"Yes" if paired else "No"}'
    for key in ('Icon', 'Trusted', 'Blocked', 'Battery Percentage'):
        if key in values:
            value = values[key]
            if key == 'Battery Percentage':
                match = re.search(r'\((\d+)\)', value)
                value = match[1] + '%' if match else value
            message += f'\n{"Battery" if key == "Battery Percentage" else key}: {value.capitalize()}'
    choice = menu(name, options, message)
    if choice is None or options[choice] == 'Back':
        return
    selected = options[choice]
    if selected == 'Disconnect':
        bt('disconnect', address)
        notify(f'Disconnected from {name}.')
    elif selected == 'Connect':
        try:
            bt('trust', address)
        except Exception:
            pass
        bt('connect', address)
        notify(f'Connected to {name}.')
    elif selected == 'Forget device':
        if confirm(f'Forget device {name}?'):
            bt('remove', address)
            notify(f'Device {name} removed.')
    elif selected == 'Bluetooth settings':
        launch('blueman-manager')


def bluetooth():
    while True:
        controller = bt('show')
        powered = 'Powered: yes' in controller
        found = []
        for line in bt('devices').splitlines():
            match = re.match(r'Device ([0-9A-Fa-f:]{17}) (.*)', line)
            if match:
                address, name = match.groups()
                state = bt('info', address)
                connected = 'Connected: yes' in state
                paired = 'Paired: yes' in state
                if paired and 'Trusted: yes' not in state:
                    try:
                        bt('trust', address)
                    except Exception:
                        pass
                battery = re.search(r'Battery Percentage:.*\((\d+)\)', state)
                label = 'Connected' if connected else 'Paired' if paired else 'Not paired'
                if battery:
                    label += f' · {battery[1]}%'
                found.append((address, name, connected, paired, label))
        found.sort(key=lambda r: (not r[2], not r[3], r[1].lower()))
        options = ['Turn Bluetooth off' if powered else 'Turn Bluetooth on', 'Scan / pair a new device', 'Bluetooth settings']
        options += [f'{"●" if r[2] else "○"}  {r[1]}  ·  {r[4]}' for r in found]
        index = menu('Bluetooth', options, 'PIN pairing may open a confirmation dialog. Esc: back')
        if index is None:
            return
        if index == 0:
            bt('power', 'off' if powered else 'on')
        elif index == 1:
            if not powered:
                bt('power', 'on')
            launch('blueman-manager')
        elif index == 2:
            launch('blueman-manager')
        else:
            address, name, connected, paired, _ = found[index - 3]
            choice = menu(name, ['Disconnect' if connected else 'Connect' if paired else 'Pair', 'Device details', 'Forget device', 'Back'])
            if choice == 0:
                if not paired:
                    launch('blueman-manager')
                else:
                    notify('Processing Bluetooth connection…')
                    try:
                        bt('trust', address)
                    except Exception:
                        pass
                    bt('disconnect' if connected else 'connect', address)
            elif choice == 1:
                info(name, bt('info', address))
            elif choice == 2 and confirm(f'Forget pairing for {name}?'):
                bt('remove', address)
                notify(f'Device {name} removed.')


def get_ethernet_status():
    adapters = devices()
    wired = [r for r in adapters if r[1] == 'ethernet']
    if not wired:
        return ('unavailable', 'No Ethernet adapter found')
    connected = next((r for r in wired if r[2] == 'connected'), None)
    if connected:
        conn = connected[3] if connected[3] != '--' else 'Connected'
        return ('connected', f'Connected ({conn})')
    if any(r[2] == 'unavailable' for r in wired):
        return ('unavailable', 'Adapter unavailable / not plugged in')
    return ('disconnected', 'Cable unplugged')


def ethernet():
    wired = [r for r in devices() if r[1] == 'ethernet']
    if not wired:
        info('Ethernet', 'No Ethernet adapter found.')
        return
    if len(wired) == 1:
        device, _, state, conn = wired[0]
        is_conn = (state == 'connected')
        options = ['Disconnect' if is_conn else 'Connect', 'Connection details', 'Back']
        status = f'Status: {state}' + (f' · {conn}' if conn and conn != '--' else '')
        choice = menu(f'Ethernet ({device})', options, status)
        if choice is None or choice == 2:
            return
        if choice == 0:
            if is_conn:
                for r in rows('UUID,DEVICE', 'connection', 'show', '--active'):
                    if r[1] == device:
                        run(['nmcli', 'connection', 'down', 'uuid', r[0]])
                nm('device', 'disconnect', device)
                notify(f'Disconnected Ethernet ({device}).')
            else:
                action(['nmcli', 'device', 'connect', device])
                notify(f'Connected Ethernet ({device}).')
        elif choice == 1:
            details(device)
        return

    index = menu('Ethernet', [f'{r[0]} · {r[2]} · {r[3]}' for r in wired] + ['Back'])
    if index is None or index == len(wired):
        return
    device, _, state, _ = wired[index]
    is_conn = (state == 'connected')
    choice = menu(device, ['Disconnect' if is_conn else 'Connect', 'Connection details', 'Back'])
    if choice is None or choice == 2:
        return
    if choice == 0:
        if is_conn:
            for r in rows('UUID,DEVICE', 'connection', 'show', '--active'):
                if r[1] == device:
                    run(['nmcli', 'connection', 'down', 'uuid', r[0]])
            nm('device', 'disconnect', device)
            notify(f'Disconnected Ethernet ({device}).')
        else:
            action(['nmcli', 'device', 'connect', device])
            notify(f'Connected Ethernet ({device}).')
    elif choice == 1:
        details(device)


PROTON_PROFILE_PREFIX = 'Proton · '
FREE_VPN_SERVERS = [
    ('Singapore (Free · SG)', 'SG'),
    ('Netherlands (Free · NL)', 'NL'),
    ('Japan (Free · JP)', 'JP'),
    ('United States (Free · US)', 'US'),
]


def proton_profiles():
    return [(name[len(PROTON_PROFILE_PREFIX):], uuid) for name, uuid, kind in
            rows('NAME,UUID,TYPE', 'connection', 'show')
            if kind == 'wireguard' and name.startswith(PROTON_PROFILE_PREFIX)]


def import_proton_server():
    filename = entry('Add Proton server',
        'Download a WireGuard configuration for your chosen server from account.protonvpn.com → Downloads. Enter the .conf file path below.')
    if not filename:
        return
    path = Path(filename).expanduser()
    if path.suffix != '.conf' or not path.is_file():
        raise RuntimeError('Choose an existing WireGuard .conf file downloaded from Proton.')
    name = entry('Server name', f'Configuration: {path.stem}\nEnter a country and server name, for example Japan · JP-FREE#1.')
    if not name or not name.strip():
        return
    result = nm('connection', 'import', 'type', 'wireguard', 'file', str(path))
    match = re.search(r'\(([0-9a-fA-F-]{36})\)', result)
    if not match:
        raise RuntimeError('The profile was imported but its ID could not be read. Check NetworkManager settings.')
    nm('connection', 'modify', 'uuid', match[1], 'connection.id',
       PROTON_PROFILE_PREFIX + clean(name.strip()), 'connection.autoconnect', 'no')


def vpn():
    if not shutil.which('protonvpn'):
        raise RuntimeError('The Proton VPN CLI is not installed. Install proton-vpn-cli.')
    while True:
        profiles = proton_profiles()
        active = {row[0] for row in rows('UUID', 'connection', 'show', '--active') if row}
        result = run(['protonvpn', 'status'], timeout=15)
        status = result.stdout.strip() or result.stderr.strip()
        status = '\n'.join(line for line in status.splitlines() if not line.strip().startswith('Load:'))
        connected = next((name for name, uuid in profiles if uuid in active), None)
        if connected:
            status = f'Status: Connected\nServer: {connected}'
        options = ['Automatic (Fastest)', 'Select server', 'Disconnect']
        message = status or 'Proton VPN'
        choice = menu('Proton VPN', options, message)
        if choice is None:
            return
        if choice == 0:
            for _, uuid in profiles:
                if uuid in active:
                    nm('connection', 'down', 'uuid', uuid)
            action(['protonvpn', 'connect'])
            return
        elif choice == 1:
            server_options = [label for label, _ in FREE_VPN_SERVERS]
            if profiles:
                server_options += [f'Custom: {name}' for name, _ in profiles]
            server_options.append('Back')
            sub_choice = menu('Select VPN server', server_options, 'Choose a server:')
            if sub_choice is None or sub_choice == len(server_options) - 1:
                continue
            if sub_choice < len(FREE_VPN_SERVERS):
                srv_label, cc = FREE_VPN_SERVERS[sub_choice]
                for _, uuid in profiles:
                    if uuid in active:
                        nm('connection', 'down', 'uuid', uuid)
                action(['protonvpn', 'connect', '--country', cc])
                return
            else:
                custom_idx = sub_choice - len(FREE_VPN_SERVERS)
                selected_uuid = profiles[custom_idx][1]
                run(['protonvpn', 'disconnect'], timeout=30)
                for _, uuid in profiles:
                    if uuid in active and uuid != selected_uuid:
                        nm('connection', 'down', 'uuid', uuid)
                nm('connection', 'up', 'uuid', selected_uuid)
                return
        elif choice == 2:
            for _, uuid in profiles:
                if uuid in active:
                    nm('connection', 'down', 'uuid', uuid)
            action(['protonvpn', 'disconnect'])
            return


def airplane():
    choice = menu('Airplane mode', ['Enable', 'Disable', 'Back'])
    if choice not in (0, 1):
        return
    enable = (choice == 0)
    if enable:
        wifi_on = ('enabled' in nm('radio', 'wifi'))
        bt_on = ('Powered: yes' in bt('show'))
        state = {'wifi': wifi_on, 'bt': bt_on}
        try:
            write_secure_state(AIRPLANE_STATE_FILE, json.dumps(state))
        except Exception:
            pass
        nm('radio', 'all', 'off')
        if shutil.which('rfkill'):
            run(['rfkill', 'block', 'all'])
        notify('Airplane mode enabled.')
    else:
        prev = {'wifi': True, 'bt': False}
        if AIRPLANE_STATE_FILE.exists():
            try:
                prev = json.loads(AIRPLANE_STATE_FILE.read_text())
            except Exception:
                pass
            AIRPLANE_STATE_FILE.unlink(missing_ok=True)
        if shutil.which('rfkill'):
            run(['rfkill', 'unblock', 'all'])
        if prev.get('wifi', True):
            nm('radio', 'wifi', 'on')
        else:
            nm('radio', 'wifi', 'off')
        if prev.get('bt', False):
            try:
                bt('power', 'on')
            except Exception:
                pass
        else:
            try:
                bt('power', 'off')
            except Exception:
                pass
        notify('Airplane mode disabled.')


def generate_secure_password(length=12):
    chars = string.ascii_letters + string.digits
    return ''.join(secrets.choice(chars) for _ in range(length))


def wifi_client_devices():
    clients = []
    for row in devices():
        if row[1] != 'wifi' or row[0] == 'hypr-hotspot':
            continue
        if row[2] == 'connected':
            uuid = nm('-g', 'GENERAL.CON-UUID', 'device', 'show', row[0])
            if uuid and uuid != '--' and nm('-g', '802-11-wireless.mode', 'connection', 'show', 'uuid', uuid) == 'ap':
                continue
        clients.append(row)
    return clients


def native_hotspot_active():
    return run(['systemctl', 'is-active', 'hypr-hotspot-ap.service'], timeout=3).returncode == 0


def get_hotspot_status():
    if native_hotspot_active():
        cfg = json.loads(HOTSPOT_CONFIG_FILE.read_text())
        actual = re.search(r'^\s*ssid (.*)$', run(['iw', 'dev', 'hypr-hotspot', 'info']).stdout, re.MULTILINE)
        mismatch = bool(actual and actual[1] != cfg['ssid'])
        if mismatch:
            cfg = {'ssid': actual[1], 'password': ''}
        return {'supported': True, 'device': 'hypr-hotspot', 'active': True,
                'ssid': cfg['ssid'], 'password': cfg['password'], 'uuid': None,
                'backend': 'hostapd', 'credentials_mismatch': mismatch}
    adapters = [r for r in devices() if r[1] == 'wifi' and r[0] != 'hypr-hotspot']
    capable = [r for r in adapters if nm('-g', 'WIFI-PROPERTIES.AP', 'device', 'show', r[0]) == 'yes']
    if not capable:
        return {'supported': False, 'device': None, 'active': False, 'ssid': 'Hyprland-Hotspot', 'password': generate_secure_password(12), 'uuid': None}
    # Prefer an existing AP, then an unused adapter; never choose the uplink first.
    active_aps = set()
    if len(capable) > 1:
        for row in capable:
            if row[2] == 'connected':
                current = nm('-g', 'GENERAL.CON-UUID', 'device', 'show', row[0])
                if current and current != '--' and nm('-g', '802-11-wireless.mode', 'connection', 'show', 'uuid', current) == 'ap':
                    active_aps.add(row[0])
    capable.sort(key=lambda r: (r[0] not in active_aps, r[0] != 'hypr-hotspot', r[2] == 'connected'))
    device = capable[0][0]
    uuid = nm('-g', 'GENERAL.CON-UUID', 'device', 'show', device)
    is_active = bool(uuid and uuid != '--' and nm('-g', '802-11-wireless.mode', 'connection', 'show', 'uuid', uuid) == 'ap')

    saved_uuid = uuid if is_active else None
    saved_ssid = 'Arch'
    saved_pwd = None
    if HOTSPOT_CONFIG_FILE.exists():
        try:
            cfg = json.loads(HOTSPOT_CONFIG_FILE.read_text())
            saved_ssid = cfg.get('ssid') or 'Arch'
            saved_pwd = cfg.get('password')
        except Exception:
            pass

    if is_active:
        s = nm('-g', '802-11-wireless.ssid', 'connection', 'show', 'uuid', uuid)
        if s and s != '--':
            saved_ssid = s
        p = get_wifi_password(uuid)
        if p:
            saved_pwd = p
    else:
        for r in rows('NAME,UUID,TYPE', 'connection', 'show'):
            if len(r) >= 3 and r[2] == '802-11-wireless' and r[0] in ('Arch', 'Hotspot', 'Hyprland Hotspot') and nm('-g', '802-11-wireless.mode', 'connection', 'show', 'uuid', r[1]) == 'ap':
                saved_uuid = r[1]
                s = nm('-g', '802-11-wireless.ssid', 'connection', 'show', 'uuid', r[1])
                if not HOTSPOT_CONFIG_FILE.exists():
                    if s and s != '--':
                        saved_ssid = s
                    p = get_wifi_password(r[1])
                    if p:
                        saved_pwd = p
                break

    if not saved_pwd:
        saved_pwd = generate_secure_password(12)
        try:
            write_secure_state(HOTSPOT_CONFIG_FILE, json.dumps({'ssid': saved_ssid, 'password': saved_pwd}))
        except Exception:
            pass

    return {
        'supported': True,
        'device': device,
        'active': is_active,
        'ssid': saved_ssid,
        'password': saved_pwd,
        'uuid': saved_uuid
    }


def save_hotspot_config(new_ssid, new_pwd):
    new_ssid = new_ssid.strip()
    if not (1 <= len(new_ssid.encode()) <= 32):
        raise RuntimeError('Hotspot name must be 1–32 bytes.')
    if not (8 <= len(new_pwd) <= 63):
        raise RuntimeError('Hotspot password must be 8–63 characters.')
    info = get_hotspot_status()
    if not info['supported']:
        raise RuntimeError('No adapter supports hotspot mode.')
    if info.get('backend') == 'hostapd':
        start_native_hotspot({**info, 'ssid': new_ssid, 'password': new_pwd})
        return True
    write_secure_state(HOTSPOT_CONFIG_FILE, json.dumps({'ssid': new_ssid, 'password': new_pwd}))
    device = info['device']
    uuid = info['uuid']
    if not uuid:
        uuid = str(uuidlib.uuid4())
        nm('connection', 'add', 'type', 'wifi', 'ifname', device,
           'con-name', 'Hyprland Hotspot', 'connection.uuid', uuid,
           'connection.autoconnect', 'no', 'ssid', new_ssid)
        nm('connection', 'modify', 'uuid', uuid,
           '802-11-wireless.mode', 'ap',
           '802-11-wireless.band', 'bg',
           '802-11-wireless-security.key-mgmt', 'wpa-psk',
           '802-11-wireless-security.psk', new_pwd,
           'ipv4.method', 'shared', 'ipv6.method', 'ignore')
    else:
        nm('connection', 'modify', 'uuid', uuid,
           '802-11-wireless.ssid', new_ssid,
           '802-11-wireless-security.psk', new_pwd)
        if info['active']:
            action(['nmcli', 'connection', 'up', 'uuid', uuid])
    return True


def native_hotspot_uplink(info):
    """A spare physical radio can use NM. A same-radio AP must use hostapd."""
    uplink = next((r[0] for r in wifi_client_devices() if r[2] == 'connected'), None)
    if not uplink:
        return None
    phy = (Path('/sys/class/net') / uplink / 'phy80211').resolve()
    device_phy = (Path('/sys/class/net') / info['device'] / 'phy80211').resolve()
    return uplink if phy == device_phy or info['device'] == 'hypr-hotspot' else None


class HotspotBandError(RuntimeError):
    pass


def hotspot_needs_band_switch(info):
    if info['active'] or not info['supported']:
        return False
    uplink = native_hotspot_uplink(info)
    if not uplink:
        return False
    try:
        hotspot_channel(uplink)
    except HotspotBandError:
        return True
    except OperationCancelled:
        raise
    except RuntimeError:
        return False
    return False


def hotspot_channel(uplink):
    phy = (Path('/sys/class/net') / uplink / 'phy80211').resolve().name
    radio = run(['iw', 'phy', phy, 'info']).stdout
    combos = radio.partition('valid interface combinations:')[2].partition('HT Capability')[0]
    if not any('managed' in block and re.search(r'(?<![\w-])AP(?=[, }])', block)
               and re.search(r'total <= ([2-9]|[1-9][0-9]+)', block) for block in combos.split('*')):
        raise RuntimeError('This adapter cannot use Wi-Fi and hotspot at the same time. Use a second adapter; the Wi-Fi connection will remain active.')
    link = run(['iw', 'dev', uplink, 'info']).stdout
    match = re.search(r'channel (\d+) \((\d+) MHz\)', link)
    if not match:
        raise RuntimeError('The Wi-Fi channel could not be detected.')
    ch, freq = map(int, match.groups())
    entry = next((line for line in radio.splitlines() if f'[{ch}]' in line and 'MHz' in line), '')
    if not entry or any(flag in entry for flag in ('no IR', 'disabled', 'radar detection')) or freq >= 5925:
        raise HotspotBandError(f'The Wi-Fi connection uses channel {ch} which does not support hotspot mode with this driver. Click "Use 2.4 GHz Wi-Fi", then start the hotspot again. Wi-Fi remains connected.')
    return ch


def start_native_hotspot(info):
    uplink = native_hotspot_uplink(info)
    if not uplink:
        raise RuntimeError('Connect to Wi-Fi first.')
    hotspot_channel(uplink)
    config = {'uplink': uplink, 'ssid': info['ssid'], 'password': info['password']}
    operation = getattr(OPERATION, 'current', None)
    if operation:
        config['cancel_file'] = str(operation.cancel_file)
    payload = json.dumps(config)
    helper = Path(__file__).with_name('hotspot-helper.py')
    # First use installs hostapd through the same system authentication.
    notify('Starting hotspot. If authentication is requested, use your laptop account password.')
    result = run(['pkexec', '/usr/bin/python3', str(helper), 'start'], data=payload, timeout=240)
    if result.returncode:
        raise RuntimeError(result.stderr.strip().replace(info['password'], '••••') or 'Hotspot startup failed or authentication was cancelled.')
    write_secure_state(HOTSPOT_CONFIG_FILE, json.dumps({'ssid': info['ssid'], 'password': info['password']}))
    notify(result.stdout.strip())


def sync_native_hotspot_credentials():
    helper = Path(__file__).with_name('hotspot-helper.py')
    result = run(['pkexec', '/usr/bin/python3', str(helper), 'status'], timeout=120)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or 'Authentication cancelled.')
    cfg = json.loads(result.stdout)
    write_secure_state(HOTSPOT_CONFIG_FILE, json.dumps({'ssid': cfg['ssid'], 'password': cfg['password']}))
    notify('The panel now uses the active hotspot name and password.')


def use_24ghz_uplink():
    client = next((r for r in wifi_client_devices() if r[2] == 'connected'), None)
    if not client:
        raise RuntimeError('Connect to Wi-Fi first.')
    device = client[0]
    current = run(['iw', 'dev', device, 'info']).stdout
    if re.search(r'channel \d+ \(24\d{2} MHz\)', current):
        notify('Wi-Fi already uses 2.4 GHz; no reconnection is needed.')
        return
    uuid = nm('-g', 'GENERAL.CON-UUID', 'device', 'show', device)
    ssid = nm('-g', '802-11-wireless.ssid', 'connection', 'show', 'uuid', uuid)
    networks = rows('SSID,FREQ,SIGNAL,BSSID', 'device', 'wifi', 'list', 'ifname', device, '--rescan', 'yes')
    candidates = [r for r in networks if len(r) == 4 and r[0] == ssid and re.fullmatch(r'24\d{2}(?: MHz)?', r[1]) is not None]
    if not candidates:
        raise RuntimeError('This network is not available on 2.4 GHz. Choose a 2.4 GHz network on the Wi-Fi page or use a second adapter.')
    chosen = max(candidates, key=lambda r: int(r[2] or 0))
    action(['nmcli', '--wait', '25', 'device', 'wifi', 'connect', chosen[3], 'ifname', device])
    notify('Wi-Fi switched to the same network on 2.4 GHz. You can now start the hotspot.')


def turn_on_hotspot():
    info = get_hotspot_status()
    if not info['supported']:
        raise RuntimeError('No adapter supports hotspot mode.')
    if info['active']:
        return
    if native_hotspot_uplink(info):
        start_native_hotspot(info)
        return
    device, channel = info['device'], None
    if not info['uuid']:
        save_hotspot_config(info['ssid'], info['password'])
        info = get_hotspot_status()
    uuid = info['uuid']
    nm('connection', 'modify', 'uuid', uuid, 'connection.interface-name', device,
       'connection.autoconnect', 'no', 'ipv4.never-default', 'yes',
       'ipv6.method', 'ignore')
    if channel:
        nm('connection', 'modify', 'uuid', uuid,
           '802-11-wireless.band', channel[0], '802-11-wireless.channel', channel[1])
    else:
        nm('connection', 'modify', 'uuid', uuid,
           '802-11-wireless.band', 'bg', '802-11-wireless.channel', '0')
    action(['nmcli', '--wait', '25', 'connection', 'up', 'uuid', uuid, 'ifname', device])
    notify(f'Hotspot "{info["ssid"]}" is active; the Wi-Fi connection remains separate.')


def turn_off_hotspot():
    info = get_hotspot_status()
    if info.get('backend') == 'hostapd':
        notify('Stopping hotspot. If authentication is requested, use your laptop account password.')
        action(['pkexec', '/usr/bin/python3', str(Path(__file__).with_name('hotspot-helper.py')), 'stop'])
        return
    if info['active'] and info['uuid']:
        nm('connection', 'down', 'uuid', info['uuid'])
    # Compatibility with old sessions that displaced the uplink.
    if PREVIOUS_WIFI_UUID_FILE.exists():
        prev = PREVIOUS_WIFI_UUID_FILE.read_text().strip()
        if prev:
            nm('connection', 'up', 'uuid', prev)
        PREVIOUS_WIFI_UUID_FILE.unlink(missing_ok=True)
    notify('Hotspot turned off.')


def hotspot():
    hs = get_hotspot_status()
    if not hs['supported']:
        info('Hotspot', 'No adapter supports hotspot mode.')
        return
    if hs['active']:
        options = ['Turn off hotspot', 'Show password & QR Code', 'Edit name & password', 'Back']
        choice = menu('Hotspot', options, f'Hotspot "{hs["ssid"]}" is currently ACTIVE on {hs["device"]}.')
        if choice is None or choice == 3:
            return
        if choice == 0:
            turn_off_hotspot()
        elif choice == 1:
            show_qr_screen(hs['ssid'], hs['password'], 'WPA')
        elif choice == 2:
            new_ssid = entry('Hotspot name', f'Current: {hs["ssid"]}\nEnter new name:')
            if not new_ssid or not new_ssid.strip():
                return
            new_pwd = entry('Hotspot password', 'Enter new password (8–63 characters):', password=True)
            if not new_pwd:
                return
            save_hotspot_config(new_ssid, new_pwd)
            notify(f'Hotspot "{new_ssid.strip()}" updated.')
            show_qr_screen(new_ssid.strip(), new_pwd, 'WPA')
    else:
        options = ['Turn on hotspot', 'Edit name & password', 'Back']
        choice = menu('Hotspot', options, f'Hotspot is currently off · Configured network: "{hs["ssid"]}"')
        if choice is None or choice == 2:
            return
        if choice == 0:
            turn_on_hotspot()
            hs = get_hotspot_status()
            show_qr_screen(hs['ssid'], hs['password'], 'WPA')
        elif choice == 1:
            new_ssid = entry('Hotspot name', f'Current: {hs["ssid"]}\nEnter new name:')
            if not new_ssid or not new_ssid.strip():
                return
            new_pwd = entry('Hotspot password', 'Enter new password (8–63 characters):', password=True)
            if not new_pwd:
                return
            save_hotspot_config(new_ssid, new_pwd)
            notify(f'Hotspot configured: "{new_ssid.strip()}".')


def adb_endpoint(value):
    value = value.strip()
    match = re.fullmatch(r'(\[[^\]]+\]|[^:]+):(\d{1,5})', value)
    if not match:
        raise RuntimeError('Use IP:port, for example 192.168.1.10:37123.')
    host, port = match.groups()
    try:
        ipaddress.ip_address(host.strip('[]'))
    except ValueError:
        raise RuntimeError('Invalid IP address.') from None
    if not 1 <= int(port) <= 65535:
        raise RuntimeError('Port must be between 1 and 65535.')
    return value


def adb_run(*args, data=None, timeout=30):
    if not shutil.which('adb'):
        raise RuntimeError('ADB is not installed. Install the android-tools package.')
    result = run(['adb', *args], data=data, timeout=timeout)
    output = (result.stdout + '\n' + result.stderr).strip()
    if result.returncode or any(word in output.lower() for word in ('failed', 'cannot connect', 'unable to connect', 'connection refused')):
        if data:
            output = output.replace(data.strip(), '••••')
        raise RuntimeError(output or 'ADB failed. Check the IP, port, and Wireless debugging on the phone.')
    return output


def get_adb_aliases():
    if ADB_ALIASES_FILE.exists():
        try:
            return json.loads(ADB_ALIASES_FILE.read_text())
        except Exception:
            pass
    return {}


def set_adb_alias(serial, alias):
    aliases = get_adb_aliases()
    if alias and alias.strip():
        aliases[serial] = alias.strip()
    elif serial in aliases:
        del aliases[serial]
    try:
        write_secure_state(ADB_ALIASES_FILE, json.dumps(aliases))
    except Exception:
        pass


def adb_rename_device(device):
    serial, name, _, _ = device
    aliases = get_adb_aliases()
    current = aliases.get(serial, '')
    new_alias = entry(f'Rename {name}', f'Serial: {serial}\nEnter custom name (leave blank to clear):')
    if new_alias is None:
        return
    set_adb_alias(serial, new_alias)
    notify(f'Device renamed to "{new_alias.strip()}".' if new_alias.strip() else 'Device alias cleared.')


def adb_devices():
    found = []
    aliases = get_adb_aliases()
    for line in adb_run('devices', '-l').splitlines():
        parts = line.split()
        if len(parts) < 2 or parts[1] not in ('device', 'offline', 'unauthorized'):
            continue
        serial = parts[0]
        raw_model = next((part[6:].replace('_', ' ') for part in parts[2:] if part.startswith('model:')), serial)
        name = aliases.get(serial) or raw_model
        wireless = ':' in serial or '_adb-tls-connect._tcp' in serial
        found.append((serial, name, parts[1], wireless))
    return found


def verify_adb_ready(serial):
    if adb_run('-s', serial, 'get-state', timeout=3).strip() != 'device':
        raise RuntimeError('The device is not connected. Check Wireless debugging on your phone and reconnect.')
    model = adb_run('-s', serial, 'shell', 'getprop', 'ro.product.model', timeout=5).strip()
    if not model:
        raise RuntimeError('ADB is connected, but the device is not responding. Reconnect before opening scrcpy.')
    return model


def start_scrcpy(serial):
    verify_adb_ready(serial)
    if not shutil.which('scrcpy'):
        raise RuntimeError('scrcpy is not installed.')
    STATE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    log_path = STATE_DIR / 'scrcpy-last.log'
    with log_path.open('w') as log:
        log_path.chmod(0o600)
        process = subprocess.Popen(['scrcpy', '-s', serial], stdout=log, stderr=subprocess.STDOUT, env=ENV)
    try:
        code = process.wait(timeout=1.5)
    except subprocess.TimeoutExpired:
        notify('scrcpy started.')
        def watch():
            if process.wait():
                notify('scrcpy stopped with an error:\n' + log_path.read_text()[-1500:])
        threading.Thread(target=watch, daemon=True).start()
        return
    if code:
        raise RuntimeError('scrcpy could not start:\n' + log_path.read_text()[-2000:])


def dns_name(data, offset, seen=None):
    """Decode a bounded DNS name, including compression pointers."""
    seen = set() if seen is None else seen
    labels = []
    while True:
        if offset >= len(data) or offset in seen:
            raise ValueError('Invalid DNS name')
        seen.add(offset)
        length = data[offset]
        offset += 1
        if length == 0:
            return '.'.join(labels), offset
        if length & 0xc0 == 0xc0:
            if offset >= len(data):
                raise ValueError('Truncated pointer')
            pointer = ((length & 0x3f) << 8) | data[offset]
            suffix, _ = dns_name(data, pointer, seen)
            labels.append(suffix)
            return '.'.join(labels), offset + 1
        if length > 63 or offset + length > len(data):
            raise ValueError('Invalid DNS label')
        labels.append(data[offset:offset + length].decode('utf-8'))
        offset += length


def parse_mdns_records(data):
    """Keep record owners and SRV target addresses; never guess from packet source."""
    if len(data) < 12:
        return []
    _, flags, questions, answers, authority, additional = struct.unpack('!6H', data[:12])
    if not flags & 0x8000:
        return []
    records, pos = [], 12
    try:
        for _ in range(questions):
            _, pos = dns_name(data, pos)
            pos += 4
        for _ in range(answers + authority + additional):
            name, pos = dns_name(data, pos)
            kind, cls, ttl, length = struct.unpack_from('!HHIH', data, pos)
            pos += 10
            end = pos + length
            if end > len(data):
                raise ValueError('Truncated record')
            if cls & 0x7fff == 1:
                if kind == 33 and length >= 7:
                    port = struct.unpack_from('!H', data, pos + 4)[0]
                    target, _ = dns_name(data, pos + 6)
                    records.append((name, 'srv', (target, port), ttl))
                elif kind == 12:
                    target, _ = dns_name(data, pos)
                    records.append((name, 'ptr', target, ttl))
                elif kind == 1 and length == 4:
                    records.append((name, 'addr', socket.inet_ntop(socket.AF_INET, data[pos:end]), ttl))
                elif kind == 28 and length == 16:
                    records.append((name, 'addr', socket.inet_ntop(socket.AF_INET6, data[pos:end]), ttl))
            pos = end
    except (ValueError, UnicodeError, struct.error):
        return []
    return records


def native_adb_mdns(cache, stop_event=None):
    """mDNS discovery for Arch builds whose ADB was compiled without mDNS."""
    kinds = ('_adb-tls-pairing._tcp', '_adb-tls-connect._tcp')
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(('', 5353))
        sock.settimeout(.2)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 255)
        ips = []
        for row in devices():
            if row[1] in ('wifi', 'ethernet') and (row[2] == 'connected' or row[0] == 'hypr-hotspot'):
                ips.extend(addr.split('/')[0] for addr in nm('-g', 'IP4.ADDRESS', 'device', 'show', row[0]).splitlines() if addr)
        for ip in ips or ['0.0.0.0']:
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP,
                            socket.inet_aton('224.0.0.251') + socket.inet_aton(ip))
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(ip))
            for kind in kinds:
                qname = b''.join(bytes([len(part)]) + part.encode() for part in (kind + '.local').split('.')) + b'\0'
                query = struct.pack('!6H', 0, 0, 1, 0, 0, 0) + qname + struct.pack('!HH', 12, 1)
                sock.sendto(query, ('224.0.0.251', 5353))
        requested = set()
        deadline = time.monotonic() + 1.5
        while time.monotonic() < deadline and not (stop_event and stop_event.is_set()):
            try:
                packet, _ = sock.recvfrom(65535)
            except socket.timeout:
                continue
            for name, kind, value, ttl in parse_mdns_records(packet):
                key = (name, kind)
                if ttl:
                    cache[key] = (value, time.monotonic() + ttl)
                else:
                    cache.pop(key, None)
            # Some responders omit additional SRV/address records from PTR answers.
            for (name, kind), (value, _) in list(cache.items()):
                questions = []
                if kind == 'ptr' and (value, 'srv') not in cache:
                    questions.append((value, 33))
                elif kind == 'srv' and (value[0], 'addr') not in cache:
                    questions.append((value[0], 1))
                for target, qtype in questions:
                    if (target, qtype) in requested:
                        continue
                    requested.add((target, qtype))
                    qname = b''.join(bytes([len(part.encode())]) + part.encode() for part in target.split('.')) + b'\0'
                    query = struct.pack('!6H', 0, 0, 1, 0, 0, 0) + qname + struct.pack('!HH', qtype, 1)
                    for ip in ips or ['0.0.0.0']:
                        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(ip))
                        sock.sendto(query, ('224.0.0.251', 5353))
        now = time.monotonic()
        for key in list(cache):
            if cache[key][1] <= now:
                cache.pop(key)
        services = []
        for (name, record_kind), ((target, port), _) in [(k, v) for k, v in cache.items() if k[1] == 'srv']:
            for kind in kinds:
                suffix = '.' + kind + '.local'
                if name.endswith(suffix) and (target, 'addr') in cache:
                    ip = cache[(target, 'addr')][0]
                    host = f'[{ip}]' if ':' in ip else ip
                    services.append((name[:-len(suffix)], kind, adb_endpoint(f'{host}:{port}')))
        return services
    finally:
        sock.close()


def get_wireless_name():
    aliases = get_adb_aliases()
    custom = aliases.get('__wireless_name__')
    if custom:
        return custom
    session_suffix = getattr(get_wireless_name, '_suffix', None)
    if not session_suffix:
        session_suffix = secrets.token_hex(2)
        get_wireless_name._suffix = session_suffix
    return f'Arch-ADB-{session_suffix}'


def set_wireless_name(name):
    set_adb_alias('__wireless_name__', name.strip() if name else '')


def adb_mdns_services():
    """Use ADB's DNS parser, with resolved Avahi records as a fallback."""
    services = []
    result = run(['adb', 'mdns', 'services'], timeout=5)
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[1] in ('_adb-tls-pairing._tcp', '_adb-tls-connect._tcp'):
            try:
                services.append((parts[0], parts[1], adb_endpoint(parts[2])))
            except RuntimeError:
                pass
    if not services and shutil.which('avahi-browse') and run(['systemctl', 'is-active', 'avahi-daemon.service'], timeout=2).returncode == 0:
        for kind in ('_adb-tls-pairing._tcp', '_adb-tls-connect._tcp'):
            res = run(['avahi-browse', '-r', '-p', '-t', kind], timeout=4)
            for line in res.stdout.splitlines():
                parts = line.split(';')
                if len(parts) >= 9 and parts[0] == '=':
                    # Avahi escapes arbitrary instance bytes as decimal \DDD.
                    name = re.sub(r'\\(\d{3})', lambda m: chr(int(m[1])), parts[3])
                    host = f'[{parts[7]}]' if ':' in parts[7] else parts[7]
                    try:
                        services.append((name, kind, adb_endpoint(f'{host}:{parts[8]}')))
                    except RuntimeError:
                        pass
    return services


def saved_zone_allows_mdns(zone):
    if not re.fullmatch(r'[A-Za-z0-9_-]+', zone):
        raise RuntimeError('Invalid Wi-Fi firewall zone.')
    # FirewallD queryService requires config.info authorization on this system,
    # so even a read-only CLI query can open a password dialog. Read the saved
    # zone instead; our setup helper applies it to runtime and permanent state.
    for directory in ('/etc/firewalld/zones', '/usr/lib/firewalld/zones'):
        path = Path(directory) / (zone + '.xml')
        try:
            root = ET.parse(path).getroot()
        except FileNotFoundError:
            continue
        except (OSError, ET.ParseError) as error:
            raise RuntimeError('The saved Wi-Fi firewall settings could not be read.') from error
        return any(service.get('name') == 'mdns' for service in root.findall('service'))
    return False


def ensure_adb_discovery():
    if run(['systemctl', 'is-active', 'firewalld.service'], timeout=3).returncode:
        return
    for device, kind, state, *_ in devices():
        if kind != 'wifi' or not (state == 'connected' or device == 'hypr-hotspot'):
            continue
        base = ['busctl', '--json=short', '--timeout=3', 'call', 'org.fedoraproject.FirewallD1', '/org/fedoraproject/FirewallD1']
        zone_result = run([*base, 'org.fedoraproject.FirewallD1.zone', 'getZoneOfInterface', 's', device], timeout=4)
        if zone_result.returncode:
            raise RuntimeError('The Wi-Fi firewall zone could not be read.')
        zone = json.loads(zone_result.stdout)['data'][0]
        if not zone:
            zone_result = run([*base, 'org.fedoraproject.FirewallD1', 'getDefaultZone'], timeout=4)
            if zone_result.returncode:
                raise RuntimeError('The Wi-Fi firewall zone could not be read.')
            zone = json.loads(zone_result.stdout)['data'][0]
        if not saved_zone_allows_mdns(zone):
            notify('System authentication is needed once to enable wireless device discovery. Use your laptop account password.')
            helper = Path(__file__).with_name('wireless-debugging-helper.py')
            result = run(['pkexec', '/usr/bin/python3', str(helper)], timeout=60)
            if result.returncode:
                raise RuntimeError('Device discovery is not permitted yet. Authentication was cancelled or failed.')
            break


class AdbQrSession:
    """One cancellable QR attempt, with separate pairing and connection states."""
    ACTIVE = ('preparing', 'waiting', 'pairing', 'connecting')

    def __init__(self, on_change=None, scan_timeout=90, connect_timeout=20):
        self.on_change = on_change
        self.scan_timeout = scan_timeout
        self.connect_timeout = connect_timeout
        self.service_name = 'studio-' + secrets.token_hex(5)
        self.code = str(secrets.randbelow(9000000000) + 1000000000)
        self.svg = qr_to_svg(f'WIFI:T:ADB;S:{self.service_name};P:{self.code};;')
        self.operation = Operation()
        self.state = 'idle'
        self.message = ''
        self.lock = threading.Lock()
        self.thread = None

    def snapshot(self):
        with self.lock:
            return {'state': self.state, 'message': self.message,
                    'active': self.state in self.ACTIVE,
                    'svg': self.svg if self.state in ('waiting', 'pairing') else None}

    def update(self, state, message):
        with self.lock:
            self.state, self.message = state, message
        if self.on_change:
            self.on_change()

    def start(self):
        if not self.svg:
            self.operation.close()
            raise RuntimeError('The pairing QR code could not be generated.')
        self.update('preparing', 'Preparing device discovery…')
        self.thread = threading.Thread(target=self.work, daemon=True)
        self.thread.start()

    def stop(self):
        if self.snapshot()['active']:
            self.operation.cancel()
            self.update('cancelled', 'Pairing stopped. You can create a new QR code.')

    def work(self):
        OPERATION.current = self.operation
        paired_host = None
        cache = {}
        deadline = time.monotonic() + self.scan_timeout
        try:
            ensure_adb_discovery()
            adb_run('start-server')
            self.update('waiting', 'Scan the QR code in Developer options → Wireless debugging → Pair device with QR code.')
            while time.monotonic() < deadline:
                check_cancelled()
                services = adb_mdns_services()
                if not services:
                    services = native_adb_mdns(cache, self.operation.cancelled)
                if paired_host is None:
                    for name, kind, endpoint in services:
                        if name != self.service_name or kind != '_adb-tls-pairing._tcp':
                            continue
                        self.update('pairing', 'Device found. Pairing…')
                        output = adb_run('pair', endpoint, data=self.code + '\n', timeout=15)
                        if 'successfully paired' not in output.lower():
                            raise RuntimeError('Pairing failed. Create a new QR code and scan again.')
                        paired_host = endpoint.rsplit(':', 1)[0]
                        deadline = time.monotonic() + self.connect_timeout
                        self.update('connecting', 'Pairing successful. Connecting the device…')
                        break
                if paired_host:
                    for _, kind, endpoint in services:
                        if kind != '_adb-tls-connect._tcp' or endpoint.rsplit(':', 1)[0] != paired_host:
                            continue
                        model = connect_adb_endpoint(endpoint)
                        self.update('connected', f'{model} connected and responding to ADB. The device appears below.')
                        return
                if self.operation.cancelled.wait(.5):
                    raise OperationCancelled()
            if paired_host:
                self.update('paired', 'Pairing succeeded, but the connection is not confirmed. Use Connect IP:port with the address on the phone\'s main Wireless debugging page.')
            else:
                self.update('timeout', 'Scanning timed out. Check that the phone and laptop share a network, then create a new QR code or pair with a code.')
        except OperationCancelled:
            self.update('cancelled', 'Pairing stopped. You can create a new QR code.')
        except Exception as error:
            self.update('error', str(error).replace(self.code, '••••'))
        finally:
            OPERATION.current = None
            self.operation.close()


def adb_pair_qr():
    session = AdbQrSession(on_change=lambda: notify(session.snapshot()['message']))
    session.start()
    try:
        if callable(show_qr):
            show_qr(session.service_name, session.code, session.svg, security='ADB')
        else:
            info('Wireless Debugging QR', 'Use the QR scanner in Wireless debugging on your phone.')
    finally:
        session.stop()


def adb_pair():
    address = entry('Pair Android', 'On the phone: Developer options → Wireless debugging → Pair device with pairing code. Enter the IP:port shown there.')
    if address is None:
        return
    address = adb_endpoint(address)
    code = entry('Pairing code', 'Enter the 6-digit code shown on the phone.', password=True)
    if code is None:
        return
    if not re.fullmatch(r'\d{6}', code):
        raise RuntimeError('The pairing code must contain 6 digits.')
    output = adb_run('pair', address, data=code + '\n')
    if 'successfully paired' not in output.lower():
        raise RuntimeError('Pairing failed. Check the code and pairing port on the phone.')
    connected = connect_after_adb_pairing(address)
    if connected:
        model, endpoint = connected
        notify(f'{model} connected and responding to ADB ({endpoint}). You can now open scrcpy.')
    else:
        info('Pairing saved, not connected', 'Your phone is paired, but there is no confirmed ADB connection yet. Use Connect IP:port with the address on the main Wireless debugging page before opening scrcpy.')


def connect_adb_endpoint(address):
    """Connect a validated endpoint and confirm that its shell responds."""
    address = adb_endpoint(address)
    output = adb_run('connect', address, timeout=5)
    if 'connected to' not in output.lower():
        raise RuntimeError(output or 'The device is not connected.')
    return verify_adb_ready(address)


def connect_after_adb_pairing(pairing_address):
    """Pairing authorizes the laptop; a separate transport is needed for scrcpy."""
    paired_host, paired_port = pairing_address.rsplit(':', 1)
    paired_ip = ipaddress.ip_address(paired_host.strip('[]'))
    services = []
    discovery_error = ''
    try:
        services = adb_mdns_services()
        if not services:
            operation = getattr(OPERATION, 'current', None)
            services = native_adb_mdns({}, operation.cancelled if operation else None)
    except OperationCancelled:
        raise
    except (OSError, RuntimeError) as error:
        discovery_error = str(error)
    for _, kind, endpoint in services:
        if kind != '_adb-tls-connect._tcp':
            continue
        host, port = adb_endpoint(endpoint).rsplit(':', 1)
        if ipaddress.ip_address(host.strip('[]')) != paired_ip or int(port) == int(paired_port):
            continue
        check_cancelled()
        try:
            return connect_adb_endpoint(endpoint), endpoint
        except OperationCancelled:
            raise
        except RuntimeError as error:
            discovery_error = str(error)
    check_cancelled()
    message = ('Pairing succeeded. Enter IP:port from the main Wireless debugging page on your phone. '
               'Use the connection port, not the port from the pairing-code dialog.')
    if discovery_error:
        message += '\nAutomatic connection was not ready: ' + discovery_error[-400:]
    address = entry('Connect paired Android', message)
    if address is None:
        return None
    address = adb_endpoint(address)
    host, port = address.rsplit(':', 1)
    if ipaddress.ip_address(host.strip('[]')) == paired_ip and int(port) == int(paired_port):
        raise RuntimeError('That is the pairing port. Use IP:port from the main Wireless debugging page to connect before opening scrcpy.')
    return connect_adb_endpoint(address), address


def adb_connect():
    address = entry('Connect Android', 'Enter the IP:port from the main Wireless debugging page, not the pairing dialog. The phone and laptop must be reachable on the same network.')
    if address is None:
        return
    address = adb_endpoint(address)
    model = connect_adb_endpoint(address)
    notify(f'{model} connected and responding to ADB.')


def adb_device_action(device):
    serial, name, state, wireless = device
    options = ['Open screen · scrcpy'] if state == 'device' else []
    options.append('Rename device')
    if wireless:
        options.append('Disconnect')
    options.append('Back')
    index = menu(name, options, {'device': 'Connected', 'offline': 'Device offline. Check Wireless debugging on the phone.', 'unauthorized': 'Approve debugging access on the phone.'}[state])
    if index is None:
        return
    if options[index] == 'Open screen · scrcpy':
        start_scrcpy(serial)
    elif options[index] == 'Rename device':
        adb_rename_device(device)
    elif options[index] == 'Disconnect':
        adb_run('disconnect', serial)


def main():
    for program in ('rofi', 'nmcli', 'bluetoothctl'):
        if not shutil.which(program):
            raise RuntimeError(f'{program} is not installed.')
    handlers = [wifi, bluetooth, ethernet, vpn, airplane, hotspot, lambda: launch('nm-connection-editor')]
    while True:
        try:
            status = ' · '.join(f'{clean(r[0])}: {clean(r[3])}' for r in devices() if r[2] == 'connected' and r[1] != 'loopback')
        except RuntimeError:
            status = 'NetworkManager unavailable · Bluetooth can still be opened'
        try:
            choice = menu('Connections', ['Wi-Fi', 'Bluetooth', 'Ethernet / LAN', 'VPN', 'Airplane mode', 'Hotspot', 'Advanced settings'], status or 'No active network · Esc: close')
            if choice is None:
                return
            handlers[choice]()
        except RuntimeError as error:
            info('Connections', str(error))


if __name__ == '__main__':
    runtime = Path(os.environ.get('XDG_RUNTIME_DIR', '/tmp'))
    with (runtime / f'connections-popup-{os.getuid()}.lock').open('w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit(0)
        try:
            main()
        except RuntimeError as error:
            notify(str(error))
