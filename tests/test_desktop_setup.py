import configparser
import importlib.util
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


viewers = load('setup-viewers')
obs = load('setup-obs')


class DesktopSetupTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name) / 'another user'
        self.apps = Path(self.temp.name) / 'applications'
        self.apps.mkdir()
        (self.home / '.config').mkdir(parents=True)

    def app(self, name, types=''):
        (self.apps / name).write_text('[Desktop Entry]\nType=Application\nName=Example\n'
            'Exec=example %F\nMimeType=' + types + '\n')

    def test_merge_and_repeat_preserve_unrelated_defaults(self):
        for name, types in {
            'org.gnome.Papers.desktop': 'application/pdf;application/epub+zip;',
            'org.gnome.Loupe.desktop': 'image/png;image/jpeg;',
            'mpv.desktop': 'video/mp4;audio/mpeg;application/ogg;x-scheme-handler/http;',
            'antigravity-ide.desktop': 'application/x-antigravity-ide-workspace;',
            'nvim.desktop': 'text/plain;', 'Alacritty.desktop': '',
        }.items():
            self.app(name, types)
        path = self.home / '.config/mimeapps.list'
        path.write_text('[Default Applications]\napplication/zip=archive.desktop;\n'
            'x-scheme-handler/https=browser.desktop;\n'
            '[Added Associations]\ntext/plain=other.desktop;\n'
            '[Removed Associations]\ntext/plain=nvim.desktop;blocked.desktop;\n')
        specific = self.home / '.config/hyprland-mimeapps.list'
        specific.write_text('[Default Applications]\nimage/png=browser.desktop;\n')
        expected = viewers.configure(self.home, self.apps, False)
        p = viewers.read_ini(path)
        self.assertEqual(p['Default Applications']['application/zip'], 'archive.desktop;')
        self.assertEqual(p['Default Applications']['x-scheme-handler/https'], 'browser.desktop;')
        self.assertEqual(p['Default Applications']['text/plain'], 'antigravity-ide.desktop;')
        self.assertEqual(p['Added Associations']['text/plain'], 'antigravity-ide.desktop;nvim.desktop;other.desktop;')
        self.assertEqual(p['Removed Associations']['text/plain'], 'blocked.desktop;')
        self.assertEqual(expected['application/pdf'], 'org.gnome.Papers.desktop')
        self.assertEqual(expected['image/png'], 'org.gnome.Loupe.desktop')
        self.assertEqual(expected['audio/mpeg'], 'mpv.desktop')
        self.assertNotIn('application/epub+zip', expected)
        self.assertNotIn('x-scheme-handler/http', expected)
        self.assertEqual(viewers.read_ini(specific)['Default Applications']['image/png'], 'org.gnome.Loupe.desktop;')
        before = path.read_bytes()
        viewers.configure(self.home, self.apps, False)
        self.assertEqual(before, path.read_bytes())
        generated = viewers.read_ini(self.home / '.local/share/applications/antigravity-ide.desktop')
        self.assertEqual(generated['Desktop Entry']['Exec'], 'example %F')

    def test_missing_viewers_do_not_claim_files(self):
        path = self.home / '.config/mimeapps.list'
        path.write_text('[Default Applications]\napplication/pdf=existing.desktop;\ntext/plain=existing.desktop;\n')
        self.app('nvim.desktop')
        self.app('Alacritty.desktop')
        self.assertEqual(viewers.configure(self.home, self.apps, False), {})
        p = viewers.read_ini(path)
        self.assertEqual(p['Default Applications']['application/pdf'], 'existing.desktop;')
        self.assertEqual(p['Default Applications']['text/plain'], 'existing.desktop;')
        self.assertEqual(p['Added Associations']['text/plain'], 'nvim.desktop;')

    def test_obs_fresh_install_and_existing_profile(self):
        self.assertTrue(obs.configure(self.home))
        profile = self.home / '.config/obs-studio/basic/profiles/Hyprland/basic.ini'
        p = viewers.read_ini(profile)
        self.assertEqual(p['SimpleOutput']['FilePath'], str(self.home / 'Videos/OBS'))
        self.assertEqual(p['SimpleOutput']['RecQuality'], 'HQ')
        self.assertEqual(p['Video']['FPSCommon'], '30')
        profile.write_text('[General]\nName=My custom profile\n')
        self.assertFalse(obs.configure(self.home))
        self.assertEqual(profile.read_text(), '[General]\nName=My custom profile\n')


if __name__ == '__main__':
    unittest.main()
