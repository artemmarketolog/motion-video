#!/usr/bin/env python3
"""Shot-bank atom cutting (ported from an earlier ffmpeg montage pipeline): one resample to
1080x1920/30fps, anti-watermark zoom-crop, no audio. Used by prepare_shots.py."""
import subprocess
import sys

W, H, FPS = 1080, 1920, 30
VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi"}
SEG_ENC = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-maxrate", "6M",
           "-bufsize", "12M", "-pix_fmt", "yuv420p"]  # лёгкий кадр банка, качество почти без потерь


def _run(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        sys.stderr.write(p.stderr[-1500:] + "\n")
        raise SystemExit(f"ffmpeg упал ({p.returncode}): {' '.join(cmd[:6])} …")
    return p


def _dur(path: str) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "csv=p=0", path], capture_output=True, text=True).stdout.strip()
    return float(out) if out else 0.0


def _cover_vf(zoom: float) -> str:
    """Один ресэмпл: масштаб с запасом zoom → центр-кроп 1080x1920 (зум-кроп уводит watermark за край)."""
    zw = int(W * zoom); zw += zw % 2
    zh = int(H * zoom); zh += zh % 2
    return (f"scale={zw}:{zh}:force_original_aspect_ratio=increase,"
            f"crop={W}:{H},setsar=1,fps={FPS},format=yuv420p")


def _fit_vf() -> str:
    return (f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
            f"setsar=1,boxblur=40:10[bg];"
            f"[0:v]scale={W}:{H}:force_original_aspect_ratio=decrease,setsar=1[fg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2,fps={FPS},format=yuv420p")


def normalize_clip(src: str, out: str, mode: str = "cover", zoom: float = 1.06):
    """Клип целиком → 1080x1920/30fps, без звука."""
    if mode == "cover":
        _run(["ffmpeg", "-y", "-i", src, "-vf", _cover_vf(zoom), "-an", *SEG_ENC, out])
    else:
        _run(["ffmpeg", "-y", "-i", src, "-filter_complex", _fit_vf(), "-an", *SEG_ENC, out])
    return out


def cut_segment(src: str, start: float, dur: float, out: str, mode: str = "cover", zoom: float = 1.06):
    """Вырезать [start, start+dur] → нормализованный кадр 1080x1920/30fps, без звука. Один ресэмпл."""
    pre = ["ffmpeg", "-y", "-ss", f"{start}", "-i", src, "-t", f"{dur}"]
    if mode == "cover":
        _run(pre + ["-vf", _cover_vf(zoom), "-an", *SEG_ENC, out])
    else:
        _run(pre + ["-filter_complex", _fit_vf(), "-an", *SEG_ENC, out])
    return out
