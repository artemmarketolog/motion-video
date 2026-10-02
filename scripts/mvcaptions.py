"""Captions from TTS word timings: grouping, placement and six animated styles.

    from mvcaptions import Captions
    cap = Captions(c, words, style='pop', font='Montserrat', weight=900, size=84, case='upper',
                   color='#fff', accent='#ffd400', y=.65)
    cap.hide(10.2, 12.0)            # a motion insert owns the frame: captions step aside
    cap.place(3.0, 6.0, y=.30)      # this shot has a face low in frame: captions go up
    cap.build()

Styles (references/captions.md):
  pop      phrase appears whole, the spoken word takes the accent colour (+ optional bump)
  karaoke  phrase appears dimmed, each word fills with colour left→right while spoken
  word     one word at a time, big, centred; for fast, rhythmic ads
  calm     phrase fades/blur-ins as a whole, sentence case, no per-word highlight (presentations)
  pill     phrase on a rounded plate; words reveal one by one as spoken

`y` is the vertical CENTRE of the caption block as a fraction of the height (old pipeline `--pos`).
  accent   phrase appears whole; only keywords (numbers, `keywords=`) glow and grow when spoken

Grouping (HyperFrames caption-grouping rules, adapted): a new phrase starts on a pause ≥ 0.45 s,
after . ! ?, after a comma followed by a pause ≥ 0.25 s, or when the phrase would exceed
`max_chars` (≈ 2 lines) / `max_words`. Phrases shorter than 0.5 s merge into a neighbour.
Short gaps (< 0.35 s) are bridged so text does not blink between phrases.
Words are the TTS words already scaled to the video timeline (voice.py / Words with delay).
"""
import html
import json
import re
from pathlib import Path

PUNCT_END = re.compile(r'[.!?…]$')
# Short function words stay with the next word (no «дело не / доводил», «дети от / семи»).
CLINGY = {'не', 'ни', 'и', 'а', 'но', 'да', 'в', 'во', 'на', 'за', 'от', 'до', 'из', 'к', 'ко', 'с', 'со', 'у', 'о', 'об',
          'по', 'при', 'про', 'для', 'без', 'под', 'над', 'же', 'ли', 'бы', 'что', 'как', 'когда', 'если', 'это', 'мы', 'вы',
          'я', 'он', 'она', 'the', 'a', 'an', 'to', 'of', 'in', 'on', 'and', 'or'}


def numeric(word):
    return word.strip('.,!?:;«»"()—–-').replace('\u00a0', '').isdigit()


def joined(a, b):
    """Words that must not be separated: parts of one number («19 990», «39 000»)."""
    return numeric(a) and numeric(b) and len(b.strip('.,!?:;')) == 3


def clingy(word):
    return word.lower().strip('.,!?:;«»"()—–-') in CLINGY and not PUNCT_END.search(word) and not word.endswith(',')
TRAIL = re.compile(r'[,:;]+$')


def load_words(path, delay=0.0, tempo=1.0):
    """Word list from a words.json; times divided by tempo (if the json is from the raw take) and shifted by delay."""
    words = json.loads(Path(path).read_text())
    return [{'word': w['word'], 'start': round(w['start'] / tempo + delay, 3), 'end': round(w['end'] / tempo + delay, 3)}
            for w in words]


def group(words, max_chars=30, max_words=7, pause=.45, comma_pause=.25, min_dur=.5, fits=None):
    """Phrases for captions, like an editor would cut them:
    1) clauses end at a pause ≥ 0.45 s, at . ! ?, or at a comma followed by a pause ≥ 0.25 s;
    2) a clause that does not fit (`fits(words)` — measured with the real font, else a character estimate,
       or more than `max_words`) is split in two at the most balanced point in time, preferring a comma and
       never leaving a function word («не», «до», «от») at the end; recursively;
    3) a clause shorter than `min_dur` joins its neighbour when the result still fits."""
    ok = fits or (lambda ws: len(' '.join(x['word'] for x in ws)) <= max_chars)
    good = lambda ws: ok(ws) and len(ws) <= max_words
    clauses, cur = [], []
    for w in words:
        if cur:
            gap = w['start'] - cur[-1]['end']
            prev = cur[-1]['word']
            if gap >= pause or PUNCT_END.search(prev) or prev[-1:] in ':;' or (prev.endswith(',') and gap >= comma_pause):
                clauses.append(cur)
                cur = []
        cur.append(w)
    if cur:
        clauses.append(cur)

    def split(ws):
        if good(ws) or len(ws) == 1:
            return [ws]
        mid = (ws[0]['start'] + ws[-1]['end']) / 2
        best = min(range(1, len(ws)), key=lambda k: abs(ws[k]['start'] - mid)
                   + (0 if ws[k - 1]['word'].endswith(',') else .35) + (5 if clingy(ws[k - 1]['word']) else 0)
                   + (9 if joined(ws[k - 1]['word'], ws[k]['word']) else 0))
        return split(ws[:best]) + split(ws[best:])

    groups = [g for c in clauses for g in split(c)]
    merged = []
    for g in groups:
        if merged and (g[-1]['end'] - g[0]['start'] < min_dur or merged[-1][-1]['end'] - merged[-1][0]['start'] < min_dur)\
                and good(merged[-1] + g):
            merged[-1] = merged[-1] + g
        else:
            merged.append(g)
    return merged


def clean(word, case):
    w = TRAIL.sub('', word)
    if case == 'upper':
        w = w.upper()
        w = PUNCT_END.sub('', w) if w.endswith('.') else w   # capitals read cleaner without full stops
    elif case == 'lower':
        w = w.lower()
    return w


class Captions:
    def __init__(self, comp, words, style='pop', font='Montserrat', weight=800, size=84, case='upper',
                 color='#ffffff', accent='#ffd400', y=.65, width=None, max_chars=None, bump=True,
                 plate='#111111', plate_ink=None, stroke=None, shadow=True, keywords=(), prefix='cap',
                 enter=.18, tail=.35, bridge=.35, font_file=None, lines=2):
        if style not in ('pop', 'karaoke', 'word', 'calm', 'pill', 'accent'):
            raise ValueError('style: pop | karaoke | word | calm | pill | accent')
        self.c, self.words, self.style = comp, words, style
        self.font, self.weight, self.size, self.case = font, weight, size, case
        self.color, self.accent, self.y, self.bump = color, accent, y, bump
        self.plate, self.plate_ink = plate, plate_ink or color
        self.stroke, self.shadow, self.keywords = stroke, shadow, {k.lower() for k in keywords}
        self.prefix, self.enter, self.tail, self.bridge = prefix, enter, tail, bridge
        self.width = width or (min(comp.w - 180, 1300) if comp.w > comp.h else comp.w - 180)   # landscape: readable line length
        glyph = .74 if weight >= 800 or case == 'upper' else .6    # average glyph width in em (Cyrillic caps are wide)
        chars_per_line = max(8, int(self.width / (size * glyph)))
        self.max_chars = max_chars or (chars_per_line * (1 if style == 'word' else 2))
        self._hide, self._place = [], []
        self.lines = 1 if style == 'word' else lines
        self._font = None
        if font_file:   # measure real glyph widths: line breaks are decided here, not by the browser
            from PIL import ImageFont
            self._font = ImageFont.truetype(str(font_file), size)

    SHRINK = (1.0, .94, .88)   # a phrase may shrink up to 12 % before it is split (old pipeline did the same)

    def _fit(self, words):
        """(scale, lines) for the largest scale at which the phrase needs ≤ self.lines lines."""
        for k in self.SHRINK:
            lines = self._wrap(words, k)
            if len(lines) <= self.lines:
                return k, lines
        return 1.0, self._wrap(words, 1.0)

    def _wrap(self, words, scale=1.0):
        """Line breaks by measured width: the fewest lines, then the most even split; a line never ends
        on a clingy function word when another split fits (word margins .4em, accent bump 8 %)."""
        if not self._font:
            return None
        gap = self.size * scale * .4
        limit = self.width * .92 - (self.size * .9 if self.style == 'pill' else 0)
        widths = [self._font.getlength(w) * scale * (1.08 if self.bump else 1.0) for w in words]

        def span(a, b):
            return sum(widths[a:b]) + gap * max(0, b - a - 1)
        if span(0, len(words)) <= limit or len(words) == 1:
            return [words]
        best = None
        for k in range(1, len(words)):
            w1, w2 = span(0, k), span(k, len(words))
            if w1 > limit or w2 > limit:
                continue
            score = abs(w1 - w2) + (10 ** 6 if clingy(words[k - 1]) or joined(words[k - 1], words[k]) else 0)
            if best is None or score < best[0]:
                best = (score, k)
        if best:
            return [words[:best[1]], words[best[1]:]]
        lines, cur, width = [], [], 0.0     # more than two lines: greedy (the caller splits the phrase)
        for w, ww in zip(words, widths):
            if cur and width + gap + ww > limit:
                lines.append(cur)
                cur, width = [], 0.0
            width += (gap if cur else 0) + ww
            cur.append(w)
        if cur:
            lines.append(cur)
        return lines

    def hide(self, t0, t1):
        """No captions in [t0, t1): a phrase overlapping the start ends at t0, one starting inside appears
        right after t1 (dropped if less than 0.5 s would remain)."""
        self._hide.append((t0, t1))

    def place(self, t0, t1, y):
        """Phrases starting in [t0, t1) are centred at height fraction y (a face or a card occupies the default zone)."""
        self._place.append((t0, t1, y))

    def _y_for(self, t):
        for t0, t1, y in self._place:
            if t0 <= t < t1:
                return y
        return self.y

    def _visible(self, t0, t1):
        for h0, h1 in self._hide:
            if h0 <= t0 < h1:          # phrase starts under an insert: show the rest after it
                t0 = h1 + .05
            if t0 < h0 < t1:
                t1 = h0
        return (t0, t1) if t1 - t0 >= (.12 if self.style == 'word' else .35) else None

    def build(self):
        c, p = self.c, self.prefix
        fits = (lambda ws: len(self._fit([clean(x['word'], self.case) for x in ws])[1]) <= self.lines) if self._font else None
        groups = [[w] for w in self.words] if self.style == 'word' else group(self.words, self.max_chars, fits=fits)
        lh = 1.12
        shadow = ''
        if self.shadow and self.style == 'karaoke':   # text-shadow would paint over background-clip:text
            shadow = 'filter: drop-shadow(0 4px 10px rgba(0,0,0,.55));'
        elif self.shadow and self.style != 'pill':
            shadow = 'text-shadow: 0 4px 14px rgba(0,0,0,.55), 0 1px 2px rgba(0,0,0,.6);'
        stroke = f'-webkit-text-stroke: {self.stroke};' if self.stroke else ''
        c.css(f'''
.{p} {{ position: absolute; left: {(c.w - self.width) // 2}px; width: {self.width}px; text-align: center; opacity: 0;
  font: {self.weight} {self.size}px/{lh} {self.font}, sans-serif; color: {self.color}; letter-spacing: -.5px; {shadow} {stroke} z-index: 60; }}
.{p} .cb {{ display: block; transform: translateY(-50%); }}
.{p} .w {{ display: inline-block; margin: 0 .2em; transform-origin: 50% 70%; }}
.{p}.acc {{ line-height: 1.32; }}
.{p}.acc .w {{ margin: 0 .3em; }}
.{p} .plate {{ display: inline-block; background: {self.plate}; color: {self.plate_ink}; padding: .18em .5em .22em; border-radius: .5em;
  box-shadow: 0 10px 30px rgba(0,0,0,.25); }}
.{p} .kf {{ text-shadow: none; background: linear-gradient(90deg, {self.accent} 50%, {self.color} 50%); background-size: 200% 100%;
  background-position: 100% 0; -webkit-background-clip: text; background-clip: text; color: transparent; }}
''')
        html_parts, count, hidden_prev = [], 0, False
        for gi, g in enumerate(groups):
            lead = self.enter if self.style != 'word' else .02
            t0 = g[0]['start'] - lead
            nxt = groups[gi + 1][0]['start'] if gi + 1 < len(groups) else None
            t1 = g[-1]['end'] + self.tail
            if nxt is not None:   # bridge short pauses; never overlap the next phrase
                t1 = min(max(t1, nxt - lead if nxt - g[-1]['end'] < self.bridge else t1), nxt - lead)
            vis = self._visible(max(0, t0), t1)
            # The continuation of a sentence whose start an insert covered is not shown either
            # (the insert already carries that line; a fragment like «тенге вместо 39 000» reads as noise).
            cont = gi and hidden_prev and not PUNCT_END.search(groups[gi - 1][-1]['word'])
            hidden_prev = not vis or bool(cont)
            if not vis or cont:
                continue
            t0, t1 = vis
            if t1 - t0 < .12:
                continue
            gid = f'{p}{gi}'
            y = self._y_for(t0) * c.h
            words = [clean(w['word'], self.case) for w in g]
            size_fix = ''
            spans = ''.join(f'<span class="w{" kf" if self.style == "karaoke" else ""}" id="{gid}w{j}">{html.escape(t)}</span>'
                            for j, t in enumerate(words))
            scale, wrapped = self._fit(words) if self._font else (1.0, None)
            if scale < 1 and self.style != 'word':
                size_fix = f'font-size:{self.size * scale:.0f}px;'
            if wrapped and len(wrapped) > 1:   # explicit breaks where the measurement put them
                j, parts = 0, []
                for line in wrapped:
                    parts.append(''.join(f'<span class="w{" kf" if self.style == "karaoke" else ""}" id="{gid}w{j + k}">{html.escape(t)}</span>'
                                         for k, t in enumerate(line)))
                    j += len(line)
                spans = '<br>'.join(parts)
            inner = f'<span class="cb">' + (f'<span class="plate">{spans}</span>' if self.style == 'pill' else spans) + '</span>'
            if self.style == 'word':
                longest = max(len(x) for x in words)
                fit = min(1.0, self.width / (self.size * .62 * max(1, longest)))
                size_fix = f'font-size:{self.size * 1.5 * fit:.0f}px;'
            html_parts.append(f'<div class="{p}{" acc" if self.style == "accent" else ""}" id="{gid}" '
                              f'style="top:{y:.0f}px;{size_fix}">{inner}</div>')
            self._animate(gid, g, t0, t1)
            count += 1
        c.html('\n'.join(html_parts))
        return {'groups': count, 'style': self.style}

    def _animate(self, gid, g, t0, t1):
        c, s = self.c, self.style
        sel = f'#{gid}'
        y_shift = {}
        c.set0(sel, {'opacity': 0, **y_shift})
        ed = min({'calm': .35, 'word': .12, 'pill': .22}.get(s, .16), (t1 - t0) / 2)   # entrance never overlaps the exit
        if s == 'calm':
            c.fromto(sel, {'opacity': 0, 'y': 14, 'filter': 'blur(8px)', **y_shift},
                     {'opacity': 1, 'y': 0, 'filter': 'blur(0px)', 'duration': ed, 'ease': 'power2.out'}, t0, later=True)
        elif s == 'word':
            c.fromto(sel, {'opacity': 0, 'scale': .86}, {'opacity': 1, 'scale': 1, 'duration': ed, 'ease': 'back.out(2)'}, t0, later=True)
        elif s == 'pill':
            c.fromto(sel, {'opacity': 0, 'scale': .9, 'y': 10, **y_shift},
                     {'opacity': 1, 'scale': 1, 'y': 0, 'duration': ed, 'ease': 'back.out(1.8)'}, t0, later=True)
        else:
            c.fromto(sel, {'opacity': 0, 'y': 12}, {'opacity': 1, 'y': 0, 'duration': ed, 'ease': 'power2.out'}, t0, later=True)
        out_at = max(t0 + ed, t1 - .1)
        c.fromto(sel, {'opacity': 1}, {'opacity': 0, 'duration': round(max(.02, min(.1, t1 - out_at)), 3), 'ease': 'power1.in'}, out_at, later=True)
        for j, w in enumerate(g):
            wsel = f'#{gid}w{j}'
            ws, we = max(t0, w['start']), max(w['start'] + .08, min(w['end'], t1))
            if s == 'pop':
                c.set0(wsel, {'color': self.color, 'scale': 1})
                on = {'color': self.accent, 'duration': .06}
                if self.bump:
                    on['scale'] = 1.08
                c.fromto(wsel, {'color': self.color, 'scale': 1}, {**on, 'ease': 'power1.out'}, ws, later=True)
                c.fromto(wsel, {'color': self.accent, 'scale': on.get('scale', 1)}, {'color': self.color, 'scale': 1, 'duration': .08}, we, later=True)
            elif s == 'karaoke':
                c.set0(wsel, {'backgroundPosition': '100% 0'})
                c.fromto(wsel, {'backgroundPosition': '100% 0'}, {'backgroundPosition': '0% 0', 'duration': round(max(.08, we - ws), 3), 'ease': 'none'}, ws, later=True)
            elif s == 'pill':
                c.set0(wsel, {'opacity': .0})
                c.fromto(wsel, {'opacity': 0, 'y': 8}, {'opacity': 1, 'y': 0, 'duration': .12, 'ease': 'power2.out'}, max(0, ws - .04), later=True)
            elif s == 'accent':
                word = clean(w['word'], 'lower')
                if word in self.keywords or any(ch.isdigit() for ch in word):
                    c.set0(wsel, {'color': self.color, 'scale': 1})
                    c.fromto(wsel, {'color': self.color, 'scale': 1}, {'color': self.accent, 'scale': 1.06, 'duration': .18, 'ease': 'back.out(2)'}, ws, later=True)
