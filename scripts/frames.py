#!/usr/bin/env python3
"""One contact sheet of exact frames: at given times, at event times, or ±1 frame around them.

  frames.py output/master-r2.mp4 --at 1.2,4.56,9.3 --out qa/r2-frames.jpg
  frames.py output/master-r2.mp4 --events events.json --around --out qa/r2-events.jpg
Batch visual checks into one image: every attached image re-sends the whole context.
"""
import argparse
import json
import subprocess
from fractions import Fraction
from pathlib import Path

FONT = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('video')
    p.add_argument('--at', default='')
    p.add_argument('--events')
    p.add_argument('--around', action='store_true', help='add the frames before and after each time')
    p.add_argument('--height', type=int, default=480)
    p.add_argument('--out', required=True)
    a = p.parse_args()
    info = json.loads(subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries',
                                      'stream=r_frame_rate,nb_frames', '-of', 'json', a.video],
                                     capture_output=True, text=True, check=True).stdout)['streams'][0]
    fps = float(Fraction(info['r_frame_rate']))
    total = int(info.get('nb_frames') or 10 ** 9)
    times = [float(x) for x in a.at.split(',') if x.strip()]
    if a.events:
        times += [float(e['t']) for e in json.loads(Path(a.events).read_text())['events']]
    frames = set()
    for t in times:
        n = round(t * fps)
        frames.update([n - 1, n, n + 1] if a.around else [n])
    frames = sorted(f for f in frames if 0 <= f < total)
    if not frames:
        raise SystemExit('no frames selected')
    cols = 3 if a.around else min(6, len(frames))
    rows = -(-len(frames) // cols)
    sel = '+'.join(f'eq(n\\,{f})' for f in frames)
    vf = (f"select='{sel}',scale=-2:{a.height},drawtext=fontfile={FONT}:text='%{{n}}':x=6:y=6:fontsize=18:"
          f"fontcolor=white:box=1:boxcolor=black@0.7,tile={cols}x{rows}:padding=4:color=gray")
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', a.video, '-vf', vf, '-frames:v', '1', '-q:v', '3', a.out], check=True)
    print(json.dumps({'image': a.out, 'frames': frames, 'times_s': [round(f / fps, 3) for f in frames],
                      'note': 'Labels are frame numbers of the selected frames in order (n of the filter), times listed here.'}))


if __name__ == '__main__':
    main()
