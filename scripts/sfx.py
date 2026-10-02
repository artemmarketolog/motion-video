#!/usr/bin/env python3
"""Synthesized SFX stem from an event list. Adult, dry, physical sounds; no toy bleeps.

  sfx.py render events.json work/sfx.wav     # stem for mix.json (role "sfx")
  sfx.py list                                 # presets and their parameters
  sfx.py audition /tmp/sfx-demo.wav           # every preset once, 0.8 s apart

events.json: {"seconds": 12.6, "seed": 7, "room": 0.22,
              "events": [{"t": 4.56, "sfx": "hit", "gain_db": -2, "pan": 0, "params": {"pitch": 1.0}}]}
Times are seconds on the video timeline (same numbers the GSAP timeline uses).
Variation by default (lesson of video 09: one identical hard sound many times in a row is irritating):
every event gets its own pitch ±4 %, length ±10 % and gain ±1.5 dB, and a 3 ms soft attack.
Per event: "attack_ms": 0 for a crisp transient, "vary": 0 for an exact repeat. "vary": 0 at the top
level restores the old fixed sound. A preset repeated 4+ times within 3 s is reported in "warnings".
Premium videos can bypass presets: synthesize from the motion function itself in build.py
(see references/sound-design.md, case hero-object-wheel) and add that file as another sfx track.
"""
import argparse
import inspect
import json
import math
import sys
import wave
from pathlib import Path

import numpy as np

SR = 48000


def t_axis(sec):
    return np.arange(int(sec * SR)) / SR


def norm(x):
    m = np.abs(x).max()
    return x / m if m else x


def band_noise(rng, sec, center, width_oct=1.2):
    n = int(sec * SR)
    spec = np.fft.rfft(rng.standard_normal(n))
    fr = np.fft.rfftfreq(n, 1 / SR)
    spec *= np.exp(-((np.log2(fr + 1) - math.log2(center)) ** 2) / (2 * (width_oct / 2) ** 2))
    return norm(np.fft.irfft(spec, n))


def sweep_noise(rng, sec, f0, f1, q=6.0):
    """Noise through a band-pass whose centre glides f0 -> f1 (per-sample RBJ biquad)."""
    n = int(sec * SR)
    x = rng.standard_normal(n)
    y = np.zeros(n)
    x1 = x2 = y1 = y2 = 0.0
    for i in range(n):
        w = 2 * math.pi * f0 * (f1 / f0) ** (i / n) / SR
        alpha = math.sin(w) / (2 * q)
        a0 = 1 + alpha
        v = (alpha * x[i] - alpha * x2 + 2 * math.cos(w) * y1 - (1 - alpha) * y2) / a0
        x2, x1, y2, y1 = x1, x[i], y1, v
        y[i] = v
    return norm(y)


# ── presets: each returns a mono float array (peak ≈ 1 before gain) ─────────
def click(rng, pitch=1.0, dur=0.09):
    """Mechanical brass/wood click (wheel pin on a flap). From the hero-object-wheel case."""
    t = t_axis(dur)
    s = np.zeros_like(t)
    for f, d, a in [(3150, .016, .45), (5230, .009, .28), (7450, .005, .15), (1080, .008, .55), (640, .013, .38), (190, .012, .32)]:
        s += a * np.sin(2 * np.pi * f * pitch * t + rng.uniform(0, 2 * np.pi)) * np.exp(-t / d)
    nb = rng.standard_normal(len(t)) * np.exp(-t / .0007)
    s += .6 * np.diff(nb, prepend=0)
    s *= 1 - np.exp(-t / .00015)
    return s / 2.2


def tick(rng, pitch=1.0):
    """Soft UI tick: short, dry, mid-high. For counters, cursor steps, list items."""
    t = t_axis(.035)
    s = .6 * np.sin(2 * np.pi * 2400 * pitch * t) * np.exp(-t / .004) + .4 * np.sin(2 * np.pi * 1200 * pitch * t) * np.exp(-t / .006)
    return s * (1 - np.exp(-t / .0002))


def tap(rng, pitch=1.0):
    """Finger tap on glass: low-passed click with a soft body."""
    t = t_axis(.08)
    s = .7 * np.sin(2 * np.pi * 180 * pitch * t) * np.exp(-t / .012) + .5 * np.sin(2 * np.pi * 900 * pitch * t) * np.exp(-t / .004)
    nb = rng.standard_normal(len(t)) * np.exp(-t / .0015)
    return norm(s + .25 * np.convolve(nb, np.ones(12) / 12, 'same'))


def key(rng, pitch=1.0):
    """Keyboard key: plastic tick + tiny thock."""
    t = t_axis(.06)
    nb = rng.standard_normal(len(t)) * np.exp(-t / .003)
    body = .5 * np.sin(2 * np.pi * 320 * pitch * t) * np.exp(-t / .01)
    return norm(.8 * np.diff(nb, prepend=0) + body)


def pop(rng, pitch=1.0):
    """Message bubble appears: soft rounded 'pop', rising sine, very short."""
    t = t_axis(.12)
    f = 420 * pitch * (1 + 1.2 * (1 - np.exp(-t / .03)))
    ph = 2 * np.pi * np.cumsum(f) / SR
    return np.sin(ph) * np.exp(-t / .03) * (1 - np.exp(-t / .002))


def notify(rng, pitch=1.0):
    """Incoming message: two soft mallet notes (a fifth), no bell ring-out."""
    out = np.zeros(int(.5 * SR))
    for k, (f, t0) in enumerate([(880, 0), (1320, .09)]):
        t = t_axis(.35)
        s = (np.sin(2 * np.pi * f * pitch * t) + .3 * np.sin(4 * np.pi * f * pitch * t)) * np.exp(-t / .09)
        s *= 1 - np.exp(-t / .002)
        i = int(t0 * SR)
        out[i:i + len(s)] += s * (1 if k == 0 else .8)
    return norm(out)


def whoosh(rng, dur=0.6, f0=300, f1=2400):
    """Air pass for a camera move or scene change; rises then falls."""
    s = sweep_noise(rng, dur, f0, f1, q=2.5)
    t = t_axis(dur)
    env = np.sin(np.pi * np.clip(t / dur, 0, 1)) ** 1.5
    return s * env


def swipe(rng, dur=0.25):
    """Short, higher whoosh for UI slides and text wipes."""
    return whoosh(rng, dur, 1200, 5000)


def air(rng, dur=1.0, center=900, attack=.12, decay=.22):
    """Breath of air before an impact (hero-object-wheel pull-out)."""
    s = band_noise(rng, dur, center)
    t = t_axis(dur)
    env = np.where(t < attack, (t / attack) ** 2, np.exp(-(t - attack) / decay))
    return s * env


def hit(rng, pitch=1.0, dur=0.9):
    """Cinematic low impact: pitched-down sine thump + short noise transient."""
    t = t_axis(dur)
    f = 58 * pitch * (1 + 1.6 * np.exp(-t / .03))
    body = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / .28)
    nb = band_noise(rng, dur, 2500, 2.0) * np.exp(-t / .012)
    return norm(body + .35 * nb) * (1 - np.exp(-t / .0008))


def sub(rng, pitch=1.0, dur=1.2):
    """808-like sub drop under a key word; glides down a fifth."""
    t = t_axis(dur)
    f = 55 * pitch * (1.5 - .5 * (1 - np.exp(-t / .25)))
    s = np.sin(2 * np.pi * np.cumsum(f) / SR)
    return np.tanh(1.6 * s) * np.exp(-t / .45) * (1 - np.exp(-t / .003))


def relay(rng, pitch=1.0):
    """Warm relay thump when a lamp or light switches on (hero-object-wheel case)."""
    t = t_axis(.2)
    s = .5 * np.sin(2 * np.pi * 120 * pitch * t) * np.exp(-t / .05) + .25 * np.sin(2 * np.pi * 820 * pitch * t) * np.exp(-t / .01)
    return norm(s * (1 - np.exp(-t / .0005)))


def shutter(rng, pitch=1.0):
    """Camera shutter: two mechanical clicks 45 ms apart."""
    out = np.zeros(int(.16 * SR))
    for t0, a in [(0, 1), (.045, .7)]:
        c = click(rng, 1.4 * pitch, .06)
        i = int(t0 * SR)
        out[i:i + len(c)] += a * c
    return norm(out)


def riser(rng, dur=1.5, f0=200, f1=4000):
    """Tension riser into a drop: filtered noise sweep + faint rising tone, ends abruptly."""
    s = sweep_noise(rng, dur, f0, f1, q=4.0)
    t = t_axis(dur)
    tone = np.sin(2 * np.pi * np.cumsum(f0 * (f1 / f0) ** (t / dur) / 4) / SR)
    env = (t / dur) ** 2
    return norm((s + .15 * tone) * env)


def shimmer(rng, dur=1.2):
    """Light sweep across gold or glass: high, airy swell (use quietly)."""
    s = band_noise(rng, dur, 7000, 1.0)
    t = t_axis(dur)
    return s * np.sin(np.pi * t / dur) ** 2


def paper(rng, dur=0.35):
    """Paper or card slide: soft broadband rustle with grainy crackle; for cards, photos, pages."""
    t = t_axis(dur)
    grain = rng.standard_normal(len(t)) * (rng.random(len(t)) < .08)
    s = .6 * band_noise(rng, dur, 3000, 2.5) + .5 * np.convolve(grain, np.ones(24) / 24, 'same')
    return norm(s) * np.sin(np.pi * t / dur) ** .8


def cloth(rng, dur=0.5):
    """Fabric or soft body move: low, velvety swish; calm editorial transitions."""
    t = t_axis(dur)
    return band_noise(rng, dur, 450, 1.6) * np.sin(np.pi * t / dur) ** 2


def glass(rng, pitch=1.0):
    """Glass touch: short clear partials, damped quickly (no long bell)."""
    t = t_axis(.4)
    s = sum(a * np.sin(2 * np.pi * f * pitch * t) * np.exp(-t / d)
            for f, d, a in [(2100, .09, .6), (3470, .05, .35), (5320, .03, .2)])
    return norm(s * (1 - np.exp(-t / .0006)))


def soft_hit(rng, pitch=1.0):
    """Gentle felt thud for calm presentations: an accent without cinema drama."""
    t = t_axis(.35)
    s = np.sin(2 * np.pi * 95 * pitch * t) * np.exp(-t / .07) + .2 * band_noise(rng, .35, 700, 1.5) * np.exp(-t / .02)
    return norm(s * (1 - np.exp(-t / .002)))


PRESETS = {f.__name__: f for f in (click, tick, tap, key, pop, notify, whoosh, swipe, air, hit, sub, relay, shutter,
                                      riser, shimmer, paper, cloth, glass, soft_hit)}


def render(events_path, out):
    spec = json.loads(Path(events_path).read_text())
    seconds = float(spec['seconds'])
    rng = np.random.default_rng(int(spec.get('seed', 7)))
    vrng = np.random.default_rng(int(spec.get('seed', 7)) + 1)   # separate stream: vary=0 keeps the old sound exactly
    vary_all = float(spec.get('vary', 1))
    n = int(round(seconds * SR))
    left, right = np.zeros(n), np.zeros(n)
    used = {}
    for ev in spec['events']:
        name = ev['sfx']
        if name not in PRESETS:
            raise ValueError(f'unknown sfx {name}; see sfx.py list')
        params = dict(ev.get('params', {}))
        vary = vary_all * float(ev.get('vary', 1))
        gain = float(ev.get('gain_db', 0))
        if vary:
            accepts = inspect.signature(PRESETS[name]).parameters
            if 'pitch' in accepts:
                params['pitch'] = params.get('pitch', 1.0) * (1 + .04 * vary * vrng.uniform(-1, 1))
            if 'dur' in accepts:
                params['dur'] = params.get('dur', accepts['dur'].default) * (1 + .1 * vary * vrng.uniform(-1, 1))
            gain += 1.5 * vary * vrng.uniform(-1, 1)
        sig = PRESETS[name](rng, **params)
        attack = int(float(ev.get('attack_ms', 3 if vary_all else 0)) * SR / 1000)
        if attack:
            sig = sig.copy()
            sig[:attack] *= np.linspace(0, 1, min(attack, len(sig)))
        sig = sig * 10 ** (gain / 20) * .5
        pan = max(-1.0, min(1.0, float(ev.get('pan', 0))))
        i = int(round(float(ev['t']) * SR))
        if i >= n:
            continue
        # A preset can pre-roll (air before an impact): 'lead' seconds before t.
        i -= int(round(float(ev.get('lead', 0)) * SR))
        j0, j1 = max(0, i), min(n, i + len(sig))
        seg = sig[j0 - i:j1 - i]
        left[j0:j1] += seg * math.cos((pan + 1) * math.pi / 4)
        right[j0:j1] += seg * math.sin((pan + 1) * math.pi / 4)
        used[name] = used.get(name, 0) + 1
    room = float(spec.get('room', .22))
    if room:
        for ch in (left, right):
            ch += room * np.roll(ch, int(.011 * SR)) * 1 + room * .55 * np.roll(ch, int(.023 * SR))
    st = np.stack([left, right], 1)
    peak = float(np.abs(st).max())
    if peak > .99:
        st *= .99 / peak
    with wave.open(str(out), 'wb') as f:
        f.setnchannels(2)
        f.setsampwidth(2)
        f.setframerate(SR)
        f.writeframes((np.clip(st, -1, 1) * 32767).astype('<i2').tobytes())
    warnings = []
    for name in used:
        times = sorted(float(e['t']) for e in spec['events'] if e['sfx'] == name)
        for i in range(len(times) - 3):
            if times[i + 3] - times[i] <= 3:
                k = sum(1 for t in times if times[i] <= t <= times[i] + 3)
                warnings.append(f'{name} x{k} within 3 s from {times[i]:.2f}: one sound per group, or alternate presets')
                break
    for w in warnings:
        print(f'sfx warning: {w}', file=sys.stderr)
    return {'file': str(out), 'events': len(spec['events']), 'presets': used, 'peak_before_limit': round(peak, 3),
            'warnings': warnings}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub_ = parser.add_subparsers(dest='cmd', required=True)
    r = sub_.add_parser('render')
    r.add_argument('events')
    r.add_argument('out')
    sub_.add_parser('list')
    a = sub_.add_parser('audition')
    a.add_argument('out')
    args = parser.parse_args()
    if args.cmd == 'list':
        for name, f in PRESETS.items():
            params = [p for p in inspect.signature(f).parameters if p != 'rng']
            print(f'{name:8} {", ".join(params):28} {f.__doc__.splitlines()[0]}')
        return
    if args.cmd == 'audition':
        tmp = Path(args.out).with_suffix('.events.json')
        events = [{'t': .3 + .8 * i, 'sfx': name} for i, name in enumerate(PRESETS)]
        tmp.write_text(json.dumps({'seconds': .8 * len(PRESETS) + 1.5, 'events': events}))
        print(json.dumps(render(tmp, args.out), ensure_ascii=False))
        return
    print(json.dumps(render(args.events, args.out), ensure_ascii=False))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError) as e:
        print(f'sfx: {e}', file=sys.stderr)
        sys.exit(2)
