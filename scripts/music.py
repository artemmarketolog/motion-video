#!/usr/bin/env python3
"""Music: paid generation (ElevenLabs Music, strictly one at a time) and free analysis.

  music.py gen --prompt-file work/music-prompt.txt --seconds 20 --out work/music.mp3 [--take 1] [--variant 1] [--dry-run]
  music.py analyze work/music.mp3 [--target 4.56] [--json out.json]
  music.py split work/music.raw.mp3 --variant 2 --out work/music.mp3     # one variant of a multi-take file
  music.py align work/music.raw.mp3 --drop-at 7.86 --out work/music.mp3 [--drop 9.25] [--bpm 100] [--pad]

gen: one global lock (parallel requests get HTTP 429), a ledger of every paid call,
reservation before dispatch; an uncertain result is marked unknown_billed and is
never retried automatically. The prompt is saved next to the track.
analyze: RMS envelope, the drop (largest sustained loudness jump after a quieter
passage), low-band (808/kick) hits, BPM estimate, and the offset that puts the drop
on --target seconds of the video. Leading silence and silent gaps are skipped.
ElevenLabs sometimes returns two variants in one file separated by seconds of silence:
gen, analyze and split detect them (gaps >= 1.5 s), gen keeps the full file as <out>.full.mp3.
align: put the drop exactly on --drop-at seconds: trims the head when the drop is late; when it is
early, repeats whole beats just before the drop (BPM grid) and trims the rest of a beat from the head;
--pad (or too little material) delays the track with silence instead. 10 ms crossfades, no clicks.
Pure numpy/ffmpeg, no network.
"""
import argparse
import fcntl
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from skill_config import DATA_DIR, CACHE_DIR, ENV_FILE, RUNTIME, setting, require_key

import numpy as np

STATE = DATA_DIR
ENV = ENV_FILE
URL = 'https://api.elevenlabs.io/v1/music?output_format=mp3_44100_192'
GUARD = ('Adult, stylish, premium. No chiptune, no 8-bit, no video game or cartoon sounds, '
         'no toy bells, no childish plucks. No fade out, keep playing to the last second.')


def api_key():
    return require_key('ELEVEN_API_KEY')


def gen(prompt_file, seconds, out, take, dry_run, variant=1, instrumental=True):
    prompt = Path(prompt_file).read_text().strip()
    if GUARD.split('.')[0] not in prompt:
        prompt = prompt + ' ' + GUARD
    request = {'prompt': prompt, 'music_length_ms': int(seconds * 1000), 'force_instrumental': instrumental}
    key = hashlib.sha256(json.dumps([request, take], ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:20]
    out = Path(out).resolve()
    STATE.mkdir(parents=True, exist_ok=True)
    cache = STATE / 'music' / f'{key}.mp3'
    meta = STATE / 'music' / f'{key}.json'
    if dry_run:
        return {'key': key, 'request': request, 'cached': cache.exists(), 'network_calls': 0}
    cache.parent.mkdir(parents=True, exist_ok=True)
    with (STATE / 'music.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)  # sequential across all agents on this VPS
        if meta.exists():
            m = json.loads(meta.read_text())
            if m['status'] == 'success' and cache.exists() and m['sha256'] == hashlib.sha256(cache.read_bytes()).hexdigest():
                return deliver(cache, out, prompt, key, True, variant)
            raise ValueError(f"take {take} is {m['status']}; check ElevenLabs history, then use a new --take deliberately")
        meta.write_text(json.dumps({**request, 'take': take, 'status': 'dispatching'}, ensure_ascii=False))
        ledger(key, 'dispatch', seconds)
        try:
            import requests
            r = requests.post(URL, headers={'xi-api-key': api_key(), 'Content-Type': 'application/json'},
                              json=request, timeout=300)
            if r.status_code == 429:
                meta.unlink()
                ledger(key, 'rate_limited', seconds)
                raise ValueError('HTTP 429 (not billed): another generation is running; wait and repeat the same command')
            r.raise_for_status()
            cache.write_bytes(r.content)
            probe = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', str(cache)],
                                   capture_output=True, text=True)
            if probe.returncode or float(probe.stdout.strip() or 0) < 1:
                raise ValueError('invalid audio returned')
            meta.write_text(json.dumps({**request, 'take': take, 'status': 'success',
                                        'sha256': hashlib.sha256(cache.read_bytes()).hexdigest()}, ensure_ascii=False))
            ledger(key, 'success', seconds)
        except ValueError:
            raise
        except Exception as error:
            meta.write_text(json.dumps({**request, 'take': take, 'status': 'unknown_billed'}, ensure_ascii=False))
            ledger(key, 'unknown_billed', seconds)
            raise ValueError(f'music result uncertain ({type(error).__name__}); not retried. Check provider history.')
    return deliver(cache, out, prompt, key, False, variant)


def ledger(key, status, seconds):
    with (STATE / 'music-ledger.jsonl').open('a') as f:
        f.write(json.dumps({'at': datetime.now(timezone.utc).isoformat(timespec='seconds'), 'key': key,
                            'status': status, 'seconds': seconds, 'cwd': os.getcwd()}) + '\n')


def deliver(cache, out, prompt, key, cached, variant=1):
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        raise ValueError(f'{out} exists; choose another name (tracks are never overwritten)')
    out.with_suffix('.prompt.txt').write_text(prompt + '\n')
    result = {'file': str(out), 'key': key, 'cached': cached, 'prompt_file': str(out.with_suffix('.prompt.txt'))}
    x, sr = decode(cache)
    parts = variants(x, sr)
    if len(parts) < 2:
        out.write_bytes(cache.read_bytes())
        return result
    full = out.with_name(out.stem + '.full' + out.suffix)
    full.write_bytes(cache.read_bytes())
    result.update(split(full, variant, out), full_file=str(full),
                  note=f'the provider returned {len(parts)} variants in one file; {out.name} = variant {variant}. '
                       f'Listen to the others with: music.py split {full.name} --variant N --out ...')
    return result


def decode(path, sr=24000, lowpass=None):
    af = ['-af', f'lowpass=f={lowpass},lowpass=f={lowpass}'] if lowpass else []
    raw = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(path), *af, '-ac', '1', '-ar', str(sr), '-f', 'f32le', '-'],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32), sr


def rms_db(x, sr, win):
    n = int(win * sr)
    k = len(x) // n
    frames = x[:k * n].reshape(k, n)
    return 20 * np.log10(np.sqrt((frames ** 2).mean(1)) + 1e-9)


def variants(x, sr, gap=1.5, floor_db=50):
    """Music regions (start_s, end_s) between silences of >= gap seconds; leading/trailing silence dropped."""
    env = rms_db(x, sr, .05)
    loud = env > env.max() - floor_db
    regions, start, quiet = [], None, 0
    for i, on in enumerate(loud):
        if on:
            if start is None:
                start = i
            quiet = 0
        elif start is not None:
            quiet += 1
            if quiet * .05 >= gap:
                regions.append((start, i - quiet + 1))
                start, quiet = None, 0
    if start is not None:
        regions.append((start, len(loud) - quiet))
    return [(round(a * .05, 2), round(b * .05, 2)) for a, b in regions if (b - a) * .05 >= 3]


def find_drop(smooth, lo, hi):
    """Biggest rise of the next 1 s over the previous 1.5 s inside [lo, hi) (50 ms frames), >= 1 s after lo."""
    best, drop = -1e9, None
    for i in range(lo + 20, hi - 20):
        pre, post = smooth[max(lo, i - 30):i].mean(), smooth[i:i + 20].mean()
        if post - pre > best:
            best, drop = post - pre, i
    return best, drop


def analyze(path, target=None, variant=1):
    x, sr = decode(path)
    env = rms_db(x, sr, .05)                      # 50 ms
    # Short breaks before a drop are near-silent: clip them 20 dB under the peak so a 0.2 s gap
    # does not outweigh the sustained rise of the real drop.
    smooth = np.convolve(np.maximum(env, env.max() - 20), np.ones(4) / 4, 'same')
    parts = variants(x, sr) or [(0.0, len(x) / sr)]
    if not 1 <= variant <= len(parts):
        raise ValueError(f'--variant {variant}: the file has {len(parts)} variant(s)')
    lo, hi = round(parts[variant - 1][0] / .05), round(parts[variant - 1][1] / .05)
    best, drop = find_drop(smooth, lo, hi)
    if drop is None:
        raise ValueError('track too short to find a drop')
    # Refine with 5 ms windows: first window reaching half of the rise.
    fine = rms_db(x, sr, .005)
    t0 = drop * .05
    f0, f1 = max(0, int((t0 - .3) / .005)), int((t0 + .3) / .005)
    seg = fine[f0:f1]
    base, peak = np.median(seg[:20]), seg.max()
    idx = int(np.argmax(seg >= base + (peak - base) / 2))
    drop_t = round((f0 + idx) * .005, 3)
    a, b = parts[variant - 1]
    # Low band hits (808 / kick): energy < 120 Hz in 10 ms windows, local maxima above threshold.
    xl, _ = decode(path, lowpass=120)
    le = rms_db(xl, sr, .01)
    thr = np.percentile(le, 75)
    hits = [round(i * .01, 2) for i in range(max(2, int(a * 100)), min(len(le) - 2, int(b * 100)))
            if le[i] >= thr and le[i] == le[i - 2:i + 3].max() and le[i] - le[i - 5 if i >= 5 else 0] > 3]
    # BPM via autocorrelation of positive spectral-energy flux.
    flux = np.maximum(0, np.diff(rms_db(x[int(a * sr):int(b * sr)], sr, .01)))
    ac = np.correlate(flux - flux.mean(), flux - flux.mean(), 'full')[len(flux) - 1:]
    lags = np.arange(len(ac)) * .01
    ok = (lags >= 60 / 180) & (lags <= 60 / 70)
    bpm = round(60 / lags[ok][np.argmax(ac[ok])], 1) if ok.any() else None
    result = {'file': str(path), 'duration_s': round(len(x) / sr, 3), 'drop_s': drop_t, 'drop_rise_db': round(float(best), 1),
              'music_starts_s': parts[0][0], 'variants': [{'start_s': a, 'end_s': b} for a, b in parts],
              'variant': variant,
              'loudness_before_drop_db': round(float(smooth[max(lo, drop - 30):drop].mean()), 1),
              'low_hits_s': hits[:64], 'bpm_estimate': bpm,
              'note': 'Automatic estimates. Confirm the drop by ear or with fine RMS around drop_s before building on it.'}
    if target is not None:
        result['offset_for_target_s'] = round(drop_t - target, 3)
        result['target_s'] = target
        result['low_hits_on_video_s'] = [round(h - result['offset_for_target_s'], 2) for h in hits
                                         if h - result['offset_for_target_s'] >= 0][:32]
    return result


def write_audio(y, sr, out):
    out = Path(out)
    if out.exists():
        raise ValueError(f'{out} exists; choose another name (tracks are never overwritten)')
    out.parent.mkdir(parents=True, exist_ok=True)
    codec = ['-c:a', 'libmp3lame', '-b:a', '320k'] if out.suffix == '.mp3' else ['-c:a', 'pcm_s24le']
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'f32le', '-ar', str(sr), '-ac', '2', '-i', '-', *codec, str(out)],
                   input=np.ascontiguousarray(y, '<f4').tobytes(), check=True)


def stereo(path, sr=48000):
    raw = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(path), '-ac', '2', '-ar', str(sr), '-f', 'f32le', '-'],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32).reshape(-1, 2).astype(np.float64), sr


def fade(y, sr, head=True, tail=True, ms=10):
    n = min(len(y) // 2, int(sr * ms / 1000))
    ramp = np.linspace(0, 1, n)[:, None]
    y = y.copy()
    if head and n:
        y[:n] *= ramp
    if tail and n:
        y[-n:] *= ramp[::-1]
    return y


def split(path, variant, out):
    x, sr = decode(path)
    parts = variants(x, sr)
    if not 1 <= variant <= max(1, len(parts)):
        raise ValueError(f'--variant {variant}: the file has {len(parts)} variant(s)')
    a, b = parts[variant - 1] if parts else (0, len(x) / sr)
    y, sr = stereo(path)
    write_audio(fade(y[int(a * sr):int(b * sr)], sr), sr, out)
    return {'file': str(out), 'variant': variant, 'variants': [{'start_s': p, 'end_s': q} for p, q in parts],
            'cut_s': [a, b]}


def splice(parts, sr, ms=10):
    """Join arrays with short linear crossfades (no clicks at the cuts)."""
    n = int(sr * ms / 1000)
    out = parts[0]
    for p in parts[1:]:
        k = min(n, len(out), len(p))
        ramp = np.linspace(0, 1, k)[:, None]
        out = np.concatenate([out[:-k], out[-k:] * (1 - ramp) + p[:k] * ramp, p[k:]]) if k else np.concatenate([out, p])
    return out


def align(path, drop_at, out, drop=None, bpm=None, pad=False):
    info = analyze(path)
    drop = info['drop_s'] if drop is None else drop
    bpm = bpm or info['bpm_estimate']
    y, sr = stereo(path)
    d, shift = int(round(drop * sr)), drop_at - drop      # shift > 0: the drop must come later
    how = []
    if shift <= 0:
        y = fade(y[int(round(-shift * sr)):], sr, tail=False)
        how.append(f'trimmed {-shift:.3f} s from the head')
    else:
        beat = 60 / bpm if bpm else None
        k = int(np.ceil(shift / beat - 1e-6)) if beat else 0
        if not pad and beat and d >= round(k * beat * sr):
            n = int(round(k * beat * sr))
            y = splice([y[:d], y[d - n:d], y[d:]], sr)         # the k beats before the drop, played twice
            cut = n - int(round(shift * sr))
            y = fade(y[cut:], sr, tail=False)
            how.append(f'repeated {k} beat(s) ({k * beat:.3f} s at {bpm} BPM) before the drop, trimmed {cut / sr:.3f} s from the head')
        else:
            y = np.concatenate([np.zeros((int(round(shift * sr)), 2)), fade(y, sr, tail=False)])
            how.append(f'delayed the track by {shift:.3f} s of silence')
    write_audio(y, sr, out)
    check = analyze(out)['drop_s']
    return {'file': str(out), 'source_drop_s': drop, 'drop_at_s': drop_at, 'measured_drop_s': check,
            'error_ms': round((check - drop_at) * 1000), 'bpm': bpm, 'how': how,
            'note': 'measured_drop_s is analyze() on the result; confirm by ear or fine RMS if error_ms is large.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='cmd', required=True)
    g = sub.add_parser('gen')
    g.add_argument('--prompt-file', required=True)
    g.add_argument('--seconds', type=float, default=20)
    g.add_argument('--out', required=True)
    g.add_argument('--take', default='1')
    g.add_argument('--dry-run', action='store_true')
    g.add_argument('--variant', type=int, default=1, help='which variant to keep when the file holds several')
    a = sub.add_parser('analyze')
    a.add_argument('file')
    a.add_argument('--target', type=float)
    a.add_argument('--json')
    a.add_argument('--variant', type=int, default=1)
    sp = sub.add_parser('split')
    sp.add_argument('file')
    sp.add_argument('--variant', type=int, default=1)
    sp.add_argument('--out', required=True)
    al = sub.add_parser('align')
    al.add_argument('file')
    al.add_argument('--drop-at', type=float, required=True, help='video second where the drop must land')
    al.add_argument('--out', required=True)
    al.add_argument('--drop', type=float, help='drop in the source, seconds (default: analyze)')
    al.add_argument('--bpm', type=float, help='beat grid for inserted beats (default: analyze estimate)')
    al.add_argument('--pad', action='store_true', help='delay with silence instead of repeating beats')
    args = parser.parse_args()
    if args.cmd == 'gen':
        if not 3 <= args.seconds <= 300:
            parser.error('--seconds 3..300')
        result = gen(args.prompt_file, args.seconds, args.out, args.take, args.dry_run, args.variant)
    elif args.cmd == 'split':
        result = split(args.file, args.variant, args.out)
    elif args.cmd == 'align':
        result = align(args.file, args.drop_at, args.out, args.drop, args.bpm, args.pad)
    else:
        result = analyze(args.file, args.target, args.variant)
        if args.json:
            Path(args.json).write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    try:
        main()
    except ValueError as e:
        print(f'music: {e}', file=sys.stderr)
        sys.exit(2)
