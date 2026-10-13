import importlib.util
from pathlib import Path
import subprocess
import sys
import threading
import time
import unittest
from concurrent.futures import Future
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'config/scripts'
spec = importlib.util.spec_from_file_location('usability_connections', SCRIPTS / 'connections.py')
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)


class UsabilityTests(unittest.TestCase):
    def test_cancel_interrupts_a_running_process_without_waiting_for_timeout(self):
        operation = c.Operation()
        c.OPERATION.current = operation
        timer = threading.Timer(.15, operation.cancel)
        timer.start()
        started = time.monotonic()
        try:
            with self.assertRaises(c.OperationCancelled):
                c.run([sys.executable, '-c', 'import time; time.sleep(30)'], timeout=40)
            self.assertLess(time.monotonic() - started, 3)
            # The following action cannot execute after cancellation.
            with self.assertRaises(c.OperationCancelled), patch.object(c.subprocess, 'Popen') as launch:
                c.run(['nmcli', 'radio', 'wifi', 'off'])
            launch.assert_not_called()
        finally:
            timer.cancel()
            c.OPERATION.current = None
            operation.close()

    def test_cancel_does_not_disconnect_an_established_wifi_connection(self):
        args = ['nmcli', 'device', 'wifi', 'connect', 'AA:BB', 'ifname', 'wlan0']
        with patch.object(c.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, '100 (connected)', '')) as run:
            c.cancel_pending_wifi(args)
            self.assertEqual(run.call_count, 1)
        with patch.object(c.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, '60 (connecting)', '')) as run:
            c.cancel_pending_wifi(args)
            self.assertEqual(run.call_count, 2)
            self.assertEqual(run.call_args.args[0][-3:], ['device', 'disconnect', 'wlan0'])

    def test_portal_state_is_per_adapter_and_does_not_label_limited_as_login(self):
        for state, expected in [('2 (portal)\n4 (full)', True), ('3 (limited)', False), ('4 (full)', False), ('0 (unknown)', False)]:
            with self.subTest(state=state), patch.object(c, 'run', return_value=subprocess.CompletedProcess([], 0, state, '')):
                self.assertEqual(bool(c.wifi_needs_login('wlan0')), expected)
        with patch.object(c, 'launch') as launch:
            c.open_wifi_login()
            launch.assert_called_once_with('xdg-open', 'http://neverssl.com/')

    def test_password_and_portal_security_are_independent(self):
        for security, locked in [('', False), ('--', False), ('OWE', False), ('WPA2', True), ('WPA1 WPA2', True), ('802.1X', True)]:
            with self.subTest(security=security):
                self.assertEqual(c.wifi_requires_password(security), locked)

    def test_qr_requires_an_active_ap_with_matching_credentials(self):
        info = {'active': False, 'password': '12345678'}
        self.assertFalse(c.hotspot_qr_available(info))
        info['active'] = True
        self.assertTrue(c.hotspot_qr_available(info))
        info['credentials_mismatch'] = True
        self.assertFalse(c.hotspot_qr_available(info))

    def test_band_switch_is_only_offered_for_a_restricted_uplink(self):
        info = {'active': False, 'supported': True}
        with patch.object(c, 'native_hotspot_uplink', return_value='wlan0'), patch.object(c, 'hotspot_channel', return_value=6):
            self.assertFalse(c.hotspot_needs_band_switch(info))
        with patch.object(c, 'native_hotspot_uplink', return_value='wlan0'), patch.object(c, 'hotspot_channel', side_effect=c.HotspotBandError('restricted')):
            self.assertTrue(c.hotspot_needs_band_switch(info))
            self.assertFalse(c.hotspot_needs_band_switch({**info, 'active': True}))


class PanelUsabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(SCRIPTS))
        spec = importlib.util.spec_from_file_location('usability_ui', SCRIPTS / 'connections-ui.py')
        cls.ui = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.ui)
        if not cls.ui.Gtk.init_check()[0]:
            raise unittest.SkipTest('A desktop display is required')
        cls.app = cls.ui.Gtk.Application(application_id='local.hyprland.ConnectionUsabilityTests', flags=cls.ui.Gio.ApplicationFlags.NON_UNIQUE)
        cls.app.register(None)

    def setUp(self):
        discovery = patch.object(self.ui.Panel, 'stop_discovery')
        discovery.start()
        self.addCleanup(discovery.stop)
        with patch.object(self.ui.Panel, 'refresh', return_value=True):
            self.panel = self.ui.Panel(self.app)
        self.addCleanup(self.panel.destroy)

    def widgets(self, widget):
        yield widget
        if isinstance(widget, self.ui.Gtk.Container):
            for child in widget.get_children():
                yield from self.widgets(child)

    def test_hotspot_off_hides_qr_and_unneeded_recovery_buttons(self):
        info = {'active': False, 'supported': True, 'ssid': 'Test', 'password': '12345678'}
        with patch.object(self.ui.backend, 'get_hotspot_status', return_value=info), patch.object(self.ui.backend, 'hotspot_needs_band_switch', return_value=False), patch.object(self.ui.backend, 'qr_to_svg') as qr:
            self.panel.render_hotspot_page()
            qr.assert_not_called()
            labels = [w.get_label() for w in self.widgets(self.panel.hotspot_box) if isinstance(w, self.ui.Gtk.Button)]
            self.assertNotIn('Sync hotspot password', labels)
            self.assertNotIn('Use 2.4 GHz Wi-Fi', labels)
        with patch.object(self.ui.backend, 'get_hotspot_status', return_value={**info, 'active': True}), patch.object(self.ui.backend, 'hotspot_needs_band_switch', return_value=False), patch.object(self.ui.backend, 'qr_to_svg', return_value='') as qr:
            self.panel.render_hotspot_page()
            qr.assert_called_once()

    def test_secure_portal_network_shows_both_lock_and_login(self):
        self.panel.add_row('Campus', 'Login required', 'network-wireless-symbolic', locked=True, login=True)
        widgets = list(self.widgets(self.panel.listbox))
        self.assertTrue(any(isinstance(w, self.ui.Gtk.Image) and w.get_icon_name()[0] == 'changes-prevent-symbolic' for w in widgets))
        login = next(w for w in widgets if isinstance(w, self.ui.Gtk.Button) and w.get_label() == 'Login')
        with patch.object(self.ui.backend, 'open_wifi_login') as launch:
            login.clicked()
            launch.assert_called_once()

    def test_wireless_debugging_expands_for_active_qr_and_keeps_devices_visible(self):
        from types import SimpleNamespace
        session = {'active': True, 'state': 'waiting', 'message': 'Scan QR', 'svg': self.ui.backend.qr_to_svg('WIFI:T:ADB;S:studio-test;P:1234567890;;')}
        self.panel.render_adb_page([])
        self.assertEqual(len(self.panel.adb_box.get_children()), 1)
        self.panel.adb_session = SimpleNamespace(snapshot=lambda: dict(session), stop=lambda: None)
        self.panel.render_adb_page([])
        self.assertEqual(len(self.panel.adb_box.get_children()), 2)
        self.assertFalse(self.panel.cancel_action_button.get_visible())
        session.update(active=False, state='connected', svg=None, message='Connected')
        self.panel.render_adb_page([('192.168.1.7:41234', 'Samsung A13', 'device', True)])
        self.assertEqual(len(self.panel.adb_box.get_children()), 1)
        labels = [w.get_text() for w in self.widgets(self.panel.adb_box) if isinstance(w, self.ui.Gtk.Label)]
        self.assertIn('Samsung A13', labels)

    def test_device_row_opens_scrcpy_directly_and_has_only_disconnect(self):
        serial = '192.168.1.7:41234'
        self.panel.render_adb_page([(serial, 'Samsung A13', 'device', True)])
        widgets = list(self.widgets(self.panel.adb_box))
        listing = next(w for w in widgets if isinstance(w, self.ui.Gtk.ListBox))
        row = listing.get_children()[0]
        buttons = [w for w in widgets if isinstance(w, self.ui.Gtk.Button)]
        self.assertNotIn('Rename device', [w.get_label() for w in buttons])
        self.assertNotIn('Pair with code', [w.get_label() for w in buttons])
        with patch.object(self.panel, 'perform', side_effect=lambda callback: callback()), \
             patch.object(self.ui.backend, 'start_scrcpy') as mirror, \
             patch.object(self.ui.backend, 'disconnect_adb_device') as disconnect:
            self.panel.activate_row(listing, row)
            mirror.assert_called_once_with(serial)
            next(w for w in buttons if w.get_label() == 'Disconnect').clicked()
            disconnect.assert_called_once_with(serial)

    def test_qr_completion_opens_the_selected_screen_only_once(self):
        from types import SimpleNamespace
        serial = '192.168.1.7:41234'
        self.panel.page = 'adb'
        self.panel.adb_session = SimpleNamespace(snapshot=lambda: {'state': 'connected', 'serial': serial}, stop=lambda: None)
        with patch.object(self.panel, 'refresh'), \
             patch.object(self.panel, 'perform', side_effect=lambda callback: callback()), \
             patch.object(self.ui.backend, 'start_scrcpy') as mirror:
            self.panel.adb_pairing_changed()
            self.panel.adb_pairing_changed()
        mirror.assert_called_once_with(serial)

    def test_offline_phone_cannot_start_scrcpy_but_can_be_disconnected(self):
        self.panel.render_adb_page([('192.168.1.7:41234', 'Samsung A13', 'offline', True)])
        widgets = list(self.widgets(self.panel.adb_box))
        listing = next(w for w in widgets if isinstance(w, self.ui.Gtk.ListBox))
        self.assertIsNone(listing.get_children()[0].callback)
        self.assertTrue(any(isinstance(w, self.ui.Gtk.Button) and w.get_label() == 'Disconnect' for w in widgets))

    def test_device_details_do_not_show_header_cancel(self):
        self.panel.busy = True
        self.panel.cancel_action_button.show()
        future = Future()
        self.panel.show_prompt(future, 'Samsung A13', 'Connected', ['Rename device', 'Disconnect', 'Back'])
        self.assertFalse(self.panel.cancel_action_button.get_visible())

    def test_connected_message_is_removed_when_the_device_disappears(self):
        from types import SimpleNamespace
        self.panel.adb_session = SimpleNamespace(snapshot=lambda: {'state': 'connected', 'active': False, 'svg': None, 'message': 'Android connected.'}, stop=lambda: None)
        self.panel.render_adb_page([])
        labels = [w.get_text() for w in self.widgets(self.panel.adb_box) if isinstance(w, self.ui.Gtk.Label)]
        self.assertNotIn('Android connected.', labels)
        self.assertTrue(any('no longer connected' in text for text in labels))

    def test_outside_click_keeps_busy_panel_open_and_cancel_resolves_prompt(self):
        operation = self.ui.backend.Operation()
        self.addCleanup(operation.close)
        self.panel.operation = operation
        self.panel.busy = True
        self.panel.pending = Future()
        future = self.panel.pending
        with patch.object(self.panel, 'close') as close:
            self.panel.dismiss_on_outside_click()
            close.assert_not_called()
        self.panel.cancel_action()
        self.assertTrue(operation.cancelled.is_set())
        self.assertIsNone(future.result(timeout=1))

    def test_cancellation_releases_busy_state_and_restores_controls(self):
        ui = self.ui
        context = ui.GLib.MainContext.default()
        with patch.object(ui.Panel, 'refresh', return_value=True):
            self.panel.perform(lambda: ui.backend.run([sys.executable, '-c', 'import time; time.sleep(30)']))
            self.assertTrue(self.panel.cancel_action_button.get_visible())
            self.panel.cancel_action()
            deadline = time.monotonic() + 3
            while self.panel.busy and time.monotonic() < deadline:
                while context.pending():
                    context.iteration(False)
                time.sleep(.01)
            self.assertFalse(self.panel.busy)
            self.assertTrue(self.panel.listbox.get_sensitive())
            self.assertTrue(self.panel.hotspot_box.get_sensitive())
            self.assertFalse(self.panel.cancel_action_button.get_visible())


if __name__ == '__main__':
    unittest.main()
