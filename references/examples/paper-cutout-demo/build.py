#!/usr/bin/env python3
"""Demo «Бумажная перекладка»: fox sprites from image-gen (cut with cutout.py) in a paper world, 9:16, 8 s.
Stop-motion at 12 drawings/s (steps ease), smooth camera, paper foley on every hop."""
import json
import subprocess
import sys
from pathlib import Path

SK = Path(__file__).with_name('.motion-skill').read_text().strip()
sys.path.insert(0, str(Path(SK) / 'scripts'))
from mvlib import FORMATS, Comp  # noqa: E402

HERE = Path(__file__).resolve().parent
W, H = FORMATS['9:16']['size']
SECONDS = 8.0
FOX_H = 560


def main():
    c = Comp(W, H, seconds=SECONDS, title='Paper cut-out', level='premium', background='#efe3cf')
    c.font('onest', 700)
    c.font('cormorant', 600)
    s0, s1, s2 = (FOX_H / 675, FOX_H / 677, FOX_H / 681)
    c.css(f"""
#film {{ background: #efe3cf; }}
#world {{ position: absolute; inset: -80px; transform-origin: 50% 60%; }}
.layer {{ position: absolute; left: 0; right: 0; }}
#sky {{ inset: 0; background: radial-gradient(900px 700px at 70% 22%, #f9efdc 0%, #efe3cf 55%, #e6d3b5 100%); }}
#sun {{ position: absolute; width: 230px; height: 230px; left: 720px; top: 330px; border-radius: 50%;
  background: #f2a541; box-shadow: 0 10px 0 rgba(120,70,20,.18); }}
.hill {{ position: absolute; border-radius: 50% 50% 0 0 / 100% 100% 0 0; box-shadow: 0 -8px 0 rgba(255,255,255,.35) inset, 0 14px 22px rgba(70,40,10,.22); }}
#h1 {{ width: 1500px; height: 700px; left: -320px; top: 1180px; background: #9bb06b; }}
#h2 {{ width: 1400px; height: 640px; left: 60px; top: 1300px; background: #6f8f4e; }}
#h3 {{ width: 1700px; height: 600px; left: -300px; top: 1480px; background: #4f6e3a; }}
.tree {{ position: absolute; width: 0; height: 0; border-left: 70px solid transparent; border-right: 70px solid transparent;
  border-bottom: 210px solid #355a2c; filter: drop-shadow(0 10px 8px rgba(40,30,10,.3)); }}
.fox {{ position: absolute; left: 0; top: 0; transform-origin: 50% 100%; filter: drop-shadow(0 18px 14px rgba(60,30,5,.35)); }}
#foxrig {{ position: absolute; left: 0; top: {1530 - FOX_H}px; width: 1px; height: 1px; }}
#f1 {{ width: {595 * s1:.0f}px; height: {FOX_H}px; margin-left: {-595 * s1 / 2:.0f}px; }}
#f0 {{ width: {443 * s0:.0f}px; height: {FOX_H}px; margin-left: {-443 * s0 / 2:.0f}px; opacity: 0; }}
#f2 {{ width: {498 * s2:.0f}px; height: {FOX_H}px; margin-left: {-498 * s2 / 2:.0f}px; opacity: 0; }}
.strip {{ position: absolute; left: 50%; padding: 18px 46px 22px; background: #fffaf0; color: #2a1b10;
  box-shadow: 0 10px 18px rgba(70,40,10,.22); white-space: nowrap; transform-origin: 50% 50%; }}
#t1 {{ top: 250px; font: 700 112px/1 Onest; letter-spacing: -3px; }}
#t2 {{ top: 400px; font: 700 112px/1 Onest; letter-spacing: -3px; background: #d9572b; color: #fffaf0; }}
#t3 {{ top: 1650px; font: 600 54px/1.15 Cormorant; padding: 14px 34px 18px; text-align: center; }}
#t3 b {{ font: 700 44px/1.2 Onest; letter-spacing: -1px; color: #b8441d; }}
""")
    trees = ''.join(f'<div class="tree" style="left:{x}px;top:{y}px;transform:scale({s})"></div>'
                    for x, y, s in ((80, 1060, .8), (230, 1110, .6), (880, 1150, .9), (990, 1210, .55)))
    c.html(f"""<div id="world">
  <div class="layer" id="sky"></div><div id="sun"></div>
  <div class="hill" id="h1"></div>{trees}<div class="hill" id="h2"></div><div class="hill" id="h3"></div>
  <div id="foxrig"><img class="fox" id="f1" src="assets/img/fox_1.webp"><img class="fox" id="f0" src="assets/img/fox_0.webp">
  <img class="fox" id="f2" src="assets/img/fox_2.webp"></div>
</div>
<div class="strip" id="t1">Бумажная</div><div class="strip" id="t2">перекладка</div>
<div class="strip" id="t3">картинка image-gen → <b>cutout.py</b> → анимация</div>""")

    # camera: slow push, one accent on the landing
    c.camera('#world', [(0, {'scale': 1.12, 'x': 40, 'y': 20, 'rotation': -1}, None),
                        (3.0, {'scale': 1.04, 'x': 0, 'y': 0, 'rotation': 0}, 'sine.inOut'),
                        (3.25, {'scale': 1.0, 'x': 0, 'y': 8, 'rotation': 0}, 'expo.out'),
                        (SECONDS, {'scale': 1.03, 'x': -10, 'y': 0, 'rotation': .6}, 'sine.inOut')])
    c.fromto('#sun', {'y': 60, 'rotation': -20}, {'y': 0, 'rotation': 0, 'duration': SECONDS, 'ease': 'steps(48)'}, 0)
    for i, sel in enumerate(('#h1', '#h2', '#h3')):   # paper breathing: stepped, 12 drawings/s
        c.fromto(sel, {'y': 0}, {'y': -6 - 3 * i, 'duration': .5, 'ease': 'steps(6)', 'repeat': 15, 'yoyo': True}, 0)

    # fox: three hops in side pose (12 drawings/s), lands, turns to camera, waves
    xs = [-260, 140, 380, 560]
    c.set0('#foxrig', {'x': xs[0]})
    for k in range(3):
        t = .35 + k * .85
        c.fromto('#foxrig', {'x': xs[k]}, {'x': xs[k + 1], 'duration': .7, 'ease': 'steps(9)'}, t, later=True)
        c.fromto('#f1', {'y': 0, 'rotation': -4}, {'y': -150, 'rotation': 6, 'duration': .35, 'ease': 'steps(4)'}, t, later=True)
        c.fromto('#f1', {'y': -150, 'rotation': 6}, {'y': 0, 'rotation': -2, 'duration': .35, 'ease': 'steps(4)'}, t + .35, later=True)
        c.fromto('#f1', {'scaleY': .86, 'scaleX': 1.08}, {'scaleY': 1, 'scaleX': 1, 'duration': .17, 'ease': 'steps(2)'}, t + .7, later=True)
        c.sfx(t + .02, 'paper', gain_db=-9, pan=-.4 + .4 * k)
        c.sfx(t + .7, 'soft_hit', gain_db=-10, pan=-.4 + .4 * k)
    c.tl(".set('#f1', {opacity: 0}, 3.0).set('#f0', {opacity: 1}, 3.0)")
    c.fromto('#f0', {'scaleY': .8, 'scaleX': 1.12}, {'scaleY': 1, 'scaleX': 1, 'duration': .34, 'ease': 'steps(4)'}, 3.0, later=True)
    c.sfx(3.0, 'hit', gain_db=-7)
    c.sfx(3.0, 'air', gain_db=-14, lead=.15)
    c.tl(".set('#f0', {opacity: 0}, 4.6).set('#f2', {opacity: 1}, 4.6)")
    c.fromto('#f2', {'rotation': -3}, {'rotation': 3, 'duration': .34, 'ease': 'steps(4)', 'repeat': 9, 'yoyo': True}, 4.6, later=True)
    c.sfx(4.6, 'cloth', gain_db=-12)

    # titles on paper strips: thrown in, stepped wobble
    c.fromto('#t1', {'xPercent': -50, 'x': -900, 'rotation': -14}, {'x': 0, 'rotation': -3, 'duration': .45, 'ease': 'back.out(1.6)'}, .2)
    c.fromto('#t2', {'xPercent': -50, 'x': 900, 'rotation': 12}, {'x': 0, 'rotation': 2, 'duration': .45, 'ease': 'back.out(1.6)'}, .55)
    c.sfx(.2, 'swipe', gain_db=-10, pan=-.5)
    c.sfx(.55, 'swipe', gain_db=-10, pan=.5)
    c.fromto('#t3', {'xPercent': -50, 'y': 700, 'rotation': 4}, {'y': 0, 'rotation': -1, 'duration': .5, 'ease': 'back.out(1.4)'}, 3.4)
    c.sfx(3.4, 'paper', gain_db=-8)
    for sel, a, t0 in (('#t1', -3, .8), ('#t2', 2, 1.05)):
        c.fromto(sel, {'rotation': a}, {'rotation': a + 1.2, 'duration': .25, 'ease': 'steps(3)', 'repeat': 25, 'yoyo': True}, t0, later=True)
    c.grain(opacity=.16)
    c.vignette(.45)
    (HERE / 'work').mkdir(exist_ok=True)
    result = c.write(HERE, mix={'tracks': [{'file': 'work/sfx.wav', 'role': 'sfx'}]})
    subprocess.run([sys.executable, str(Path(SK) / 'scripts/sfx.py'), 'render',
                    str(HERE / 'events.json'), str(HERE / 'work/sfx.wav')], check=True, capture_output=True)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
