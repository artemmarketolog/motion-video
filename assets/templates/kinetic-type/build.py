#!/usr/bin/env python3
"""Template «kinetic-type»: short phrases cut on the beat, 9:16 (kinetic typography: one voiced word = one word on screen).

Change BRAND, BPM/FIRST_BEAT (from `music.py analyze`), CARDS, then:
  python3 build.py && python3 <motion-video>/scripts/mv.py build $PWD -o output/master-r1.mp4
Grammar: every card is a hard cut on a beat; each card has ONE entrance style (slam, side-snap,
rise, mask-up) and holds with a slow drift so nothing freezes. One accent colour, one hero card.
Every cut is a cache anchor: editing card 4 re-renders only card 4.
"""
import json
import subprocess
import sys
from pathlib import Path

SK = Path(__file__).with_name('.motion-skill').read_text().strip()
sys.path.insert(0, str(Path(SK) / 'scripts'))
from mvlib import FORMATS, Comp, orientation, safe_box  # noqa: E402

HERE = Path(__file__).resolve().parent
LEVEL = 'medium'
FORMAT = '9:16'                  # 9:16 | 4:5 | 3:4 | 1:1 | 16:9 (new_project.py --format sets it)
FORMATS_OK = ('9:16', '4:5', '3:4', '1:1', '16:9')
W, H = FORMATS[FORMAT]['size']
ORIENT = orientation(W, H)
SAFE = safe_box(FORMAT)                 # left, top, right, bottom
BRAND = {'bg': '#0e0a0c', 'ink': '#f6efe9', 'accent': '#e8b86b', 'font': 'onest', 'serif': 'cormorant'}
BPM, FIRST_BEAT = 120.0, 0.25          # from music.py analyze; without music the cards still cut on this grid
# (beats to hold, text, style, hero). style: slam | side | rise | mask ; hero=True gets the accent + sub hit.
CARDS = [
    (2, 'Погоди', 'slam', False),
    (2, 'не листай', 'side', False),
    (4, 'это займёт', 'rise', False),
    (2, 'три секунды', 'mask', True),
    (4, 'а скидка останется', 'rise', False),
    (4, 'YOUR BRAND', 'mask', False),
]
MUSIC = None   # {'file': 'work/music.mp3', 'offset': 0.0, 'gain_db': -8}


def main():
    beat = 60.0 / BPM
    starts, t = [], FIRST_BEAT
    for n, *_ in CARDS:
        starts.append(round(round(t * 30) / 30, 4))   # cuts land on whole frames
        t += n * beat
    seconds = round(t + .6, 3)
    c = Comp(W, H, seconds=seconds, title='Kinetic type', level=LEVEL, background=BRAND['bg'])
    c.font(BRAND['font'], 600, 700)
    c.font(BRAND['serif'], 700)
    c.css(f'''
#film {{ background: {BRAND['bg']}; color: {BRAND['ink']}; }}
.card {{ position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; opacity: 0; }}
.w {{ font: 700 150px/1.02 Onest; letter-spacing: -5px; text-align: center; padding: 0 80px; }}
.w.hero {{ color: {BRAND['accent']}; font: 700 190px/1 Cormorant; letter-spacing: -2px; }}
.mask {{ overflow: hidden; padding: 20px 0; }}
.line {{ position: absolute; left: 90px; right: 90px; top: {H * .615:.0f}px; height: 3px; background: {BRAND['accent']}; transform-origin: 0 50%; }}
''')
    html = []
    for i, (n, text, style, hero) in enumerate(CARDS):
        inner = f'<div class="w{" hero" if hero else ""}" id="w{i}">{text}</div>'
        html.append(f'<div class="card" id="c{i}">' + (f'<div class="mask">{inner}</div>' if style == 'mask' else inner) + '</div>')
    html.append('<div class="line" id="line"></div>')
    c.html('\n'.join(html))
    ends = starts[1:] + [seconds]
    for i, ((n, text, style, hero), st, en) in enumerate(zip(CARDS, starts, ends)):
        c.scene(st)
        w = f'#w{i}'
        c.set0(f'#c{i}', {'opacity': 0})
        c.fromto(f'#c{i}', {'opacity': 0}, {'opacity': 1, 'duration': .01}, st, later=True)     # hard cut in
        if i < len(CARDS) - 1:
            c.fromto(f'#c{i}', {'opacity': 1}, {'opacity': 0, 'duration': .01}, en - .01, later=True)  # hard cut out
        if style == 'slam':
            c.fromto(w, {'scale': 1.35, 'filter': 'blur(8px)'}, {'scale': 1, 'filter': 'blur(0px)', 'duration': .28, 'ease': 'expo.out'}, st)
            c.sfx(st, 'hit', gain_db=-6, pitch=1.2, dur=.5)
        elif style == 'side':
            c.fromto(w, {'x': 220, 'opacity': 0}, {'x': 0, 'opacity': 1, 'duration': .3, 'ease': 'expo.out'}, st)
            c.sfx(st, 'swipe', gain_db=-8, pan=.3)
        elif style == 'rise':
            c.fromto(w, {'y': 90, 'opacity': 0}, {'y': 0, 'opacity': 1, 'duration': .4, 'ease': 'power3.out'}, st)
            c.sfx(st, 'whoosh', gain_db=-12, dur=.45)
        else:  # mask
            c.fromto(w, {'yPercent': 110}, {'yPercent': 0, 'duration': .45, 'ease': 'power3.out'}, st)
            c.sfx(st, 'tick', gain_db=-10)
        # hold drift: nothing freezes (references/direction.md, rule "nothing fully stops")
        c.fromto(f'#c{i}', {'scale': 1}, {'scale': 1.04, 'duration': round(en - st, 3), 'ease': 'none'}, st, later=True)
        if hero:
            c.sfx(st, 'sub', gain_db=-4)
            c.fromto('#line', {'scaleX': 0, 'opacity': 1}, {'scaleX': 1, 'duration': round(en - st - .1, 3), 'ease': 'power2.inOut'}, st, later=True)
            c.fromto('#line', {'opacity': 1}, {'opacity': 0, 'duration': .01}, en - .01, later=True)
    c.set0('#line', {'scaleX': 0, 'opacity': 0})
    c.grain()
    (HERE / 'work').mkdir(exist_ok=True)
    tracks = [{'file': 'work/sfx.wav', 'role': 'sfx'}]
    if MUSIC:
        tracks.append({'file': MUSIC['file'], 'role': 'music', 'offset': MUSIC['offset'], 'gain_db': MUSIC['gain_db'], 'fade_out': .6})
    result = c.write(HERE, mix={'tracks': tracks})
    subprocess.run([sys.executable, str(Path(SK) / 'scripts/sfx.py'), 'render',
                    str(HERE / 'events.json'), str(HERE / 'work/sfx.wav')], check=True, capture_output=True)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
