#!/usr/bin/env python3
"""Template «explainer»: calm animated presentation / explainer, 16:9 (also works 9:16 with LAYOUT).

Change BRAND, SCENES and (optionally) VOICE/MUSIC, then:
  python3 build.py && python3 <motion-video>/scripts/mv.py build $PWD -o output/master-r1.mp4
Each scene has its own local time (start + dt) and is a cache anchor: editing scene 3
re-renders only scene 3, even if its length changes.
Pace: one idea per scene, 4–8 s, entrances 0.4–0.7 s, camera drift 1.00 → 1.03.
"""
import json
import sys
from pathlib import Path

SK = Path(__file__).with_name('.motion-skill').read_text().strip()
sys.path.insert(0, str(Path(SK) / 'scripts'))
from mvlib import FORMATS, Comp, orientation, safe_box  # noqa: E402

HERE = Path(__file__).resolve().parent
LEVEL = 'medium'                      # simple | medium | premium (references/levels.md)
FORMAT = '16:9'                  # 9:16 | 4:5 | 3:4 | 1:1 | 16:9 (new_project.py --format sets it)
FORMATS_OK = ('9:16', '4:5', '3:4', '1:1', '16:9')
W, H = FORMATS[FORMAT]['size']
ORIENT = orientation(W, H)
SAFE = safe_box(FORMAT)                 # left, top, right, bottom
BRAND = {'bg': '#f6f3ee', 'ink': '#1d1b19', 'muted': '#6f6a63', 'accent': '#d8583c', 'panel': '#ffffff',
         'font': 'manrope', 'serif': 'cormorant'}
# One dict per scene. kind: title | points | number | compare. Durations come from the voice when present.
SCENES = [
    {'kind': 'title', 'dur': 5.0, 'eyebrow': 'Как это работает', 'title': 'Одна правка — одна сцена', 'sub': 'остальное берётся из кэша'},
    {'kind': 'points', 'dur': 6.5, 'title': 'Что происходит при правке',
     'points': ['Скрипт находит изменённые кадры', 'Рендерит только их кусок', 'Склеивает без перекодирования']},
    {'kind': 'number', 'dur': 5.5, 'value': '63', 'unit': 'секунды', 'caption': 'правка титра в ролике на 12 секунд'},
    {'kind': 'compare', 'dur': 6.0, 'title': 'Было и стало', 'left': ['Полный рендер', '11 минут'], 'right': ['Только кусок', '1 минута']},
]
VOICE = None      # e.g. {'file': 'work/voice.wav', 'words': 'work/voice.words.json', 'scene_words': [...]} (see references/voice.md)
MUSIC = None      # e.g. {'file': 'work/music.mp3', 'offset': 0.0, 'gain_db': -22}


def main():
    total = round(sum(s['dur'] for s in SCENES), 3)
    c = Comp(W, H, seconds=total, title='Explainer', level=LEVEL, background=BRAND['bg'])
    c.font(BRAND['font'], 400, 600, 700)
    c.font(BRAND['serif'], 600)
    fam = {'manrope': 'Manrope', 'onest': 'Onest', 'montserrat': 'Montserrat'}[BRAND['font']]
    L, T, R, B = SAFE
    wide = ORIENT == 'landscape'
    # Layout from the frame: side-by-side cards only when there is width, stacked otherwise.
    card_w = 700 if wide else (W - 2 * L - 60) // 2 if ORIENT == 'square' else W - 2 * L - 60
    card_h = 420 if ORIENT != 'portrait' else 330
    c.css(f'''
#film {{ background: {BRAND['bg']}; color: {BRAND['ink']}; font-family: {fam}, sans-serif; }}
#cam {{ position: absolute; inset: 0; transform-origin: 50% 50%; }}
.sc {{ position: absolute; inset: 0; opacity: 0; }}
.eyebrow {{ font: 600 34px/1 {fam}; letter-spacing: 6px; text-transform: uppercase; color: {BRAND['accent']}; }}
.h1 {{ font: 700 {104 if wide else 96}px/1.04 {fam}; letter-spacing: -3px; }}
.h2 {{ font: 700 72px/1.08 {fam}; letter-spacing: -2px; }}
.sub {{ font: 400 44px/1.3 {fam}; color: {BRAND['muted']}; }}
.center {{ position: absolute; left: {L + (70 if wide else 20)}px; right: {W - R + (70 if wide else 20)}px; text-align: center; }}
.pt {{ display: flex; align-items: center; gap: 36px; font: 600 54px/1.2 {fam}; margin: 0 0 44px; }}
.dot {{ width: 22px; height: 22px; border-radius: 50%; background: {BRAND['accent']}; flex: none; }}
.big {{ font: 700 300px/1.0 {fam}; letter-spacing: -14px; color: {BRAND['accent']}; }}
.card {{ position: absolute; width: {card_w}px; height: {card_h}px; border-radius: 36px; background: {BRAND['panel']};
  box-shadow: 0 30px 80px rgba(40,30,20,.12); padding: 64px; }}
.card .k {{ font: 600 40px/1.2 {fam}; color: {BRAND['muted']}; }}
.card .v {{ font: 700 {110 if card_w >= 600 else 84}px/1.1 {fam}; letter-spacing: -4px; margin-top: 40px; }}
''')
    html = ['<div id="cam">']
    t = 0.0
    for i, s in enumerate(SCENES):
        st = c.scene(t)
        sid = f's{i}'
        html.append(f'<div class="sc" id="{sid}">' + scene_html(s, sid) + '</div>')
        # Scene container: fade in, hold, fade out. Everything below is scene-local (st + dt).
        c.set0(f'#{sid}', {'opacity': 0, 'scale': 1})  # stable baseline for every seek
        c.fromto(f'#{sid}', {'opacity': 0}, {'opacity': 1, 'duration': .35, 'ease': 'power1.out'}, st, later=True)
        c.fromto(f'#{sid}', {'opacity': 1}, {'opacity': 0, 'duration': .35, 'ease': 'power1.in'}, st + s['dur'] - .35, later=True)
        animate(c, s, sid, st)
        c.sfx(st + .25, 'cloth', gain_db=-14)
        t += s['dur']
    html.append('</div>')
    c.html('\n'.join(html))
    # Slow camera breathing inside each scene (scene-local, so scenes stay independent for the cache).
    t = 0.0
    for i, s in enumerate(SCENES):
        c.fromto(f'#s{i}', {'scale': 1.0}, {'scale': 1.03, 'duration': s['dur'], 'ease': 'sine.inOut'}, t, later=True)
        t += s['dur']
    # No global progress bar: a value that depends on the total length changes every frame
    # of every scene after any timing edit and defeats the cache (references/cache-and-edits.md).
    c.grain()
    tracks = [{'file': 'work/sfx.wav', 'role': 'sfx'}]
    if VOICE:
        tracks.append({'file': VOICE['file'], 'role': 'voice', 'start': VOICE.get('start', 0.3)})
    if MUSIC:
        tracks.append({'file': MUSIC['file'], 'role': 'music', 'offset': MUSIC.get('offset', 0), 'gain_db': MUSIC.get('gain_db', -22),
                       'fade_in': 1.0, 'fade_out': 1.5, 'carve': .25})
    (HERE / 'work').mkdir(exist_ok=True)
    result = c.write(HERE, mix={'tracks': tracks, 'loudness': {'I': -16, 'TP': -1.5, 'LRA': 11}})
    import subprocess
    subprocess.run([sys.executable, str(Path(SK) / 'scripts/sfx.py'), 'render',
                    str(HERE / 'events.json'), str(HERE / 'work/sfx.wav')], check=True, capture_output=True)
    print(json.dumps(result, ensure_ascii=False))


def scene_html(s, sid):
    k = s['kind']
    if k == 'title':
        return (f'<div class="center" style="top:{H * .3:.0f}px"><div class="eyebrow" id="{sid}e">{s["eyebrow"]}</div>'
                f'<div class="h1" id="{sid}t" style="margin-top:44px">{s["title"]}</div>'
                f'<div class="sub" id="{sid}s" style="margin-top:40px">{s["sub"]}</div></div>')
    if k == 'points':
        pts = ''.join(f'<div class="pt" id="{sid}p{j}"><span class="dot"></span>{p}</div>' for j, p in enumerate(s['points']))
        L, T, R, B = SAFE
        left = L + (130 if ORIENT == 'landscape' else 30)
        return (f'<div style="position:absolute;left:{left}px;right:{W - R + 30}px;top:{max(T, H * .17):.0f}px">'
                f'<div class="h2" id="{sid}t">{s["title"]}</div><div style="margin-top:90px">{pts}</div></div>')
    if k == 'number':
        return (f'<div class="center" style="top:{H * .14:.0f}px"><div class="big" id="{sid}n">{s["value"]}</div>'
                f'<div class="h2" id="{sid}u" style="margin-top:70px">{s["unit"]}</div>'
                f'<div class="sub" id="{sid}c" style="margin-top:30px">{s["caption"]}</div></div>')
    if k == 'compare':
        L, T, R, B = SAFE
        if ORIENT == 'portrait':        # stacked
            top1, top2 = H * .30, H * .30 + 390
            lpos = rpos = f'left:{L + 30}px'
        else:                           # side by side
            top1 = top2 = H * .33
            lpos, rpos = f'left:{L + (130 if ORIENT == "landscape" else 20)}px', f'right:{W - R + (130 if ORIENT == "landscape" else 20)}px'
        return (f'<div class="center" style="top:{max(T, H * .14):.0f}px"><div class="h2" id="{sid}t">{s["title"]}</div></div>'
                f'<div class="card" id="{sid}l" style="{lpos};top:{top1:.0f}px"><div class="k">{s["left"][0]}</div><div class="v">{s["left"][1]}</div></div>'
                f'<div class="card" id="{sid}r" style="{rpos};top:{top2:.0f}px"><div class="k">{s["right"][0]}</div><div class="v" style="color:{BRAND["accent"]}">{s["right"][1]}</div></div>')
    raise ValueError(k)


def animate(c, s, sid, st):
    k = s['kind']
    if k == 'title':
        c.enter(f'#{sid}e', st + .3)
        c.enter(f'#{sid}t', st + .55)
        c.enter(f'#{sid}s', st + 1.2)
    elif k == 'points':
        c.enter(f'#{sid}t', st + .3)
        for j, _ in enumerate(s['points']):
            c.enter(f'#{sid}p{j}', st + 1.0 + j * .9)
            c.sfx(st + 1.0 + j * .9, 'tick', gain_db=-18)
    elif k == 'number':
        c.enter(f'#{sid}n', st + .3, scale=1)
        c.enter(f'#{sid}u', st + .8)
        c.enter(f'#{sid}c', st + 1.4)
        c.sfx(st + .3, 'soft_hit', gain_db=-10)
    elif k == 'compare':
        c.enter(f'#{sid}t', st + .3)
        c.fromto(f'#{sid}l', {'opacity': 0, 'x': -40}, {'opacity': 1, 'x': 0, 'duration': .6, 'ease': 'power3.out'}, st + .9)
        c.fromto(f'#{sid}r', {'opacity': 0, 'x': 40}, {'opacity': 1, 'x': 0, 'duration': .6, 'ease': 'power3.out'}, st + 1.7)
        c.sfx(st + 1.7, 'soft_hit', gain_db=-12)


if __name__ == '__main__':
    main()
