"""Motion inserts, cards and bars over footage (replaces overlay_bars / overlay_cards of the old pipeline).

    from mvblocks import Brand, Blocks
    brand = Brand(bg='#fff3f7', ink='#2a0f1a', accent='#d81b55', font='Onest', weight=700)
    b = Blocks(c, brand)
    span = b.offer(t=24.0, dur=2.6, title='Первый визит', old='59 €', new='29 €', sub='для новых клиентов')
    cap.hide(*span)                         # captions step aside while the insert owns the frame
    b.card('ОФИЦ. ДОСТАВКА|ИЗ КИТАЯ', t=.3, end=11.4, y=.24, style='yellow')
    b.bars(top='БЕСПЛАТНОЕ ЗАНЯТИЕ|ДЛЯ ДЕТЕЙ 7-17 ЛЕТ', bottom='~60 BYN~ 0 BYN|ОСТАВЛЯЙТЕ ЗАЯВКУ')

Inserts (1–3 s): offer, stat, points, cta, logo. mode='full' covers the footage with a brand panel,
mode='over' keeps the footage visible under a dark scrim. Transitions: in_='wipe'|'zoom'|'blur'|'cut'.
Each insert adds its own SFX events and returns (t0, t1) for Captions.hide().
Text syntax: '|' = new line, '~text~' = struck through (an old price).
"""
import html
import re
from dataclasses import dataclass


@dataclass
class Brand:
    bg: str = '#111111'
    ink: str = '#ffffff'
    accent: str = '#ffd400'
    accent_ink: str = '#111111'
    font: str = 'Montserrat'
    weight: int = 800
    radius: int = 34
    scrim: str = 'rgba(12,8,12,.55)'     # tint over blurred footage in mode='over'
    over_ink: str = '#ffffff'


def rich(text):
    """'|' → line breaks, '~x~' → struck-through span, escaping everything else."""
    lines = []
    for line in text.split('|'):
        parts = re.split(r'(~[^~]+~)', line)
        lines.append(''.join(f'<s class="strike">{html.escape(p[1:-1])}</s>' if p.startswith('~') else html.escape(p) for p in parts))
    return '<br>'.join(lines)


class Blocks:
    def __init__(self, comp, brand):
        self.c, self.b, self.n = comp, brand, 0
        b = brand
        comp.css(f'''
.ins {{ position: absolute; inset: 0; z-index: 70; opacity: 0; display: flex; flex-direction: column; align-items: center;
  justify-content: center; text-align: center; font-family: {b.font}, sans-serif; color: {b.ink}; }}
.ins.full {{ background: radial-gradient(120% 80% at 50% 38%, {b.bg} 0%, {b.bg} 55%, color-mix(in srgb, {b.bg} 82%, {b.accent}) 100%); }}
.ins.over {{ background: {b.scrim}; backdrop-filter: blur(22px) saturate(1.15); -webkit-backdrop-filter: blur(22px) saturate(1.15); color: {b.over_ink}; }}
.ins .t1 {{ font: {b.weight} 78px/1.08 {b.font}; letter-spacing: -1px; }}
.ins .big {{ font: {b.weight} 190px/1 {b.font}; letter-spacing: -6px; color: {b.accent}; }}
.ins .old {{ font: {b.weight} 76px/1 {b.font}; opacity: .55; position: relative; display: inline-block; }}
.ins .old::after {{ content: ""; position: absolute; left: -4%; right: -4%; top: 52%; height: 8px; background: {b.accent};
  transform: scaleX(var(--cut, 0)); transform-origin: 0 50%; border-radius: 4px; }}
.ins .sub {{ font: 600 46px/1.25 {b.font}; opacity: .85; margin-top: 26px; }}
.ins .pt {{ font: {b.weight} 62px/1.2 {b.font}; margin: 14px 0; display: flex; gap: 22px; align-items: center; }}
.ins .pt i {{ width: 22px; height: 22px; border-radius: 50%; background: {b.accent}; display: block; flex: none; }}
.ins .btn {{ margin-top: 44px; background: {b.accent}; color: {b.accent_ink}; font: {b.weight} 54px/1 {b.font};
  padding: 30px 60px; border-radius: 999px; box-shadow: 0 14px 40px rgba(0,0,0,.25); }}
.card {{ position: absolute; z-index: 65; opacity: 0; font-family: {b.font}, sans-serif; text-align: center;
  padding: 18px 34px 20px; border-radius: {b.radius}px; box-shadow: 0 12px 34px rgba(0,0,0,.28); }}
.card.yellow {{ background: {b.accent}; color: {b.accent_ink}; }}
.card.white {{ background: #fff; color: #111; }}
.card.dark {{ background: rgba(12,10,14,.86); color: #fff; }}
.card .ck {{ display: inline-block; width: 1em; margin-right: .35em; color: {b.accent}; }}
.bar {{ position: absolute; left: 0; right: 0; z-index: 65; display: flex; align-items: center; justify-content: center;
  text-align: center; font-family: {b.font}, sans-serif; line-height: 1.08; transform-origin: 50% 50%; }}
s.strike {{ text-decoration: none; position: relative; opacity: .8; }}
s.strike::after {{ content: ""; position: absolute; left: -3%; right: -3%; top: 50%; height: .09em; background: currentColor; }}
''')

    # ── helpers ─────────────────────────────────────────────────────────────
    def _box(self, cls, inner, mode):
        self.n += 1
        i = f'ins{self.n}'
        self.c.html(f'<div class="ins {mode} {cls}" id="{i}">{inner}</div>')
        self.c.set0(f'#{i}', {'opacity': 0})
        return i

    def _in(self, sel, t, kind):
        c = self.c
        if kind == 'wipe':
            c.fromto(sel, {'opacity': 1, 'clipPath': 'inset(100% 0% 0% 0%)'}, {'opacity': 1, 'clipPath': 'inset(0% 0% 0% 0%)', 'duration': .38, 'ease': 'power3.inOut'}, t, later=True)
            c.sfx(t, 'whoosh', gain_db=-10, dur=.45)
        elif kind == 'zoom':
            c.fromto(sel, {'opacity': 0, 'scale': 1.18, 'filter': 'blur(14px)'}, {'opacity': 1, 'scale': 1, 'filter': 'blur(0px)', 'duration': .35, 'ease': 'expo.out'}, t, later=True)
            c.sfx(t, 'whoosh', gain_db=-10, dur=.35, f0=600, f1=3000)
        elif kind == 'blur':
            c.fromto(sel, {'opacity': 0, 'filter': 'blur(18px)'}, {'opacity': 1, 'filter': 'blur(0px)', 'duration': .4, 'ease': 'power2.out'}, t, later=True)
            c.sfx(t, 'cloth', gain_db=-12)
        else:
            c.fromto(sel, {'opacity': 0}, {'opacity': 1, 'duration': .01}, t, later=True)

    def _out(self, sel, t, kind):
        c = self.c
        if kind == 'wipe':
            c.fromto(sel, {'clipPath': 'inset(0% 0% 0% 0%)'}, {'clipPath': 'inset(0% 0% 100% 0%)', 'duration': .32, 'ease': 'power3.inOut'}, t - .32, later=True)
        elif kind in ('zoom', 'blur'):
            c.fromto(sel, {'opacity': 1, 'filter': 'blur(0px)'}, {'opacity': 0, 'filter': 'blur(14px)', 'duration': .28, 'ease': 'power2.in'}, t - .28, later=True)
        else:
            c.fromto(sel, {'opacity': 1}, {'opacity': 0, 'duration': .01}, t - .01, later=True)

    def _enter_items(self, sels, t, step=.12):
        for k, s in enumerate(sels):
            self.c.fromto(s, {'opacity': 0, 'y': 26}, {'opacity': 1, 'y': 0, 'duration': .32, 'ease': 'power3.out'}, t + k * step, later=True)
            self.c.set0(s, {'opacity': 0})

    # ── inserts ─────────────────────────────────────────────────────────────
    def offer(self, t, dur, title, old, new, sub='', mode='over', in_='wipe', out='wipe'):
        """Price offer: title, old price struck through on screen, new price lands with a hit."""
        i = self._box('offer', f'<div class="t1" id="t{self.n + 1}">{rich(title)}</div>'
                               f'<div class="old" id="o{self.n + 1}" style="margin-top:34px">{html.escape(old)}</div>'
                               f'<div class="big" id="b{self.n + 1}" style="margin-top:18px">{html.escape(new)}</div>'
                               + (f'<div class="sub" id="s{self.n + 1}">{rich(sub)}</div>' if sub else ''), mode)
        k, c = self.n, self.c
        self._in(f'#{i}', t, in_)
        self._enter_items([f'#t{k}', f'#o{k}'], t + .2)
        c.set0(f'#o{k}', {'--cut': 0, 'opacity': 0})
        c.fromto(f'#o{k}', {'--cut': 0}, {'--cut': 1, 'duration': .3, 'ease': 'power2.inOut'}, t + .65, later=True)
        c.set0(f'#b{k}', {'opacity': 0})
        c.fromto(f'#b{k}', {'opacity': 0, 'scale': 1.35, 'filter': 'blur(8px)'}, {'opacity': 1, 'scale': 1, 'filter': 'blur(0px)', 'duration': .4, 'ease': 'expo.out'}, t + .95, later=True)
        c.sfx(t + .95, 'soft_hit', gain_db=-6)
        if sub:
            self._enter_items([f'#s{k}'], t + 1.3)
        self._out(f'#{i}', t + dur, out)
        return (t, t + dur)

    def stat(self, t, dur, value, label, mode='over', in_='zoom', out='blur'):
        """One number that matters (5 студий, 2000+ отзывов, 4.9): lands with a hit, label under it."""
        i = self._box('stat', f'<div class="big" id="n{self.n + 1}">{html.escape(value)}</div><div class="t1" id="l{self.n + 1}" style="margin-top:18px">{rich(label)}</div>', mode)
        k, c = self.n, self.c
        self._in(f'#{i}', t, in_)
        c.set0(f'#n{k}', {'opacity': 0})
        c.fromto(f'#n{k}', {'opacity': 0, 'scale': 1.3}, {'opacity': 1, 'scale': 1, 'duration': .4, 'ease': 'expo.out'}, t + .15, later=True)
        c.sfx(t + .15, 'soft_hit', gain_db=-8)
        self._enter_items([f'#l{k}'], t + .45)
        self._out(f'#{i}', t + dur, out)
        return (t, t + dur)

    def points(self, t, dur, title, items, mode='over', in_='wipe', out='wipe'):
        """Short benefit list; items arrive one by one with a soft tick."""
        pts = ''.join(f'<div class="pt" id="p{self.n + 1}_{j}"><i></i>{rich(x)}</div>' for j, x in enumerate(items))
        i = self._box('points', f'<div class="t1" id="h{self.n + 1}" style="margin-bottom:30px">{rich(title)}</div><div style="text-align:left">{pts}</div>', mode)
        k, c = self.n, self.c
        self._in(f'#{i}', t, in_)
        self._enter_items([f'#h{k}'], t + .2)
        step = min(.45, (dur - 1.0) / max(1, len(items)))
        for j in range(len(items)):
            self._enter_items([f'#p{k}_{j}'], t + .55 + j * step)
            c.sfx(t + .55 + j * step, 'tick', gain_db=-14)
        self._out(f'#{i}', t + dur, out)
        return (t, t + dur)

    def cta(self, t, dur, title, button, sub='', mode='over', in_='zoom', out='cut'):
        """Call to action: headline + button that presses once."""
        i = self._box('cta', f'<div class="t1" id="c{self.n + 1}">{rich(title)}</div><div class="btn" id="btn{self.n + 1}">{html.escape(button)}</div>'
                             + (f'<div class="sub" id="cs{self.n + 1}">{rich(sub)}</div>' if sub else ''), mode)
        k, c = self.n, self.c
        self._in(f'#{i}', t, in_)
        self._enter_items([f'#c{k}', f'#btn{k}'] + ([f'#cs{k}'] if sub else []), t + .2, .16)
        c.fromto(f'#btn{k}', {'scale': 1}, {'scale': .94, 'duration': .1, 'ease': 'power2.in', 'yoyo': True, 'repeat': 1}, t + 1.1, later=True)
        c.sfx(t + 1.1, 'tap', gain_db=-8)
        if out != 'cut' or t + dur < c.seconds - .05:
            self._out(f'#{i}', t + dur, out)
        return (t, t + dur)

    def logo(self, t, dur, text=None, image=None, mode='full', in_='blur', out='cut'):
        """Brand sign-off: wordmark text (brand font) or a logo image from assets/."""
        inner = f'<img id="lg{self.n + 1}" src="{image}" style="max-width:60%;max-height:30%">' if image else f'<div class="t1" id="lg{self.n + 1}" style="font-size:96px">{html.escape(text)}</div>'
        i = self._box('logo', inner, mode)
        k = self.n
        self._in(f'#{i}', t, in_)
        self.c.fromto(f'#lg{k}', {'scale': .94}, {'scale': 1, 'duration': dur, 'ease': 'sine.out'}, t, later=True)
        self.c.set0(f'#lg{k}', {'scale': .94})
        if out != 'cut' or t + dur < self.c.seconds - .05:
            self._out(f'#{i}', t + dur, out)
        return (t, t + dur)

    # ── overlays that live over the footage ─────────────────────────────────
    def card(self, text, t, end=None, y=.24, style='yellow', anchor='center', size=38, check=False):
        """Rounded pill card sized to its text (old overlay_cards). y = top as a fraction of height."""
        self.n += 1
        i = f'card{self.n}'
        c = self.c
        end = c.seconds if end is None else end
        pos = {'center': 'left:50%', 'left': 'left:70px', 'right': 'right:70px'}[anchor]
        ck = '<span class="ck">✓</span>' if check else ''
        c.html(f'<div class="card {style}" id="{i}" style="{pos};top:{y * c.h:.0f}px;font:{self.b.weight} {size}px/1.2 {self.b.font}">{ck}{rich(text)}</div>')
        base = {'xPercent': -50} if anchor == 'center' else {}
        c.set0(f'#{i}', {'opacity': 0, **base})
        c.fromto(f'#{i}', {'opacity': 0, 'y': 16, 'scale': .92, **base}, {'opacity': 1, 'y': 0, 'scale': 1, 'duration': .35, 'ease': 'back.out(1.7)'}, t, later=True)
        c.sfx(t, 'pop', gain_db=-14)
        if end < c.seconds - .05:
            c.fromto(f'#{i}', {'opacity': 1}, {'opacity': 0, 'duration': .25, 'ease': 'power1.in'}, end - .25, later=True)
        return (t, end)

    def bars(self, top=None, bottom=None, t=0.0, end=None, top_style=('#ffffff', '#e4002b'), bottom_style=('#e4002b', '#ffffff'),
             top_y=460, top_h=170, bottom_y=1240, bottom_h=200, size=46):
        """Two full-width plates (old overlay_bars). Default positions sit inside y 420..1500 of a 1080×1920
        frame: they survive both the Reels UI and the 9:16 → 1:1 feed crop. Plates wipe in, text follows."""
        c = self.c
        end = c.seconds if end is None else end
        out = []
        for key, text, (bg, ink), y, h in (('top', top, top_style, top_y, top_h), ('bottom', bottom, bottom_style, bottom_y, bottom_h)):
            if not text:
                continue
            self.n += 1
            i = f'bar{self.n}'
            c.html(f'<div class="bar" id="{i}" style="top:{y}px;height:{h}px;background:{bg};color:{ink};font:{self.b.weight} {size}px/1.1 {self.b.font}">'
                   f'<div id="{i}t">{rich(text)}</div></div>')
            c.set0(f'#{i}', {'scaleX': 0})
            c.set0(f'#{i}t', {'opacity': 0})
            c.fromto(f'#{i}', {'scaleX': 0}, {'scaleX': 1, 'duration': .35, 'ease': 'power3.out'}, t + (.1 if key == 'bottom' else 0), later=True)
            c.fromto(f'#{i}t', {'opacity': 0, 'y': 10}, {'opacity': 1, 'y': 0, 'duration': .25, 'ease': 'power2.out'}, t + .3, later=True)
            out.append((y, y + h))
        if out:
            c.sfx(t, 'swipe', gain_db=-14)
        return out
