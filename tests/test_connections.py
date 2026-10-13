import importlib.util
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location('connections', Path(__file__).resolve().parents[1] / 'config/scripts/connections.py')
popup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(popup)


class ConnectionsTest(unittest.TestCase):
    def setUp(self):
        native = patch.object(popup, 'native_hotspot_active', return_value=False)
        native.start()
        self.addCleanup(native.stop)

    def test_native_action_dialog_opens_and_returns_selection(self):
        try:
            import gi
        except ImportError:
            self.skipTest('GTK bindings are only needed for the graphical panel')
        sys.modules.setdefault('connections', popup)
        ui_spec = importlib.util.spec_from_file_location('connections_ui', Path(__file__).resolve().parents[1] / 'config/scripts/connections-ui.py')
        ui = importlib.util.module_from_spec(ui_spec)
        ui_spec.loader.exec_module(ui)
        def show_prompt(future, title, message, options):
            self.assertEqual((title, options), ('Hotspot', ['wlan0', 'Back']))
            future.set_result(0)
        panel = SimpleNamespace(show_prompt=show_prompt)
        with patch.object(ui.GLib, 'idle_add', side_effect=lambda callback, *args: callback(*args)), \
             patch.object(ui.Gtk, 'Dialog') as dialog:
            result = ui.Panel.menu(panel, 'Hotspot', ['wlan0', 'Back'])
        self.assertEqual(result, 0)
        dialog.assert_not_called()

    def test_detail_back_does_not_launch_settings(self):
        network = ['', 'Guest', '80', '', 'AA:BB:CC:DD:EE:FF', 'wlan0']
        with patch.object(popup, 'wifi_profiles', return_value=[]), \
             patch.object(popup, 'menu', return_value=1), \
             patch.object(popup, 'launch') as launch:
            popup.wifi_details(network)
            launch.assert_not_called()
        with patch.object(popup, 'bt', return_value='Paired: no'), \
             patch.object(popup, 'menu', return_value=1), \
             patch.object(popup, 'launch') as launch:
            popup.bluetooth_details(('AA:BB:CC:DD:EE:FF', 'Headphones', False, False, ''))
            launch.assert_not_called()

    def test_vpn_manual_server_uses_saved_uuid(self):
        with patch.object(popup.shutil, 'which', return_value='/usr/bin/protonvpn'), \
             patch.object(popup, 'proton_profiles', return_value=[('Japan', 'saved-uuid')]), \
             patch.object(popup, 'rows', return_value=[]), \
             patch.object(popup, 'run', return_value=subprocess.CompletedProcess([], 0, 'Disconnected.', '')) as run, \
             patch.object(popup, 'menu', side_effect=[1, 4]) as menu, \
             patch.object(popup, 'nm') as nm:
            popup.vpn()
            self.assertEqual(menu.call_args_list[0].args[1], ['Automatic (Fastest)', 'Select server', 'Disconnect'])
            self.assertIn('Custom: Japan', menu.call_args_list[1].args[1])
            nm.assert_called_once_with('connection', 'up', 'uuid', 'saved-uuid')
            self.assertFalse(any(call.args[0] == ['protonvpn', 'connect'] for call in run.call_args_list))

    def test_vpn_cancel_does_not_change_connections(self):
        with patch.object(popup.shutil, 'which', return_value='/usr/bin/protonvpn'), \
             patch.object(popup, 'proton_profiles', return_value=[]), \
             patch.object(popup, 'rows', return_value=[]), \
             patch.object(popup, 'run', return_value=subprocess.CompletedProcess([], 0, 'Disconnected.', '')) as run, \
             patch.object(popup, 'menu', return_value=None), \
             patch.object(popup, 'nm') as nm:
            popup.vpn()
            nm.assert_not_called()
            run.assert_called_once_with(['protonvpn', 'status'], timeout=15)

    def test_vpn_automatic_disconnects_only_managed_servers(self):
        with patch.object(popup.shutil, 'which', return_value='/usr/bin/protonvpn'), \
             patch.object(popup, 'proton_profiles', return_value=[('Japan', 'saved-uuid')]), \
             patch.object(popup, 'rows', return_value=[['saved-uuid'], ['work-vpn']]), \
             patch.object(popup, 'run', return_value=subprocess.CompletedProcess([], 0, '', '')) as run, \
             patch.object(popup, 'menu', return_value=0), \
             patch.object(popup, 'nm') as nm:
            popup.vpn()
            nm.assert_called_once_with('connection', 'down', 'uuid', 'saved-uuid')
            self.assertTrue(any(call.args[0] == ['protonvpn', 'connect'] for call in run.call_args_list))

    def test_network_names_and_mac_addresses_are_not_split(self):
        self.assertEqual(popup.fields(r'*:Cafe\: Guest\\AP:80:WPA2:AA\:BB\:CC\:DD\:EE\:FF:wlan0'),
                         ['*', 'Cafe: Guest\\AP', '80', 'WPA2', 'AA:BB:CC:DD:EE:FF', 'wlan0'])

    def test_menu_cannot_inject_extra_rows_or_markup(self):
        with patch.object(popup, 'run', return_value=subprocess.CompletedProcess([], 0, '1\n', '')) as run:
            self.assertEqual(popup.menu('Wi-Fi', ['A\nB\x00urgent\x1ftrue', '<b>Guest</b>']), 1)
            args = run.call_args.args[0]
            self.assertNotIn('-markup-rows', args)
            self.assertEqual(len(run.call_args.kwargs['data'].splitlines()), 2)

    def test_cancel_wifi_password_does_not_retry_connection(self):
        network = ['', 'Guest', '80', 'WPA2', 'AA:BB:CC:DD:EE:FF', 'wlan0']
        with patch.object(popup, 'devices', return_value=[['wlan0', 'wifi', 'disconnected', '']]), \
             patch.object(popup, 'nm', return_value='enabled'), \
             patch.object(popup, 'rows', return_value=[network]), \
             patch.object(popup, 'menu', side_effect=[4, None]), \
             patch.object(popup, 'notify'), \
             patch.object(popup, 'entry', return_value=None), \
             patch.object(popup, 'run', return_value=subprocess.CompletedProcess([], 4, '', 'Secrets required')), \
             patch.object(popup, 'action') as action:
            popup.wifi()
            action.assert_not_called()

    def test_wifi_password_is_sent_via_stdin_not_arguments(self):
        network = ['', 'Guest $(touch /tmp/nope)', '80', 'WPA2', 'AA:BB:CC:DD:EE:FF', 'wlan0']
        with patch.object(popup, 'devices', return_value=[['wlan0', 'wifi', 'disconnected', '']]), \
             patch.object(popup, 'nm', return_value='enabled'), \
             patch.object(popup, 'rows', return_value=[network]), \
             patch.object(popup, 'menu', side_effect=[4, None]), \
             patch.object(popup, 'notify'), \
             patch.object(popup, 'entry', return_value='secret-value'), \
             patch.object(popup, 'run', return_value=subprocess.CompletedProcess([], 4, '', 'Secrets required')), \
             patch.object(popup, 'action') as action:
            popup.wifi()
            command, data = action.call_args.args
            self.assertNotIn('secret-value', command)
            self.assertIn('--ask', command)
            self.assertEqual(data, 'secret-value\n')

    def test_bluetooth_remains_accessible_without_networkmanager(self):
        with patch.object(popup.shutil, 'which', return_value='/usr/bin/program'), \
             patch.object(popup, 'devices', side_effect=RuntimeError('Offline')), \
             patch.object(popup, 'menu', side_effect=[1, None]), \
             patch.object(popup, 'bluetooth') as bluetooth:
            popup.main()
            bluetooth.assert_called_once()

    def test_unsupported_hotspot_cannot_create_connection(self):
        with patch.object(popup, 'devices', return_value=[['wlan0', 'wifi', 'connected', 'Home']]), \
             patch.object(popup, 'nm', return_value='no') as nm, \
             patch.object(popup, 'info') as info, \
             patch.object(popup, 'entry') as entry:
            popup.hotspot()
            self.assertIn('No adapter', info.call_args.args[1])
            entry.assert_not_called()
            self.assertEqual(nm.call_count, 1)

    def test_cancel_supported_hotspot_preserves_current_wifi(self):
        with patch.object(popup, 'devices', return_value=[['wlan0', 'wifi', 'connected', 'Home']]), \
             patch.object(popup, 'nm', side_effect=['yes', '']) as nm, \
             patch.object(popup, 'rows', return_value=[]), \
             patch.object(popup, 'menu', return_value=2), \
             patch.object(popup, 'action') as action:
            popup.hotspot()
            action.assert_not_called()

    def test_vpn_select_free_country(self):
        with patch.object(popup.shutil, 'which', return_value='/usr/bin/protonvpn'), \
             patch.object(popup, 'proton_profiles', return_value=[]), \
             patch.object(popup, 'rows', return_value=[]), \
             patch.object(popup, 'run', return_value=subprocess.CompletedProcess([], 0, 'Disconnected.', '')), \
             patch.object(popup, 'menu', side_effect=[1, 0]), \
             patch.object(popup, 'action') as action:
            popup.vpn()
            action.assert_called_once_with(['protonvpn', 'connect', '--country', 'SG'])

    def test_ethernet_connected_offers_disconnect(self):
        with patch.object(popup, 'devices', return_value=[['eth0', 'ethernet', 'connected', 'Wired 1']]), \
             patch.object(popup, 'menu', return_value=0) as menu, \
             patch.object(popup, 'rows', return_value=[['uuid-123', 'eth0']]), \
             patch.object(popup, 'run') as run, \
             patch.object(popup, 'nm') as nm:
            popup.ethernet()
            self.assertEqual(menu.call_args.args[1][0], 'Disconnect')
            nm.assert_called_with('device', 'disconnect', 'eth0')
            self.assertTrue(any('connection' in call.args[0] and 'down' in call.args[0] for call in run.call_args_list))

    def test_adb_pair_qr_displays_qr(self):
        with patch.object(popup.shutil, 'which', return_value='/usr/bin/adb'), \
             patch.object(popup, 'adb_run', return_value=''), \
             patch.object(popup.threading, 'Thread'), \
             patch.object(popup, 'show_qr') as show_qr:
            popup.adb_pair_qr()
            show_qr.assert_called_once()
            service, code, svg = show_qr.call_args.args[:3]
            self.assertTrue(service.startswith('studio-'))
            self.assertTrue(code.isdigit() and len(code) == 10)
            self.assertEqual(show_qr.call_args.kwargs.get('security'), 'ADB')

    def test_adb_endpoint_rejects_invalid_addresses_and_ports(self):
        self.assertEqual(popup.adb_endpoint('192.168.1.10:37123'), '192.168.1.10:37123')
        self.assertEqual(popup.adb_endpoint('[fd00::1]:37123'), '[fd00::1]:37123')
        for value in ('--help', '1.2.3.4:0', '1.2.3.4:65536', '1.2.3.4:123;touch /tmp/nope', 'bad:123'):
            with self.subTest(value=value), self.assertRaises(RuntimeError):
                popup.adb_endpoint(value)

    def test_adb_pairing_code_goes_through_stdin(self):
        with patch.object(popup, 'entry', side_effect=['192.168.1.10:37123', '123456']), \
             patch.object(popup, 'adb_run', return_value='Successfully paired to device') as adb, \
             patch.object(popup, 'connect_after_adb_pairing', return_value=None) as connect, \
             patch.object(popup, 'info'):
            popup.adb_pair()
            self.assertNotIn('123456', adb.call_args.args)
            self.assertEqual(adb.call_args.kwargs['data'], '123456\n')
            connect.assert_called_once_with('192.168.1.10:37123')

    def test_adb_cancel_pairing_has_no_side_effects(self):
        with patch.object(popup, 'entry', side_effect=['192.168.1.10:37123', None]), \
             patch.object(popup, 'adb_run') as adb:
            popup.adb_pair()
            adb.assert_not_called()

    def test_adb_zero_exit_connection_failure_is_reported(self):
        with patch.object(popup.shutil, 'which', return_value='/usr/bin/adb'), \
             patch.object(popup, 'run', return_value=subprocess.CompletedProcess([], 0, 'failed to connect', '')):
            with self.assertRaises(RuntimeError):
                popup.adb_run('connect', '192.168.1.10:37123')

    def test_wifi_qr_text_format(self):
        self.assertEqual(popup.wifi_qr_text('Cafe;Net', 'secret:123', 'WPA2'),
                         r'WIFI:T:WPA;S:Cafe\;Net;P:secret\:123;;')
        self.assertEqual(popup.wifi_qr_text('OpenWifi', '', None),
                         'WIFI:T:nopass;S:OpenWifi;;')

    def test_qr_to_svg_produces_valid_svg(self):
        svg = popup.qr_to_svg('WIFI:T:WPA;S:Test;P:12345678;;')
        self.assertIn('<svg xmlns="http://www.w3.org/2000/svg"', svg)
        self.assertIn('</svg>', svg)
        self.assertIn('<rect', svg)

    def test_bluetooth_connect_ensures_trust(self):
        with patch.object(popup, 'bt') as bt:
            bt.side_effect = lambda *args: 'Connected: yes' if args[0] == 'info' else ''
            popup.connect_bluetooth(('AA:BB:CC:DD:EE:FF', 'Earbuds', False, True, ''))
            self.assertTrue(any(call.args == ('trust', 'AA:BB:CC:DD:EE:FF') for call in bt.call_args_list))

    def test_hotspot_active_offers_qr_and_shutdown(self):
        with patch.object(popup, 'devices', return_value=[['wlan0', 'wifi', 'connected', 'Hyprland Hotspot']]), \
             patch.object(popup, 'nm', side_effect=['yes', 'hotspot-uuid', 'ap', 'Hyprland Hotspot', 'secret12345']), \
             patch.object(popup, 'menu', return_value=1), \
             patch.object(popup, 'show_qr_screen') as show_qr, \
             patch.object(popup, 'notify'):
            popup.hotspot()
            show_qr.assert_called_once_with('Hyprland Hotspot', 'secret12345', 'WPA')

    def test_home_list_layout_has_all_connection_items(self):
        try:
            import gi
        except ImportError:
            self.skipTest('GTK bindings are only needed for the graphical panel')
        sys.modules.setdefault('connections', popup)
        ui_spec = importlib.util.spec_from_file_location('connections_ui', Path(__file__).resolve().parents[1] / 'config/scripts/connections-ui.py')
        ui = importlib.util.module_from_spec(ui_spec)
        ui_spec.loader.exec_module(ui)
        home_list = ui.Gtk.ListBox()
        panel = SimpleNamespace(
            closed=False, busy=False, page='home', snapshot=None,
            home_list=home_list, listbox=ui.Gtk.ListBox(),
            select_page=Mock(), perform=Mock(), set_notice=Mock(),
            clear_rows=Mock(),
            add_home_row=lambda *args, **kwargs: ui.Panel.add_home_row(panel, *args, **kwargs)
        )
        data = (['wlan0'], [], 'HomeNet', '', 'MyHeadset')
        ui.Panel.render(panel, 'home', data, None)
        children = home_list.get_children()
        self.assertEqual(len(children), 7)
        titles = [row.get_child().get_children()[1].get_children()[0].get_text() for row in children]
        self.assertEqual(titles, ['Wi-Fi', 'Bluetooth', 'Ethernet', 'Hotspot', 'VPN', 'Airplane Mode', 'Wireless Debugging'])

    def test_default_names_and_renaming(self):
        with patch.object(popup, 'get_adb_aliases', return_value={}):
            self.assertTrue(popup.get_wireless_name().startswith('Arch-ADB'))
        with patch.object(popup, 'set_adb_alias') as mock_set:
            popup.set_wireless_name('ArchDevice')
            mock_set.assert_called_once_with('__wireless_name__', 'ArchDevice')

    def test_qr_icon_pixbuf_loads(self):
        try:
            import gi
        except ImportError:
            self.skipTest('GTK bindings are only needed for the graphical panel')
        ui_spec = importlib.util.spec_from_file_location('connections_ui', Path(__file__).resolve().parents[1] / 'config/scripts/connections-ui.py')
        ui = importlib.util.module_from_spec(ui_spec)
        ui_spec.loader.exec_module(ui)
        pb = ui.qr_icon_pixbuf(18)
        self.assertIsNotNone(pb)
        self.assertEqual(pb.get_width(), 18)
        self.assertEqual(pb.get_height(), 18)

    def test_get_ethernet_status_states(self):
        with patch.object(popup, 'devices', return_value=[]):
            self.assertEqual(popup.get_ethernet_status()[0], 'unavailable')
        with patch.object(popup, 'devices', return_value=[['enp0s31f6', 'ethernet', 'unavailable', '--']]):
            self.assertEqual(popup.get_ethernet_status()[0], 'unavailable')
        with patch.object(popup, 'devices', return_value=[['enp0s31f6', 'ethernet', 'disconnected', '--']]):
            self.assertEqual(popup.get_ethernet_status()[0], 'disconnected')
        with patch.object(popup, 'devices', return_value=[['enp0s31f6', 'ethernet', 'connected', 'OfficeNet']]):
            status, text = popup.get_ethernet_status()
            self.assertEqual(status, 'connected')
            self.assertIn('OfficeNet', text)

    def test_wifi_qr_escaping_special_chars(self):
        text = popup.wifi_qr_text('Test;SSID,with"special:chars\\', 'P@ss;w,o:r"d\\', 'WPA')
        self.assertIn(r'S:Test\;SSID\,with\"special\:chars\\', text)
        self.assertIn(r'P:P@ss\;w\,o\:r\"d\\', text)
        open_text = popup.wifi_qr_text('OpenNet', None, None)
        self.assertEqual(open_text, 'WIFI:T:nopass;S:OpenNet;;')


if __name__ == '__main__':
    unittest.main()
