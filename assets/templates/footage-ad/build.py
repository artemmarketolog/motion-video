#!/usr/bin/env python3
"""Template «footage-ad»: advertising montage from a shot bank + voice + captions + motion inserts.

Everything is data in creative.json (see references/footage.md); this file does not need editing.
  python3 build.py --plan-shows      # phrases of the voice for "sync": true (one shot per phrase)
  python3 build.py && python3 <motion-video>/scripts/mv.py build $PWD -o output/master-r1.mp4
Replacing a shot, a caption style or an insert re-renders only the affected shots (every cut is a cache
anchor); changing music or voice volume is `mv.py audio` (seconds).
"""
import json
import subprocess
import sys
from pathlib import Path

SK = Path(Path(__file__).with_name('.motion-skill').read_text().strip()) / 'scripts'
sys.path.insert(0, str(SK))
from mvblocks import Blocks, Brand  # noqa: E402
from mvcaptions import Captions, load_words  # noqa: E402
from mvlib import FORMATS, Comp  # noqa: E402

HERE = Path(__file__).resolve().parent
FORMATS_OK = ('9:16', '4:5', '3:4', '1:1', '16:9')   # 9:16 native; 4:5/3:4/1:1 crop the centre; 16:9 = shot over its blurred copy
from skill_config import STUDIO  # noqa: E402
VC = STUDIO   # clients.json, shots/, music/, fonts/ of your studio
FONTS = SK.parent / 'assets/fonts'
FONT_FILES = {  # family → {weight: file}; add your own brand fonts here (files in <studio>/fonts/)
    'Montserrat': {w: FONTS / f'Montserrat-{n}.ttf' for w, n in ((400, 'Regular'), (500, 'Medium'), (600, 'SemiBold'),
                                                            (700, 'Bold'), (800, 'ExtraBold'), (900, 'Black'))},
}
SKILL_FONTS = {'Onest': 'onest', 'Manrope': 'manrope', 'Cormorant': 'cormorant'}


def main():
    cfg = json.loads((HERE / 'creative.json').read_text())
    clients = json.loads((VC / 'clients.json').read_text()) if (VC / 'clients.json').is_file() else {}
    client = clients.get(cfg.get('client'), {})
    over = client.get('overrides', {})
    fmt = cfg.get('format', '9:16')
    W, H = FORMATS[fmt]['size']
    (HERE / 'work').mkdir(exist_ok=True)

    # ── voice: an existing take (mp3 + words.json) or a fresh one through voice.py ──
    v = cfg['voice']
    tempo = float(v.get('tempo', 1.15))
    vstart = float(v.get('start', 0.0))
    if 'script' in v:   # new take: paid, cached by exact text
        out = subprocess.run([sys.executable, SK / 'voice.py', 'tts', '--voice', v.get('voice', client.get('tts_voice', 'narrator')),
                              '--file', HERE / v['script'], '--tempo', str(tempo), '--out', HERE / 'work/voice.wav'],
                             capture_output=True, text=True, check=True)
        words = load_words(HERE / 'work/voice.words.json', delay=vstart)
    else:               # reuse an approved take from the old pipeline
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', v['mp3'], '-af', f'atempo={tempo},aresample=48000', '-ac', '1',
                        HERE / 'work/voice.wav'], check=True)
        words = load_words(v['words'], delay=vstart, tempo=tempo)
    total = round(words[-1]['end'] + float(cfg.get('tail', .6)), 3)

    c = Comp(W, H, seconds=round(round(total * 30) / 30, 4), title=cfg.get('title', 'footage ad'), level=cfg.get('level', 'medium'),
             background='#000')

    # ── shots ──
    shots_dir = Path(cfg['shots_dir'])
    seg = float(cfg.get('seg_len', over.get('seg_len', 3)))
    edl = [dict(x) for x in cfg['edl']]
    if cfg.get('sync'):
        # «кадр под фразу»: one shot per show, len = interval to the next show (pause included),
        # the first from zero, the last to the end (references/footage-bank.md).
        shows = split_shows(words)
        if len(edl) != len(shows):
            raise SystemExit(f'sync: {len(shows)} shows but {len(edl)} shots; run `python3 build.py --plan-shows`')
        starts = [0.0] + [sh[0]['start'] for sh in shows[1:]] + [c.seconds]
        for x, a, b in zip(edl, starts, starts[1:]):
            x['len'] = round(b - a, 3)
    else:
        # fit: every shot seg_len (or its own len); trim the middle, keep the hook and the ending
        for x in edl:
            x['len'] = float(x.get('len', seg))
        while sum(x['len'] for x in edl) - edl[-1]['len'] >= c.seconds and len(edl) > 2:
            edl.pop(len(edl) // 2)
        if sum(x['len'] for x in edl) < c.seconds:
            raise SystemExit(f"edit list covers {sum(x['len'] for x in edl):.1f} s of {c.seconds} s: add shots")
    t, cuts = 0.0, []
    zoom = float(cfg.get('zoom', 1.0))   # bank atoms already carry the anti-watermark zoom (prepare_shots)
    drift = float(cfg.get('drift', .03))
    fit = cfg.get('fit', 'blur' if W > H else 'cover')
    for k, x in enumerate(edl):
        dur = x['len'] if k < len(edl) - 1 else round(c.seconds - t, 4)
        src = shots_dir / x['shot']
        if not src.exists():
            raise SystemExit(f'missing shot {src}')
        have = float(subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', src],
                                    capture_output=True, text=True).stdout or 0) - float(x.get('from', 0))
        if dur > have + .04:
            raise SystemExit(f'{src.name}: slot {dur:.2f} s is longer than the shot ({have:.2f} s); pick a longer shot or shorten len')
        c.clip(src, t, round(dur, 4), media_start=float(x.get('from', 0)), zoom=zoom, drift=drift, fit=fit, name=f'{k:02d}_{src.name}')
        cuts.append(t)
        t = round(t + dur, 4)

    # ── fonts and brand ──
    cap_cfg = {**caption_defaults(over), **cfg.get('captions', {})}
    for fam, weight in {(cap_cfg['font'], cap_cfg['weight']), (cfg.get('brand', {}).get('font', cap_cfg['font']), cfg.get('brand', {}).get('weight', cap_cfg['weight']))}:
        add_font(c, fam, weight)
    brand = Brand(**{**{'font': cap_cfg['font'], 'weight': cap_cfg['weight']}, **cfg.get('brand', {})})
    blocks = Blocks(c, brand)
    cap = Captions(c, words, font_file=font_path(cap_cfg['font'], cap_cfg['weight']), **{k: v for k, v in cap_cfg.items() if k in (
        'style', 'font', 'weight', 'size', 'case', 'color', 'accent', 'y', 'bump', 'plate', 'plate_ink', 'keywords', 'max_chars', 'stroke')})

    # ── inserts, cards, bars ──
    for ins in cfg.get('inserts', []):
        ins = dict(ins)
        kind = ins.pop('type')
        at = at_time(ins.pop('at', None), ins.pop('at_word', None), ins.pop('nth', 0), words)
        span = getattr(blocks, kind)(t=at, **ins)
        cap.hide(*span)
    for card in cfg.get('cards', []):
        blocks.card(**card)
    if cfg.get('bars'):
        blocks.bars(**cfg['bars'])
    for z in cfg.get('caption_zones', []):
        cap.place(z['from'], z['to'], z['y'])
    cap.build()

    # ── sound ──
    tracks = [{'file': 'work/voice.wav', 'role': 'voice', 'start': vstart}]
    m = cfg.get('music')
    if m:
        lv = VC / 'music/levels.json'
        levels = json.loads(lv.read_text()) if lv.is_file() else {}
        gain = m.get('gain_db', levels.get(Path(m['file']).name, levels.get('default', -25)) + 6)  # +6: carve replaces blanket ducking
        rel = c.asset(m['file'], f'assets/music/{Path(m["file"]).name}')
        tracks.append({'file': rel, 'role': 'music', 'offset': m.get('offset', 0), 'gain_db': gain,
                       'fade_in': m.get('fade_in', .8), 'fade_out': m.get('fade_out', .8), 'carve': m.get('carve', .5)})
    c.grain(cfg.get('grain', 0))
    result = c.write(HERE, mix={'tracks': tracks + ([{'file': 'work/sfx.wav', 'role': 'sfx'}] if c.events else [])},
                     spec_extra={'quality': cfg.get('quality', 'standard'), 'format': fmt})
    # Cache grid: cuts on a uniform integer grid → one segment per shot; otherwise a 2 s grid from zero.
    # Either way all dirty segments render in one HyperFrames run and a replaced shot touches 1–2 segments.
    uniform = float(seg).is_integer() and all(abs(a / seg - round(a / seg)) < 1e-6 for a in cuts)
    spec = json.loads((HERE / 'video-spec.json').read_text())
    spec['segment_seconds'] = int(seg) if uniform else 2
    spec['anchors'] = [0.0]
    (HERE / 'video-spec.json').write_text(json.dumps(spec, ensure_ascii=False, indent=2) + '\n')
    if c.events:
        subprocess.run([sys.executable, SK / 'sfx.py', 'render', HERE / 'events.json', HERE / 'work/sfx.wav'], check=True, capture_output=True)
    print(json.dumps({**result, 'shots': len(edl), 'words': len(words)}, ensure_ascii=False))


def split_shows(words, cut_min=1.7, force=2.85, glue=.8):
    """Voice → shows (≤ ~3 s phrases): cut at punctuation once ≥ 1.7 s, force after 2.85 s, glue < 0.8 s."""
    shows, cur = [], []
    for w in words:
        if cur:
            if cur[-1]['word'][-1:] in '.,!?;:' and cur[-1]['end'] - cur[0]['start'] >= cut_min:
                shows.append(cur)
                cur = []
            elif w['end'] - cur[0]['start'] > force:
                # too long: cut at the last punctuation inside (if it leaves ≥ 1 s), else here
                k = max((i for i, x in enumerate(cur) if x['word'][-1:] in '.,!?;:' and x['end'] - cur[0]['start'] >= 1.0), default=None)
                if k is not None and k < len(cur) - 1:
                    shows.append(cur[:k + 1])
                    cur = cur[k + 1:]
                else:
                    shows.append(cur)
                    cur = []
        cur.append(w)
    if cur:
        shows.append(cur)
    out = []
    for sh in shows:
        if out and sh[-1]['end'] - sh[0]['start'] < glue:
            out[-1] += sh
        else:
            out.append(sh)
    return out


def plan_shows():
    cfg = json.loads((HERE / 'creative.json').read_text())
    v = cfg['voice']
    tempo = float(v.get('tempo', 1.15))
    words = load_words(HERE / 'work/voice.words.json', delay=float(v.get('start', 0))) if 'script' in v else\
        load_words(v['words'], delay=float(v.get('start', 0)), tempo=tempo)
    for i, sh in enumerate(split_shows(words)):
        print(f"{i:2d}  {sh[0]['start']:6.2f}  {' '.join(w['word'] for w in sh)}")


def caption_defaults(over):
    """Client overrides from clients.json (old pipeline keys) → caption settings."""
    return {'style': 'pop', 'font': over.get('font', 'Montserrat'), 'weight': over.get('weight', 900),
            'size': over.get('fontsize', 84), 'case': over.get('text_case', 'upper'), 'color': '#ffffff',
            'accent': over.get('highlight_color', '#ffd400'), 'y': over.get('pos', .65),
            'bump': over.get('highlight', 'pop') == 'pop'}


def font_path(family, weight):
    """Font file used by captions to measure line breaks."""
    import mvlib
    if family in SKILL_FONTS:
        key = min((k for k in mvlib.FONT_FILES if k[0] == SKILL_FONTS[family]), key=lambda k: abs(k[1] - weight))
        return mvlib.FONTS / mvlib.FONT_FILES[key]
    files = FONT_FILES.get(family)
    return files[min(files, key=lambda x: abs(x - weight))] if files else None


def add_font(c, family, weight):
    if family in SKILL_FONTS:
        c.font(SKILL_FONTS[family], weight)
    elif family in FONT_FILES:
        files = FONT_FILES[family]
        w = min(files, key=lambda x: abs(x - weight))
        c.font_file(family, weight, files[w])
    else:
        raise SystemExit(f'font {family} not available; add it to FONT_FILES with its licence')


def at_time(at, word, nth, words):
    if at is not None:
        return float(at)
    norm = lambda s: s.lower().strip('.,!?:;«»"()—–-').replace('ё', 'е')
    hits = [w for w in words if norm(w['word']) == norm(word)]
    if len(hits) <= nth:
        raise SystemExit(f'word not in voice: {word}')
    return round(hits[nth]['start'] - .05, 3)


if __name__ == '__main__':
    plan_shows() if '--plan-shows' in sys.argv else main()
