#!/usr/bin/env python3
"""Set OBS recording paths and seed a recording profile on fresh installs."""
import argparse
import configparser
import datetime
import io
from pathlib import Path
import shutil
import subprocess


def configure(home):
    destination = home / 'Videos/OBS'
    destination.mkdir(parents=True, exist_ok=True)
    profiles = home / '.config/obs-studio/basic/profiles'
    existing = sorted(profiles.glob('*/basic.ini'))
    if existing:
        changed = False
        for path in existing:
            settings = configparser.ConfigParser(interpolation=None)
            settings.optionxform = str
            settings.read(path)
            updated = False
            for section, key in (
                ('SimpleOutput', 'FilePath'),
                ('AdvOut', 'RecFilePath'),
                ('AdvOut', 'FFFilePath'),
            ):
                if not settings.has_section(section):
                    settings.add_section(section)
                if settings.get(section, key, fallback=None) != str(destination):
                    settings[section][key] = str(destination)
                    updated = True
            if updated:
                output = io.StringIO()
                settings.write(output, space_around_delimiters=False)
                stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
                shutil.copy2(path, path.with_name('basic.ini.backup-' + stamp))
                path.write_text(output.getvalue())
                changed = True
        print(f'OBS: recording paths set to {destination}; other profile settings preserved.')
        return changed
    profile = profiles / 'Hyprland'
    profile.mkdir(parents=True, exist_ok=True)
    (profile / 'basic.ini').write_text(
        '[General]\nName=Hyprland Recording\n\n'
        '[Output]\nMode=Simple\n\n'
        f'[SimpleOutput]\nFilePath={destination}\nRecQuality=HQ\n'
        'RecEncoder=x264\nRecFormat2=mkv\n\n'
        f'[AdvOut]\nRecFilePath={destination}\nFFFilePath={destination}\n\n'
        '[Video]\nBaseCX=1920\nBaseCY=1080\nOutputCX=1920\nOutputCY=1080\n'
        'FPSType=0\nFPSCommon=30\n\n'
        '[Audio]\nSampleRate=48000\nChannelSetup=Stereo\n')
    user = home / '.config/obs-studio/user.ini'
    settings = configparser.ConfigParser(interpolation=None)
    settings.optionxform = str
    settings.read(user)
    if not settings.has_section('Basic'):
        settings.add_section('Basic')
    settings['Basic']['Profile'] = 'Hyprland Recording'
    settings['Basic']['ProfileDir'] = 'Hyprland'
    output = io.StringIO()
    settings.write(output, space_around_delimiters=False)
    if user.exists():
        stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        shutil.copy2(user, user.with_name('user.ini.backup-' + stamp))
    user.write_text(output.getvalue())
    print(f'OBS: 1080p, 30 FPS, Indistinguishable (x264), MKV, {destination}')
    return True


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--home', type=Path, default=Path.home())
    args = parser.parse_args()
    if subprocess.run(['pgrep', '-x', 'obs'], stdout=subprocess.DEVNULL).returncode == 0:
        print('OBS is running; close it and rerun scripts/setup-obs.py to update recording paths.')
    else:
        configure(args.home)
