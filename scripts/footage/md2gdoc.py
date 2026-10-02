#!/usr/bin/env python3
"""
md2gdoc.py — выгрузить markdown-файл в Google Doc (через HTML-импорт Drive API).

Нужен, когда ТЗ на кадры (или любой другой рабочий документ) надо отдать пользователю
в читаемом виде: markdown в терминале смотреть неудобно, Google Doc открывается
с телефона, имеет навигацию по заголовкам и правится руками.

Идемпотентно: документ с тем же именем в той же папке ОБНОВЛЯЕТСЯ, а не дублируется,
поэтому ссылка, однажды отданная пользователю, остаётся рабочей после любых правок.

  python md2gdoc.py sources/<slug>/shot_ideas.md "Кадры для генерации — <клиент>" <folder_id>

folder_id — подпапка клиента на Drive (из <studio>/clients.json, поле drive_folder_id).

Что переживает конвертацию: заголовки (h1-h4 → стили Google Docs, работает навигация),
жирный, курсив, `код`, списки, горизонтальные линии. Блоки `> цитата` становятся серыми
моноширинными абзацами — так промпты видно как отдельные блоки и они копируются
одним выделением.
"""
import argparse
import html
import io
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from googleapiclient.http import MediaIoBaseUpload  # noqa: E402
from upload_gdrive import get_drive  # noqa: E402

QUOTE_STYLE = (
    "margin-left:24pt;margin-right:12pt;padding:6pt;"
    "background-color:#f1f3f4;font-family:'Roboto Mono',monospace;font-size:9.5pt;"
)


def inline(s: str) -> str:
    """`код`, **жирный**, *курсив* → html. Экранируем ДО подстановки тегов."""
    s = html.escape(s)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<i>\1</i>", s)
    return s


def md_to_html(md: str, title: str) -> str:
    out, in_ul, in_ol = [], False, False

    def close_lists():
        nonlocal in_ul, in_ol
        if in_ul:
            out.append("</ul>")
            in_ul = False
        if in_ol:
            out.append("</ol>")
            in_ol = False

    for raw in md.split("\n"):
        line = raw.rstrip()
        if not line.strip():
            close_lists()
            continue
        if re.match(r"^---+$", line.strip()):
            close_lists()
            out.append("<hr>")
            continue
        m = re.match(r"^(#{1,4})\s+(.*)$", line)
        if m:
            close_lists()
            out.append(f"<h{len(m.group(1))}>{inline(m.group(2))}</h{len(m.group(1))}>")
            continue
        if line.startswith(">"):
            close_lists()
            out.append(f'<p style="{QUOTE_STYLE}">{inline(line.lstrip("> ").strip())}</p>')
            continue
        m = re.match(r"^\s*[-*]\s+(.*)$", line)
        if m:
            if in_ol:
                out.append("</ol>")
                in_ol = False
            if not in_ul:
                out.append("<ul>")
                in_ul = True
            out.append(f"<li>{inline(m.group(1))}</li>")
            continue
        m = re.match(r"^\s*\d+\.\s+(.*)$", line)
        if m:
            if in_ul:
                out.append("</ul>")
                in_ul = False
            if not in_ol:
                out.append("<ol>")
                in_ol = True
            out.append(f"<li>{inline(m.group(1))}</li>")
            continue
        close_lists()
        out.append(f"<p>{inline(line)}</p>")
    close_lists()
    body = "\n".join(out)
    return (f"<html><head><meta charset='utf-8'><title>{html.escape(title)}</title></head>"
            f"<body>{body}</body></html>")


def main():
    ap = argparse.ArgumentParser(description="Markdown → Google Doc (обновляет существующий по имени)")
    ap.add_argument("md_path", help="путь к .md файлу")
    ap.add_argument("title", help="имя документа на Drive (по нему же ищется существующий)")
    ap.add_argument("folder_id", help="ID папки на Drive")
    args = ap.parse_args()

    md = Path(args.md_path).read_text(encoding="utf-8")
    doc_html = md_to_html(md, args.title)

    drive = get_drive()
    safe = args.title.replace("'", "\\'")
    q = (f"name = '{safe}' and '{args.folder_id}' in parents "
         f"and mimeType = 'application/vnd.google-apps.document' and trashed = false")
    existing = drive.files().list(q=q, fields="files(id)").execute().get("files", [])

    media = MediaIoBaseUpload(io.BytesIO(doc_html.encode("utf-8")), mimetype="text/html", resumable=False)
    if existing:
        file_id = existing[0]["id"]
        drive.files().update(fileId=file_id, media_body=media).execute()
        action = "обновлён"
    else:
        created = drive.files().create(
            body={"name": args.title,
                  "mimeType": "application/vnd.google-apps.document",
                  "parents": [args.folder_id]},
            media_body=media, fields="id",
        ).execute()
        file_id = created["id"]
        action = "создан"
    print(f"{action}: https://docs.google.com/document/d/{file_id}/edit")


if __name__ == "__main__":
    main()
