#!/usr/bin/env python3
"""Fullscreen only the terminal running the installer, then restore its state."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys


def ancestors(pid):
    found = set()
    while pid > 1 and pid not in found:
        found.add(pid)
        try:
            fields = dict(line.split(':', 1) for line in Path(f'/proc/{pid}/status').read_text().splitlines() if ':' in line)
            pid = int(fields['PPid'])
        except (OSError, KeyError, ValueError):
            break
    return found


def dispatch(address, action, mode='fullscreen'):
    if not re.fullmatch(r'0x[0-9a-fA-F]+', address):
        raise ValueError('Invalid window address')
    result = subprocess.run(['hyprctl', 'dispatch',
        f'hl.dsp.window.fullscreen({{window="address:{address}", action="{action}", mode="{mode}"}})'],
        capture_output=True, text=True, timeout=3)
    return result.returncode == 0


def enter():
    clients = json.loads(subprocess.check_output(['hyprctl', '-j', 'clients'], timeout=3))
    parents = ancestors(os.getpid())
    client = next((c for c in clients if c.get('pid') in parents), None)
    if not client or client.get('fullscreen') == 2:
        return {}
    if dispatch(client['address'], 'set'):
        return {'address': client['address'], 'fullscreen': client.get('fullscreen', 0)}
    return {}


def leave(state):
    if state.get('address'):
        if state.get('fullscreen') == 1:
            dispatch(state['address'], 'set', 'maximized')
        else:
            dispatch(state['address'], 'unset')


if __name__ == '__main__':
    try:
        if sys.argv[1] == 'enter':
            print(json.dumps(enter()))
        else:
            leave(json.loads(sys.argv[2]))
    except (OSError, ValueError, subprocess.SubprocessError, IndexError):
        if len(sys.argv) > 1 and sys.argv[1] == 'enter':
            print('{}')
