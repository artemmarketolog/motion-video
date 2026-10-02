#!/usr/bin/env python3
"""
compress_media.py — сжать видео в папке (H.264 crf23) без сильной потери качества, сохранив имена.
Чтобы не хранить тяжёлые исходники/кадры. Заменяет файл на месте, если сжатая версия ощутимо меньше.

Запускать после скачивания клиентских клипов и после нарезки банка:
  python compress_media.py --dir sources/<клиент> --no-audio  # исходники (без звука: в монтаж идёт только озвучка+музыка)
  python compress_media.py --dir shots/<клиент> --no-audio    # кадры банка (без звука)
"""
import argparse
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi"}


def compress_one(path, crf, maxrate, audio):
    ext = os.path.splitext(path)[1]
    tmp = path + f".compress{ext}"
    bufs = f"{int(maxrate.rstrip('M')) * 2}M"
    cmd = ["ffmpeg", "-y", "-i", path, "-c:v", "libx264", "-preset", "medium", "-crf", str(crf),
           "-maxrate", maxrate, "-bufsize", bufs, "-pix_fmt", "yuv420p", "-movflags", "+faststart"]
    cmd += (["-c:a", "aac", "-b:a", "128k"] if audio else ["-an"])
    cmd += [tmp]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode == 0 and os.path.exists(tmp):
        old, new = os.path.getsize(path), os.path.getsize(tmp)
        if new < old * 0.95:                     # заменяем только если реально легче
            os.replace(tmp, path)
            return old, new
        os.remove(tmp)
    elif os.path.exists(tmp):
        os.remove(tmp)                           # частичный огрызок при падении ffmpeg — не оставляем
    return None


def main():
    ap = argparse.ArgumentParser(description="Сжать видео в папке (crf23) без сильной потери качества")
    ap.add_argument("--dir", required=True)
    ap.add_argument("--crf", type=int, default=23)
    ap.add_argument("--maxrate", default="6M")
    ap.add_argument("--no-audio", action="store_true", help="выкинуть звук (для кадров банка)")
    ap.add_argument("--workers", type=int, default=5)
    args = ap.parse_args()

    files = [os.path.join(args.dir, f) for f in sorted(os.listdir(args.dir))
             if os.path.splitext(f)[1].lower() in VIDEO_EXTS and ".compress." not in f]  # не жать свои огрызки
    if not files:
        sys.exit(f"нет видео в {args.dir}")

    def _do(f):
        res = compress_one(f, args.crf, args.maxrate, not args.no_audio)
        if res:
            o, n = res
            print(f"  {os.path.basename(f)}: {o//1024//1024}MB → {n//1024//1024}MB", file=sys.stderr)
        return res

    with ThreadPoolExecutor(max_workers=max(1, min(args.workers, len(files)))) as ex:
        results = list(ex.map(_do, files))

    done = [r for r in results if r]
    to, tn = sum(o for o, _ in done), sum(n for _, n in done)
    print(f"✅ сжато {len(done)}/{len(files)} | {to//1024//1024}MB → {tn//1024//1024}MB "
          f"(−{100*(to-tn)//to if to else 0}%)")


if __name__ == "__main__":
    main()
