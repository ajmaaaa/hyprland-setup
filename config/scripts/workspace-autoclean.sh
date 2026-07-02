#!/usr/bin/env python3
import socket
import subprocess
import json
import time
import os
import sys
import threading

# Prevent concurrent modifications of workspaces
lock = threading.Lock()

def get_hyprland_state():
    try:
        clients_proc = subprocess.run(["hyprctl", "clients", "-j"], capture_output=True, text=True)
        clients = json.loads(clients_proc.stdout)
    except Exception:
        clients = []

    try:
        workspaces_proc = subprocess.run(["hyprctl", "workspaces", "-j"], capture_output=True, text=True)
        workspaces = json.loads(workspaces_proc.stdout)
    except Exception:
        workspaces = []

    try:
        rules_proc = subprocess.run(["hyprctl", "workspacerules", "-j"], capture_output=True, text=True)
        rules = json.loads(rules_proc.stdout)
    except Exception:
        rules = []

    try:
        active_proc = subprocess.run(["hyprctl", "activeworkspace", "-j"], capture_output=True, text=True)
        active_ws = json.loads(active_proc.stdout)
    except Exception:
        active_ws = {}

    return clients, workspaces, rules, active_ws

def dispatch_move(workspace, address):
    # Try Lua-style first (v0.55+)
    cmd = ["hyprctl", "eval", f"hl.dispatch(hl.dsp.window.move({{ workspace = {workspace}, window = 'address:{address}' }}))"]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if "error:" in res.stdout or res.returncode != 0:
        # Fallback to legacy syntax
        subprocess.run(["hyprctl", "dispatch", "movetoworkspacesilent", f"{workspace},address:{address}"], capture_output=True)

def dispatch_focus(workspace):
    # Try Lua-style first (v0.55+)
    cmd = ["hyprctl", "eval", f"hl.dispatch(hl.dsp.focus({{ workspace = {workspace} }}))"]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if "error:" in res.stdout or res.returncode != 0:
        # Fallback to legacy syntax
        subprocess.run(["hyprctl", "dispatch", "workspace", str(workspace)], capture_output=True)

def reorder_workspaces():
    if not lock.acquire(blocking=False):
        return
    try:
        # Give Hyprland state a moment to settle after event
        time.sleep(0.05)
        
        clients, workspaces, rules, active_ws = get_hyprland_state()
        if not clients:
            return

        # Map workspace ID to monitor name
        ws_to_monitor = {}
        for rule in rules:
            ws_str = rule.get("workspaceString", "")
            monitor = rule.get("monitor", "")
            if ws_str.isdigit() and monitor:
                ws_to_monitor[int(ws_str)] = monitor

        for ws in workspaces:
            ws_id = ws.get("id")
            monitor = ws.get("monitor")
            if ws_id is not None and ws_id > 0 and monitor:
                ws_to_monitor[ws_id] = monitor

        # Group clients by workspace ID (excluding special workspaces)
        ws_clients = {}
        for client in clients:
            ws_id = client.get("workspace", {}).get("id")
            if ws_id is not None and ws_id > 0:
                if ws_id not in ws_clients:
                    ws_clients[ws_id] = []
                ws_clients[ws_id].append(client)

        # Group occupied workspaces by monitor
        monitor_occupied = {}
        for ws_id in sorted(ws_clients.keys()):
            monitor = ws_to_monitor.get(ws_id)
            if not monitor:
                continue
            if monitor not in monitor_occupied:
                monitor_occupied[monitor] = []
            monitor_occupied[monitor].append(ws_id)

        # Get defined workspace IDs per monitor
        monitor_defined_ids = {}
        for ws_id, monitor in ws_to_monitor.items():
            if monitor not in monitor_defined_ids:
                monitor_defined_ids[monitor] = []
            monitor_defined_ids[monitor].append(ws_id)

        for monitor in monitor_defined_ids:
            monitor_defined_ids[monitor].sort()

        default_defined = {
            "eDP-1": [1, 2, 3, 4, 5],
            "HDMI-A-1": [6, 7, 8, 9, 10]
        }

        # Perform collapsing/shifting
        active_id = active_ws.get("id")
        for monitor, occupied_ids in monitor_occupied.items():
            defined_ids = monitor_defined_ids.get(monitor, default_defined.get(monitor, []))
            if not defined_ids:
                continue
            
            for i, old_ws in enumerate(occupied_ids):
                # Calculate the correct contiguous workspace ID
                if i < len(defined_ids):
                    new_ws = defined_ids[i]
                else:
                    new_ws = defined_ids[-1] + (i - len(defined_ids) + 1)
                
                if old_ws != new_ws:
                    # Move all clients from old_ws to new_ws
                    for client in ws_clients.get(old_ws, []):
                        addr = client.get("address")
                        if addr:
                            dispatch_move(new_ws, addr)
                    
                    # If this workspace was active, move focus to the new workspace
                    if active_id == old_ws:
                        dispatch_focus(new_ws)
                        active_id = new_ws  # Update tracking for subsequent shifts
    except Exception as e:
        print(f"Error in reorder_workspaces: {e}", file=sys.stderr)
    finally:
        lock.release()

def find_socket():
    sig = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
    xdg_runtime = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    paths = [
        f"{xdg_runtime}/hypr/{sig}/.socket2.sock",
        f"/run/user/{os.getuid()}/hypr/{sig}/.socket2.sock",
        f"/tmp/hypr/{sig}/.socket2.sock"
    ]
    for p in paths:
        if os.path.exists(p):
            return p
    return None

def main():
    socket_path = find_socket()
    if not socket_path:
        print("Hyprland socket not found.", file=sys.stderr)
        sys.exit(1)

    # Initial check and reorder at startup
    threading.Thread(target=reorder_workspaces).start()

    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.connect(socket_path)
    
    buffer = b""
    while True:
        data = s.recv(4096)
        if not data:
            break
        buffer += data
        while b"\n" in buffer:
            line, buffer = buffer.split(b"\n", 1)
            line_str = line.decode('utf-8', errors='replace')
            # Trigger on workspace, window open/close/move events
            if any(event in line_str for event in ["openwindow>>", "closewindow>>", "movewindow>>", "workspace>>"]):
                threading.Thread(target=reorder_workspaces).start()

if __name__ == "__main__":
    main()
