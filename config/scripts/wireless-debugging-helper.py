#!/usr/bin/env python3
"""Permit only mDNS discovery in the zones used by Wi-Fi interfaces."""
import os
import subprocess


def run(args):
    return subprocess.run(args, capture_output=True, text=True, timeout=10)


def enable_discovery():
    if run(['firewall-cmd', '--state']).returncode:
        return
    devices = run(['nmcli', '-t', '-f', 'DEVICE,TYPE,STATE', 'device'])
    if devices.returncode:
        raise RuntimeError('The network adapter list could not be read.')
    zones = set()
    for line in devices.stdout.splitlines():
        interface, kind, state = line.split(':', 2)
        if kind != 'wifi' or not (state == 'connected' or interface == 'hypr-hotspot'):
            continue
        zone = run(['firewall-cmd', '--get-zone-of-interface=' + interface])
        if zone.returncode:
            zone = run(['firewall-cmd', '--get-default-zone'])
        if zone.returncode or not zone.stdout.strip():
            raise RuntimeError('The Wi-Fi firewall zone could not be read.')
        zones.add(zone.stdout.strip())
    for zone in zones:
        for persistent in ([], ['--permanent']):
            result = run(['firewall-cmd', *persistent, '--zone=' + zone, '--add-service=mdns'])
            if result.returncode:
                raise RuntimeError(result.stderr.strip() or 'Device discovery permission could not be applied.')
    print('Wireless debugging device discovery is ready.')


if __name__ == '__main__':
    if os.geteuid() != 0:
        raise SystemExit('System authentication is required.')
    try:
        enable_discovery()
    except Exception as error:
        raise SystemExit(str(error))
