#!/usr/bin/env python3
"""Local-only audio mixdown, stream-copy assembly and reproducible technical QA (no network)."""
import argparse
import hashlib
import json
import math
import re
import shutil
import subprocess
import tempfile
from fractions import Fraction
from pathlib import Path


def run(args):
    p = subprocess.run([str(x) for x in args], capture_output=True, text=True)
    if p.returncode:
        raise ValueError(p.stderr[-5000:] or p.stdout[-1000:])
    return p.stdout


def digest(path):
    with open(path, 'rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def probe(path):
    return json.loads(run(['ffprobe', '-v', 'error', '-show_streams', '-show_format',
                           '-show_data_hash', 'sha256', '-of', 'json', path]))


def video(p):
    return next(s for s in p['streams'] if s['codec_type'] == 'video')


def duration(p):
    return float(p['format']['duration'])


def video_hash(path):
    return run(['ffmpeg', '-v', 'error', '-i', path, '-map', '0:v:0', '-c', 'copy',
                '-f', 'streamhash', '-hash', 'sha256', '-']).strip()


def new_output(path):
    p = Path(path).resolve()
    if p.exists():
        raise ValueError(f'Output exists; choose a new revision: {p}')
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def plan_read(path):
    path = Path(path).resolve()
    p = json.loads(path.read_text())
    w, h, fps = p['width'], p['height'], p['fps']
    if not all(type(x) is int and x > 0 for x in (w, h, fps)):
        raise ValueError('width, height, fps must be positive integers')
    if w % 2 or h % 2 or Fraction(w, h) not in (Fraction(16, 9), Fraction(9, 16), Fraction(1, 1), Fraction(4, 5), Fraction(3, 4)):
        raise ValueError('Use even dimensions in 16:9, 9:16, 1:1, 4:5 or 3:4')
    if 'design_width' in p or 'design_height' in p:
        dw, dh = p.get('design_width'), p.get('design_height')
        if not all(type(x) is int and x > 0 and x % 2 == 0 for x in (dw, dh)):
            raise ValueError('design_width and design_height must both be positive even integers')
        if w * dh != h * dw:
            raise ValueError('Output and design canvas must have the same aspect ratio')
    if not p['scenes'] or len({s['id'] for s in p['scenes']}) != len(p['scenes']):
        raise ValueError('Scenes must be nonempty with unique IDs')
    clips = []
    start = 0
    for scene in p['scenes']:
        if type(scene['frames']) is not int or scene['frames'] < 1:
            raise ValueError('Scene frames must be positive integers')
        for clip in scene.get('audio', []):
            at = clip.get('at_frame', 0)
            if type(at) is not int or at < 0:
                raise ValueError('at_frame must be a nonnegative integer')
            f = (path.parent / clip['file']).resolve()
            info = probe(f)
            if not any(s['codec_type'] == 'audio' for s in info['streams']):
                raise ValueError(f'No audio: {f}')
            if at / fps + duration(info) > scene['frames'] / fps + .025:
                raise ValueError(f'Audio overruns {scene["id"]}: {f.name}; extend the scene, do not cut speech')
            gain = float(clip.get('gain_db', 0))
            if not math.isfinite(gain):
                raise ValueError('gain_db must be finite')
            clips.append((f, (start + at) / fps, gain))
        start += scene['frames']
    return p, path.parent, start, clips


SR = 48000


def _num(value, name, low=None, high=None):
    value = float(value)
    if not math.isfinite(value) or (low is not None and value < low) or (high is not None and value > high):
        raise ValueError(f'{name} out of range: {value}')
    return value


def carve_db(strength):
    """Voiceover carve depth, as in HyperFrames Studio: 0.25 -> 6 dB, 0.5 -> 10 dB."""
    return min(18.0, 6 + (strength - 0.25) * 16)


def _decode(args):
    import numpy as np
    raw = subprocess.run([str(a) for a in args] + ['-f', 'f32le', '-ac', '2', '-ar', str(SR), '-'],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32).reshape(-1, 2).astype(np.float64)


def voice_activity(voice, fps=1000):
    """0..1 speech activity at 1 kHz: 20 ms RMS, gate 30 dB under the loudest speech, attack 15 ms, release 250 ms."""
    import numpy as np
    mono = voice.mean(1)
    hop = SR // fps
    n = len(mono) // hop
    rms = np.sqrt((mono[:n * hop].reshape(n, hop) ** 2).mean(1) + 1e-12)
    rms = np.sqrt(np.convolve(rms ** 2, np.ones(20) / 20, 'same'))
    db = 20 * np.log10(rms + 1e-9)
    top = np.percentile(db, 99)
    target = np.clip((db - (top - 30)) / 12, 0, 1)
    out = np.zeros(n)
    a_att, a_rel = math.exp(-1 / (0.015 * fps)), math.exp(-1 / (0.25 * fps))
    level = 0.0
    for i, x in enumerate(target):
        k = a_att if x > level else a_rel
        level = k * level + (1 - k) * x
        out[i] = level
    return np.repeat(out, hop)[:len(mono)] if n else np.zeros(len(mono))


def carve(music, activity, depth_db, low=300.0, high=4000.0):
    """Dip only the band the voice occupies, following the speech. Linear-phase FFT split,
    raised-cosine edges one octave wide; lo + mid + hi reconstructs the input exactly."""
    import numpy as np
    n = len(music)
    freqs = np.fft.rfftfreq(n, 1 / SR)
    lf = np.log2(np.maximum(freqs, 1))

    def edge(f0):
        return np.clip((lf - (math.log2(f0) - .5)) / 1.0, 0, 1)
    mask = (0.5 - 0.5 * np.cos(np.pi * edge(low))) * (0.5 + 0.5 * np.cos(np.pi * edge(high)))
    spec = np.fft.rfft(music, axis=0)
    mid = np.fft.irfft(spec * mask[:, None], n, axis=0)
    gain = 10 ** (-depth_db * activity[:n] / 20)
    return music + mid * (gain[:, None] - 1)


def mixdown(mix_path, cache_dir):
    """Render mix.json to a cached 48 kHz stereo WAV. Key = settings + input bytes + this script.

    mix.json: {"seconds": 12.6, "tracks": [
        {"file": "work/voice.wav", "role": "voice", "start": 0.4, "gain_db": 0},
        {"file": "work/music.mp3", "role": "music", "offset": 3.1, "gain_db": -9, "carve": 0.25,
         "fade_in": 0, "fade_out": 0.6},
        {"file": "work/sfx.wav", "role": "sfx", "gain_db": -2}],
      "loudness": {"I": -14, "TP": -1.5, "LRA": 11}}
    start = timeline position, offset = source in-point, duration = optional source length
    (fade_out then ends at start + duration, so two pieces of one track can crossfade).
    carve (music only): the 300 Hz–4 kHz band dips while the voice speaks (0.25 ≈ 6 dB);
    the low end and the top of the bed stay, so the music keeps its body. Silence is untouched.
    """
    import numpy as np
    mix_path = Path(mix_path).resolve()
    base = mix_path.parent
    spec = json.loads(mix_path.read_text())
    seconds = spec.get('seconds')
    if seconds is None:
        seconds = json.loads((base / 'video-spec.json').read_text())['seconds']
    seconds = _num(seconds, 'seconds', 0.1, 3600)
    samples = round(seconds * SR)
    tracks = spec['tracks']
    if not tracks:
        raise ValueError('mix.json has no tracks')
    files = []
    for t in tracks:
        f = (base / t['file']).resolve()
        if not f.is_file():
            raise ValueError(f'missing audio: {t["file"]}')
        files.append(f)
    key = hashlib.sha256(json.dumps([spec, [digest(f) for f in files], digest(__file__)],
                                    sort_keys=True).encode()).hexdigest()[:24]
    cache_dir = Path(cache_dir)
    out = cache_dir / f'mix-{key}.wav'
    meta = cache_dir / f'mix-{key}.json'
    if out.exists() and meta.exists() and json.loads(meta.read_text())['sha256'] == digest(out):
        return out
    cache_dir.mkdir(parents=True, exist_ok=True)
    placed = []
    for t, f in zip(tracks, files):
        role = t.get('role', 'sfx')
        if role not in ('voice', 'music', 'sfx'):
            raise ValueError('role must be voice, music or sfx')
        start = _num(t.get('start', 0), 'start', 0, seconds)
        offset = _num(t.get('offset', 0), 'offset', 0)
        gain = _num(t.get('gain_db', 0), 'gain_db', -60, 24)
        length = seconds - start
        chain = f'atrim=start={offset}'
        if 'duration' in t:
            chain += f":duration={_num(t['duration'], 'duration', 0.01)}"
            length = min(length, float(t['duration']))   # fade_out ends with the piece, not with the video
        chain += f',asetpts=PTS-STARTPTS,volume={gain}dB'
        if t.get('fade_in'):
            chain += f",afade=t=in:d={_num(t['fade_in'], 'fade_in', 0, length)}"
        if t.get('fade_out'):
            d = _num(t['fade_out'], 'fade_out', 0, length)
            chain += f',afade=t=out:st={max(0, length - d)}:d={d}'
        chain += f',adelay={round(start * SR)}S:all=1,apad=whole_len={samples},atrim=end_sample={samples}'
        x = _decode(['ffmpeg', '-v', 'error', '-i', f, '-af', f'aresample={SR},aformat=channel_layouts=stereo,{chain}'])
        placed.append((role, t, np.pad(x, ((0, max(0, samples - len(x))), (0, 0)))[:samples]))
    voices = [x for role, _, x in placed if role == 'voice']
    activity = voice_activity(sum(voices)) if voices else None
    total = np.zeros((samples, 2))
    music = np.zeros((samples, 2))
    for role, t, x in placed:
        if role == 'music' and t.get('carve') and activity is not None:
            x = carve(x, activity, carve_db(_num(t['carve'], 'carve', 0.01, 1)))
        if role == 'music':
            music += x
        total += x
    balance = None   # how far the music sits under the speech, measured where the voice speaks (references/mix.md)
    if activity is not None and (activity > .5).any() and music.any():
        on = activity[:samples] > .5
        rms = lambda y: float(np.sqrt((y[on] ** 2).mean()) + 1e-12)
        balance = round(20 * math.log10(rms(sum(voices)) / rms(music)), 1)
    raw = cache_dir / f'mix-{key}.raw.f32'
    raw.write_bytes(total.astype('<f4').tobytes())
    src = ['-f', 'f32le', '-ar', str(SR), '-ac', '2', '-i', raw]
    loud = spec.get('loudness', {'I': -14, 'TP': -1.5, 'LRA': 11})
    if loud:
        target = f"I={loud['I']}:TP={loud['TP']}:LRA={loud.get('LRA', 11)}"
        measured = subprocess.run(['ffmpeg', '-hide_banner', '-nostdin', *map(str, src), '-af',
                                   f'loudnorm={target}:print_format=json', '-f', 'null', '-'],
                                  capture_output=True, text=True).stderr
        m = json.loads(measured[measured.rindex('{'):measured.rindex('}') + 1])
        af = (f"loudnorm={target}:measured_I={m['input_i']}:measured_TP={m['input_tp']}:"
              f"measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:"
              f"offset={m['target_offset']}:linear=true,aresample={SR},atrim=end_sample={samples}")
    else:
        af = f'atrim=end_sample={samples}'
    run(['ffmpeg', '-v', 'error', '-y', *src, '-af', af, '-c:a', 'pcm_s24le', '-ar', str(SR), '-ac', '2', out])
    raw.unlink()
    meta.write_text(json.dumps({'sha256': digest(out), 'mix': str(mix_path), 'music_under_voice_db': balance}))
    return out

def mix(plan, out):
    p, base, frames, clips = plan_read(plan)
    out = new_output(out)
    seconds, samples = frames / p['fps'], round(frames * 48000 / p['fps'])
    args = ['ffmpeg', '-v', 'error', '-n']
    filters, labels = [], []
    for i, (file, offset, gain) in enumerate(clips):
        args += ['-i', file]
        filters.append(f'[{i}:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,'
                       f'volume={gain}dB,adelay={round(offset*48000)}S:all=1[a{i}]')
        labels.append(f'[a{i}]')
    music = p.get('music')
    if music:
        idx = len(clips)
        file = (base / music['file']).resolve()
        probe(file)
        args += ['-stream_loop', '-1', '-i', file]
        fade_in = min(float(music.get('fade_in_s', 1)), seconds)
        fade_out = min(float(music.get('fade_out_s', 2)), seconds)
        gain = float(music.get('gain_db', -26))
        if not all(math.isfinite(x) for x in (fade_in, fade_out, gain)) or min(fade_in, fade_out) < 0:
            raise ValueError('Invalid music fade/gain')
        filters.append(f'[{idx}:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,'
                       f'atrim=end_sample={samples},volume={gain}dB,'
                       f'afade=t=in:d={fade_in},afade=t=out:st={seconds-fade_out}:d={fade_out}[m]')
        labels.append('[m]')
    if not labels:
        args += ['-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=stereo']
        filters.append(f'[0:a]atrim=end_sample={samples}[out]')
    else:
        filters.append(''.join(labels) + f'amix=inputs={len(labels)}:normalize=0,'
                       f'apad=whole_len={samples},atrim=end_sample={samples}[out]')
    args += ['-filter_complex', ';'.join(filters), '-map', '[out]', '-c:a', 'pcm_s24le', out]
    run(args)
    return {'file': str(out), 'duration_s': duration(probe(out)), 'sha256': digest(out)}


def concat(plan, manifest_path, out):
    p, _, total, _ = plan_read(plan)
    m = json.loads(Path(manifest_path).read_text())
    out = new_output(out)
    if any(m[k] != p[k] for k in ('width', 'height', 'fps')) or len(m['scenes']) != len(p['scenes']):
        raise ValueError('Manifest does not match timeline')
    visual_plan = {'shared_visual_files':p.get('shared_visual_files',[]), 'scenes':[
        {'id':s['id'],'frames':s['frames'],'visual':s['visual'],'visual_files':s.get('visual_files',[])} for s in p['scenes']]}
    if 'design_width' in p:
        visual_plan.update(design_width=p['design_width'], design_height=p['design_height'])
    if m.get('visual_plan') != visual_plan or any(digest(f) != h for f,h in m['dependencies']):
        raise ValueError('Visual inputs changed since render; run render-scenes first')
    keys = ('codec_name', 'profile', 'level', 'width', 'height', 'pix_fmt', 'sample_aspect_ratio',
            'r_frame_rate', 'time_base', 'color_range', 'color_space', 'color_transfer',
            'color_primaries', 'extradata_hash')
    signature = None
    with tempfile.TemporaryDirectory(prefix='animated-concat-') as temp:
        tmp = Path(temp)
        lines = []
        for i, (s, r) in enumerate(zip(p['scenes'], m['scenes'])):
            f = Path(r['file']).resolve()
            if r['id'] != s['id'] or r['frames'] != s['frames'] or digest(f) != r['sha256']:
                raise ValueError('Stale/corrupt scene manifest; run render-scenes first')
            info = probe(f)
            v = video(info)
            if len(info['streams']) != 1 or v['codec_name'] != 'h264' or int(v['nb_frames']) != s['frames']:
                raise ValueError('Expected a silent H.264 scene with exact frame count')
            if (v['width'], v['height'], Fraction(v['r_frame_rate'])) != (p['width'], p['height'], p['fps']):
                raise ValueError('Scene geometry/rate does not match plan')
            current = [v.get(k) for k in keys]
            if signature is not None and current != signature:
                raise ValueError('Scene codec parameters differ; render with one encoding preset')
            signature = current
            name = f'scene-{i}.mp4'
            (tmp / name).symlink_to(f)
            lines.append(f"file '{name}'")
        (tmp / 'list.txt').write_text('\n'.join(lines) + '\n')
        run(['ffmpeg', '-v', 'error', '-n', '-f', 'concat', '-safe', '1', '-i', tmp / 'list.txt',
             '-map', '0:v:0', '-c:v', 'copy', '-an', '-movflags', '+faststart', out])
    if int(video(probe(out))['nb_frames']) != total:
        raise ValueError(f'Unexpected joined frame count; do not deliver {out}')
    return {'file': str(out), 'frames': total, 'sha256': digest(out)}


def mux(silent, audio, out):
    out = new_output(out)
    v = probe(silent)
    a = probe(audio)
    if abs(duration(v) - duration(a)) > .06:
        raise ValueError('Audio/video length mismatch >60 ms; adjust timeline/mix first')
    before = video_hash(silent)
    run(['ffmpeg', '-v', 'error', '-n', '-i', silent, '-i', audio, '-map', '0:v:0', '-map', '1:a:0',
         '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', '-ar', '48000', '-ac', '2',
         '-movflags', '+faststart', out])
    after = video_hash(out)
    if before != after:
        raise ValueError(f'Video payload changed; do not deliver {out}')
    return {'file': str(out), 'sha256': digest(out), 'video_stream_hash': after, 'video_copy_verified': True}


def qa(file, plan, out, interval):
    if interval <= 0:
        raise ValueError('interval must be positive')
    file = Path(file).resolve()
    folder = Path(out).resolve()
    fingerprint = {'sha256': digest(file), 'plan_sha256': digest(plan) if plan else None,
                   'script_sha256': digest(__file__), 'interval': interval}
    report_path = folder / 'report.json'
    if report_path.exists():
        report = json.loads(report_path.read_text())
        if report['input'] == fingerprint and report['technical_pass'] and all(Path(x).exists() for x in report['contact_sheets']):
            return {'cached': True, 'report': str(report_path)}
        raise ValueError('QA folder belongs to another revision or failed run; use a new folder')
    folder.mkdir(parents=True, exist_ok=True)
    info = probe(file)
    v = video(info)
    audio = next((s for s in info['streams'] if s['codec_type'] == 'audio'), {})
    sample_step = max(1,round(float(Fraction(v['r_frame_rate']))*interval))
    sample_frames = list(range(0,int(v.get('nb_frames',round(duration(info)*float(Fraction(v['r_frame_rate']))))),sample_step))
    thumb_w, thumb_h = (216,384) if v['height'] > v['width'] else (384,216)
    rows = min(4,max(1,math.ceil(len(sample_frames)/4)))
    # Decode once: detect black sections before sampling; meter complete audio in the same process.
    proc = subprocess.run(['ffmpeg', '-hide_banner', '-nostdin', '-n', '-i', str(file),
        '-map', '0:v:0', '-vf', f'blackdetect=d=0.15:pix_th=0.03,select=not(mod(n\\,{sample_step})),'
        f'scale={thumb_w}:{thumb_h}:force_original_aspect_ratio=decrease,pad={thumb_w}:{thumb_h}:(ow-iw)/2:(oh-ih)/2:color=0xdddddd,'
        f'tile=4x{rows}:nb_frames={4*rows}:padding=4:margin=4', '-fps_mode', 'vfr', '-q:v', '3',
        str(folder / 'sheet-%03d.jpg'), '-map', '0:a:0?',
        '-af', 'ebur128=peak=true,silencedetect=noise=-45dB:d=1', '-f', 'null', '-'],
        capture_output=True, text=True)
    (folder / 'ffmpeg.log').write_text(proc.stderr)
    checks = {'decode': proc.returncode == 0 and not re.search(r'Error while decoding|corrupt decoded frame', proc.stderr),
              'h264': v['codec_name'] == 'h264', 'yuv420p': v['pix_fmt'] == 'yuv420p',
              'square_pixels': v.get('sample_aspect_ratio') in (None, '1:1'),
              'aac_stereo_48k': audio.get('codec_name') == 'aac' and audio.get('channels') == 2 and audio.get('sample_rate') == '48000'}
    peaks = re.findall(r'Peak:\s+([\-\d.]+) dBFS', proc.stderr)
    loudness = re.findall(r'I:\s+([\-\d.]+) LUFS', proc.stderr)
    if peaks:
        checks['true_peak_below_minus_1'] = float(peaks[-1]) <= -1
    if plan:
        p, _, frames, _ = plan_read(plan)
        checks['timeline'] = (v['width'],v['height'],Fraction(v['r_frame_rate']),int(v.get('nb_frames',0))) == (p['width'],p['height'],p['fps'],frames)
    checks['supported_aspect'] = Fraction(v['width'],v['height']) in (Fraction(16,9),Fraction(9,16),Fraction(1,1),Fraction(4,5),Fraction(3,4))
    checks['contact_sheets_created'] = bool(list(folder.glob('sheet-*.jpg')))
    report = {'input':fingerprint,'technical_pass':all(checks.values()),'checks':checks,
              'video_stream_hash':video_hash(file),'probe':info,
              'integrated_lufs':float(loudness[-1]) if loudness else None,
              'peak_dbtp':float(peaks[-1]) if peaks else None,
              'review_flags':[line.strip() for line in proc.stderr.splitlines() if 'black_start:' in line or 'silence_start:' in line or 'silence_end:' in line],
              'contact_sheets':[str(x) for x in sorted(folder.glob('sheet-*.jpg'))],
              'sample_frames':sample_frames, 'sample_times_s':[round(f/float(Fraction(v['r_frame_rate'])),3) for f in sample_frames],
              'human_review':'pending: inspect visuals, facts, speech and music; technical_pass is not approval'}
    report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2))
    return {'technical_pass':report['technical_pass'],'report':str(report_path),'contact_sheets':report['contact_sheets']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('preflight')
    v = sub.add_parser('validate'); v.add_argument('plan')
    m = sub.add_parser('mix'); m.add_argument('plan'); m.add_argument('out')
    c = sub.add_parser('concat'); c.add_argument('plan'); c.add_argument('manifest'); c.add_argument('out')
    u = sub.add_parser('mux'); u.add_argument('video'); u.add_argument('audio'); u.add_argument('out')
    q = sub.add_parser('qa'); q.add_argument('file'); q.add_argument('--plan'); q.add_argument('--out', required=True); q.add_argument('--interval',type=float,default=5)
    args = parser.parse_args()
    if args.command == 'preflight':
        paths = [str(Path(__file__).with_name('hf.py'))]
        result = {'tools':{x:shutil.which(x) for x in ('python3','node','ffmpeg','ffprobe')},
                  'paths':{x:Path(x).exists() for x in paths},'network_calls':0}
    elif args.command == 'validate':
        p, _, frames, clips = plan_read(args.plan)
        result = {'valid':True,'scenes':len(p['scenes']),'frames':frames,'seconds':frames/p['fps'],'speech_clips':len(clips)}
    elif args.command == 'mix': result = mix(args.plan,args.out)
    elif args.command == 'concat': result = concat(args.plan,args.manifest,args.out)
    elif args.command == 'mux': result = mux(args.video,args.audio,args.out)
    else: result = qa(args.file,args.plan,args.out,args.interval)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    if result.get('technical_pass') is False:
        raise SystemExit(2)


if __name__ == '__main__':
    try:
        main()
    except (ValueError,KeyError,StopIteration) as exc:
        raise SystemExit(f'ERROR: {exc}')
