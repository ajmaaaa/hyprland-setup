#!/usr/bin/env python3
"""Keyboard-driven connection popup. Network names are data, never shell code."""
import fcntl
import html
import ipaddress
import os
from pathlib import Path
import re
import shutil
import subprocess
import uuid as uuidlib

ENV = dict(os.environ, LC_ALL='C')
THEME = Path.home() / '.config/rofi/connections.rasi'


def run(args, *, data=None, timeout=40):
    try:
        return subprocess.run(args, input=data, text=True, capture_output=True,
                              timeout=timeout, env=ENV)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(args, 124, '', 'The operation timed out. Please try again.')


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
    choice = menu(name, ['Connect', 'Edit settings', 'Forget network', 'Back'])
    if choice == 0:
        action(['nmcli', '--wait', '25', 'connection', 'up', 'uuid', uuid])
    elif choice == 1:
        launch('nm-connection-editor', '--edit', uuid)
    elif choice == 2 and confirm(f'Forget saved network {name}?'):
        nm('connection', 'delete', 'uuid', uuid)


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
    options = (['Disconnect'] if active == '*' else []) + (['Forget network'] if profiles else []) + ['Network settings', 'Back']
    choice = menu(ssid, options, message)
    if choice is None:
        return
    if options[choice] == 'Disconnect':
        nm('device', 'disconnect', device)
    elif options[choice] == 'Forget network':
        index = 0 if len(profiles) == 1 else menu('Choose a profile', [p[0] for p in profiles])
        if index is not None and confirm(f'Forget network {profiles[index][0]}?'):
            nm('connection', 'delete', 'uuid', profiles[index][1])
    elif options[choice] == 'Network settings':
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
    if not paired:
        # Activate Blueman's authentication agent; only PIN/confirmation needs a dialog.
        from gi.repository import Gio, GLib
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        bus.call_sync('org.freedesktop.DBus', '/org/freedesktop/DBus', 'org.freedesktop.DBus',
            'StartServiceByName', GLib.Variant('(su)', ('org.blueman.Applet', 0)),
            None, Gio.DBusCallFlags.NONE, 10000, None)
        bt('pair', address)
    if 'Connected: yes' not in bt('info', address):
        bt('connect', address)


def bluetooth_details(device):
    address, name, connected, paired, _ = device
    options = (['Disconnect'] if connected else []) + (['Forget device'] if paired else []) + ['Bluetooth settings', 'Back']
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
    if choice is None:
        return
    if options[choice] == 'Disconnect':
        bt('disconnect', address)
    elif options[choice] == 'Forget device':
        if confirm(f'Forget device {name}?'):
            bt('remove', address)
    elif options[choice] == 'Bluetooth settings':
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
                    bt('disconnect' if connected else 'connect', address)
            elif choice == 1:
                info(name, bt('info', address))
            elif choice == 2 and confirm(f'Forget pairing for {name}?'):
                bt('remove', address)


def ethernet():
    wired = [r for r in devices() if r[1] == 'ethernet']
    index = menu('Ethernet', [f'{r[0]} · {r[2]} · {r[3]}' for r in wired] + ['Back'])
    if index is None or index == len(wired):
        return
    device, _, state, _ = wired[index]
    choice = menu(device, ['Connection details', 'Disconnect' if state == 'connected' else 'Connect', 'Back'])
    if choice == 0:
        details(device)
    elif choice == 1:
        nm('device', 'disconnect' if state == 'connected' else 'connect', device)


PROTON_PROFILE_PREFIX = 'Proton · '


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
        # Avoid numerical server-load indicators in the connection panel.
        status = '\n'.join(line for line in status.splitlines() if not line.strip().startswith('Load:'))
        connected = next((name for name, uuid in profiles if uuid in active), None)
        if connected:
            status = f'Status: Connected\nServer: {connected}'
        options = ['Automatic'] + [name for name, _ in profiles] + ['Add server…', 'Disconnect']
        message = status
        if not profiles:
            message += '\n\nAdd a Proton WireGuard configuration to choose a specific server. Automatic uses the Proton app account.'
        choice = menu('Proton VPN', options, message)
        if choice is None:
            return
        if choice == len(profiles) + 1:
            import_proton_server()
            continue
        active = {row[0] for row in rows('UUID', 'connection', 'show', '--active') if row}
        if choice == 0 or choice == len(profiles) + 2:
            for _, uuid in profiles:
                if uuid in active:
                    nm('connection', 'down', 'uuid', uuid)
            command = 'connect' if choice == 0 else 'disconnect'
            result = run(['protonvpn', command], timeout=90)
            if result.returncode:
                raise RuntimeError(result.stderr.strip() or result.stdout.strip() or 'Proton VPN failed.')
            return
        # Stop the official client before activating a manually configured tunnel.
        result = run(['protonvpn', 'disconnect'], timeout=30)
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip() or 'Could not disconnect the Proton client.')
        selected = profiles[choice - 1][1]
        for _, uuid in profiles:
            if uuid in active and uuid != selected:
                nm('connection', 'down', 'uuid', uuid)
        nm('connection', 'up', 'uuid', selected)
        return


def airplane():
    choice = menu('Airplane mode', ['Enable', 'Disable'])
    if choice not in (0, 1):
        return
    nm('radio', 'wifi', 'off' if choice == 0 else 'on')
    if run(['bluetoothctl', 'list']).stdout.strip():
        bt('power', 'off' if choice == 0 else 'on')


def hotspot():
    adapters = [r for r in devices() if r[1] == 'wifi']
    capable = [r for r in adapters if nm('-g', 'WIFI-PROPERTIES.AP', 'device', 'show', r[0]) == 'yes']
    if not capable:
        info('Hotspot', 'No adapter supports hotspot mode.'); return
    index = menu('Hotspot', [f'{r[0]} · {r[3]}' for r in capable] + ['Back'], 'Choose an adapter. Sharing uses the available internet connection. An adapter already connected to Wi-Fi cannot be reused here.')
    if index is None or index == len(capable):
        return
    device = capable[index][0]
    uuid = nm('-g', 'GENERAL.CON-UUID', 'device', 'show', device)
    if uuid and uuid != '--' and nm('-g', '802-11-wireless.mode', 'connection', 'show', 'uuid', uuid) == 'ap':
        choice = menu('Active hotspot', ['Show name and password', 'Turn hotspot off', 'Edit hotspot', 'Back'])
        if choice == 0:
            ssid = nm('-g', '802-11-wireless.ssid', 'connection', 'show', 'uuid', uuid)
            password = nm('--show-secrets', '-g', '802-11-wireless-security.psk', 'connection', 'show', 'uuid', uuid)
            info('Hotspot', f'Name: {ssid}\nPassword: {password}')
        elif choice == 1:
            nm('connection', 'down', 'uuid', uuid)
        elif choice == 2:
            launch('nm-connection-editor', '--edit', uuid)
        return
    if capable[index][2] == 'connected':
        info('Hotspot', 'This Wi-Fi adapter is in use. Sharing Wi-Fi through the same adapter requires a separate virtual AP interface, which this panel does not yet configure. Choose another adapter to keep the current Wi-Fi connection.')
        return
    ssid = entry('Hotspot name', 'Enter a name for the shared network.')
    if not ssid:
        return
    if not 1 <= len(ssid.encode()) <= 32:
        raise RuntimeError('Hotspot name must be 1–32 bytes.')
    password = entry('Hotspot password', 'Use 8–63 characters.', password=True)
    if password is None:
        return
    if not 8 <= len(password) <= 63:
        raise RuntimeError('Hotspot password must contain 8–63 characters.')
    if not confirm(f'Enable hotspot {ssid} on {device}?'):
        return
    profile_uuid = str(uuidlib.uuid4())
    nm('connection', 'add', 'type', 'wifi', 'ifname', device,
       'con-name', 'Hyprland Hotspot', 'connection.uuid', profile_uuid,
       'connection.autoconnect', 'no', 'ssid', ssid)
    try:
        nm('connection', 'modify', 'uuid', profile_uuid, '802-11-wireless.mode', 'ap',
           '802-11-wireless-security.key-mgmt', 'wpa-psk',
           '802-11-wireless-security.psk-flags', '2', 'ipv4.method', 'shared', 'ipv6.method', 'ignore')
        action(['nmcli', '--ask', '--wait', '25', 'connection', 'up', 'uuid', profile_uuid, 'ifname', device], password + '\n')
    except Exception:
        try:
            nm('connection', 'delete', 'uuid', profile_uuid)
        except RuntimeError:
            pass
        raise
    info('Hotspot active', f'Name: {ssid}\nAdapter: {device}')


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


def adb_run(*args, data=None):
    if not shutil.which('adb'):
        raise RuntimeError('ADB is not installed. Install the android-tools package.')
    result = run(['adb', *args], data=data, timeout=30)
    output = (result.stdout + '\n' + result.stderr).strip()
    if result.returncode or any(word in output.lower() for word in ('failed', 'cannot connect', 'unable to connect', 'connection refused')):
        if data:
            output = output.replace(data.strip(), '••••')
        raise RuntimeError(output or 'ADB failed. Check the IP, port, and Wireless debugging on the phone.')
    return output


def adb_devices():
    found = []
    for line in adb_run('devices', '-l').splitlines():
        parts = line.split()
        if len(parts) < 2 or parts[1] not in ('device', 'offline', 'unauthorized'):
            continue
        name = next((part[6:].replace('_', ' ') for part in parts[2:] if part.startswith('model:')), parts[0])
        wireless = ':' in parts[0] or '_adb-tls-connect._tcp' in parts[0]
        found.append((parts[0], name, parts[1], wireless))
    return found


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
    info('Pairing complete', 'If the device does not appear, use Connect IP:port. The connection port on the main Wireless debugging page can differ from the pairing port.')


def adb_connect():
    address = entry('Connect Android', 'Enter the IP:port from the main Wireless debugging page, not the pairing dialog. The phone and laptop must be reachable on the same network.')
    if address is None:
        return
    output = adb_run('connect', adb_endpoint(address))
    if 'connected to' not in output.lower():
        raise RuntimeError(output or 'The device is not connected.')
    notify('Android connected.')


def adb_device_action(device):
    serial, name, state, wireless = device
    options = ['Open screen · scrcpy'] if state == 'device' else []
    if wireless:
        options.append('Disconnect')
    options.append('Back')
    index = menu(name, options, {'device': 'Connected', 'offline': 'Device offline. Check Wireless debugging on the phone.', 'unauthorized': 'Approve debugging access on the phone.'}[state])
    if index is None:
        return
    if options[index] == 'Open screen · scrcpy':
        launch('scrcpy', '-s', serial)
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
