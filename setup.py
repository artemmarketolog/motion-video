#!/usr/bin/env python3
"""Install motion-video: Python venv, pinned HyperFrames runtime, Chrome for Testing, private config and studio folder.

  python3 setup.py                # everything (network: PyPI, npm registry, Chrome for Testing download)
  python3 setup.py --with-drive   # plus Google Drive libraries for scripts/footage/*_gdrive.py
  python3 setup.py --check        # only report what is installed; changes nothing

Rendering needs Linux (or WSL2) with ffmpeg, ffprobe, Node.js 22+, npm and bubblewrap (bwrap).
Never reads, prints or sends API keys. No paid request is made.
"""
import argparse
import os
import platform
import shutil
import stat
import subprocess
import sys
import urllib.request
import venv
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
NAME = 'motion-video'
CONFIG_HOME = Path((os.getenv('XDG_CONFIG_HOME') or Path.home() / '.config')).expanduser()
DATA_HOME = Path((os.getenv('XDG_DATA_HOME') or Path.home() / '.local/share')).expanduser()
CONFIG = CONFIG_HOME / 'media-skills' / f'{NAME}.env'
CHROME_VERSION = '149.0.7827.55'   # the version every render test of this skill passed on
CHROME_URL = f'https://storage.googleapis.com/chrome-for-testing-public/{CHROME_VERSION}/linux64/chrome-linux64.zip'
NODE_MAJOR = 22


def env_value(name, default):
    if os.getenv(name):
        return os.environ[name]
    if CONFIG.is_file():
        for line in CONFIG.read_text().splitlines():
            if line.startswith(name + '=') and line.split('=', 1)[1].strip():
                return line.split('=', 1)[1].strip().strip('"\'')
    return default


def runtime_dir():
    return Path(env_value('MOTION_VIDEO_RUNTIME', str(DATA_HOME / 'motion-video/runtime'))).expanduser()


def studio_dir():
    return Path(env_value('MOTION_VIDEO_STUDIO', str(Path.home() / 'video-studio'))).expanduser()


def chrome_path():
    return Path(env_value('MOTION_VIDEO_CHROME', str(runtime_dir() / 'chrome/chrome-linux64/chrome'))).expanduser()


def node_major():
    node = shutil.which('node')
    if not node:
        return None
    out = subprocess.run([node, '--version'], capture_output=True, text=True).stdout.strip().lstrip('v')
    return int(out.split('.')[0]) if out[:1].isdigit() else None


def report():
    py = ROOT / '.venv/bin/python'
    rt = runtime_dir()
    rows = [
        ('python venv', 'ok' if py.is_file() else 'missing → python3 setup.py'),
        ('node', f'v{node_major()}' if node_major() else 'missing (Node.js 22+ required)'),
        ('npm', shutil.which('npm') or 'missing'),
        ('ffmpeg', shutil.which('ffmpeg') or 'missing'),
        ('ffprobe', shutil.which('ffprobe') or 'missing'),
        ('bwrap', shutil.which('bwrap') or 'missing (apt install bubblewrap) — render refuses to run unsandboxed'),
        ('runtime', 'ok' if (rt / 'node_modules/hyperframes/package.json').is_file() else f'missing in {rt}'),
        ('chrome', 'ok' if chrome_path().is_file() else f'missing: {chrome_path()}'),
        ('upstream library', 'ok' if (ROOT / 'references/upstream/hyperframes/SKILL.md').is_file() else 'missing'),
        ('elevenlabs-voice', 'ok' if (ROOT.parent / 'elevenlabs-voice/scripts/eleven.py').is_file() or os.getenv('ELEVENLABS_VOICE_SKILL') else 'not next to this folder (needed only for voice)'),
        ('image-gen', 'ok' if (ROOT.parent / 'image-gen/generate.py').is_file() else 'not next to this folder (needed only for generated images)'),
        ('config', f'{CONFIG} ' + ('present' if CONFIG.is_file() else 'missing')),
        ('studio', f'{studio_dir()} ' + ('present' if studio_dir().is_dir() else 'missing')),
    ]
    for name, value in rows:
        print(f'{name:17} {value}')


def install_runtime():
    rt = runtime_dir()
    rt.mkdir(parents=True, exist_ok=True)
    for name in ('package.json', 'package-lock.json', 'GSAP-LICENSE.txt'):
        shutil.copyfile(ROOT / 'runtime' / name, rt / name)
    if not (rt / 'node_modules/hyperframes/package.json').is_file():
        if (node_major() or 0) < NODE_MAJOR or not shutil.which('npm'):
            raise SystemExit(f'Node.js {NODE_MAJOR}+ with npm is required for the renderer (https://nodejs.org).')
        print(f'Installing pinned HyperFrames runtime into {rt} (npm ci, install scripts disabled)…')
        subprocess.run(['npm', 'ci', '--ignore-scripts', '--no-fund', '--no-audit'], cwd=rt, check=True)
    chrome = chrome_path()
    if chrome.is_file():
        return
    if platform.system() != 'Linux' or platform.machine() not in ('x86_64', 'AMD64'):
        print('Chrome for Testing auto-download supports Linux x86_64 only; set MOTION_VIDEO_CHROME to a Chrome binary.')
        return
    target = rt / 'chrome'
    archive = rt / 'chrome-linux64.zip'
    print(f'Downloading Chrome for Testing {CHROME_VERSION} (~170 MB)…')
    urllib.request.urlretrieve(CHROME_URL, archive)
    with zipfile.ZipFile(archive) as zf:
        for info in zf.infolist():
            path = Path(zf.extract(info, target))
            mode = info.external_attr >> 16
            if mode:
                path.chmod(stat.S_IMODE(mode))
    archive.unlink()
    print(f'Chrome: {chrome}')


def init_studio():
    studio = studio_dir()
    (studio / 'projects').mkdir(parents=True, exist_ok=True)
    index = studio / 'MAKING-OF-INDEX.md'
    if not index.exists():
        shutil.copyfile(ROOT / 'assets/making-of-index-template.md', index)
    clients = studio / 'clients.json'
    if not clients.exists():
        shutil.copyfile(ROOT / 'assets/clients.example.json', clients)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--check', action='store_true', help='report only, install nothing')
    p.add_argument('--with-drive', action='store_true', help='also install Google Drive client libraries')
    p.add_argument('--skip-runtime', action='store_true', help='Python part only (no npm, no Chrome)')
    a = p.parse_args()
    if sys.version_info < (3, 10):
        raise SystemExit('Python 3.10+ required')
    if a.check:
        report()
        return
    py = ROOT / '.venv/bin/python'
    if not py.is_file():
        venv.EnvBuilder(with_pip=True).create(ROOT / '.venv')
    pip = [str(py), '-m', 'pip', 'install', '--disable-pip-version-check', '-q']
    subprocess.run(pip + ['-r', str(ROOT / 'requirements.txt')], check=True)
    if a.with_drive:
        subprocess.run(pip + ['-r', str(ROOT / 'requirements-drive.txt')], check=True)
    if not a.skip_runtime:
        install_runtime()
    if not CONFIG.exists():
        CONFIG.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        shutil.copyfile(ROOT / '.env.example', CONFIG)
        CONFIG.chmod(0o600)
        print(f'Created {CONFIG} (chmod 600).')
    init_studio()
    print()
    report()
    print(f'\nSmoke test (no paid calls, ~5 min): {py} {ROOT / "scripts/smoke_test.py"} --out /tmp/motion-smoke-1')


if __name__ == '__main__':
    main()
