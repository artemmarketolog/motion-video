#!/usr/bin/env python3
"""Copy of a finished video with a few on-screen words changed (another city, online, a date, a price).

  variant.py SRC DST --replace OLD=NEW [--replace OLD=>NEW ...]   (OLD=>NEW when the text itself has «=»)
             [--render] [--audio-from SRC_MASTER.mp4] [--note "..."]

1. Copies SRC → DST without output/, qa/, snapshots/, .cache/, edits.jsonl, review.json (DST must not exist).
2. Applies every OLD=NEW to the top-level *.py sources of DST (build.py and its helpers); a pair with
   no hit is an error, because then the change lives somewhere else (a shared kit, a picture, the voice).
3. Runs build.py, then checks that no OLD seen in the source index.html is left and its NEW is there.
4. `hf.py check` must report no errors.
5. --render: `mv.py build` → output/master-r1.mp4 (full render: a copy has no cache).
6. --audio-from: the sound track of the approved source master is copied onto the new picture bit for bit
   (build.py re-synthesises SFX, and the current sfx.py varies repeats, so a rebuild would sound slightly
   different). Durations must match within 0.05 s. The mv.py output is kept as master-r1.mv.mp4.
7. Prepends a «Вариант» note to DST/MAKING-OF.md (source, replacements, date).

Words in the voice are not touched: changing them is a new TTS take (voice.py) and a mix rebuild.
Recipe and per-brand notes: references/variants.md.
"""
import argparse
import json
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
EXCLUDE = ('output', 'qa', 'snapshots', '.cache', 'edits.jsonl', 'review.json')   # the copy starts its own history


def run(cmd, cwd=None):
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if r.returncode:
        sys.exit(f'✗ {" ".join(map(str, cmd))}\n{r.stdout[-2000:]}\n{r.stderr[-2000:]}')
    return r.stdout


def duration(path):
    return float(run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', str(path)]))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('src', type=Path)
    ap.add_argument('dst', type=Path)
    ap.add_argument('--replace', action='append', required=True, metavar='OLD=NEW')
    ap.add_argument('--render', action='store_true')
    ap.add_argument('--audio-from', type=Path, help='approved master of SRC whose sound goes onto the copy')
    ap.add_argument('--note', default='')
    a = ap.parse_args()
    src, dst = a.src.resolve(), a.dst.resolve()
    pairs = [tuple(r.split('=>' if '=>' in r else '=', 1)) for r in a.replace]   # OLD=>NEW when the text has «=»
    if not (src / 'build.py').exists():
        sys.exit(f'✗ {src}/build.py not found')
    if dst.exists():
        sys.exit(f'✗ {dst} already exists')
    if a.audio_from and not a.audio_from.exists():
        sys.exit(f'✗ {a.audio_from} not found')

    shutil.copytree(src, dst, ignore=lambda d, names: [n for n in names if Path(d) == src and n in EXCLUDE])
    (dst / 'output').mkdir()
    sources = sorted(dst.glob('*.py'))
    for old, new in pairs:
        hits = 0
        for f in sources:
            s = f.read_text()
            if old in s:
                hits += s.count(old)
                f.write_text(s.replace(old, new))
        if not hits:
            sys.exit(f'✗ «{old}» is not in {[f.name for f in sources]}: it lives in a shared kit, a picture or the voice '
                     f'(see references/variants.md); {dst} is left for inspection')
        print(f'✓ «{old}» → «{new}»: {hits}')

    run([sys.executable, 'build.py'], cwd=dst)
    page = (dst / 'index.html').read_text()
    seen = (src / 'index.html').read_text() if (src / 'index.html').exists() else ''
    shown = [(old, new) for old, new in pairs if old in seen]   # code-only pairs (an icon switch) are not on the page
    left = [old for old, _ in shown if old in page]
    missing = [new for _, new in shown if new not in page]
    if left or missing:
        sys.exit(f'✗ index.html: still has {left}, lacks {missing}')
    check = json.loads(run([sys.executable, SCRIPTS / 'hf.py', dst, 'check', '--json']))
    errors = {k: v.get('errorCount') for k, v in check.items() if isinstance(v, dict) and v.get('errorCount')}
    if errors:
        sys.exit(f'✗ hf.py check: {errors}')
    print('✓ build.py, index.html, hf.py check')

    note = '; '.join(f'«{o}» → «{n}»' for o, n in pairs)
    mk = dst / 'MAKING-OF.md'
    head = (f'> **Вариант** ролика `{src.name}` ({date.today():%d.%m.%Y}, `variant.py`): {note}. {a.note}\n'
            f'> Всё остальное (голос, музыка, сцены, история правок) как в исходнике ниже.\n\n')
    mk.write_text(head + (mk.read_text() if mk.exists() else ''))

    if not a.render:
        print(f'→ render: python3 {SCRIPTS}/mv.py build {dst} -o output/master-r1.mp4')
        return
    out = dst / 'output' / ('master-r1.mv.mp4' if a.audio_from else 'master-r1.mp4')
    run([sys.executable, SCRIPTS / 'mv.py', 'build', dst, '-o', out, '--note', f'вариант: {note} {a.note}'.strip()])
    if a.audio_from:
        d_new, d_src = duration(out), duration(a.audio_from)
        if abs(d_new - d_src) > .05:
            sys.exit(f'✗ duration {d_new:.3f} s vs source {d_src:.3f} s: sound not copied, master is {out}')
        final = dst / 'output' / 'master-r1.mp4'
        run(['ffmpeg', '-v', 'error', '-y', '-i', out, '-i', a.audio_from, '-map', '0:v', '-map', '1:a', '-c', 'copy',
             '-shortest', '-movflags', '+faststart', final])
        run([sys.executable, SCRIPTS / 'mv.py', 'log', dst, final.relative_to(dst),
             '--note', f'вариант: картинка {out.name} + звук {a.audio_from}'])
        out = final
    print(f'✓ {out} ({out.stat().st_size / 1e6:.0f} MB, {duration(out):.2f} s)')


if __name__ == '__main__':
    main()
