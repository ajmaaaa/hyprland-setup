#!/usr/bin/env python3
"""Privileged, isolated AP lifecycle. Never reconfigure or disconnect the uplink."""
import fcntl
import ipaddress
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path('/run/hypr-hotspot')
IFACE = 'hypr-hotspot'
SUBNET = '10.42.88.0/24'
GATEWAY = '10.42.88.1'
UNITS = ('hypr-hotspot-dhcp.service', 'hypr-hotspot-ap.service')
SHARING_ZONE = 'nm-shared'
CANCEL_FILE = None


def run(args, check=True, timeout=40, cancellable=True):
    if CANCEL_FILE is None or not cancellable:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    else:
        if CANCEL_FILE.exists():
            raise RuntimeError('Operation cancelled.')
        process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        deadline = time.monotonic() + timeout
        try:
            while True:
                if CANCEL_FILE.exists():
                    raise RuntimeError('Operation cancelled.')
                if time.monotonic() >= deadline:
                    raise RuntimeError('The operation timed out.')
                try:
                    stdout, stderr = process.communicate(timeout=.2)
                    result = subprocess.CompletedProcess(args, process.returncode, stdout, stderr)
                    break
                except subprocess.TimeoutExpired:
                    pass
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()
    if check and result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or 'Command failed: ' + args[0])
    return result


def rules(uplink):
    return [(['-t', 'nat'], ['POSTROUTING', '-s', SUBNET, '-o', uplink, '-m', 'comment', '--comment', 'hypr-hotspot', '-j', 'MASQUERADE']),
            ([], ['FORWARD', '-i', IFACE, '-o', uplink, '-m', 'comment', '--comment', 'hypr-hotspot', '-j', 'ACCEPT']),
            ([], ['FORWARD', '-i', uplink, '-o', IFACE, '-m', 'conntrack', '--ctstate', 'RELATED,ESTABLISHED', '-m', 'comment', '--comment', 'hypr-hotspot', '-j', 'ACCEPT'])]


def configure_firewall(state):
    if not shutil.which('firewall-cmd') or run(['firewall-cmd', '--state'], check=False).returncode:
        return
    # iptables ACCEPT cannot override a later rejection by firewalld's nft hooks.
    # The shared zone permits DHCP/DNS to the host and forwarding from clients.
    if 'firewalld_previous_zone' not in state:
        previous = run(['firewall-cmd', '--get-zone-of-interface=' + IFACE], check=False)
        state['firewalld_previous_zone'] = previous.stdout.strip() if previous.returncode == 0 else ''
        (ROOT / 'state.json').write_text(json.dumps(state))
    run(['firewall-cmd', '--zone=' + SHARING_ZONE, '--change-interface=' + IFACE])


def restore_firewall(state):
    if 'firewalld_previous_zone' not in state or not shutil.which('firewall-cmd'):
        return
    current = run(['firewall-cmd', '--get-zone-of-interface=' + IFACE], check=False)
    if current.returncode or current.stdout.strip() != SHARING_ZONE:
        return
    previous = state['firewalld_previous_zone']
    if previous:
        run(['firewall-cmd', '--zone=' + previous, '--change-interface=' + IFACE], check=False)
    else:
        run(['firewall-cmd', '--zone=' + SHARING_ZONE, '--remove-interface=' + IFACE], check=False)


def stop():
    global CANCEL_FILE
    previous, CANCEL_FILE = CANCEL_FILE, None
    try:
        _stop()
    finally:
        CANCEL_FILE = previous


def _stop():
    state_path = ROOT / 'state.json'
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    run(['systemctl', 'stop', *UNITS], check=False)
    restore_firewall(state)
    if state.get('uplink'):
        for table, rule in rules(state['uplink']):
            run(['iptables', *table, '-D', *rule], check=False)
    if Path('/sys/class/net').joinpath(IFACE).exists():
        run(['ip', 'address', 'del', GATEWAY + '/24', 'dev', IFACE], check=False)
        run(['ip', 'link', 'set', IFACE, 'down'], check=False)
        run(['iw', 'dev', IFACE, 'del'], check=False)
    # Keep global forwarding intact: Docker/VPN may also need it.
    for name in ('hostapd.conf', 'state.json', 'dnsmasq.leases'):
        (ROOT / name).unlink(missing_ok=True)
    run(['systemctl', 'reset-failed', *UNITS], check=False)


def validate(config):
    uplink = config.get('uplink', '')
    if not uplink or not Path('/sys/class/net', uplink).exists() or uplink == IFACE:
        raise RuntimeError('Invalid Wi-Fi interface.')
    ssid = config.get('ssid', '')
    password = config.get('password', '')
    if not 1 <= len(ssid.encode()) <= 32 or not 8 <= len(password) <= 63 or not password.isascii() or any(ch in password for ch in '\r\n\x00'):
        raise RuntimeError('Invalid hotspot name or password.')
    # Derive channel and country from actual radio state; UI input cannot override these.
    import re
    link = run(['iw', 'dev', uplink, 'info']).stdout
    channel = re.search(r'channel (\d+) \((\d+) MHz\)', link)
    if not channel or 'type managed' not in link:
        raise RuntimeError('Connect to Wi-Fi first.')
    ch, freq = map(int, channel.groups())
    phy = Path('/sys/class/net', uplink, 'phy80211').resolve().name
    radio = run(['iw', 'phy', phy, 'info']).stdout
    entry = next((line for line in radio.splitlines() if f'[{ch}]' in line and 'MHz' in line), '')
    if not entry or any(flag in entry for flag in ('no IR', 'disabled', 'radar detection')):
        raise RuntimeError(f'Wi-Fi channel {ch} does not permit hotspot mode with this driver. Choose 2.4 GHz Wi-Fi in the panel or use a second adapter.')
    if freq >= 5925:
        raise RuntimeError('6 GHz hotspots are not supported yet.')
    for line in json.loads(run(['ip', '-j', 'address']).stdout):
        if line['ifname'] == IFACE:
            continue
        for addr in line.get('addr_info', []):
            if addr.get('family') == 'inet' and ipaddress.ip_interface(f"{addr['local']}/{addr['prefixlen']}").network.overlaps(ipaddress.ip_network(SUBNET)):
                raise RuntimeError('The hotspot subnet overlaps another network.')
    return uplink, ch, ('a' if freq >= 5000 else 'g')


def start(config):
    global CANCEL_FILE
    CANCEL_FILE = Path(config['cancel_file']) if config.get('cancel_file') else None
    uplink, channel, band = validate(config)
    for command in ('iw', 'ip', 'iptables', 'dnsmasq'):
        if not shutil.which(command):
            raise RuntimeError(f'Required tool {command} is not installed.')
    if not shutil.which('hostapd'):
        run(['pacman', '-S', '--needed', '--noconfirm', 'hostapd'], timeout=180, cancellable=False)
    stop()
    ROOT.mkdir(mode=0o700, exist_ok=True)
    # Persist cleanup context before changing any routing or starting daemons.
    (ROOT / 'state.json').write_text(json.dumps({'uplink': uplink, 'ssid': config['ssid']}))
    try:
        run(['iw', 'dev', uplink, 'interface', 'add', IFACE, 'type', '__ap'])
        run(['nmcli', 'device', 'set', IFACE, 'managed', 'no'])
        run(['ip', 'link', 'set', IFACE, 'down'])
        run(['iw', 'dev', IFACE, 'set', 'type', '__ap'])
        text = (f'interface={IFACE}\ndriver=nl80211\nssid2={config["ssid"].encode().hex()}\n'
                f'hw_mode={band}\nchannel={channel}\n'
                'wmm_enabled=1\nauth_algs=1\nwpa=2\nwpa_key_mgmt=WPA-PSK\nrsn_pairwise=CCMP\n'
                f'wpa_passphrase={config["password"]}\n')
        conf = ROOT / 'hostapd.conf'
        conf.write_text(text)
        conf.chmod(0o600)
        run(['systemd-run', '--quiet', '--collect', '--unit=hypr-hotspot-ap',
             '--property=Type=exec', '/usr/bin/hostapd', str(conf)])
        # Wait for AP startup; this wait does not touch the client interface.
        time.sleep(1)
        if run(['systemctl', 'is-active', UNITS[1]], check=False).returncode:
            log = run(['journalctl', '-u', UNITS[1], '-n', '15', '--no-pager'], check=False).stdout
            raise RuntimeError('The driver could not start the hotspot.\n' + log)
        run(['ip', 'address', 'add', GATEWAY + '/24', 'dev', IFACE])
        run(['ip', 'link', 'set', IFACE, 'up'])
        run(['sysctl', '-w', 'net.ipv4.ip_forward=1'])
        for table, rule in rules(uplink):
            run(['iptables', *table, '-I', *rule])
        configure_firewall(json.loads((ROOT / 'state.json').read_text()))
        run(['systemd-run', '--quiet', '--collect', '--unit=hypr-hotspot-dhcp',
             '--property=Type=exec', '/usr/bin/dnsmasq', '--keep-in-foreground',
             '--conf-file=/dev/null', '--bind-interfaces', '--interface=' + IFACE,
             '--listen-address=' + GATEWAY, '--dhcp-range=10.42.88.10,10.42.88.200,12h',
             '--dhcp-option=3,' + GATEWAY, '--dhcp-option=6,' + GATEWAY,
             '--dhcp-leasefile=' + str(ROOT / 'dnsmasq.leases')])
        time.sleep(.5)
        if run(['systemctl', 'is-active', UNITS[0]], check=False).returncode:
            raise RuntimeError('The hotspot DHCP service failed to start.')
        print('Hotspot active; Wi-Fi remains connected.')
    except Exception:
        stop()
        raise


def status():
    if run(['systemctl', 'is-active', UNITS[1]], check=False).returncode:
        raise RuntimeError('The hotspot is not active.')
    settings = dict(line.split('=', 1) for line in (ROOT / 'hostapd.conf').read_text().splitlines() if '=' in line)
    print(json.dumps({'ssid': bytes.fromhex(settings['ssid2']).decode(), 'password': settings['wpa_passphrase']}))


def repair_firewall():
    for unit in UNITS:
        if run(['systemctl', 'is-active', unit], check=False).returncode:
            raise RuntimeError('The hotspot is not active.')
    configure_firewall(json.loads((ROOT / 'state.json').read_text()))
    print('Hotspot firewall repaired without restarting connections.')


def main():
    if os.geteuid() != 0:
        raise RuntimeError('Run this helper with system authentication.')
    os.umask(0o077)
    ROOT.mkdir(mode=0o700, exist_ok=True)
    with (ROOT / 'lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if len(sys.argv) != 2 or sys.argv[1] not in ('start', 'stop', 'status', 'repair-firewall'):
            raise RuntimeError('Invalid action')
        if sys.argv[1] == 'status':
            status()
        elif sys.argv[1] == 'repair-firewall':
            repair_firewall()
        elif sys.argv[1] == 'stop':
            stop()
            print('Hotspot stopped.')
        else:
            start(json.load(sys.stdin))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
