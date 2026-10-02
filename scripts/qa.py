#!/usr/bin/env python3
"""Technical MP4 checks and contact sheets; visual review remains manual."""
import argparse
import hashlib
import json
import math
import subprocess
import sys
from fractions import Fraction
from pathlib import Path


def run(command):
    return subprocess.run(command, capture_output=True, text=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", type=Path)
    parser.add_argument("--spec", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--interval", type=float, help="Seconds between review samples")
    args = parser.parse_args()
    video, spec_path, out = args.video.resolve(), args.spec.resolve(), args.out.resolve()
    spec = json.loads(spec_path.read_text())
    width, height = int(spec["width"]), int(spec["height"])
    fps, seconds = Fraction(str(spec["fps"])), float(spec["seconds"])
    if min(width, height, fps, seconds) <= 0 or not math.isfinite(seconds):
        raise ValueError("Spec dimensions, fps and seconds must be positive and finite")
    if type(spec["expect_audio"]) is not bool:
        raise ValueError("expect_audio must be true or false")
    interval = args.interval if args.interval is not None else max(1, seconds / 24)
    if interval <= 0 or not math.isfinite(interval):
        raise ValueError("--interval must be positive and finite")
    if not video.is_file():
        raise ValueError(f"Video does not exist: {video}")
    out.mkdir(parents=True, exist_ok=False)
    checks = {}
    report = {
        "video": str(video), "spec_path": str(spec_path), "spec": spec,
        "sha256": "", "checks": checks, "probe": None,
        "sample_times": [], "contact_sheets": [], "visual_review": "pending",
        "note": "Technical checks do not assess design, meaning, caption accuracy or sound quality.",
    }

    def check(name, actual, expected, ok):
        checks[name] = {"ok": bool(ok), "actual": actual, "expected": expected}

    try:
        with video.open("rb") as source:
            report["sha256"] = hashlib.file_digest(source, "sha256").hexdigest()
        probe = run(["ffprobe", "-v", "error", "-show_format", "-show_streams",
                     "-of", "json", str(video)])
        if probe.returncode:
            raise ValueError(f"ffprobe failed: {probe.stderr[-2000:]}")
        data = report["probe"] = json.loads(probe.stdout)
        videos = [s for s in data["streams"] if s["codec_type"] == "video"]
        audios = [s for s in data["streams"] if s["codec_type"] == "audio"]
        if not videos:
            raise ValueError("No video stream")
        stream = videos[0]
        check("video_stream_count", len(videos), 1, len(videos) == 1)
        check("codec", stream.get("codec_name"), "h264", stream.get("codec_name") == "h264")
        check("pixel_format", stream.get("pix_fmt"), "yuv420p", stream.get("pix_fmt") == "yuv420p")
        sar = stream.get("sample_aspect_ratio")
        check("square_pixels", sar, "1:1", sar == "1:1")
        geometry = [stream.get("width"), stream.get("height")]
        check("dimensions", geometry, [width, height], geometry == [width, height])
        actual_fps = Fraction(stream.get("avg_frame_rate", "0/1"))
        check("fps", str(actual_fps), str(fps), actual_fps == fps)
        nominal_fps = Fraction(stream.get("r_frame_rate", "0/1"))
        check("nominal_fps", str(nominal_fps), str(fps), nominal_fps == fps)
        check("audio_present", bool(audios), spec["expect_audio"], bool(audios) == spec["expect_audio"])
        tolerance = 1 / float(fps) + 0.000001
        for name, value in (("video_duration", stream.get("duration")),
                            ("container_duration", data.get("format", {}).get("duration"))):
            duration = float(value) if value is not None else None
            check(name, duration, seconds, duration is not None and abs(duration - seconds) <= tolerance)
        report["duration_tolerance_seconds"] = tolerance
        decode = run(["ffmpeg", "-nostdin", "-v", "error", "-xerror", "-err_detect", "explode",
                      "-threads", "1", "-i", str(video), "-map", "0:v:0", "-map", "0:a?",
                      "-progress", "pipe:1", "-nostats", "-fps_mode", "passthrough", "-f", "null", "-"])
        check("full_decode", decode.returncode, 0, decode.returncode == 0)
        if decode.stderr:
            report["decode_stderr"] = decode.stderr[-4000:]
        decoded_frames = [int(line.split("=", 1)[1]) for line in decode.stdout.splitlines()
                          if line.startswith("frame=")]
        count = decoded_frames[-1] if decoded_frames else 0
        expected_count = round(seconds * float(fps))
        check("frame_count", count, expected_count, count == expected_count)
        if count > 0 and actual_fps > 0 and decode.returncode == 0:
            step = max(1, round(interval * float(actual_fps)))
            indices = sorted(set(range(0, count, step)) | {count - 1})
            report["sample_times"] = [round(n / float(actual_fps), 6) for n in indices]
            report["sample_frame_indices"] = indices
            report["sample_interval_seconds"] = step / float(actual_fps)
            columns = min(4, len(indices))
            rows = min(5, math.ceil(len(indices) / columns))
            vf = (f"select='not(mod(n,{step}))+eq(n,{count - 1})',"
                  "scale=320:320:force_original_aspect_ratio=decrease,"
                  "pad=320:320:(ow-iw)/2:(oh-ih)/2,"
                  "drawtext=text='%{pts\\:hms}':x=8:y=h-28:fontsize=18:"
                  "fontcolor=white:box=1:boxcolor=black@0.8,"
                  f"tile={columns}x{rows}:padding=8:margin=8")
            sheets = run(["ffmpeg", "-nostdin", "-v", "error", "-xerror", "-threads", "1",
                          "-filter_threads", "1", "-i", str(video), "-map", "0:v:0", "-an",
                          "-vf", vf, "-fps_mode", "vfr", "-q:v", "3", str(out / "contact-%03d.jpg")])
            paths = sorted(out.glob("contact-*.jpg"))
            expected_sheets = math.ceil(len(indices) / (columns * rows))
            check("contact_sheets", len(paths), expected_sheets,
                  sheets.returncode == 0 and len(paths) == expected_sheets)
            report["contact_sheets"] = [str(p) for p in paths]
            if sheets.stderr:
                report["contact_stderr"] = sheets.stderr[-2000:]
    except (OSError, ValueError, KeyError, ZeroDivisionError) as error:
        report["error"] = str(error)
    report["ok"] = bool(checks) and "error" not in report and all(c["ok"] for c in checks.values())
    report_path = out / "report.json"
    with report_path.open("x") as target:
        json.dump(report, target, ensure_ascii=False, indent=2)
        target.write("\n")
    print(json.dumps({"ok": report["ok"], "report": str(report_path), "visual_review": "pending"}))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, KeyError, ZeroDivisionError) as error:
        print(f"qa: {error}", file=sys.stderr)
        sys.exit(1)
