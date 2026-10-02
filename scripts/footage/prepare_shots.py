#!/usr/bin/env python3
"""
prepare_shots.py — банк готовых кадров. Нарезает исходные клипы на короткие кадры-«атомы»
ОДИН РАЗ: каждый уже нормализован (9:16 1080x1920, зум против watermark, 30fps, без звука),
назван и описан. Дальше сборка любого креатива = просто склейка готовых кадров (быстро).

Вход: clips_catalog.json (нейтральная опись клипов с best_segments).
Выход: shots/<клиент>/*.mp4 + shots_catalog.json + shots_catalog.md.

  python prepare_shots.py \\
    --catalog sources/sample-brand/clips_catalog.json \\
    --clips-root sources/sample-brand \\
    --out-dir shots/sample-brand
"""
import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from shotcut import cut_segment, _dur  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="Нарезать банк готовых кадров из клипов")
    ap.add_argument("--catalog", required=True, help="clips_catalog.json")
    ap.add_argument("--clips-root", required=True, help="папка с исходными клипами")
    ap.add_argument("--out-dir", required=True, help="куда класть готовые кадры (shots/<клиент>)")
    ap.add_argument("--zoom", type=float, default=1.06)
    ap.add_argument("--mode", choices=["cover", "fit"], default="cover")
    ap.add_argument("--max-seg", type=float, default=3.0, help="потолок длины кадра, сек")
    ap.add_argument("--min-seg", type=float, default=2.0,
                    help="минимальная длина кадра, сек: короче — хвостовой огрызок, даст стоп-кадр")
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()

    cat = json.load(open(args.catalog, encoding="utf-8"))
    os.makedirs(args.out_dir, exist_ok=True)

    plan = []  # (src, start, dur, out, meta)
    for clip in cat["clips"]:
        src = os.path.join(args.clips_root, clip["file"])
        stem = os.path.splitext(clip["file"])[0]
        # клип-исключение: не режем, берём ЦЕЛИКОМ одним кадром (флаг "whole": true в каталоге)
        if clip.get("whole"):
            dur = float(clip.get("duration") or 0) or _dur(src)
            name = f"{stem}__whole.mp4"
            plan.append((src, 0.0, dur, os.path.join(args.out_dir, name), {
                "shot": name, "source": clip["file"], "src_start": 0.0,
                "duration": round(dur, 2), "scene": clip.get("scene", ""),
                "emotion": clip.get("emotion", ""), "tags": clip.get("tags", []),
                "note": "ЦЕЛЬНЫЙ клип — не режется, вставлять целиком", "whole": True,
            }))
            continue
        for i, seg in enumerate(clip.get("best_segments", []), 1):
            start = float(seg["start"])
            dur = min(float(seg["end"]) - start, args.max_seg)
            if dur < args.min_seg:
                # хвостовой огрызок клипа: в слот показа он не влезает, и монтаж дотянет его
                # стоп-кадром (pad_atom) — на экране это выглядит как зависшая пауза
                print(f"⏭ {clip['file']} сегмент {i}: {dur:.2f}с < {args.min_seg}с — пропускаю",
                      file=sys.stderr)
                continue
            name = f"{stem}__s{i}.mp4"
            out = os.path.join(args.out_dir, name)
            plan.append((src, start, dur, out, {
                "shot": name, "source": clip["file"], "src_start": round(start, 2),
                "duration": round(dur, 2), "scene": clip.get("scene", ""),
                "emotion": clip.get("emotion", ""), "tags": clip.get("tags", []),
                "note": seg.get("note", ""),
            }))

    print(f"→ нарезаю {len(plan)} кадров в {min(args.workers, len(plan))} потоков…", file=sys.stderr)

    def _do(item):
        src, start, dur, out, meta = item
        cut_segment(src, start, dur, out, mode=args.mode, zoom=args.zoom)
        meta["duration"] = round(_dur(out), 2)  # фактическая длина атома
        return meta

    with ThreadPoolExecutor(max_workers=max(1, min(args.workers, len(plan)))) as ex:
        shots = list(ex.map(_do, plan))

    client = cat.get("client", os.path.basename(args.out_dir))
    cat_json = os.path.join(args.out_dir, "shots_catalog.json")

    # Переносим per-shot описания (desc) из прошлого каталога по КОНТЕНТНОМУ ключу (source + src_start),
    # а НЕ по позиционному имени __sN: при пере-нарезке (сегменты сдвинулись/добавились) одно и то же
    # имя s{N} может указывать на другой кусок клипа — и старый desc молча прилип бы к чужому кадру.
    old = []
    if os.path.exists(cat_json):
        try:
            for s in json.load(open(cat_json, encoding="utf-8")).get("shots", []):
                if s.get("desc"):
                    old.append({"source": s.get("source", ""), "src_start": float(s.get("src_start", 0.0)),
                                "desc": s["desc"]})
        except Exception:
            pass
    used, carried, shifted, no_desc = set(), 0, 0, 0
    for s in shots:
        best_i, best_d = None, 0.6            # допуск совпадения по времени внутри клипа, сек
        for i, o in enumerate(old):
            if o["source"] == s["source"]:
                d = abs(o["src_start"] - float(s["src_start"]))
                if d <= best_d:
                    best_i, best_d = i, d
        if best_i is not None:
            s["desc"] = old[best_i]["desc"]
            used.add(best_i)
            carried += 1
            if best_d > 0.5:
                shifted += 1
        elif old:
            no_desc += 1
    if old:
        msg = f"  desc: перенесено {carried}/{len(shots)} кадров"
        if shifted:
            msg += f"; ⚠ смещение src_start >0.5с у {shifted} — перепроверить подпись"
        if no_desc:
            msg += f"; {no_desc} без desc — описать субагентом"
        if len(old) - len(used):
            msg += f"; {len(old) - len(used)} старых desc не легли на новую нарезку"
        print(msg, file=sys.stderr)
    json.dump({"client": client, "note": "Готовые нормализованные кадры (9:16, зум применён). "
              "Сборка креатива = склейка этих кадров без перенарезки.", "shots": shots},
              open(cat_json, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    md = [f"# Банк кадров — {client}", "",
          f"{len(shots)} готовых кадров (9:16 1080×1920, зум применён, без звука). "
          "Сборка креатива = склейка этих кадров, без перенарезки.", "",
          "| Кадр | Из клипа | Длит | Что на кадре | Эмоция | Теги |",
          "|------|----------|------|--------------|--------|------|"]
    for s in shots:
        md.append(f"| {s['shot']} | {s['source']} | {s['duration']}с | {s['note'] or s['scene']} "
                  f"| {s['emotion']} | {', '.join(s['tags'][:4])} |")
    open(os.path.join(args.out_dir, "shots_catalog.md"), "w", encoding="utf-8").write("\n".join(md) + "\n")

    print(f"✅ {len(shots)} кадров → {args.out_dir}\n   {cat_json}")


if __name__ == "__main__":
    main()
