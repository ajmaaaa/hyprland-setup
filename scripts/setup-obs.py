#!/usr/bin/env python3
"""Seed a recording profile on fresh OBS installs; preserve existing profiles."""
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
    if any(profiles.glob('*/basic.ini')):
        print('OBS already has a profile; kept existing recording settings.')
        return False
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
        print('OBS is running; close it and rerun scripts/setup-obs.py to seed a fresh profile.')
    else:
        configure(args.home)
