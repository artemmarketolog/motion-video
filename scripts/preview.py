#!/usr/bin/env python3
"""Лист превью до рендера: кадры композиции по таймкодам одним JPG с подписью секунд.

Обязательный шаг перед первым рендером (и перед перерендером после крупных правок): лист уходит
пользователю вместе с таблицей «с | что в кадре», рендер только после его «ок».

  preview.py /ABS/VIDEO --at 0,2,4.0,9.35 --name v1
  preview.py /ABS/VIDEO --words "Слышишь,Бам,скидка,крути" --offset 0.15 --at 0 --name v1
      слово#2 — второе вхождение (повторные слова иначе цепляются за первое), время = слово + offset

Снимки делает `hf.py snapshot` (до рендера, по index.html), лист — qa/preview-NAME.jpg.
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
FONT = HERE.parent / 'assets' / 'fonts' / 'Onest-Bold.ttf'


def word_times(video: Path, spec: str, offset: float) -> list[float]:
    data = json.loads((video / 'work' / 'voice.words.json').read_text())
    words = data['words'] if isinstance(data, dict) else data
    norm = lambda s: re.sub(r'[^\wё]', '', s.lower())
    out = []
    for item in [x.strip() for x in spec.split(',') if x.strip()]:
        name, _, nth = item.partition('#')
        hits = [w for w in words if norm(w.get('word', w.get('text', ''))) == norm(name)]
        n = int(nth or 1)
        if len(hits) < n:
            raise SystemExit(f'слово «{item}» не найдено в voice.words.json')
        out.append(round(float(hits[n - 1]['start']) + offset, 2))
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('video')
    p.add_argument('--at', default='', help='таймкоды в секундах через запятую')
    p.add_argument('--words', default='', help='слова голоса через запятую, слово#N для N-го вхождения')
    p.add_argument('--offset', type=float, default=0.0, help='старт голоса в ролике, с (для --words)')
    p.add_argument('--name', default='v1')
    p.add_argument('--cols', type=int, default=6)
    a = p.parse_args()

    video = Path(a.video).resolve()
    times = [float(x) for x in a.at.split(',') if x.strip()]
    if a.words:
        times += word_times(video, a.words, a.offset)
    times = sorted(set(round(t, 2) for t in times))
    if not times:
        raise SystemExit('нужны --at или --words')

    snap = f'qa/preview-{a.name}-snap'
    cmd = [sys.executable, str(HERE / 'hf.py'), str(video), 'snapshot', '--at', ','.join(f'{t:g}' for t in times),
           '--no-end', '--describe', 'false', '-o', snap]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL)

    files = sorted((video / snap).glob('frame-*-at-*s.png'), key=lambda f: int(f.name.split('-')[1]))
    if len(files) != len(times):
        raise SystemExit(f'снимков {len(files)}, ожидалось {len(times)}: {video / snap}')

    first = Image.open(files[0])
    w = 300
    h = round(w * first.height / first.width)
    cols = min(a.cols, len(files))
    rows = -(-len(files) // cols)
    sheet = Image.new('RGB', (cols * (w + 8) + 8, rows * (h + 8) + 8), (20, 20, 20))
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.truetype(str(FONT), 26)
    for i, (f, t) in enumerate(zip(files, times)):
        x, y = 8 + (i % cols) * (w + 8), 8 + (i // cols) * (h + 8)
        sheet.paste(Image.open(f).convert('RGB').resize((w, h)), (x, y))
        draw.rectangle([x, y + h - 34, x + 96, y + h], fill=(0, 0, 0))
        draw.text((x + 6, y + h - 32), f'{t:.2f}', fill=(255, 255, 255), font=font)
    out = video / 'qa' / f'preview-{a.name}.jpg'
    sheet.save(out, quality=88)
    print(json.dumps({'image': str(out), 'times_s': times, 'snapshots': str(video / snap)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
