#!/usr/bin/env python3
"""Template «blank»: an empty generator for a bespoke piece (premium macro-object, custom world, anything
the other templates do not fit). Read references/direction.md and a matching case in references/cases/
before writing; hero-object-wheel.md shows a full premium build (camera, DOF, light, physics-driven sound).

  python3 build.py && python3 <motion-video>/scripts/mv.py build $PWD -o output/master-r1.mp4
"""
import json
import subprocess
import sys
from pathlib import Path

SK = Path(__file__).with_name('.motion-skill').read_text().strip()
sys.path.insert(0, str(Path(SK) / 'scripts'))
from mvlib import FORMATS, Comp, orientation, safe_box  # noqa: E402

HERE = Path(__file__).resolve().parent
LEVEL = 'premium'
FORMAT = '9:16'                  # 9:16 | 4:5 | 3:4 | 1:1 | 16:9 (new_project.py --format sets it)
FORMATS_OK = ('9:16', '4:5', '3:4', '1:1', '16:9')
W, H = FORMATS[FORMAT]['size']
ORIENT = orientation(W, H)
SAFE = safe_box(FORMAT)                 # left, top, right, bottom
SECONDS = 6.0


def main():
    c = Comp(W, H, seconds=SECONDS, title='Bespoke', level=LEVEL, background='#08060a')
    c.font('onest', 600, 700)
    d = min(W, H) * .46                      # hero diameter follows the short side
    c.css(f"""
#film {{ background: radial-gradient({W * .85:.0f}px {H * .62:.0f}px at 50% 45%, #2a1420 0%, #08060a 75%); color: #f6eee9; }}
#world {{ position: absolute; inset: 0; transform-origin: 50% 50%; }}
#hero {{ position: absolute; left: {(W - d) / 2:.0f}px; top: {H * .42 - d / 2:.0f}px; width: {d:.0f}px; height: {d:.0f}px; border-radius: 50%;
  background: radial-gradient(circle at 36% 32%, #fff3e0 0%, #e2b877 30%, #7a5424 100%); box-shadow: 0 60px 120px rgba(0,0,0,.6); }}
#t1 {{ position: absolute; left: 70px; right: 70px; top: {H * .42 + d / 2 + H * .06:.0f}px; text-align: center;
  font: 700 {min(W, H) * .089:.0f}px/1.05 Onest; letter-spacing: -3px; }}
""")
    c.html('<div id="world"><div id="hero"></div></div><div id="t1">Один объект</div>')
    # One continuous camera move with a single accent; nothing ever fully stops.
    c.camera('#world', [(0, {'scale': 1.25, 'rotation': -2}, None), (2.4, {'scale': 1.1, 'rotation': 0}, 'sine.inOut'),
                        (2.9, {'scale': .96, 'rotation': 0}, 'expo.out'), (SECONDS, {'scale': 1.0, 'rotation': .8}, 'sine.inOut')])
    c.enter('#t1', 2.9)
    c.sfx(2.9, 'hit', gain_db=-4)
    c.sfx(2.9, 'air', gain_db=-10, lead=.12)
    c.grain()
    c.vignette(.7)
    (HERE / 'work').mkdir(exist_ok=True)
    result = c.write(HERE, mix={'tracks': [{'file': 'work/sfx.wav', 'role': 'sfx'}]})
    subprocess.run([sys.executable, str(Path(SK) / 'scripts/sfx.py'), 'render',
                    str(HERE / 'events.json'), str(HERE / 'work/sfx.wav')], check=True, capture_output=True)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
