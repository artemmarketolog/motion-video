#!/usr/bin/env python3
"""Synthetic demo material for the footage-ad template: try the whole pipeline offline, with no shots and no keys.

  demo_assets.py /ABS/VIDEO        # a folder made by new_project.py --template footage-ad

Writes shots/demo-01..06.mp4 (colour clips with a moving label), work/demo-voice.wav (quiet tone in the rhythm
of the words) and work/demo-voice.words.json, then points creative.json at them (voice = existing take,
no music). Replace all of it with real shots and a real voice for an actual video.
"""
import json
import subprocess
import sys
from pathlib import Path

FONT = Path(__file__).resolve().parents[2] / 'assets/fonts/Onest-Bold.ttf'
COLORS = ['0x2b2d42', '0x8d5524', '0x355070', '0x6d597a', '0x3a5a40', '0xb56576']
LABELS = ['утро', 'кофе', 'зёрна', 'друзья', 'капучино', 'заходите']
SCRIPT = ('Утро начинается с кофе. Мы обжариваем зёрна каждую неделю. Приходите с друзьями. '
          'Второй капучино в подарок до одиннадцати. Заходите в Эйкми Кофи.')


def clip(path, color, label, seconds=4):
    text = f"drawtext=fontfile={FONT}:text='{label}':fontcolor=white:fontsize=120:x=(w-tw)/2:y=h/2-th/2+60*sin(t)"
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', f'color=c={color}:s=1080x1920:r=30:d={seconds}',
                    '-vf', f'noise=alls=14:allf=t+u,vignette,{text},format=yuv420p',
                    '-c:v', 'libx264', '-crf', '23', '-preset', 'veryfast', '-an', str(path)],
                   check=True, stdin=subprocess.DEVNULL)


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    d = Path(sys.argv[1]).resolve()
    cfg_path = d / 'creative.json'
    if not cfg_path.is_file():
        sys.exit('creative.json not found: create the folder with new_project.py --template footage-ad')
    (d / 'shots').mkdir(exist_ok=True)
    (d / 'work').mkdir(exist_ok=True)
    for i, (color, label) in enumerate(zip(COLORS, LABELS), 1):
        out = d / 'shots' / f'demo-{i:02d}.mp4'
        if not out.exists():
            clip(out, color, label)
    words, t = [], 0.3
    for w in SCRIPT.split():
        dur = 0.12 + 0.055 * len(w)
        words.append({'word': w, 'start': round(t, 3), 'end': round(t + dur, 3)})
        t += dur + (0.32 if w[-1] in '.!?' else 0.06)
    (d / 'work/demo-voice.words.json').write_text(json.dumps(words, ensure_ascii=False, indent=1))
    beeps = '+'.join(f"between(t,{x['start']},{x['end']})*0.05*sin(2*PI*220*t)" for x in words)
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', f"aevalsrc='{beeps}':s=48000:d={t + 0.3:.2f}",
                    '-ac', '1', str(d / 'work/demo-voice.wav')], check=True, stdin=subprocess.DEVNULL)
    cfg = json.loads(cfg_path.read_text())
    cfg.update({'title': 'Демо: синтетические кадры и голос-заглушка', 'shots_dir': str(d / 'shots'),
                'edl': [{'shot': f'demo-{i:02d}.mp4'} for i in range(1, 7)],
                'voice': {'mp3': str(d / 'work/demo-voice.wav'), 'words': str(d / 'work/demo-voice.words.json'),
                          'tempo': 1.0, 'start': 0.0}})
    cfg.pop('music', None)
    cfg.pop('client', None)
    for ins in cfg.get('inserts', []):
        if ins.get('at_word') and not any(w['word'].strip('.,!?').lower() == ins['at_word'].lower() for w in words):
            ins.pop('at_word'); ins.pop('nth', None); ins['at'] = 2.0
    cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=1) + '\n')
    print(json.dumps({'shots': 6, 'voice_s': round(t, 2), 'creative': str(cfg_path)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
