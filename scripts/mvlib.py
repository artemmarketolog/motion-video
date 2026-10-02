"""Small helpers for build.py generators of HyperFrames videos (functions, not a framework).

    import sys; sys.path.insert(0, '<motion-video>/scripts')
    from mvlib import Comp, Words

    c = Comp(1080, 1920, seconds=12.0, title='YOUR BRAND — пример', level='medium')
    c.font('onest', 600, 700)
    c.css('#t1 { top: 700px; font: 700 96px/1.05 Onest; }')
    s1 = c.scene(0.0)                       # anchor for cache segments; returns start time
    c.html('<div class="cap" id="t1">Текст</div>')
    c.enter('#t1', s1 + 0.4)                # entrance by level (see TEXT_IN)
    c.exit('#t1', s1 + 2.6)
    c.sfx(s1 + 0.4, 'swipe', gain_db=-8)    # events.json → sfx.py render
    c.grain(); c.vignette()
    c.write('/ABS/VIDEO', mix={...})        # index.html, video-spec.json, events.json, mix.json

Everything is a pure function of timeline time: one paused GSAP timeline, fromTo with
explicit start states, no Math.random / Date / onUpdate side effects. Scene-local
time (every scene tween positioned as scene_start + dt) lets unchanged scenes hit
the render cache after an earlier scene changes length.
"""
import json
import math
import os
import random
import shutil
from pathlib import Path
from skill_config import DATA_DIR, CACHE_DIR, ENV_FILE, RUNTIME, setting, require_key

SKILL = Path(__file__).resolve().parents[1]
FONTS = SKILL / 'assets/fonts'
GSAP = RUNTIME / 'node_modules/gsap/dist/gsap.min.js'

# Typeface files shipped with the skill (all SIL OFL 1.1, Cyrillic included).
FONT_FILES = {
    ('onest', 400): 'Onest-Regular.ttf', ('onest', 600): 'Onest-SemiBold.ttf', ('onest', 700): 'Onest-Bold.ttf',
    ('cormorant', 600): 'CormorantGaramond-SemiBold.ttf', ('cormorant', 700): 'CormorantGaramond-Bold.ttf',
    ('manrope', 400): 'Manrope-Variable.ttf', ('manrope', 600): 'Manrope-Variable.ttf', ('manrope', 700): 'Manrope-Variable.ttf',
    ('montserrat', 500): 'Montserrat-Medium.ttf', ('montserrat', 900): 'Montserrat-Black.ttf',
}
# Main delivery formats. Safe margins (top, right, bottom, left) keep text clear of platform UI:
# 9:16 Stories/Reels 180/70/240/70; feed 4:5 and 3:4 (Instagram profile grid crops to 3:4) and 1:1 60 px;
# 16:9 YouTube/presentations 80/90.
FORMATS = {
    '9:16': {'size': (1080, 1920), 'safe': (180, 70, 240, 70), 'use': 'Reels, Stories, TikTok, Shorts'},
    '4:5': {'size': (1080, 1350), 'safe': (60, 60, 60, 60), 'use': 'Instagram/Facebook feed (max vertical in feed)'},
    '3:4': {'size': (1080, 1440), 'safe': (60, 60, 60, 60), 'use': 'Instagram feed and profile grid (3:4)'},
    '1:1': {'size': (1080, 1080), 'safe': (60, 60, 60, 60), 'use': 'feed, carousels, Telegram'},
    '16:9': {'size': (1920, 1080), 'safe': (80, 90, 80, 90), 'use': 'YouTube, presentations, screens'},
}


def orientation(w, h):
    r = w / h
    return 'landscape' if r > 1.2 else 'square' if r > 0.95 else 'portrait'


def safe_box(fmt):
    """(left, top, right, bottom) of the text-safe area in pixels for a format key."""
    w, h = FORMATS[fmt]['size']
    t, r, b, l = FORMATS[fmt]['safe']
    return l, t, w - r, h - b


FAMILY = {'onest': 'Onest', 'cormorant': 'Cormorant', 'manrope': 'Manrope', 'montserrat': 'Montserrat'}

# Text entrances per level. Simple = one fade-rise; medium = blur-in; premium adds scale settle.
TEXT_IN = {
    'simple': ({'opacity': 0, 'y': 20}, {'opacity': 1, 'y': 0, 'duration': .45, 'ease': 'power2.out'}),
    'medium': ({'opacity': 0, 'y': 22, 'filter': 'blur(10px)'}, {'opacity': 1, 'y': 0, 'filter': 'blur(0px)', 'duration': .5, 'ease': 'power3.out'}),
    'premium': ({'opacity': 0, 'y': 26, 'scale': 1.04, 'filter': 'blur(12px)'},
                {'opacity': 1, 'y': 0, 'scale': 1, 'filter': 'blur(0px)', 'duration': .6, 'ease': 'power3.out'}),
}
TEXT_OUT = {
    'simple': {'opacity': 0, 'duration': .3, 'ease': 'power1.in'},
    'medium': {'opacity': 0, 'filter': 'blur(8px)', 'duration': .3, 'ease': 'power2.in'},
    'premium': {'opacity': 0, 'filter': 'blur(10px)', 'y': -8, 'duration': .35, 'ease': 'power2.in'},
}


def js(v):
    return json.dumps(v, ensure_ascii=False)


class Words:
    """Word timings from voice.py (<voice>.words.json), shifted by where the voice starts in the video."""

    def __init__(self, path, delay=0.0):
        self.words = json.loads(Path(path).read_text())
        self.delay = delay

    def at(self, word, nth=0, edge='start'):
        norm = lambda s: s.lower().strip('.,!?:;«»"()—–-').replace('ё', 'е')
        hits = [w for w in self.words if norm(w['word']) == norm(word)]
        if len(hits) <= nth:
            raise KeyError(f'word not found: {word} (#{nth})')
        return round(hits[nth][edge] + self.delay, 3)

    def end(self):
        return round(self.words[-1]['end'] + self.delay, 3)


class Comp:
    def __init__(self, width, height, seconds, fps=30, title='video', level='medium', background='#000'):
        if level not in TEXT_IN:
            raise ValueError('level: simple | medium | premium')
        self.w, self.h, self.fps, self.seconds = width, height, fps, round(seconds, 3)
        self.title, self.level, self.background = title, level, background
        self._css, self._html, self._js, self._pre, self._under, self._media = [], [], [], [], [], []
        self.fonts, self.anchors, self.events, self.copies = [], [0.0], [], []
        self.segment_seconds = 2

    # ── content ─────────────────────────────────────────────────────────────
    def font(self, name, *weights):
        for w in weights:
            f = FONT_FILES[(name, w)]
            self.copies.append((FONTS / f, f'assets/fonts/{f}'))
            self.fonts.append(f"@font-face {{ font-family: {FAMILY[name]}; src: url('assets/fonts/{f}'); font-weight: {w}; }}")

    def font_file(self, family, weight, path):
        """A brand font that is not shipped with the skill (client file + its licence stays with the client)."""
        rel = self.asset(path, f'assets/fonts/{Path(path).name}')
        self.fonts.append(f"@font-face {{ font-family: '{family}'; src: url('{rel}'); font-weight: {weight}; }}")

    def asset(self, src, rel):
        """Copy (hard-link when possible) a local file into the video folder: the render sandbox
        cannot read outside it and cannot follow symlinks."""
        self.copies.append((Path(src), rel))
        return rel

    def clip(self, src, t, dur, media_start=0.0, zoom=1.0, drift=0.0, fit='cover', name=None):
        """A footage clip on the timeline: source `src` from `media_start` for `dur` s at time `t`.
        fit='cover' fills the frame (crop); fit='blur' keeps the whole shot centred over a blurred,
        darkened copy of itself (vertical footage in 16:9, old --mode fit).
        zoom crops edges (bank atoms already carry the anti-watermark zoom); drift adds a slow push.
        Every clip start is a cache anchor, so replacing one shot re-renders only that shot."""
        i = getattr(self, '_nclips', 0)
        self._nclips = i + 1
        rel = self.asset(src, f'assets/footage/{name or Path(src).name}')
        t, dur = round(t, 4), round(dur, 4)
        if not getattr(self, '_clip_css', False):
            self._clip_css = True
            self.css('.vw { position: absolute; inset: 0; overflow: hidden; } '
                     '.vw video { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; } '
                     '.vw video.fg { object-fit: contain; } '
                     '.vw .bgw { position: absolute; inset: -6%; filter: blur(38px) brightness(.62) saturate(1.1); }')
        timing = (f'muted playsinline data-start="{t}" data-duration="{dur}" data-media-start="{round(media_start, 4)}"')
        if fit == 'blur':
            self.media(f'<div class="vw" id="vw{i}"><div class="bgw"><video id="vb{i}" class="clip" src="{rel}" {timing} '
                       f'data-track-index="{3 + i % 2}"></video></div><video id="v{i}" class="clip fg" src="{rel}" {timing} '
                       f'data-track-index="{1 + i % 2}"></video></div>')
        else:
            self.media(f'<div class="vw" id="vw{i}"><video id="v{i}" class="clip" src="{rel}" {timing} '
                       f'data-track-index="{1 + i % 2}"></video></div>')
        self.scene(t)
        self.set0(f'#vw{i}', {'scale': zoom})
        if drift:
            self.fromto(f'#vw{i}', {'scale': zoom}, {'scale': round(zoom * (1 + drift), 4), 'duration': dur, 'ease': 'none'}, t, later=True)
        return f'#vw{i}' 

    def media(self, text):
        """<video>/<audio> clips with their own data-start: placed directly in the root, under the
        graphics layer (a video inside a timed parent is rejected: video_nested_in_timed_element)."""
        self._media.append(text)

    def css(self, text):
        self._css.append(text)

    def html(self, text):
        self._html.append(text)

    def tl(self, code):
        """Raw GSAP call on the shared timeline, e.g. c.tl(".to('#a', {x: 10, duration: 1}, 2.0)")."""
        self._js.append('tl' + code + ';')

    def set0(self, sel, props):
        """Baseline state at t=0 inside the timeline (seek-safe start pose)."""
        self._js.append(f'tl.set({js(sel)}, {js(props)}, 0);')

    def fromto(self, sel, frm, to, at, later=False):
        to = dict(to)
        if later:
            to['immediateRender'] = False
        self._js.append(f'tl.fromTo({js(sel)}, {js(frm)}, {js(to)}, {round(at, 3)});')

    def enter(self, sel, at, level=None, **override):
        frm, to = TEXT_IN[level or self.level]
        to = {**to, **override}
        self.fromto(sel, frm, to, at)

    def exit(self, sel, at, level=None, **override):
        to = {**TEXT_OUT[level or self.level], **override}
        self._js.append(f'tl.to({js(sel)}, {js(to)}, {round(at, 3)});')

    def gold_sweep(self, sel, at, dur=1.2):
        """Highlight travelling through background-clip:text gold (class .gold)."""
        self.fromto(sel, {'backgroundPosition': '100% 0'}, {'backgroundPosition': '0% 0', 'duration': dur, 'ease': 'sine.inOut'}, at, later=True)

    def camera(self, sel, keys):
        """keys: [(t, {'x':..,'y':..,'scale':..,'rotation':..}, ease), ...]; first key is the start pose.
        Each leg is its own fromTo with explicit from-state (seek-safe, no relative values)."""
        t0, p0, _ = keys[0]
        self.set0(sel, p0)
        for (ta, pa, _), (tb, pb, ease) in zip(keys, keys[1:]):
            self.fromto(sel, pa, {**pb, 'duration': round(tb - ta, 3), 'ease': ease}, ta, later=True)

    def scene(self, start):
        """Mark a scene start: a cache-segment anchor. Position that scene's tweens as start + dt."""
        start = round(round(start * self.fps) / self.fps, 4)
        if start not in self.anchors:
            self.anchors.append(start)
        return start

    def sfx(self, t, name, gain_db=0.0, pan=0.0, lead=0.0, **params):
        self.events.append({'t': round(t, 3), 'sfx': name, 'gain_db': gain_db, 'pan': pan, 'lead': lead, 'params': params})

    # ── texture ─────────────────────────────────────────────────────────────
    def grain(self, opacity=None, seed=11, size=384, blend='overlay'):
        """Film grain: a seeded noise tile shifted every frame. Restarts at every scene anchor so
        scenes stay independent for the cache. Level default: simple none, medium .07, premium .12."""
        if opacity is None:
            opacity = {'simple': 0, 'medium': .07, 'premium': .12}[self.level]
        if not opacity:
            return
        self._grain = (seed, size)
        self.css(f'#grain {{ position: absolute; inset: 0; background: url(assets/grain.png); opacity: {opacity}; '
                 f'mix-blend-mode: {blend}; pointer-events: none; z-index: 90; }}')
        self._pre.append('<div id="grain"></div>')
        self._grain_on = True

    def vignette(self, strength=.6, z=0):
        """Darkened edges. Painted under the content (titles stay above it: a vignette over text
        fails the occlusion check and dims the words)."""
        self.css(f'#vig {{ position: absolute; inset: 0; pointer-events: none; z-index: {z}; '
                 f'background: radial-gradient({int(self.w * 1.05)}px {int(self.h * .8)}px at 50% 50%, transparent 45%, rgba(0,0,0,{strength}) 100%); }}')
        self._under.append('<div id="vig"></div>')

    # ── output ──────────────────────────────────────────────────────────────
    def _grain_js(self):
        if not getattr(self, '_grain_on', False):
            return ''
        bounds = sorted(self.anchors) + [self.seconds]
        out = []
        for a, b in zip(bounds, bounds[1:]):
            n = max(1, round((b - a) * self.fps))
            out.append(f"tl.fromTo('#grain', {{backgroundPosition: '0px 0px'}}, {{backgroundPosition: '{149 * n}px {233 * n}px', "
                       f"duration: {round(b - a, 4)}, ease: 'steps({n})', immediateRender: {'true' if a == 0 else 'false'}}}, {a});")
        return '\n'.join(out)

    def write(self, project, mix=None, spec_extra=None):
        project = Path(project).resolve()
        (project / 'assets/fonts').mkdir(parents=True, exist_ok=True)
        shutil.copy2(GSAP, project / 'assets/gsap.min.js')
        for src, rel in self.copies:
            dest = project / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            if not dest.exists() or dest.stat().st_size != Path(src).stat().st_size:
                if dest.exists():
                    dest.unlink()
                try:
                    os.link(src, dest)
                except OSError:
                    shutil.copy2(src, dest)
        if getattr(self, '_grain_on', False):
            write_grain(project / 'assets/grain.png', *self._grain)
        html = f'''<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width={self.w}, height={self.h}">
<title>{self.title}</title>
<script src="assets/gsap.min.js"></script>
<style>
{chr(10).join(self.fonts)}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
html, body {{ width: {self.w}px; height: {self.h}px; overflow: hidden; background: {self.background}; }}
#root {{ width: 100%; height: 100%; position: relative; overflow: hidden; }}
.scene {{ position: absolute; inset: 0; overflow: hidden; }}
{chr(10).join(self._css)}
</style>
</head>
<body>
<div id="root" data-composition-id="main" data-start="0" data-duration="{self.seconds}" data-width="{self.w}" data-height="{self.h}" data-fps="{self.fps}">
{chr(10).join(self._media)}
<section id="film" class="scene clip" data-start="0" data-duration="{self.seconds}" data-track-index="1">
{chr(10).join(self._under)}
{chr(10).join(self._html)}
{chr(10).join(self._pre)}
</section>
</div>
<script>
const tl = gsap.timeline({{ paused: true }});
{chr(10).join(self._js)}
{self._grain_js()}
window.__timelines = window.__timelines || {{}};
window.__timelines['main'] = tl;
</script>
</body>
</html>
'''
        (project / 'index.html').write_text(html)
        spec = {'width': self.w, 'height': self.h, 'fps': self.fps, 'seconds': self.seconds,
                'expect_audio': bool(mix or self.events), 'segment_seconds': self.segment_seconds,
                'anchors': sorted(self.anchors), 'level': self.level, **(spec_extra or {})}
        (project / 'video-spec.json').write_text(json.dumps(spec, ensure_ascii=False, indent=2) + '\n')
        if self.events:
            (project / 'events.json').write_text(json.dumps({'seconds': self.seconds, 'seed': 7, 'room': .2,
                                                             'events': self.events}, ensure_ascii=False, indent=1))
        if mix is not None:
            (project / 'mix.json').write_text(json.dumps({'seconds': self.seconds, **mix}, ensure_ascii=False, indent=2))
        return {'index': str(project / 'index.html'), 'seconds': self.seconds, 'anchors': sorted(self.anchors),
                'events': len(self.events), 'bytes': len(html)}


def write_grain(path, seed=11, size=384):
    """Seeded grey noise tile (PNG, no numpy/Pillow needed)."""
    import struct
    import zlib
    rng = random.Random(seed)
    rows = b''.join(b'\x00' + bytes(max(0, min(255, int(rng.gauss(128, 42)))) for _ in range(size)) for _ in range(size))

    def chunk(tag, data):
        return struct.pack('>I', len(data)) + tag + data + struct.pack('>I', zlib.crc32(tag + data) & 0xffffffff)
    png = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', size, size, 8, 0, 0, 0, 0)) +\
        chunk(b'IDAT', zlib.compress(rows, 9)) + chunk(b'IEND', b'')
    Path(path).write_bytes(png)


def ease_samples(values, fps=60):
    """Bake a numeric curve (list sampled at `fps`) into a GSAP custom ease string body.
    Use for physically simulated motion (wheel spin, spring) without onUpdate."""
    return '[' + ','.join(f'{v:.4f}' for v in values) + ']'
