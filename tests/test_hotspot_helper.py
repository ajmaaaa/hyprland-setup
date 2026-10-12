import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('hotspot_helper', Path(__file__).resolve().parents[1] / 'config/scripts/hotspot-helper.py')
h = importlib.util.module_from_spec(spec)
spec.loader.exec_module(h)


class HelperTests(unittest.TestCase):
    def test_cancelled_start_never_runs_commands_and_cleanup_ignores_marker(self):
        with tempfile.TemporaryDirectory() as folder:
            marker = Path(folder) / 'cancel'
            marker.touch()
            with patch.object(h, 'CANCEL_FILE', marker), patch.object(h.subprocess, 'Popen') as process:
                with self.assertRaisesRegex(RuntimeError, 'cancelled'):
                    h.run(['ip', 'link', 'set', 'hypr-hotspot', 'up'])
                process.assert_not_called()
                with patch.object(h, '_stop') as cleanup:
                    cleanup.side_effect = lambda: self.assertIsNone(h.CANCEL_FILE)
                    h.stop()
                    self.assertEqual(h.CANCEL_FILE, marker)

    def test_firewalld_binding_remembers_and_restores_original_zone(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(h, 'ROOT', Path(folder)), patch.object(h.shutil, 'which', return_value='/usr/bin/firewall-cmd'):
            state = {'uplink': 'wlan0', 'ssid': 'AP'}
            zone = ['public']
            def run(args, **kw):
                if '--get-zone-of-interface=hypr-hotspot' in args:
                    return subprocess.CompletedProcess(args, 0, zone[0] + '\n', '')
                if '--change-interface=hypr-hotspot' in args:
                    # Cleanup context must exist even if the following command fails.
                    self.assertEqual(json.loads((Path(folder) / 'state.json').read_text())['firewalld_previous_zone'], 'public')
                    zone[0] = args[1].split('=', 1)[1]
                return subprocess.CompletedProcess(args, 0, '', '')
            with patch.object(h, 'run', side_effect=run):
                h.configure_firewall(state)
                self.assertEqual(zone[0], 'nm-shared')
                h.configure_firewall(state)
                h.restore_firewall(state)
                self.assertEqual(zone[0], 'public')

    def test_firewalld_unassigned_interface_binding_is_removed(self):
        with patch.object(h.shutil, 'which', return_value='/usr/bin/firewall-cmd'), patch.object(h, 'run', return_value=subprocess.CompletedProcess([], 0, 'nm-shared\n', '')) as run:
            h.restore_firewall({'firewalld_previous_zone': ''})
            self.assertEqual(run.call_args.args[0], ['firewall-cmd', '--zone=nm-shared', '--remove-interface=hypr-hotspot'])

    def test_firewalld_disabled_does_not_modify_zones(self):
        with patch.object(h.shutil, 'which', return_value='/usr/bin/firewall-cmd'), patch.object(h, 'run', return_value=subprocess.CompletedProcess([], 252, '', 'not running')) as run:
            h.configure_firewall({'uplink': 'wlan0'})
            self.assertEqual(run.call_count, 1)

    def test_firewall_cleanup_preserves_zone_changed_by_user(self):
        with patch.object(h.shutil, 'which', return_value='/usr/bin/firewall-cmd'), patch.object(h, 'run', return_value=subprocess.CompletedProcess([], 0, 'work\n', '')) as run:
            h.restore_firewall({'firewalld_previous_zone': 'public'})
            self.assertEqual(run.call_count, 1)

    def test_restricted_channel_is_rejected_before_installing_or_starting_services(self):
        def run(args, **kw):
            text = 'type managed\nchannel 64 (5320 MHz)' if 'dev' in args else '* 5320 MHz [64] (22 dBm) (no IR, radar detection)'
            return subprocess.CompletedProcess(args, 0, text, '')
        with patch.object(h.Path, 'exists', return_value=True), patch.object(h, 'run', side_effect=run) as mocked:
            with self.assertRaisesRegex(RuntimeError, '2.4 GHz'):
                h.start({'uplink': 'wlan0', 'ssid': 'Home AP', 'password': '12345678'})
            self.assertTrue(all(c.args[0][0] == 'iw' for c in mocked.call_args_list))

    def test_ap_lifecycle_never_configures_client_as_ap(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(h, 'ROOT', Path(folder)), patch.object(h, 'validate', return_value=('wlan0', 11, 'g')), patch.object(h, 'stop') as stop, patch.object(h.shutil, 'which', return_value='/usr/bin/tool'), patch.object(h.time, 'sleep'), patch.object(h, 'run', return_value=subprocess.CompletedProcess([], 0, '', '')) as run:
            h.start({'uplink': 'wlan0', 'ssid': 'AP;Name', 'password': '12345678'})
            commands = [c.args[0] for c in run.call_args_list]
            self.assertIn(['nmcli', 'device', 'set', 'hypr-hotspot', 'managed', 'no'], commands)
            self.assertNotIn(['nmcli', 'device', 'disconnect', 'wlan0'], commands)
            self.assertTrue(any(c[:2] == ['systemd-run', '--quiet'] and '/usr/bin/hostapd' in c for c in commands))
            self.assertIn('ssid2=' + 'AP;Name'.encode().hex(), (Path(folder) / 'hostapd.conf').read_text())
            self.assertEqual((Path(folder) / 'hostapd.conf').stat().st_mode & 0o777, 0o600)
            self.assertEqual(stop.call_count, 1)

    def test_ap_failure_cleans_up_private_services_and_rules(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(h, 'ROOT', Path(folder)), patch.object(h, 'validate', return_value=('wlan0', 11, 'g')), patch.object(h, 'stop') as stop, patch.object(h.shutil, 'which', return_value='/usr/bin/tool'), patch.object(h.time, 'sleep'):
            def run(args, **kw):
                return subprocess.CompletedProcess(args, 1 if args[:2] == ['systemctl', 'is-active'] else 0, 'AP startup failed', '')
            with patch.object(h, 'run', side_effect=run), self.assertRaises(RuntimeError):
                h.start({'uplink': 'wlan0', 'ssid': 'AP', 'password': '12345678'})
            self.assertEqual(stop.call_count, 2)


if __name__ == '__main__':
    unittest.main()
