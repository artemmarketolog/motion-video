#!/usr/bin/env python3
"""Every template × every format: new_project → build.py → hf.py check → one sheet of frames per template.

  templates_test.py --out /ABS/NEW-DIR [--templates explainer,chat-ui] [--formats 9:16,1:1] [--jobs 2]
No renders, no paid calls. Look at the sheets: check passing does not mean the layout is good.
"""
import argparse
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
TEMPLATES = sorted(p.name for p in (SCRIPTS.parent / 'assets/templates').iterdir())
FORMATS = ['9:16', '4:5', '3:4', '1:1', '16:9']


def one(root, template, fmt):
    d = root / template / fmt.replace(':', 'x')
    r = subprocess.run([sys.executable, SCRIPTS / 'new_project.py', d, '--template', template, '--format', fmt],
                       capture_output=True, text=True)
    if r.returncode:
        return {'template': template, 'format': fmt, 'ok': False, 'error': r.stderr[-300:]}
    if template == 'footage-ad':   # no real shots in a fresh install: synthetic clips and a placeholder voice
        subprocess.run([sys.executable, SCRIPTS / 'footage/demo_assets.py', d], capture_output=True, check=True)
    subprocess.run([sys.executable, d / 'build.py'], capture_output=True, check=True)
    spec = json.loads((d / 'video-spec.json').read_text())
    at = round(spec['seconds'] * .62, 2)
    out = subprocess.run([sys.executable, SCRIPTS / 'hf.py', d, 'check', '--json'], capture_output=True, text=True)
    data = json.loads(out.stdout)
    issues = [f"{f['code']}@{f.get('time')}" for k in ('lint', 'layout', 'contrast', 'runtime', 'motion')
              for f in (data.get(k) or {}).get('findings', []) if f.get('severity') in ('error', 'warning')
              and f['code'] != 'nested_structure_needs_subcomposition']
    subprocess.run([sys.executable, SCRIPTS / 'hf.py', d, 'snapshot', '--at', str(at), '--no-end', '-o', 'tt'],
                   capture_output=True)
    frame = next((d / 'tt').glob('frame-*.png'), None)
    return {'template': template, 'format': fmt, 'ok': bool(data.get('ok')), 'issues': issues[:6],
            'frame': str(frame) if frame else None, 'at': at}


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--out', required=True, type=Path)
    p.add_argument('--templates', default=','.join(TEMPLATES))
    p.add_argument('--formats', default=','.join(FORMATS))
    p.add_argument('--jobs', type=int, default=2)
    a = p.parse_args()
    root = a.out.resolve()
    root.mkdir(parents=True, exist_ok=False)
    jobs = [(t, f) for t in a.templates.split(',') for f in a.formats.split(',')]
    with ThreadPoolExecutor(a.jobs) as ex:
        results = list(ex.map(lambda j: one(root, *j), jobs))
    for t in a.templates.split(','):
        frames = [r['frame'] for r in results if r['template'] == t and r.get('frame')]
        if frames:
            inputs = sum((['-i', f] for f in frames), [])
            chain = ''.join(f'[{i}]scale=-2:420[v{i}];' for i in range(len(frames)))
            chain += ''.join(f'[v{i}]' for i in range(len(frames))) + f'hstack={len(frames)}' if len(frames) > 1 else '[v0]null'
            subprocess.run(['ffmpeg', '-v', 'error', '-y', *inputs, '-filter_complex', chain.rstrip(';'), str(root / f'{t}.jpg')])
    (root / 'results.json').write_text(json.dumps(results, ensure_ascii=False, indent=2))
    for r in results:
        print(f"{r['template']:16} {r['format']:5} ok={r['ok']} {' '.join(r.get('issues', [])) or r.get('error', '')}")
    print(json.dumps({'all_ok': all(r['ok'] for r in results), 'sheets': [str(root / f'{t}.jpg') for t in a.templates.split(',')]}))


if __name__ == '__main__':
    main()
