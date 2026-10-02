#!/usr/bin/env python3
"""
merge_shot_meta.py — влить per-shot подписи/поля от субагентов в shots_catalog.json (шаг 6 онбординга).

Субагенты описывают кадры пачками и возвращают JSON-фрагменты вида
  {"shots": {"01_boy__s1.mp4": {"desc": "…", "subjects": ["мальчик ~11"], "beat": "боль",
                                 "plan": "средний", "location": "класс", "on_screen": "Scratch"}}}
или сокращённо {"shots": {"01_boy__s1.mp4": "строка-desc"}}.

Хелпер сливает их в shots_catalog.json по ИМЕНИ кадра, валидирует и печатает покрытие:
  • неизвестное имя (нет такого кадра в банке) → ОШИБКА (опечатка субагента, а не тихий пропуск);
  • кадры без desc после слияния → перечисляются (описать);
  • одно имя в двух фрагментах → предупреждение (берётся последнее).
desc/поля НЕ трогаются prepare_shots при пере-нарезке (переносятся по контентному ключу).

  python merge_shot_meta.py --catalog shots/<slug>/shots_catalog.json frag1.json frag2.json …
  python merge_shot_meta.py --catalog shots/<slug>/shots_catalog.json --check   # только отчёт, без изменений
"""
import argparse
import json
import sys

# per-shot поля (структурные — для подбора кадра под смысл фразы; desc — текстовый тай-брейк)
FIELDS = ("desc", "subjects", "beat", "plan", "location", "on_screen")


def load_frag(path):
    d = json.load(open(path, encoding="utf-8"))
    return d.get("shots", d)          # допускаем и {"shots": {...}}, и голый {...}


def main():
    ap = argparse.ArgumentParser(description="Влить per-shot подписи субагентов в shots_catalog.json")
    ap.add_argument("--catalog", required=True, help="shots/<slug>/shots_catalog.json")
    ap.add_argument("fragments", nargs="*", help="JSON-фрагменты от субагентов")
    ap.add_argument("--check", action="store_true", help="только отчёт покрытия, без записи")
    args = ap.parse_args()

    cat = json.load(open(args.catalog, encoding="utf-8"))
    shots = cat["shots"]
    by_name = {s["shot"]: s for s in shots}

    seen, unknown = {}, []
    for fp in args.fragments:
        for name, val in load_frag(fp).items():
            if name not in by_name:
                unknown.append((fp, name))
                continue
            if name in seen and seen[name] != fp:
                print(f"⚠ {name} описан в двух фрагментах ({seen[name]} и {fp}) — беру последний",
                      file=sys.stderr)
            seen[name] = fp
            s = by_name[name]
            if isinstance(val, str):
                s["desc"] = val.strip()
            elif isinstance(val, dict):
                for k in FIELDS:
                    if val.get(k) not in (None, "", []):
                        s[k] = val[k]
            else:
                print(f"⚠ {name}: неожиданный тип значения {type(val).__name__}", file=sys.stderr)

    if unknown:
        print("✗ неизвестные кадры (нет в банке — опечатка в имени?):", file=sys.stderr)
        for fp, name in unknown:
            print(f"    {name}  ({fp})", file=sys.stderr)
        sys.exit(1)

    no_desc = [s["shot"] for s in shots if not s.get("desc")]
    total, described = len(shots), len(shots) - len(no_desc)
    if not args.check:
        json.dump(cat, open(args.catalog, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"{'проверка' if args.check else '✅ влито'}: desc у {described}/{total} кадров")
    if no_desc:
        print(f"  без desc ({len(no_desc)}): " + ", ".join(no_desc[:20])
              + (" …" if len(no_desc) > 20 else ""))
        sys.exit(0 if args.check else 2)   # ненулевой код при неполном покрытии (гейт готовности банка)


if __name__ == "__main__":
    main()
