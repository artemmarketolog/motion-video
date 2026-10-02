#!/usr/bin/env python3
"""Incremental HyperFrames build: render only the segments whose frames changed.

  mv.py plan  /ABS/VIDEO [--draft]                  what is dirty, time estimate
  mv.py build /ABS/VIDEO -o output/master-rN.mp4 [--draft] [--note "..."]
  mv.py audio /ABS/VIDEO -o output/master-rN.mp4 [--note "..."]   sound-only edit, no video render
  mv.py seams /ABS/VIDEO output/master-rN.mp4       frames around re-rendered boundaries
  mv.py registry                                    every project: index row, MAKING-OF, shared ledger
  mv.py log   /ABS/VIDEO output/master-rN.mp4 --note "..."   record a master made outside mv.py

Frames are fingerprinted (probe.mjs, seconds for a whole video). The video is
cut into segments of `segment_seconds` (default 2) starting at every anchor in
video-spec.json (scene starts; default [0]). A segment's cache key is the hash
of its frame fingerprints + render settings, so unchanged segments are reused
even if they moved in time. Dirty neighbours render together in one sandboxed
HyperFrames run (HLS output: fixed GOP, every segment starts on a keyframe),
then all segments are stream-copied into one MP4 and the mix is muxed on top.

At most RENDER_SLOTS renders run on this VPS at once: a build waits for a free slot by
itself (no manual flock needed). New projects encode compactly (x264 ~14 Mbit/s, a 40 s
1080x1920 master stays under 100 MB); projects with an older cache keep their settings so
the cache stays valid, and their joined video is re-encoded once if it is thicker than MAX_MBPS.
"""
import argparse
import fcntl
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from skill_config import CACHE_DIR, DATA_DIR, PROJECTS, RUNTIME, STUDIO

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
import media  # noqa: E402
import segment  # noqa: E402

HF = SCRIPTS / 'hf.py'
LEDGER = DATA_DIR / 'ledger.jsonl'        # every master of every studio project
INDEX = STUDIO / 'MAKING-OF-INDEX.md'      # one row per delivered video
RUNTIME_PKG = RUNTIME / 'node_modules/hyperframes/package.json'
DEFAULT_WORKERS = min(3, max(1, (os.cpu_count() or 2) // 2))  # 6 cores: 1 → 62 s, 2 → 46 s, 3 → 29 s, 4–5 → 40 s per 60 heavy frames
KEY_VERSION = 'mv-seg-v1'
SLOTS_DIR = CACHE_DIR / 'render-slots'
RENDER_SLOTS = 2        # 6 cores: two renders × 3 Chrome workers
COMPACT_BITRATE = '14M'  # segment encoder for new projects (measured 01.10.2026: ~15–17 Mbit/s real)
MAX_MBPS = 20            # thicker joined video (old projects, CRF 15) is re-encoded once for delivery


def sha(data):
    return hashlib.sha256(data if isinstance(data, bytes) else data.encode()).hexdigest()


def log(msg):
    print(msg, file=sys.stderr, flush=True)


def load_spec(project):
    spec = json.loads((project / 'video-spec.json').read_text())
    info = segment.composition_info((project / 'index.html').read_text())
    fps = int(spec.get('fps', 30))
    if (info['width'], info['height']) != (spec['width'], spec['height']) or int(info['fps']) != fps:
        raise ValueError('video-spec.json and index.html root disagree on size/fps')
    if abs(info['duration'] - float(spec['seconds'])) > 1e-6:
        raise ValueError(f"video-spec seconds {spec['seconds']} != root data-duration {info['duration']}")
    seg = spec.get('segment_seconds', 2)
    if not isinstance(seg, int) or not 1 <= seg <= 10:
        raise ValueError('segment_seconds must be an integer 1..10 (HLS segment length)')
    return spec, fps, seg


def probe(project):
    out = '.cache/probe/latest.json'
    proc = subprocess.run([sys.executable, str(HF), '--timeout', '600', str(project), 'probe', out],
                          capture_output=True, text=True)
    if proc.returncode:
        raise ValueError('probe failed: ' + (proc.stderr or proc.stdout)[-3000:])
    data = json.loads((project / out).read_text())
    if data['page_errors']:
        raise ValueError('page errors during probe: ' + '; '.join(data['page_errors'][:3]))
    return data


def segments_for(frames, fps, seg_seconds, anchors_s, step):
    anchors = sorted({0, *[round(a * fps) for a in anchors_s if 0 < round(a * fps) < frames]})
    bounds = anchors + [frames]
    out = []
    for group, (a, b) in enumerate(zip(bounds, bounds[1:])):
        for s in range(a, b, seg_seconds * fps):
            out.append({'group': group, 'f0': s, 'f1': min(s + seg_seconds * fps, b)})
    for s in out:
        if (s['f0'] - anchors[s['group']]) % step or s['f0'] % step:
            raise ValueError('Draft frame step must divide segment and anchor positions')
    return out


def encode_mode(project):
    """'compact' for new projects; 'legacy' (CRF 15, old cache keys) for projects cached before 01.10.2026."""
    path = project / '.cache/encode.json'
    if path.exists():
        return json.loads(path.read_text())['mode']
    old = any((project / '.cache/segments').glob('*.ts'))
    mode = 'legacy' if old else 'compact'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({'mode': mode}))
    return mode


def settings(spec, fps, seg_seconds, draft, mode):
    version = json.loads(RUNTIME_PKG.read_text())['version']
    conf = {'key_version': KEY_VERSION, 'hyperframes': version, 'width': spec['width'], 'height': spec['height'],
            'fps_out': fps // 2 if draft else fps, 'quality': 'draft' if draft else spec.get('quality', 'delivery'),
            'segment_seconds': seg_seconds, 'container': 'hls-ts'}
    if mode == 'compact' and not draft:   # legacy keys stay byte-identical so their cache remains valid
        conf.update(quality='standard', bitrate=COMPACT_BITRATE)
    return conf


def plan(project, draft=False):
    spec, fps, seg_seconds = load_spec(project)
    started = time.monotonic()
    fp = probe(project)
    probe_s = time.monotonic() - started
    step = 2 if draft else 1
    conf = settings(spec, fps, seg_seconds, draft, encode_mode(project))
    segs = segments_for(fp['frames'], fps, seg_seconds, spec.get('anchors', [0]), step)
    cache = project / '.cache/segments'
    for s in segs:
        hashes = fp['hashes'][s['f0']:s['f1']:step]
        s['key'] = sha(json.dumps([conf, fp['global'], hashes]))
        s['file'] = str(cache / f"{s['key']}.ts")
        meta = cache / f"{s['key']}.json"
        s['hit'] = False
        if meta.exists() and Path(s['file']).exists():
            m = json.loads(meta.read_text())
            s['hit'] = m.get('sha256') == media.digest(s['file'])
    stats = project / '.cache/stats.json'
    rate = json.loads(stats.read_text()).get('frames_per_s', {}).get(conf['quality'], 1.0) if stats.exists() else 1.0
    dirty = [s for s in segs if not s['hit']]
    frames = sum((s['f1'] - s['f0']) // step for s in dirty)
    pieces = group_pieces(segs, seg_seconds * fps)
    estimate = frames / rate + 8 * len(pieces) + 10
    return {'spec': spec, 'fps': fps, 'step': step, 'settings': conf, 'probe': fp, 'probe_s': round(probe_s, 1),
            'segments': segs, 'pieces': pieces, 'dirty_frames': frames, 'estimate_s': round(estimate)}


def group_pieces(segs, full_frames=None):
    """Consecutive dirty segments render in one HyperFrames run. A run may cross a scene anchor only
    when every segment before the crossing is full length: HLS then still cuts exactly at the anchors."""
    pieces, run = [], []
    for s in segs:
        contiguous = run and run[-1]['f1'] == s['f0']
        same_scene = run and run[-1]['group'] == s['group']
        full = run and full_frames and all(x['f1'] - x['f0'] == full_frames for x in run)
        if not s['hit'] and contiguous and (same_scene or full):
            run.append(s)
            continue
        if run:
            pieces.append(run)
        run = [s] if not s['hit'] else []
    if run:
        pieces.append(run)
    return pieces


def render_piece(project, piece, conf, fps, workers):
    f0, f1 = piece[0]['f0'], piece[-1]['f1']
    work = project / '.cache/work' / f'piece-{f0}-{f1}-{os.getpid()}'
    if work.exists():
        shutil.rmtree(work)
    segment.build(project, work, [(f0, f1)])
    cmd = [sys.executable, str(HF), '--timeout', '3600', str(work), 'render', '--format', 'hls',
           '--hls-segment-seconds', str(conf['segment_seconds']), '--quality', conf['quality'],
           '--workers', str(workers), '-o', 'out/hls']
    if conf.get('bitrate'):
        cmd += ['--video-bitrate', conf['bitrate']]
    if conf['fps_out'] != fps:
        cmd += ['--fps', str(conf['fps_out'])]
    started = time.monotonic()
    proc = subprocess.run(cmd, capture_output=True, text=True)
    elapsed = time.monotonic() - started
    (project / '.cache/logs').mkdir(parents=True, exist_ok=True)
    (project / '.cache/logs' / f'render-{f0}-{f1}.log').write_text(proc.stdout[-20000:] + proc.stderr[-20000:])
    if proc.returncode:
        raise ValueError(f'render of frames {f0}-{f1} failed; see .cache/logs/render-{f0}-{f1}.log\n' + (proc.stdout + proc.stderr)[-2500:])
    files = sorted((work / 'out/hls').glob('video_*.ts'))
    if len(files) != len(piece):
        raise ValueError(f'expected {len(piece)} HLS segments, got {len(files)} for frames {f0}-{f1}')
    step = fps // conf['fps_out']
    for s, f in zip(piece, files):
        count = count_frames(f)
        if count != (s['f1'] - s['f0']) // step:
            raise ValueError(f"segment {s['f0']}-{s['f1']}: {count} frames")
        dest = Path(s['file'])
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(f), dest)
        Path(str(dest)[:-3] + '.json').write_text(json.dumps(
            {'sha256': media.digest(dest), 'f0': s['f0'], 'f1': s['f1'], 'frames': count}))
    shutil.rmtree(work)
    return elapsed


def count_frames(path):
    out = media.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-count_packets',
                     '-show_entries', 'stream=nb_read_packets', '-of', 'csv=p=0', path])
    return int(next(line for line in out.split() if line.strip()))  # MPEG-TS lists the stream per program


def concat(project, segs, dest, fps_out, step):
    lst = dest.with_suffix('.txt')
    # Explicit durations: a 1-frame tail segment otherwise shifts every later timestamp by half a frame.
    lst.write_text(''.join(f"file '{s['file']}'\nduration {(s['f1'] - s['f0']) // step / fps_out:.6f}\n" for s in segs))
    media.run(['ffmpeg', '-v', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', lst, '-map', '0:v:0',
               '-c', 'copy', '-an', '-movflags', '+faststart', dest])
    lst.unlink()
    return dest


def compact(silent, seconds):
    """Old-cache projects: one x264 pass (CRF 18, capped 14 Mbit/s) when the joined video is too thick."""
    if silent.stat().st_size * 8 / seconds / 1e6 <= MAX_MBPS:
        return silent
    out = silent.with_name(silent.stem + '-compact.mp4')
    if not out.exists():
        tmp = out.with_suffix('.tmp.mp4')
        media.run(['ffmpeg', '-v', 'error', '-y', '-i', silent, '-map', '0:v:0', '-c:v', 'libx264', '-preset', 'medium',
                   '-crf', '18', '-maxrate', '14M', '-bufsize', '28M', '-pix_fmt', 'yuv420p', '-colorspace', 'bt709',
                   '-color_primaries', 'bt709', '-color_trc', 'bt709', '-an', '-movflags', '+faststart', tmp])
        tmp.rename(out)
    return out


class RenderSlot:
    """Global semaphore: at most RENDER_SLOTS HyperFrames renders on the VPS; waits with a clear message."""
    def __init__(self, project):
        self.project = project

    def __enter__(self):
        SLOTS_DIR.mkdir(parents=True, exist_ok=True)
        said = False
        while True:
            for i in range(RENDER_SLOTS):
                fd = open(SLOTS_DIR / f'slot-{i}.lock', 'a+')
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    fd.close()
                    continue
                fd.seek(0)
                fd.truncate()
                fd.write(f'{os.getpid()} {self.project}\n')
                fd.flush()
                self.fd = fd
                return self
            if not said:
                busy = [(SLOTS_DIR / f'slot-{i}.lock').read_text().strip() for i in range(RENDER_SLOTS)]
                log(f'waiting for a render slot: {RENDER_SLOTS} of {RENDER_SLOTS} busy ({"; ".join(busy)}); '
                    'the build starts by itself when one frees up')
                said = True
            time.sleep(3)

    def __exit__(self, *exc):
        fcntl.flock(self.fd, fcntl.LOCK_UN)
        self.fd.close()


class Lock:
    def __init__(self, project):
        self.path = project / '.cache/build.lock'

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.fd = open(self.path, 'a+')
        try:
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('Another mv.py build is running for this video; do not start a second one')
        return self

    def __exit__(self, *exc):
        fcntl.flock(self.fd, fcntl.LOCK_UN)
        self.fd.close()


def audio_for(project, spec):
    """Mix.json → cached mix; else a single full-length <audio> in index.html (legacy projects)."""
    if (project / 'mix.json').exists():
        return media.mixdown(project / 'mix.json', project / '.cache/audio')
    tags = [m for m in segment.TAG.finditer((project / 'index.html').read_text()) if m.group('name').lower() == 'audio']
    if len(tags) == 1:
        a = segment.attrs_of(tags[0].group('attrs'))
        if float(a.get('data-start', 0)) == 0 and 'data-media-start' not in a:
            return project / a['src']
    if tags:
        raise ValueError('Several <audio> elements: describe the mix in mix.json instead')
    return None


def finish(project, silent, out, spec, note, info):
    out = (project / out).resolve()
    if not out.is_relative_to(project):
        raise ValueError('output must be inside the video folder')
    if out.exists():
        raise ValueError(f'{out} exists; choose a new revision')
    audio = audio_for(project, spec) if spec.get('expect_audio') else None
    if spec.get('expect_audio') and audio is None:
        raise ValueError('expect_audio is true but there is no mix.json or <audio>')
    if audio:
        result = media.mux(silent, audio, out)
        meta = Path(audio).with_suffix('.json')
        balance = json.loads(meta.read_text()).get('music_under_voice_db') if meta.exists() else None
        if balance is not None:
            info = {**info, 'music_under_voice_db': balance}
            log(f'mix: music {balance} dB under the voice (ads 8-12, presentations 15-20: references/mix.md)')
    else:
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(silent, out)
        result = {'file': str(out), 'sha256': media.digest(out)}
    size_mb = round(out.stat().st_size / 1e6, 1)
    if size_mb > 100:
        log(f'warning: {size_mb} MB > 100 MB, Meta rejects a single upload this large; see references/delivery.md')
    record = {'at': datetime.now(timezone.utc).isoformat(timespec='seconds'), 'output': str(out.relative_to(project)),
              'sha256': result['sha256'], 'size_mb': size_mb, 'note': note, **info}
    with (project / 'edits.jsonl').open('a') as f:
        f.write(json.dumps(record, ensure_ascii=False) + '\n')
    register(project, record)
    return record


def register(project, record):
    """Studio projects (under MOTION_VIDEO_STUDIO/projects) go to the video ledger and must have a MAKING-OF and an index row."""
    if PROJECTS.resolve() not in project.resolve().parents:
        return
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with LEDGER.open('a') as f:
        f.write(json.dumps({'project': str(project.resolve()), **record}, ensure_ascii=False) + '\n')
    for issue in project_issues(project):
        log(f'reminder: {project.name}: {issue} (references/making-of.md)')


def project_issues(project, index=None, logged=None):
    """What a real project lacks: a row in the index, a MAKING-OF (unless its row says «без истории»), ledger lines."""
    index = index if index is not None else (INDEX.read_text() if INDEX.exists() else '')
    row = next((line for line in index.splitlines() if project.name in line), '')
    issues = [] if row else ['нет строки в MAKING-OF-INDEX.md']
    if not (project / 'MAKING-OF.md').exists() and 'без истории' not in row:
        issues.append('нет MAKING-OF.md')
    if logged is not None:
        missing = [m.name for m in sorted(project.glob('output/master-*.mp4'))
                   if (str(project), str(m.relative_to(project))) not in logged]
        if missing:
            issues.append(f'нет в ledger.jsonl: {", ".join(missing)} (собран не через mv.py → mv.py log)')
    return issues


def log_master(project, out, note):
    """Record a master made outside build/audio (ffmpeg mux, variant.py sound copy) in edits.jsonl and the ledger."""
    out = (project / out).resolve()
    record = {'at': datetime.now(timezone.utc).isoformat(timespec='seconds'), 'output': str(out.relative_to(project)),
              'sha256': media.digest(out), 'size_mb': round(out.stat().st_size / 1e6, 1), 'note': note, 'mode': 'external'}
    with (project / 'edits.jsonl').open('a') as f:
        f.write(json.dumps(record, ensure_ascii=False) + '\n')
    register(project, record)
    return record


def registry():
    """Audit of every project under the index folder: index row, MAKING-OF, ledger."""
    index = INDEX.read_text() if INDEX.exists() else ''
    rows = [json.loads(line) for line in LEDGER.read_text().splitlines() if line.strip()] if LEDGER.exists() else []
    logged = {(r['project'], r.get('output')) for r in rows}
    projects = sorted(d.resolve() for d in PROJECTS.iterdir() if (d / 'index.html').exists()) if PROJECTS.is_dir() else []
    problems = {d.name: i for d in projects if (i := project_issues(d, index, logged))}
    return {'projects': len(projects), 'ok': len(projects) - len(problems), 'problems': problems,
            'index': str(INDEX), 'ledger': str(LEDGER)}


def build(project, out, draft, note, workers):
    total_started = time.monotonic()
    with Lock(project):
        p = plan(project, draft)
        conf, fps = p['settings'], p['fps']
        log(f"probe {p['probe_s']} s; segments {len(p['segments'])}, dirty {sum(not s['hit'] for s in p['segments'])}, "
            f"pieces {len(p['pieces'])}, estimate ~{p['estimate_s']} s")
        render_s = 0.0
        if p['pieces']:
            with RenderSlot(project):
                for piece in p['pieces']:
                    log(f"render frames {piece[0]['f0']}-{piece[-1]['f1']} ({len(piece)} segments)")
                    render_s += render_piece(project, piece, conf, fps, workers)
        frames = p['dirty_frames']
        if frames and render_s:
            stats_path = project / '.cache/stats.json'
            stats = json.loads(stats_path.read_text()) if stats_path.exists() else {}
            stats.setdefault('frames_per_s', {})[conf['quality']] = round(frames / render_s, 3)
            stats_path.write_text(json.dumps(stats, indent=2))
        videos = project / '.cache/video'
        videos.mkdir(parents=True, exist_ok=True)
        key = sha(''.join(s['key'] for s in p['segments']))[:20]
        silent = videos / f'{key}.mp4'
        if not silent.exists():
            concat(project, p['segments'], silent, conf['fps_out'], p['step'])
        expected = sum((s['f1'] - s['f0']) // p['step'] for s in p['segments'])
        if count_frames(silent) != expected:
            silent.unlink()
            raise ValueError('joined frame count mismatch; nothing delivered')
        if not draft:
            silent = compact(silent, float(p['spec']['seconds']))
        info = {'mode': 'draft' if draft else 'final', 'segments': len(p['segments']),
                'rendered_segments': sum(not s['hit'] for s in p['segments']),
                'rendered_ranges_s': [[round(x[0]['f0'] / fps, 3), round(x[-1]['f1'] / fps, 3)] for x in p['pieces']],
                'render_s': round(render_s, 1), 'probe_s': p['probe_s'], 'video_key': key,
                'video_file': str(silent.relative_to(project))}
        if draft:
            info['note_draft'] = f"{conf['fps_out']} fps, draft encoder"
        record = finish(project, silent, out, p['spec'], note, info)
        record['total_s'] = round(time.monotonic() - total_started, 1)
        (project / '.cache/last-build.json').write_text(json.dumps(
            {**record, 'boundaries': [x[0]['f0'] for x in p['pieces']] + [x[-1]['f1'] for x in p['pieces']]}, indent=2))
        return record


def audio_only(project, out, note):
    with Lock(project):
        last = json.loads((project / '.cache/last-build.json').read_text())
        if last.get('mode') != 'final':
            raise ValueError('Last build was a draft; run a final build first')
        silent = project / last.get('video_file', f".cache/video/{last['video_key']}.mp4")
        spec, _, _ = load_spec(project)
        started = time.monotonic()
        record = finish(project, silent, out, spec, note, {'mode': 'audio-only', 'video_key': last['video_key'],
                                                           'rendered_segments': 0})
        record['total_s'] = round(time.monotonic() - started, 1)
        return record


def seams(project, master):
    last = json.loads((project / '.cache/last-build.json').read_text())
    fps = json.loads((project / 'video-spec.json').read_text()).get('fps', 30)
    total = count_frames(project / master)
    out = project / '.cache/seams' / Path(master).stem
    out.mkdir(parents=True, exist_ok=True)
    made = []
    for b in sorted(set(last.get('boundaries', []))):
        if b <= 0 or b >= total:
            continue
        sel = '+'.join(f'eq(n\\,{n})' for n in (b - 1, b, b + 1))
        img = out / f'seam-{b:05d}.jpg'
        media.run(['ffmpeg', '-v', 'error', '-y', '-i', project / master, '-vf',
                   f"select='{sel}',scale=-2:480,tile=3x1:padding=6", '-frames:v', '1', '-q:v', '3', img])
        made.append({'frame': b, 'time_s': round(b / fps, 3), 'image': str(img)})
    return {'seams': made, 'note': 'Left/middle/right = frames b-1, b, b+1 around each re-rendered boundary.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='cmd', required=True)
    for name in ('plan', 'build', 'audio', 'seams'):
        p = sub.add_parser(name)
        p.add_argument('project', type=Path)
        if name in ('build', 'audio'):
            p.add_argument('-o', '--output', required=True)
            p.add_argument('--note', default='')
        if name in ('plan', 'build'):
            p.add_argument('--draft', action='store_true', help='half fps, draft encoder; separate cache keys')
        if name == 'build':
            p.add_argument('--workers', type=int, default=DEFAULT_WORKERS)
        if name == 'seams':
            p.add_argument('master')
    sub.add_parser('registry', help='every project: index row, MAKING-OF, ledger; exit 1 on gaps')
    p = sub.add_parser('log', help='record a master made outside build/audio')
    p.add_argument('project', type=Path)
    p.add_argument('master')
    p.add_argument('--note', required=True)
    a = parser.parse_args()
    if a.cmd == 'registry':
        result = registry()
        print(json.dumps(result, ensure_ascii=False, indent=1))
        sys.exit(1 if result['problems'] else 0)
    project = a.project.resolve()
    if a.cmd == 'log':
        print(json.dumps(log_master(project, a.master, a.note), ensure_ascii=False))
        return
    if a.cmd == 'plan':
        p = plan(project, a.draft)
        fps = p['fps']
        result = {'segments': len(p['segments']), 'cached': sum(s['hit'] for s in p['segments']),
                  'dirty_ranges_s': [[round(x[0]['f0'] / fps, 3), round(x[-1]['f1'] / fps, 3)] for x in p['pieces']],
                  'dirty_frames': p['dirty_frames'], 'estimate_s': p['estimate_s'], 'probe_s': p['probe_s']}
    elif a.cmd == 'build':
        result = build(project, a.output, a.draft, a.note, a.workers)
    elif a.cmd == 'audio':
        result = audio_only(project, a.output, a.note)
    else:
        result = seams(project, a.master)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, FileNotFoundError) as error:
        print(f'mv: {error}', file=sys.stderr)
        sys.exit(2)
