#!/usr/bin/env python3
"""Do sounds start where the picture events are? Onsets in audio vs events.json times.

  audiocheck.py output/master-r2.mp4 --events events.json [--tolerance-ms 20]
  audiocheck.py work/sfx.wav --events events.json
Measures only transient timing (above 800 Hz) and loudness/true peak of the file.
It does not judge taste, balance or pronunciation: say "not listened" if nobody listened.
"""
import argparse
import json
import re
import subprocess
from pathlib import Path

import numpy as np

SR = 48000
# Presets with a deliberate swell: their 30 %-of-peak point lands later than the event by design.
SWELL = {'whoosh', 'swipe', 'riser', 'shimmer', 'cloth', 'air', 'paper'}


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('media')
    p.add_argument('--events', required=True)
    p.add_argument('--tolerance-ms', type=float, default=20)
    a = p.parse_args()
    raw = subprocess.run(['ffmpeg', '-v', 'error', '-i', a.media, '-map', '0:a:0', '-af', 'highpass=f=800,highpass=f=800',
                          '-ac', '1', '-ar', str(SR), '-f', 'f32le', '-'], capture_output=True, check=True).stdout
    x = np.abs(np.frombuffer(raw, np.float32))
    k = int(.001 * SR)
    env = np.convolve(x, np.ones(k) / k, 'same')
    rows = []
    for ev in json.loads(Path(a.events).read_text())['events']:
        t = float(ev['t']) - float(ev.get('lead', 0)) * 0
        i0, i1 = int((t - .05) * SR), int((t + .08) * SR)
        if i0 < 0 or i1 > len(env):
            continue
        w = env[i0:i1]
        floor = np.median(env[max(0, i0 - int(.1 * SR)):i0]) if i0 > 0 else 0
        peak = w.max()
        if peak < 3 * (floor + 1e-6):
            rows.append({'t': t, 'sfx': ev.get('sfx'), 'onset_ms': None, 'status': 'not_detected'})
            continue
        onset = (i0 + int(np.argmax(w >= floor + .3 * (peak - floor)))) / SR
        dev = (onset - t) * 1000
        rows.append({'t': t, 'sfx': ev.get('sfx'), 'onset_ms': round(dev, 1),
                     'status': 'ok' if abs(dev) <= (a.tolerance_ms * 4 if ev.get('sfx') in SWELL else a.tolerance_ms) else 'off'})
    stats = subprocess.run(['ffmpeg', '-hide_banner', '-nostdin', '-i', a.media, '-map', '0:a:0', '-af', 'ebur128=peak=true',
                            '-f', 'null', '-'], capture_output=True, text=True).stderr
    lufs = re.findall(r'I:\s+([-\d.]+) LUFS', stats)
    peak = re.findall(r'Peak:\s+([-\d.]+) dBFS', stats)
    devs = [abs(r['onset_ms']) for r in rows if r['onset_ms'] is not None]
    print(json.dumps({'events': len(rows), 'ok': sum(r['status'] == 'ok' for r in rows),
                      'off': [r for r in rows if r['status'] != 'ok'],
                      'median_abs_ms': round(float(np.median(devs)), 1) if devs else None,
                      'max_abs_ms': round(max(devs), 1) if devs else None,
                      'integrated_lufs': float(lufs[-1]) if lufs else None, 'true_peak_dbfs': float(peak[-1]) if peak else None,
                      'listened': False}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
