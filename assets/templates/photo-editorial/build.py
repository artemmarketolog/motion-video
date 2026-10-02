#!/usr/bin/env python3
"""Template «photo-editorial»: photos (real or generated) in natural colour + editorial type, 9:16.

Put photos into assets/photos/ (image-gen for generated plates), list them in SHOTS, then:
  python3 build.py && python3 <motion-video>/scripts/mv.py build $PWD -o output/master-r1.mp4
Grammar: one photo per shot, slow push or pan (3–6 %), a clean frame-to-frame move
(soft crossfade, light leak or wipe), serif headline + small sans caption, paper/shutter foley.
Do not tint photos into a brand duotone (YOUR BRAND 30.09: «страшно, непрезентабельно»):
keep natural colour; bring the brand in with type, frames and light.
Each shot is a cache anchor. Placeholder photos are drawn when a file is missing (demo only).
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
BRAND = {'bg': '#f4efe9', 'ink': '#1f1a17', 'accent': '#a8324f', 'sans': 'onest', 'serif': 'cormorant'}
# (seconds, photo, move, headline, caption). move: push | pull | pan-left | pan-right
SHOTS = [
    (3.2, 'assets/photos/01.jpg', 'push', 'Тихое утро', 'студия открывается в 9:00'),
    (3.0, 'assets/photos/02.jpg', 'pan-left', 'Без спешки', 'до 60 минут на визит'),
    (3.4, 'assets/photos/03.jpg', 'pull', 'Для себя', 'запишись на консультацию'),
]
XFADE = 0.5


def main():
    seconds = round(sum(s[0] for s in SHOTS), 3)
    c = Comp(W, H, seconds=seconds, title='Photo editorial', level=LEVEL, background=BRAND['bg'])
    c.font(BRAND['sans'], 400, 600)
    c.font(BRAND['serif'], 600, 700)
    L, T, R, B = SAFE
    if ORIENT == 'landscape':       # photo left, type column right
        fx, fy, fw, fh = L, T, int(W * .56), B - T
        tx, tw = fx + fw + 80, R - (fx + fw + 80)
        ty = H * .40
    else:                           # photo on top, type under it
        fx, fy, fw = L, T, R - L
        fh = int((B - T) * (.70 if ORIENT == 'portrait' else .64))
        tx, tw, ty = L + 20, R - L - 40, fy + fh + 70
    hl = 118 if ORIENT != 'square' else 96
    c.css(f'''
#film {{ background: {BRAND['bg']}; }}
.shot {{ position: absolute; inset: 0; opacity: 0; }}
.frame {{ position: absolute; left: {fx}px; top: {fy}px; width: {fw}px; height: {fh}px; overflow: hidden; border-radius: 6px;
  box-shadow: 0 40px 90px rgba(40,25,20,.18); }}
.frame img {{ position: absolute; left: -6%; top: -6%; width: 112%; height: 112%; object-fit: cover; }}
.hl {{ position: absolute; left: {tx}px; width: {tw}px; top: {ty:.0f}px; font: 700 {hl}px/1 Cormorant; color: {BRAND['ink']}; letter-spacing: -1px; }}
.rule {{ position: absolute; left: {tx + 4}px; top: {ty + hl * 1.28:.0f}px; width: 120px; height: 3px; background: {BRAND['accent']}; }}
.cp {{ position: absolute; left: {tx + 4}px; width: {tw}px; top: {ty + hl * 1.28 + 24:.0f}px; font: 400 40px/1.3 Onest; color: #6d6259; }}
''')
    html, t = [], 0.0
    for i, (dur, photo, move, hl, cp) in enumerate(SHOTS):
        src = HERE / photo
        if not src.exists():
            placeholder(src, i)
        html.append(f'<div class="shot" id="s{i}"><div class="frame"><img id="p{i}" src="{photo}"></div>'
                    f'<div class="hl" id="h{i}">{hl}</div><div class="rule" id="r{i}"></div><div class="cp" id="c{i}">{cp}</div></div>')
        st = c.scene(t)
        c.set0(f'#s{i}', {'opacity': 0})
        c.fromto(f'#s{i}', {'opacity': 0}, {'opacity': 1, 'duration': XFADE if i else .4, 'ease': 'sine.inOut'}, st, later=True)
        if i:  # the previous shot leaves while this one arrives (text of both never stacks for long)
            c.fromto(f'#s{i - 1}', {'opacity': 1}, {'opacity': 0, 'duration': XFADE * .6, 'ease': 'sine.in'}, st, later=True)
        moves = {'push': ({'scale': 1.0}, {'scale': 1.06}), 'pull': ({'scale': 1.07}, {'scale': 1.0}),
                 'pan-left': ({'x': 30}, {'x': -30}), 'pan-right': ({'x': -30}, {'x': 30})}
        frm, to = moves[move]
        c.fromto(f'#p{i}', frm, {**to, 'duration': dur + XFADE, 'ease': 'none'}, st)
        c.enter(f'#h{i}', st + .45)
        c.fromto(f'#r{i}', {'scaleX': 0, 'transformOrigin': '0% 50%'}, {'scaleX': 1, 'duration': .6, 'ease': 'power3.out'}, st + .7)
        c.enter(f'#c{i}', st + .85)
        c.sfx(st + .05, 'paper', gain_db=-12)
        if i == len(SHOTS) - 1:
            c.sfx(st + .7, 'shutter', gain_db=-14)
        t += dur
    c.html('\n'.join(html))
    c.grain(.05)
    (HERE / 'work').mkdir(exist_ok=True)
    result = c.write(HERE, mix={'tracks': [{'file': 'work/sfx.wav', 'role': 'sfx'}]})
    subprocess.run([sys.executable, str(Path(SK) / 'scripts/sfx.py'), 'render',
                    str(HERE / 'events.json'), str(HERE / 'work/sfx.wav')], check=True, capture_output=True)
    print(json.dumps(result, ensure_ascii=False))


def placeholder(path, i):
    """Demo-only stand-in photo (soft gradient + label). Replace with real or generated photos."""
    from PIL import Image, ImageDraw, ImageFilter, ImageFont
    path.parent.mkdir(parents=True, exist_ok=True)
    tones = [((196, 170, 150), (120, 92, 80)), ((170, 180, 176), (80, 96, 98)), ((210, 186, 176), (140, 96, 100))]
    a, b = tones[i % len(tones)]
    img = Image.new('RGB', (1200, 1600))
    d = ImageDraw.Draw(img)
    for y in range(1600):
        k = y / 1599
        d.line([(0, y), (1200, y)], fill=tuple(int(a[j] * (1 - k) + b[j] * k) for j in range(3)))
    d.ellipse([300, 350, 900, 950], fill=tuple(min(255, x + 30) for x in a))
    img = img.filter(ImageFilter.GaussianBlur(60))
    d = ImageDraw.Draw(img)
    font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 64)
    d.text((70, 1480), f'ФОТО {i + 1} (заглушка)', fill=(255, 255, 255), font=font)
    img.save(path, quality=90)


if __name__ == '__main__':
    main()
