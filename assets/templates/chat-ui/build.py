#!/usr/bin/env python3
"""Template «chat-ui»: a story told as a phone chat (case references/cases/chat-story.md), 9:16.

Change BRAND, CHAT (who says what and when) and FINAL, then:
  python3 build.py && python3 <motion-video>/scripts/mv.py build $PWD -o output/master-r1.mp4
Grammar: typing dots → bubble pops in (scale .9 → 1 from its corner) → the list scrolls up;
the camera slowly pushes toward the phone; UI foley (pop, notify, key) sits on the same times.
Time the bubbles to the voice with Words('work/voice.words.json', delay).at('слово').
Continuous camera: anchors stay [0]; the cache works on the 2 s grid.
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
BRAND = {'bg1': '#1a0b12', 'bg2': '#3b1224', 'accent': '#ff5c8a', 'mine': '#c2185b', 'theirs': '#ffffff',
         'ink': '#1d1016', 'font': 'onest'}
CONTACT = {'name': 'Аня', 'status': 'в сети', 'avatar': None}   # avatar: path to a local jpg, or None for initials
# (time, side, text). side: 'in' (friend) | 'out' (viewer). Time = when the bubble lands.
CHAT = [
    (0.9, 'in', 'Смотри, что нашла'),
    (2.3, 'in', 'Кофейня у метро дарит второй кофе'),
    (3.9, 'out', 'Серьёзно? Когда?'),
    (5.3, 'in', 'До 11 утра по будням'),
    (6.6, 'out', 'Завтра идём'),
]
FINAL = {'at': 8.2, 'title': 'Второй в подарок', 'sub': 'до 11:00 по будням'}
SECONDS = 10.5


def main():
    c = Comp(W, H, seconds=SECONDS, title='Chat story', level=LEVEL, background=BRAND['bg1'])
    c.font(BRAND['font'], 400, 600, 700)
    fam = 'Onest'
    L, T, R, B = SAFE
    # The phone is designed at 780×1480 and scaled to fit the safe area of any format.
    k = min((B - T) / 1480, (R - L) / 780, 1.0)
    px, py = (W - 780 * k) / 2, T + ((B - T) - 1480 * k) / 2
    c.css(f'''
#film {{ background: radial-gradient(1200px 1500px at 50% 40%, {BRAND['bg2']} 0%, {BRAND['bg1']} 70%); font-family: {fam}, sans-serif; }}
#cam {{ position: absolute; inset: 0; transform-origin: 50% 46%; }}
#pw {{ position: absolute; left: {px:.0f}px; top: {py:.0f}px; width: 780px; height: 1480px; transform: scale({k:.4f}); transform-origin: 0 0; }}
#phone {{ position: absolute; left: 0; top: 0; width: 780px; height: 1480px; border-radius: 96px;
  background: #0d0d0f; box-shadow: 0 60px 140px rgba(0,0,0,.6), inset 0 0 0 3px #2a2a2e; padding: 26px; }}
#screen {{ position: absolute; inset: 26px; border-radius: 72px; overflow: hidden; background: #f3eef0; }}
#head {{ position: absolute; left: 0; right: 0; top: 0; height: 220px; background: #fff; display: flex; align-items: flex-end;
  padding: 0 44px 30px; gap: 26px; box-shadow: 0 2px 0 rgba(0,0,0,.05); z-index: 2; }}
.ava {{ width: 96px; height: 96px; border-radius: 50%; background: {BRAND['mine']}; color: #fff; display: flex;
  align-items: center; justify-content: center; font: 700 44px/1 {fam}; overflow: hidden; flex: none; }}
.ava img {{ width: 100%; height: 100%; object-fit: cover; }}
.nm {{ font: 700 40px/1.1 {fam}; color: {BRAND['ink']}; }}
.st {{ font: 400 28px/1.3 {fam}; color: #8a7f84; }}
#list {{ position: absolute; left: 34px; right: 34px; top: 250px; }}
.msg {{ display: flex; margin: 0 0 22px; }}
.msg.out {{ justify-content: flex-end; }}
.b {{ max-width: 560px; padding: 26px 34px; border-radius: 44px; font: 400 40px/1.3 {fam}; }}
.in .b {{ background: {BRAND['theirs']}; color: {BRAND['ink']}; border-bottom-left-radius: 12px; transform-origin: 0% 100%;
  box-shadow: 0 6px 18px rgba(0,0,0,.06); }}
.out .b {{ background: {BRAND['mine']}; color: #fff; border-bottom-right-radius: 12px; transform-origin: 100% 100%; }}
.typing {{ position: absolute; left: 34px; bottom: 60px; background: #fff; border-radius: 40px; padding: 28px 34px; display: flex; gap: 14px; opacity: 0; }}
.typing i {{ width: 18px; height: 18px; border-radius: 50%; background: #b9adb3; display: block; }}
.cap {{ position: absolute; left: 70px; right: 70px; text-align: center; color: #fff3f7; }}
#fin {{ top: {H * .38:.0f}px; }}
#fin .t {{ font: 700 120px/1.05 {fam}; letter-spacing: -3px; }}
#fin .s {{ font: 600 60px/1.2 {fam}; color: {BRAND['accent']}; margin-top: 24px; }}
''')
    ava = f'<img src="{c.asset(CONTACT["avatar"], "assets/avatar.jpg")}">' if CONTACT['avatar'] else CONTACT['name'][0]
    msgs = ''.join(f'<div class="msg {side}" id="m{i}"><div class="b" id="b{i}">{text}</div></div>'
                   for i, (_, side, text) in enumerate(CHAT))
    c.html(f'''<div id="cam"><div id="pw"><div id="phone"><div id="screen">
<div id="head"><div class="ava">{ava}</div><div><div class="nm">{CONTACT['name']}</div><div class="st">{CONTACT['status']}</div></div></div>
<div id="list">{msgs}</div>
<div class="typing" id="typing"><i></i><i></i><i></i></div>
</div></div></div></div>
<div class="cap" id="fin"><div class="t" id="fint">{FINAL['title']}</div><div class="s" id="fins">{FINAL['sub']}</div></div>''')
    # Camera: slow push into the phone, one continuous move, then pull back for the final line.
    c.camera('#cam', [(0, {'scale': 1.0, 'y': 40}, None), (FINAL['at'] - .2, {'scale': 1.08, 'y': -30}, 'sine.inOut'),
                      (SECONDS, {'scale': .96, 'y': 0}, 'power2.out')])
    # Bubbles: every message is hidden at t=0, pops in at its time; the list scrolls so the newest stays in view.
    ROW = 150  # approx. bubble height + gap; scroll offset per message beyond the visible ones
    for i, (t, side, _) in enumerate(CHAT):
        c.set0(f'#m{i}', {'opacity': 0})
        c.fromto(f'#m{i}', {'opacity': 0}, {'opacity': 1, 'duration': .01}, t, later=True)
        c.fromto(f'#b{i}', {'scale': .86, 'y': 16}, {'scale': 1, 'y': 0, 'duration': .42, 'ease': 'back.out(1.6)'}, t)
        if side == 'in':
            c.sfx(t, 'pop', gain_db=-8, pan=-.2)
            # typing dots before the friend's message
            c.fromto('#typing', {'opacity': 0}, {'opacity': 1, 'duration': .15}, max(0, t - .75), later=True)
            c.fromto('#typing', {'opacity': 1}, {'opacity': 0, 'duration': .08}, t - .05, later=True)
        else:
            for k in range(4):
                c.sfx(t - .7 + k * .13, 'key', gain_db=-20, pan=.15)
            c.sfx(t, 'swipe', gain_db=-16, pan=.2)
    c.set0('#typing', {'opacity': 0})
    visible = 5
    for i, (t, _, _) in enumerate(CHAT[visible:], start=visible):
        c.fromto('#list', {'y': -(i - visible) * ROW}, {'y': -(i - visible + 1) * ROW, 'duration': .45, 'ease': 'power2.out'}, t - .1, later=True)
    c.sfx(CHAT[0][0] - .5, 'notify', gain_db=-10)
    # Final: the chat is done, the phone goes away (blur + fade, nothing painted over its text), the line lands.
    c.fromto('#phone', {'opacity': 1, 'filter': 'blur(0px)'}, {'opacity': 0, 'filter': 'blur(14px)', 'duration': .5, 'ease': 'power2.in'}, FINAL['at'] - .45)
    c.enter('#fint', FINAL['at'])
    c.enter('#fins', FINAL['at'] + .45)
    c.sfx(FINAL['at'], 'soft_hit', gain_db=-6)
    c.grain()
    c.vignette(.55)
    (HERE / 'work').mkdir(exist_ok=True)
    result = c.write(HERE, mix={'tracks': [{'file': 'work/sfx.wav', 'role': 'sfx'}]})
    subprocess.run([sys.executable, str(Path(SK) / 'scripts/sfx.py'), 'render',
                    str(HERE / 'events.json'), str(HERE / 'work/sfx.wav')], check=True, capture_output=True)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
