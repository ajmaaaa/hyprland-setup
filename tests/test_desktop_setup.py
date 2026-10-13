import configparser
import importlib.util
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


viewers = load('setup-viewers')
obs = load('setup-obs')
places = load('setup-places')
zen = load('setup-zen')


class DesktopSetupTest(unittest.TestCase):
    def test_places_merge_preserves_custom_bookmarks_and_repeated_runs(self):
        gtk = self.home / '.config/gtk-3.0/bookmarks'
        gtk.parent.mkdir(parents=True)
        download_uri = (self.home / 'Downloads').as_uri()
        gtk.write_text(f'file:///custom Custom\n{download_uri} My downloads\n')
        kde = self.home / '.local/share/user-places.xbel'
        kde.parent.mkdir(parents=True)
        kde.write_text('<xbel><bookmark href="sftp://server/files"><title>Server</title></bookmark>'
            f'<bookmark href="{download_uri}"><title>My downloads</title><info>'
            '<metadata owner="http://www.kde.org"><isHidden>true</isHidden>'
            '<OnlyInApp>other-app</OnlyInApp></metadata></info></bookmark></xbel>')
        places.configure(self.home)
        root = ET.parse(kde).getroot()
        self.assertEqual(root.find('bookmark/title').text, 'Server')
        downloads = next(b for b in root.findall('bookmark') if b.get('href') == download_uri)
        self.assertEqual(downloads.find('title').text, 'My downloads')
        self.assertEqual(downloads.find('info/metadata/isHidden').text, 'false')
        self.assertIsNone(downloads.find('info/metadata/OnlyInApp'))
        for name, _ in places.FOLDERS:
            folder = self.home / name
            self.assertTrue(folder.is_dir())
            self.assertEqual(len([b for b in root.findall('bookmark') if b.get('href') == folder.as_uri()]), 1)
            for version in ('gtk-3.0', 'gtk-4.0'):
                lines = (self.home / '.config' / version / 'bookmarks').read_text().splitlines()
                self.assertEqual(sum(line.split(' ', 1)[0] == folder.as_uri() for line in lines), 1)
        self.assertTrue(gtk.read_text().startswith('file:///custom Custom\n'))
        paths = [gtk, kde, self.home / '.config/gtk-4.0/bookmarks']
        before = {path: path.read_bytes() for path in paths}
        places.configure(self.home)
        for path in paths:
            self.assertEqual(path.read_bytes(), before[path])
        self.assertEqual(len(list(gtk.parent.glob('bookmarks.backup-*'))), 1)
        self.assertEqual(len(list(kde.parent.glob('user-places.xbel.backup-*'))), 1)

    def test_zen_default_is_false_and_preserves_other_browser_settings(self):
        with tempfile.TemporaryDirectory() as folder:
            installation = Path(folder)
            (installation / 'application.ini').write_text('[App]\nName=Zen\n')
            directory = installation / 'defaults/pref'
            directory.mkdir(parents=True)
            original = directory / 'channel-prefs.js'
            original.write_text('pref("app.update.channel", "release");\n')
            target = zen.configure(installation)
            self.assertEqual(target.read_text(), 'pref("zen.window-sync.enabled", false);\n')
            self.assertIn('release', original.read_text())
            zen.configure(installation)
            self.assertEqual(list(directory.glob('*.backup-*')), [])

    def test_zen_default_is_skipped_when_browser_is_not_installed(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertIsNone(zen.configure(Path(folder)))
            self.assertEqual(list(Path(folder).iterdir()), [])

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
        self.assertFalse(obs.configure(self.home))
        self.assertEqual(list(profile.parent.glob('*.backup-*')), [])

    def test_obs_existing_profiles_update_paths_preserve_settings_and_backup(self):
        original = ('[General]\nName=My custom profile\n'
            '[Output]\nMode=Advanced\nFilenameFormatting=%CCYY-%MM-%DD\n'
            '[SimpleOutput]\nFilePath=/old/simple\nRecQuality=Small\n'
            '[AdvOut]\nRecFilePath=/old/advanced\nFFFilePath=/old/ffmpeg\n'
            'RecEncoder=obs_x264\nRecFormat2=hybrid_mp4\n'
            '[Video]\nFPSCommon=60\n')
        profiles = self.home / '.config/obs-studio/basic/profiles'
        for name in ('Untitled', 'Streaming'):
            folder = profiles / name
            folder.mkdir(parents=True)
            (folder / 'basic.ini').write_text(original)
        user = profiles.parents[1] / 'user.ini'
        user.write_text('[Basic]\nProfileDir=Untitled\n')
        self.assertTrue(obs.configure(self.home))
        for path in profiles.glob('*/basic.ini'):
            p = viewers.read_ini(path)
            for section, key in (('SimpleOutput', 'FilePath'),
                    ('AdvOut', 'RecFilePath'), ('AdvOut', 'FFFilePath')):
                self.assertEqual(p[section][key], str(self.home / 'Videos/OBS'))
            expected = configparser.ConfigParser(interpolation=None)
            expected.optionxform = str
            expected.read_string(original)
            for section, key in (('SimpleOutput', 'FilePath'),
                    ('AdvOut', 'RecFilePath'), ('AdvOut', 'FFFilePath')):
                expected[section][key] = str(self.home / 'Videos/OBS')
            self.assertEqual(dict(p), dict(expected))
            backups = list(path.parent.glob('basic.ini.backup-*'))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_text(), original)
        self.assertEqual(user.read_text(), '[Basic]\nProfileDir=Untitled\n')
        before = {path: path.read_bytes() for path in profiles.glob('*/basic.ini')}
        self.assertFalse(obs.configure(self.home))
        for path, content in before.items():
            self.assertEqual(path.read_bytes(), content)
            self.assertEqual(len(list(path.parent.glob('basic.ini.backup-*'))), 1)


if __name__ == '__main__':
    unittest.main()
