import importlib.util
from pathlib import Path
import socket
import struct
import subprocess
import threading
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('repair_connections', Path(__file__).resolve().parents[1] / 'config/scripts/connections.py')
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)


def dns(name):
    return b''.join(bytes([len(p)]) + p.encode() for p in name.split('.')) + b'\0'


class RepairsTest(unittest.TestCase):
    def test_code_pairing_connects_only_the_paired_host_on_its_connection_port(self):
        services = [
            ('other-phone', '_adb-tls-connect._tcp', '192.168.1.8:41234'),
            ('paired-phone', '_adb-tls-pairing._tcp', '192.168.1.7:37123'),
            ('paired-phone', '_adb-tls-connect._tcp', '192.168.1.7:41234'),
        ]
        def adb(*args, **kw):
            return 'Successfully paired to device' if args[0] == 'pair' else 'connected to 192.168.1.7:41234'
        with patch.object(c, 'entry', side_effect=['192.168.1.7:37123', '123456']) as entry, \
             patch.object(c, 'adb_mdns_services', return_value=services), \
             patch.object(c, 'adb_run', side_effect=adb) as run, \
             patch.object(c, 'verify_adb_ready', return_value='Phone') as ready, \
             patch.object(c, 'notify') as notify:
            c.adb_pair()
        self.assertEqual(entry.call_count, 2)
        self.assertEqual(run.call_args.args, ('connect', '192.168.1.7:41234'))
        ready.assert_called_once_with('192.168.1.7:41234')
        self.assertIn('You can now open scrcpy', notify.call_args.args[0])

    def test_code_pairing_falls_back_to_prompt_when_discovery_finds_no_phone(self):
        with patch.object(c, 'adb_mdns_services', return_value=[]), \
             patch.object(c, 'native_adb_mdns', return_value=[]), \
             patch.object(c, 'entry', return_value='192.168.1.7:41234') as entry, \
             patch.object(c, 'adb_run', return_value='already connected to 192.168.1.7:41234'), \
             patch.object(c, 'verify_adb_ready', return_value='Phone'):
            self.assertEqual(c.connect_after_adb_pairing('192.168.1.7:37123'), ('Phone', '192.168.1.7:41234'))
        self.assertIn('main Wireless debugging page', entry.call_args.args[1])

    def test_pairing_port_is_rejected_before_trying_to_connect(self):
        with patch.object(c, 'adb_mdns_services', return_value=[]), \
             patch.object(c, 'native_adb_mdns', return_value=[]), \
             patch.object(c, 'entry', return_value='192.168.1.7:37123'), \
             patch.object(c, 'adb_run') as adb:
            with self.assertRaisesRegex(RuntimeError, 'pairing port'):
                c.connect_after_adb_pairing('192.168.1.7:37123')
            adb.assert_not_called()

    def test_unusable_transport_after_pairing_never_claims_scrcpy_is_ready(self):
        services = [('phone', '_adb-tls-connect._tcp', '192.168.1.7:41234')]
        def adb(*args, **kw):
            return 'Successfully paired to device' if args[0] == 'pair' else 'connected to 192.168.1.7:41234'
        with patch.object(c, 'entry', side_effect=['192.168.1.7:37123', '123456', None]), \
             patch.object(c, 'adb_mdns_services', return_value=services), \
             patch.object(c, 'adb_run', side_effect=adb), \
             patch.object(c, 'verify_adb_ready', side_effect=RuntimeError('offline')), \
             patch.object(c, 'notify') as notify, patch.object(c, 'info') as info:
            c.adb_pair()
        notify.assert_not_called()
        self.assertEqual(info.call_args.args[0], 'Pairing saved, not connected')

    def test_cancelled_discovery_does_not_open_the_manual_connection_prompt(self):
        with patch.object(c, 'adb_mdns_services', side_effect=c.OperationCancelled()), \
             patch.object(c, 'entry') as entry:
            with self.assertRaises(c.OperationCancelled):
                c.connect_after_adb_pairing('192.168.1.7:37123')
            entry.assert_not_called()

    def test_device_state_alone_is_not_enough_without_a_working_shell(self):
        with patch.object(c, 'adb_run', side_effect=['device', RuntimeError('device offline')]):
            with self.assertRaisesRegex(RuntimeError, 'offline'):
                c.verify_adb_ready('192.168.1.7:41234')

    def test_manual_connect_does_not_report_success_for_an_unusable_transport(self):
        with patch.object(c, 'entry', return_value='192.168.1.7:41234'), patch.object(c, 'adb_run', return_value='connected to 192.168.1.7:41234'), patch.object(c, 'verify_adb_ready', side_effect=RuntimeError('offline')), patch.object(c, 'notify') as notify:
            with self.assertRaisesRegex(RuntimeError, 'offline'):
                c.adb_connect()
            notify.assert_not_called()

    def test_scrcpy_startup_error_is_reported_instead_of_discarded(self):
        import tempfile
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as folder:
            def launch(args, **kw):
                kw['stdout'].write('ERROR: Could not connect to server\n')
                kw['stdout'].flush()
                return Mock(wait=Mock(return_value=1))
            with patch.object(c, 'STATE_DIR', Path(folder)), patch.object(c, 'verify_adb_ready', return_value='Phone'), patch.object(c.shutil, 'which', return_value='/usr/bin/scrcpy'), patch.object(c.subprocess, 'Popen', side_effect=launch):
                with self.assertRaisesRegex(RuntimeError, 'Could not connect to server'):
                    c.start_scrcpy('192.168.1.7:41234')

    def test_configured_wireless_discovery_never_queries_services_or_runs_pkexec(self):
        def run(args, **kw):
            self.assertNotIn('--query-service=mdns', args)
            self.assertNotEqual(args[0], 'pkexec')
            self.assertNotEqual(args[0], 'firewall-cmd')
            return subprocess.CompletedProcess(args, 0, '{"data":["public"]}' if args[0] == 'busctl' else '', '')
        with patch.object(c.shutil, 'which', return_value='/usr/bin/firewall-cmd'), patch.object(c, 'devices', return_value=[['wlan0', 'wifi', 'connected', 'Home']]), patch.object(c, 'saved_zone_allows_mdns', return_value=True), patch.object(c, 'run', side_effect=run):
            c.ensure_adb_discovery()

    def test_cancelled_discovery_setup_stops_before_pairing(self):
        session = c.AdbQrSession()
        with patch.object(c, 'ensure_adb_discovery', side_effect=RuntimeError('Authentication cancelled.')), patch.object(c, 'adb_run') as adb:
            session.work()
            adb.assert_not_called()
        self.assertEqual(session.snapshot()['state'], 'error')
        self.assertFalse(session.snapshot()['active'])
        self.assertIsNone(session.snapshot()['svg'])

    def test_saved_zone_override_is_used_instead_of_default_zone_definition(self):
        from xml.etree import ElementTree as ET
        custom = ET.ElementTree(ET.fromstring('<zone><service name="ssh"/></zone>'))
        with patch.object(c.ET, 'parse', return_value=custom) as parse:
            self.assertFalse(c.saved_zone_allows_mdns('public'))
            self.assertEqual(parse.call_count, 1)
        enabled = ET.ElementTree(ET.fromstring('<zone><service name="mdns"/></zone>'))
        with patch.object(c.ET, 'parse', side_effect=[FileNotFoundError(), enabled]):
            self.assertTrue(c.saved_zone_allows_mdns('nm-shared'))

    def test_qr_timeout_ends_session_and_removes_qr(self):
        session = c.AdbQrSession(scan_timeout=0)
        with patch.object(c, 'ensure_adb_discovery'), patch.object(c, 'adb_run'):
            session.work()
        self.assertEqual(session.snapshot()['state'], 'timeout')
        self.assertFalse(session.snapshot()['active'])
        self.assertIsNone(session.snapshot()['svg'])

    def test_qr_pairing_error_is_terminal_and_secret_is_redacted(self):
        session = c.AdbQrSession()
        services = [(session.service_name, '_adb-tls-pairing._tcp', '192.168.1.7:37123')]
        def adb(*args, **kw):
            if args[0] == 'pair':
                raise RuntimeError('Authentication failed: ' + session.code)
            return ''
        with patch.object(c, 'ensure_adb_discovery'), patch.object(c, 'adb_mdns_services', return_value=services), patch.object(c, 'adb_run', side_effect=adb):
            session.work()
        self.assertEqual(session.snapshot()['state'], 'error')
        self.assertFalse(session.snapshot()['active'])
        self.assertNotIn(session.code, session.snapshot()['message'])

    def test_qr_cancel_interrupts_pairing_client_and_ends_session(self):
        session = c.AdbQrSession()
        services = [(session.service_name, '_adb-tls-pairing._tcp', '192.168.1.7:37123')]
        def adb(*args, **kw):
            if args[0] == 'pair':
                session.stop()
                c.check_cancelled()
            return ''
        with patch.object(c, 'ensure_adb_discovery'), patch.object(c, 'adb_mdns_services', return_value=services), patch.object(c, 'adb_run', side_effect=adb):
            session.work()
        self.assertEqual(session.snapshot()['state'], 'cancelled')
        self.assertFalse(session.snapshot()['active'])

    def test_dns_srv_port_and_target_are_resolved_with_compression(self):
        owner = 'studio-example._adb-tls-pairing._tcp.local'
        srv = struct.pack('!HHH', 0, 0, 37123) + dns('phone.local')
        packet = struct.pack('!6H', 0, 0x8400, 0, 2, 0, 0)
        packet += dns(owner) + struct.pack('!HHIH', 33, 0x8001, 120, len(srv)) + srv
        packet += dns('phone.local') + struct.pack('!HHIH', 1, 1, 120, 4) + socket.inet_aton('192.168.1.7')
        self.assertEqual(c.parse_mdns_records(packet), [(owner, 'srv', ('phone.local', 37123), 120), ('phone.local', 'addr', '192.168.1.7', 120)])
        self.assertEqual(c.dns_name(dns('phone.local') + b'\xc0\x00', len(dns('phone.local')))[0], 'phone.local')
        self.assertEqual(c.parse_mdns_records(packet[:-1]), [])
        with self.assertRaises(ValueError):
            c.dns_name(b'\xc0\x00', 0)

    def test_adb_without_compiled_mdns_uses_fallback_without_raising(self):
        with patch.object(c, 'run', return_value=subprocess.CompletedProcess([], 1, '', 'mdns is not supported')), patch.object(c.shutil, 'which', return_value=None):
            self.assertEqual(c.adb_mdns_services(), [])

    def test_qr_pairs_only_matching_session_and_connects_to_correct_port(self):
        workers = []
        class Worker:
            def __init__(self, target, **kw):
                workers.append(target)
            def start(self):
                pass
        def display(*args, **kw):
            self.assertEqual(args[0], 'studio-' + 'a' * 10)
            workers[0]()
        services = [('another-phone', '_adb-tls-pairing._tcp', '192.168.1.8:30000'),
                    ('studio-' + 'a' * 10, '_adb-tls-pairing._tcp', '192.168.1.7:37123'),
                    ('adb-phone', '_adb-tls-connect._tcp', '192.168.1.7:41234')]
        with patch.object(c, 'verify_adb_ready', return_value='Samsung A13'), patch.object(c, 'ensure_adb_discovery'), patch.object(c.shutil, 'which', return_value='/usr/bin/adb'), patch.object(c.secrets, 'token_hex', return_value='a' * 10), patch.object(c.threading, 'Thread', Worker), patch.object(c, 'show_qr', side_effect=display), patch.object(c, 'adb_mdns_services', return_value=services), patch.object(c, 'notify'), patch.object(c, 'adb_devices', return_value=[('192.168.1.7:41234', 'Phone', 'device', True)]), patch.object(c, 'adb_run', return_value='Successfully paired to device') as adb:
            c.adb_pair_qr()
            self.assertEqual([x.args for x in adb.call_args_list], [('start-server',), ('pair', '192.168.1.7:37123'), ('connect', '192.168.1.7:41234')])

    def test_concurrent_ap_requires_a_channel_allowed_by_driver(self):
        radio = '* 2462 MHz [11] (22.0 dBm)\nvalid interface combinations:\n * #{ managed } <= 1, #{ AP } <= 1, total <= 2, #channels <= 1'
        def run(args, **kw):
            return subprocess.CompletedProcess(args, 0, radio if args[1] == 'phy' else 'channel 11 (2462 MHz)', '')
        with patch.object(c, 'run', side_effect=run):
            self.assertEqual(c.hotspot_channel('wlan0'), 11)
        radio = radio.replace('2462 MHz [11] (22.0 dBm)', '5320 MHz [64] (22.0 dBm) (no IR, radar detection)')
        def dfs(args, **kw):
            return subprocess.CompletedProcess(args, 0, radio if args[1] == 'phy' else 'channel 64 (5320 MHz)', '')
        with patch.object(c, 'run', side_effect=dfs), self.assertRaisesRegex(RuntimeError, '2.4 GHz'):
            c.hotspot_channel('wlan0')

    def test_unsupported_concurrent_mode_preserves_wifi(self):
        with patch.object(c, 'run', return_value=subprocess.CompletedProcess([], 0, 'valid interface combinations: * #{ managed } <= 1, total <= 1', '')), patch.object(c, 'action') as action:
            with self.assertRaises(RuntimeError):
                c.hotspot_channel('wlan0')
            action.assert_not_called()

    def test_same_radio_uses_native_ap_backend(self):
        info = {'device': 'wlan0', 'supported': True, 'uuid': 'hotspot-uuid', 'ssid': 'Test', 'active': False}
        with patch.object(c, 'get_hotspot_status', return_value=info), patch.object(c, 'native_hotspot_uplink', return_value='wlan0'), patch.object(c, 'start_native_hotspot') as native, patch.object(c, 'nm') as nm:
            c.turn_on_hotspot()
            native.assert_called_once_with(info)
            nm.assert_not_called()

    def test_24ghz_selection_keeps_same_ssid(self):
        rows = [['Home', '2462 MHz', '70', 'AA:BB:CC:DD:EE:01'], ['Other', '2437 MHz', '99', 'AA:BB:CC:DD:EE:02'], ['Home', '5320 MHz', '85', 'AA:BB:CC:DD:EE:03']]
        with patch.object(c, 'wifi_client_devices', return_value=[['wlan0', 'wifi', 'connected', 'Home']]), patch.object(c, 'rows', return_value=rows), patch.object(c, 'nm', return_value='Home'), patch.object(c, 'run', return_value=subprocess.CompletedProcess([], 0, 'channel 64 (5320 MHz)', '')), patch.object(c, 'notify'), patch.object(c, 'action') as action:
            c.use_24ghz_uplink()
            self.assertIn('AA:BB:CC:DD:EE:01', action.call_args.args[0])
            self.assertNotIn('AA:BB:CC:DD:EE:02', action.call_args.args[0])

    def test_hotspot_activation_never_runs_on_uplink(self):
        info = {'device': 'wlan1', 'supported': True, 'uuid': 'hotspot-uuid', 'ssid': 'Test', 'active': False}
        with patch.object(c, 'get_hotspot_status', return_value=info), patch.object(c, 'native_hotspot_uplink', return_value=None), patch.object(c, 'nm') as nm, patch.object(c, 'notify'), patch.object(c, 'action') as action:
            c.turn_on_hotspot()
            self.assertEqual(action.call_args.args[0][-2:], ['ifname', 'wlan1'])
            self.assertFalse(any(x.args[:2] == ('device', 'disconnect') for x in nm.call_args_list))

    def test_ap_is_not_reported_as_client_wifi(self):
        def nm(*args):
            return 'ap' if '802-11-wireless.mode' in args else 'ap-uuid'
        with patch.object(c, 'devices', return_value=[['wlan0', 'wifi', 'connected', 'Hotspot'], ['hypr-hotspot', 'wifi', 'connected', 'Hotspot']]), patch.object(c, 'nm', side_effect=nm):
            self.assertEqual(c.wifi_client_devices(), [])

    def test_active_ap_mismatch_never_exposes_stale_password(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            cfg = Path(folder) / 'hotspot.json'
            cfg.write_text('{"ssid": "Arch", "password": "old-secret"}')
            with patch.object(c, 'HOTSPOT_CONFIG_FILE', cfg), patch.object(c, 'native_hotspot_active', return_value=True), patch.object(c, 'run', return_value=subprocess.CompletedProcess([], 0, 'Interface hypr-hotspot\n\tssid Actual-AP\n', '')):
                info = c.get_hotspot_status()
                self.assertEqual(info['ssid'], 'Actual-AP')
                self.assertTrue(info['credentials_mismatch'])
                self.assertEqual(info['password'], '')

    def test_native_start_persists_the_credentials_used_by_ap(self):
        import tempfile, json
        info = {'device': 'wlan0', 'ssid': 'Actual-AP', 'password': 'actual-secret'}
        with tempfile.TemporaryDirectory() as folder:
            cfg = Path(folder) / 'hotspot.json'
            with patch.object(c, 'STATE_DIR', Path(folder)), patch.object(c, 'HOTSPOT_CONFIG_FILE', cfg), patch.object(c, 'native_hotspot_uplink', return_value='wlan0'), patch.object(c, 'hotspot_channel', return_value=6), patch.object(c, 'run', return_value=subprocess.CompletedProcess([], 0, 'ok', '')), patch.object(c, 'notify'):
                c.start_native_hotspot(info)
                self.assertEqual(json.loads(cfg.read_text()), {'ssid': info['ssid'], 'password': info['password']})


if __name__ == '__main__':
    unittest.main()
