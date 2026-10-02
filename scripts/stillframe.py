#!/usr/bin/env python3
"""Style frame: screenshot one local HTML composite (image-gen picture + real type and layers) at video size.

  stillframe.py work/style/frame1.html work/style/frame1.png [--size 1080x1920]
Shown to the user before the build when a style is new or the level is premium (references/style-frame.md).
Playwright's chrome-headless-shell (the full chrome-linux64/chrome hangs in --headless here), no network
(external requests go to a dead proxy), no GPU. ~3 s per frame.
"""
import argparse
import subprocess
import tempfile
from pathlib import Path
from skill_config import RUNTIME, setting

SHELL = Path(setting('MOTION_VIDEO_CHROME', str(RUNTIME / 'chrome/chrome-linux64/chrome'))).expanduser()


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('html', type=Path)
    p.add_argument('out', type=Path)
    p.add_argument('--size', default='1080x1920')
    a = p.parse_args()
    w, h = (int(x) for x in a.size.lower().split('x'))
    a.out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='stillframe-') as profile:
        subprocess.run([str(SHELL), '--headless', '--no-sandbox', '--disable-gpu', '--hide-scrollbars',
                        '--force-device-scale-factor=1', f'--window-size={w},{h}', f'--user-data-dir={profile}',
                        '--proxy-server=http://127.0.0.1:9', '--allow-file-access-from-files',
                        '--virtual-time-budget=3000', f'--screenshot={a.out.resolve()}', a.html.resolve().as_uri()],
                       check=True, capture_output=True, timeout=120)
    print(a.out.resolve())


if __name__ == '__main__':
    main()
