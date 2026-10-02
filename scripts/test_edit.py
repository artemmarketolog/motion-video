#!/usr/bin/env python3
"""HyperFrames media regression. Usage: python3 test_edit.py /tmp/new-empty-test-dir

Requires the pinned offline hf.py runtime, system FFmpeg, numpy and Pillow.
Creates and preserves a synthetic source, HTML, output, decoded samples and logs.
Never overwrites an existing directory. No network or paid API use.
"""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import numpy as np
from PIL import Image

if len(sys.argv) != 2:
    raise SystemExit('Usage: python3 test_edit.py /tmp/new-empty-test-dir')
ROOT = Path(sys.argv[1]).resolve()
ROOT.mkdir(parents=True, exist_ok=False)
(ROOT / 'assets').mkdir()
from skill_config import RUNTIME
WRAPPER = str(Path(__file__).with_name('hf.py'))
shutil.copyfile(RUNTIME / 'node_modules/gsap/dist/gsap.min.js', ROOT / 'assets/gsap.min.js')
HTML = '<!doctype html>\n<html lang="ru">\n<head>\n<meta charset="UTF-8">\n<meta name="viewport" content="width=640, height=360">\n<title>HyperFrames media reorder verification</title>\n<script src="assets/gsap.min.js"></script>\n<style>\n* { box-sizing: border-box; }\nhtml, body { margin: 0; width: 640px; height: 360px; overflow: hidden; background: #000; }\n#root { position: relative; width: 640px; height: 360px; overflow: hidden; }\nvideo { position: absolute; inset: 0; width: 640px; height: 360px; object-fit: cover; z-index: 0; }\n.label { position: absolute; top: 18px; left: 24px; padding: 10px 16px; color: white; background: #171717; font: bold 24px sans-serif; z-index: 2; }\n#marker { position: absolute; left: 30px; top: 298px; width: 32px; height: 32px; background: #ffff00; z-index: 3; }\n</style>\n</head>\n<body>\n<div id="root" data-composition-id="main" data-start="0" data-duration="2" data-width="640" data-height="360" data-fps="30">\n  <video id="video-blue" class="clip" src="source.mp4" muted playsinline preload="auto" data-start="0" data-duration="1" data-media-start="2" data-track-index="0"></video>\n  <video id="video-red" class="clip" src="source.mp4" muted playsinline preload="auto" data-start="1" data-duration="1" data-media-start="0" data-track-index="0"></video>\n  <audio id="audio-blue" src="source.mp4" data-start="0" data-duration="1" data-media-start="2" data-volume="1" data-track-index="1"></audio>\n  <audio id="audio-red" src="source.mp4" data-start="1" data-duration="1" data-media-start="0" data-volume="1" data-track-index="1"></audio>\n  <div id="label-blue" class="clip label" data-start="0" data-duration="1" data-track-index="2">SOURCE 2–3s / 880 Hz</div>\n  <div id="label-red" class="clip label" data-start="1" data-duration="1" data-track-index="2">SOURCE 0–1s / 440 Hz</div>\n  <div id="marker" class="clip" data-start="0" data-duration="2" data-track-index="3"></div>\n</div>\n<script>\nconst tl = gsap.timeline({ paused: true });\ntl.to(\'#marker\', { x: 548, duration: 2, ease: \'none\' }, 0);\nwindow.__timelines = window.__timelines || {};\nwindow.__timelines.main = tl;\n</script>\n</body>\n</html>\n'
(ROOT / "index.html").write_text(HTML)
subprocess.run([
    'ffmpeg', '-hide_banner', '-loglevel', 'error', '-threads', '1',
    '-f', 'lavfi', '-i', 'color=c=red:s=640x360:r=30:d=2',
    '-f', 'lavfi', '-i', 'color=c=blue:s=640x360:r=30:d=2',
    '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000:duration=2',
    '-f', 'lavfi', '-i', 'sine=frequency=880:sample_rate=48000:duration=2',
    '-filter_complex_threads', '1', '-filter_complex',
    '[0:v][1:v]concat=n=2:v=1:a=0[v];[2:a][3:a]concat=n=2:v=0:a=1[a]',
    '-map', '[v]', '-map', '[a]', '-c:v', 'libx264', '-preset', 'veryfast',
    '-crf', '16', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '160k',
    '-threads', '1', str(ROOT / 'source.mp4')], check=True)


def cli_step(directory, args, logfile):
    with logfile.open('w') as log:
        return subprocess.run([sys.executable, WRAPPER, str(directory), *args],
                              stdout=log, stderr=subprocess.STDOUT, timeout=1800).returncode


for command in ('lint', 'check'):
    code = cli_step(ROOT, [command], ROOT / (command + '.log'))
    if code:
        raise SystemExit(f'{command} failed with exit {code}; see {ROOT / (command + ".log")}')
render_args = ['render', '--fps', '30', '--format', 'mp4', '--quality', 'standard',
               '--video-frame-format', 'png', '-o']
code = cli_step(ROOT, [*render_args, 'output.mp4'], ROOT / 'render.log')
if code:
    raise SystemExit(f'Render failed with exit {code}; see {ROOT / "render.log"}')
missing = ROOT / 'missing-media'
(missing / 'assets').mkdir(parents=True)
shutil.copyfile(ROOT / 'assets/gsap.min.js', missing / 'assets/gsap.min.js')
(missing / 'index.html').write_text(HTML.replace('source.mp4', 'deliberately-absent.mp4'))
missing_code = cli_step(missing, [*render_args, 'output-must-not-exist.mp4'], missing / 'render.log')
if missing_code == 0:
    raise SystemExit('ERROR: missing media did not cause render failure')


def run(*cmd):
    return subprocess.run(cmd, check=True, capture_output=True).stdout


def frame(path, seconds):
    raw = run('ffmpeg', '-v', 'error', '-ss', str(seconds), '-i', str(path),
              '-frames:v', '1', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-')
    return np.frombuffer(raw, dtype=np.uint8).reshape(360, 640, 3)


def spectrum(path, start):
    raw = run('ffmpeg', '-v', 'error', '-ss', str(start), '-i', str(path),
              '-t', '0.4', '-vn', '-af', 'pan=mono|c0=c0', '-ar', '48000', '-f', 'f32le', '-')
    pcm = np.frombuffer(raw, dtype='<f4').astype(np.float64)
    rms = float(np.sqrt(np.mean(pcm * pcm)))
    fft = np.abs(np.fft.rfft(pcm * np.hanning(len(pcm))))
    bins = np.fft.rfftfreq(len(pcm), 1 / 48000)
    peak = float(bins[np.argmax(fft)])
    power_440 = float(fft[np.argmin(np.abs(bins - 440))] ** 2)
    power_880 = float(fft[np.argmin(np.abs(bins - 880))] ** 2)
    return {'peak_hz': peak, 'rms': rms, 'power_440': power_440, 'power_880': power_880}


output = ROOT / 'output.mp4'
source = ROOT / 'source.mp4'
probe = json.loads(run('ffprobe', '-v', 'error', '-show_entries',
                       'format=duration,size:stream=codec_name,codec_type,width,height,r_frame_rate,nb_frames',
                       '-of', 'json', str(output)))
video = next(s for s in probe['streams'] if s['codec_type'] == 'video')
audio = next(s for s in probe['streams'] if s['codec_type'] == 'audio')
checks = {
    'h264': video['codec_name'] == 'h264',
    'aac_audio': audio['codec_name'] == 'aac',
    'resolution_640x360': (video['width'], video['height']) == (640, 360),
    'fps_30': video['r_frame_rate'] == '30/1',
    'duration_2s': abs(float(probe['format']['duration']) - 2) < .08,
    '60_frames': int(video.get('nb_frames', 0)) == 60,
}
pixel_samples = []
audio_samples = []
centroids = []
for i, (out_time, src_time, tone) in enumerate(((.5, 2.5, 880), (1.5, .5, 440))):
    actual = frame(output, out_time)
    reference = frame(source, src_time)
    # The central patch is free of the labels and animated marker.
    patch = actual[150:210, 290:350].astype(float)
    ref_patch = reference[150:210, 290:350].astype(float)
    error = float(np.mean(np.abs(patch - ref_patch)))
    pixel_samples.append({'output_time': out_time, 'source_time': src_time,
                          'actual_rgb': patch.mean(axis=(0, 1)).tolist(),
                          'source_rgb': ref_patch.mean(axis=(0, 1)).tolist(),
                          'mean_absolute_error': error})
    checks[f'source_window_{i + 1}_video'] = error < 8
    Image.fromarray(actual).save(ROOT / f'frame-{out_time:.1f}s.png')
    tone_actual = spectrum(output, out_time - .2)
    tone_reference = spectrum(source, src_time - .2)
    audio_samples.append({'output_time': out_time, 'source_time': src_time,
                          'expected_hz': tone, 'actual': tone_actual,
                          'source': tone_reference})
    checks[f'source_window_{i + 1}_audio'] = (
        abs(tone_actual['peak_hz'] - tone) < 8 and tone_actual['rms'] > .02)
    marker_region = actual[295:335]
    yellow = ((marker_region[:, :, 0] > 190) & (marker_region[:, :, 1] > 190)
              & (marker_region[:, :, 2] < 80))
    ys, xs = np.where(yellow)
    centroids.append(float(xs.mean()) if len(xs) else None)
checks['animated_overlay_moves_right'] = (
    all(c is not None for c in centroids) and centroids[1] - centroids[0] > 200)
missing_log = (ROOT / 'missing-media/render.log').read_text()
missing_pass = ('Aborting render due to lint issues' in missing_log
                and 'missing_local_asset' in missing_log
                and 'audio_src_not_found' in missing_log
                and not (ROOT / 'missing-media/output-must-not-exist.mp4').exists())
checks['missing_media_rejected_without_output'] = missing_pass
report = {'status': 'pass' if all(checks.values()) else 'fail', 'checks': checks,
          'probe': probe, 'pixel_samples': pixel_samples, 'audio_samples': audio_samples,
          'overlay_x_centroids': centroids,
          'missing_media_test': {'status': 'pass' if missing_pass else 'fail',
                                 'exit_code': missing_code, 'output_exists': False,
                                 'reason': 'strict lint: missing_local_asset + audio_src_not_found'},
          'notes': ['Decoded-video and decoded-PCM assertions; source retained unmodified.']}
(ROOT / 'test-report.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report, indent=2))
raise SystemExit(0 if all(checks.values()) else 1)
