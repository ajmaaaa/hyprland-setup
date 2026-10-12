#!/usr/bin/env python3
"""Dismiss registered panels on outside clicks, without relying on hover focus."""
import json
import os
from pathlib import Path
import socket
import subprocess
import threading


def directory():
    return Path(os.environ.get('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}')) / 'hypr-panels'


def listen(window, name, GLib):
    root = directory()
    root.mkdir(mode=0o700, exist_ok=True)
    path = root / (name + '.sock')
    path.unlink(missing_ok=True)
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    sock.bind(str(path))
    os.chmod(path, 0o600)
    stopped = threading.Event()
    sock.settimeout(.5)
    def receive():
        while not stopped.is_set():
            try:
                data = sock.recv(32)
                if data == b'close':
                    GLib.idle_add(getattr(window, 'dismiss_on_outside_click', window.close))
            except socket.timeout:
                continue
            except OSError:
                break
    def cleanup(*_):
        stopped.set()
        sock.close()
        path.unlink(missing_ok=True)
        try:
            root.rmdir()
        except OSError:
            pass
    window.connect('destroy', cleanup)
    threading.Thread(target=receive, daemon=True).start()


def dismiss():
    root = directory()
    if not root.exists():
        return
    clients = json.loads(subprocess.check_output(['hyprctl', '-j', 'clients'], timeout=2))
    cursor = json.loads(subprocess.check_output(['hyprctl', '-j', 'cursorpos'], timeout=2))
    names = {'archtidy': 'archtidy', 'local.hyprland.ArchTidy': 'archtidy',
             'hypr-connections': 'connections', 'local.hyprland.Connections': 'connections'}
    for client in clients:
        name = names.get(client['class'])
        if not name:
            continue
        x, y = client['at']; w, h = client['size']
        if x <= cursor['x'] < x + w and y <= cursor['y'] < y + h:
            continue
        # Leave system authentication usable when it covers the panel.
        if any(('polkit' in c['class'].lower() or 'pinentry' in c['class'].lower())
               and c['at'][0] <= cursor['x'] < c['at'][0] + c['size'][0]
               and c['at'][1] <= cursor['y'] < c['at'][1] + c['size'][1] for c in clients):
            continue
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
                sock.sendto(b'close', str(root / (name + '.sock')))
        except OSError:
            pass


if __name__ == '__main__':
    dismiss()
