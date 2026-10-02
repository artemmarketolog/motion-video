#!/usr/bin/env python3
"""End-to-end smoke test, no paid calls: three formats from the `blank` template, then the edit loop.

  smoke_test.py --out /ABS/NEW-TEST-DIR
For 16:9, 1:1, 9:16: new_project → build.py → hf.py check → mv.py build → qa.py.
For 9:16 also: change the title → mv.py build renders fewer segments than the total and the
untouched segments come from the cache; change the mix gain → mv.py audio keeps the video stream bit-exact.
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
import media  # noqa: E402


def run(cmd, log):
    with log.open('a') as f:
        f.write('$ ' + ' '.join(map(str, cmd)) + '\n')
        p = subprocess.run(list(map(str, cmd)), stdout=subprocess.PIPE, stderr=f, text=True)
        f.write(p.stdout)
    if p.returncode:
        raise AssertionError(f'failed: {cmd}; see {log}')
    return p.stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    root = args.out.resolve()
    root.mkdir(parents=True, exist_ok=False)
    results = []
    for ratio, name in [('16:9', '16x9'), ('1:1', '1x1'), ('9:16', '9x16')]:
        started = time.monotonic()
        project = root / name
        log = root / f'{name}.log'
        run([sys.executable, SCRIPTS / 'new_project.py', project, '--template', 'blank', '--format', ratio], log)
        run([sys.executable, project / 'build.py'], log)
        check = json.loads(run([sys.executable, SCRIPTS / 'hf.py', project, 'check', '--json'], log))
        assert check['ok'], f'check failed for {ratio}'
        r1 = json.loads(run([sys.executable, SCRIPTS / 'mv.py', 'build', project, '-o', 'output/master-r1.mp4', '--note', 'smoke'], log))
        qa = run([sys.executable, SCRIPTS / 'qa.py', project / 'output/master-r1.mp4', '--spec', project / 'video-spec.json',
                  '--out', project / 'qa/r1'], log)
        assert json.loads(qa)['ok'], f'qa failed for {ratio}'
        item = {'format': ratio, 'first_build_s': r1['total_s'], 'segments': r1['segments']}
        if ratio == '9:16':
            build = project / 'build.py'
            build.write_text(build.read_text().replace('>Один объект<', '>Другой текст<'))
            run([sys.executable, build], log)
            r2 = json.loads(run([sys.executable, SCRIPTS / 'mv.py', 'build', project, '-o', 'output/master-r2.mp4', '--note', 'title'], log))
            assert 0 < r2['rendered_segments'] < r2['segments'], r2
            mix = json.loads((project / 'mix.json').read_text())
            mix['tracks'][0]['gain_db'] = -6
            (project / 'mix.json').write_text(json.dumps(mix))
            r3 = json.loads(run([sys.executable, SCRIPTS / 'mv.py', 'audio', project, '-o', 'output/master-r3.mp4', '--note', 'gain'], log))
            same = media.video_hash(project / 'output/master-r2.mp4') == media.video_hash(project / 'output/master-r3.mp4')
            assert same, 'audio-only edit changed the video stream'
            refused = subprocess.run([sys.executable, SCRIPTS / 'mv.py', 'audio', project, '-o', 'output/master-r3.mp4'],
                                     capture_output=True, text=True)
            assert refused.returncode != 0, 'existing master was not protected'
            item.update(edit_build_s=r2['total_s'], edit_rendered=f"{r2['rendered_segments']}/{r2['segments']}",
                        audio_only_s=r3['total_s'], video_stream_identical=same, overwrite_refused=True)
        item['elapsed_s'] = round(time.monotonic() - started, 1)
        results.append(item)
        print(json.dumps(item, ensure_ascii=False), flush=True)
    (root / 'results.json').write_text(json.dumps(results, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'passed': True, 'results': str(root / 'results.json'), 'visual_review': 'pending'}))
    return 0


if __name__ == '__main__':
    sys.exit(main())
