#!/usr/bin/env python3
"""
upload_gdrive.py — заливка готовых видео-креативов на Google Drive.

Переиспользует OAuth-токен пользователя (google-token.json), тем же способом,
что и md2gdoc.py. Токен создаётся один раз: scripts/footage/google_auth.py. Работает с личным Диском пользователя.

Примеры:
  # залить один файл в папку Диска
  python upload_gdrive.py output/campaign/krео_1.mp4 --folder-id 1AbC...xyz

  # залить всю папку с готовыми креативами, предварительно создав подпапку по дате
  python upload_gdrive.py output/campaign/ --folder-id 1AbC...xyz --subfolder "Example campaign"

Печатает webViewLink каждого залитого файла. Возвращает ненулевой код при ошибке.
"""
import argparse
import mimetypes
import os
import sys
import time

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

TOKEN_PATH = os.getenv('GOOGLE_TOKEN_PATH', os.path.expanduser('~/.config/media-skills/google-token.json'))
VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".webm", ".mkv"}


def get_drive():
    """Авторизация по OAuth-токену пользователя (с авто-refresh)."""
    creds = Credentials.from_authorized_user_file(TOKEN_PATH)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(TOKEN_PATH, "w") as f:
            f.write(creds.to_json())
    return build("drive", "v3", credentials=creds)


def ensure_subfolder(drive, parent_id: str, name: str) -> str:
    """Найти подпапку по имени внутри parent_id или создать новую. Вернуть её id."""
    safe = name.replace("'", "\\'")
    q = (
        f"name = '{safe}' and mimeType = 'application/vnd.google-apps.folder' "
        f"and '{parent_id}' in parents and trashed = false"
    )
    hits = drive.files().list(q=q, fields="files(id)", pageSize=1).execute().get("files", [])
    if hits:
        return hits[0]["id"]
    meta = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [parent_id],
    }
    folder = drive.files().create(body=meta, fields="id").execute()
    return folder["id"]


def upload_file(drive, path: str, parent_id: str, rename: str | None = None,
                replace: bool = False) -> dict:
    """Залить один файл в parent_id. Вернуть {name, id, link}. replace — удалить одноимённые в папке."""
    name = rename or os.path.basename(path)
    if replace:
        safe = name.replace("'", "\\'")
        q = f"name = '{safe}' and '{parent_id}' in parents and trashed = false"
        for old in drive.files().list(q=q, fields="files(id)").execute().get("files", []):
            drive.files().update(fileId=old["id"], body={"trashed": True}).execute()
    mime = mimetypes.guess_type(path)[0] or "application/octet-stream"
    # Кусками по 8 МБ с повтором: 01.10.2026 загрузка 200 МБ одним куском трижды падала на SSLEOFError.
    media = MediaFileUpload(path, mimetype=mime, resumable=True, chunksize=8 * 1024 * 1024)
    meta = {"name": name, "parents": [parent_id]}
    req = drive.files().create(body=meta, media_body=media, fields="id, name, webViewLink")
    f, fails = None, 0
    while f is None:
        try:
            _, f = req.next_chunk(num_retries=3)
        except (OSError, ConnectionError) as e:
            fails += 1
            if fails > 8:
                raise
            print(f"  повтор куска {fails}: {type(e).__name__}", file=sys.stderr)
            time.sleep(5)
    return {"name": f["name"], "id": f["id"], "link": f.get("webViewLink", "")}


def main():
    ap = argparse.ArgumentParser(description="Залить видео-креативы на Google Drive")
    ap.add_argument("path", help="файл или папка с готовыми креативами")
    ap.add_argument("--folder-id", required=True, help="ID целевой папки Google Drive")
    ap.add_argument("--subfolder", default=None, help="создать/использовать подпапку с этим именем")
    ap.add_argument("--name", default=None, help="переименовать при заливке (только для одного файла)")
    ap.add_argument("--replace", action="store_true", help="удалить одноимённые в папке перед заливкой")
    args = ap.parse_args()

    if not os.path.exists(args.path):
        print(f"НЕТ ТАКОГО ПУТИ: {args.path}", file=sys.stderr)
        return 2

    drive = get_drive()
    parent = args.folder_id
    if args.subfolder:
        parent = ensure_subfolder(drive, parent, args.subfolder)
        print(f"Папка назначения: {args.subfolder} ({parent})")

    if os.path.isfile(args.path):
        files = [args.path]
    else:
        files = sorted(
            os.path.join(args.path, f)
            for f in os.listdir(args.path)
            if os.path.splitext(f)[1].lower() in VIDEO_EXTS
        )
        if not files:
            print(f"В папке нет видеофайлов ({', '.join(sorted(VIDEO_EXTS))})", file=sys.stderr)
            return 2

    ok = 0
    for p in files:
        try:
            res = upload_file(drive, p, parent, rename=args.name if len(files) == 1 else None,
                              replace=args.replace)
            print(f"✅ {res['name']} → {res['link']}")
            ok += 1
        except Exception as e:
            print(f"❌ {os.path.basename(p)}: {e}", file=sys.stderr)

    print(f"\nЗалито: {ok}/{len(files)}")
    return 0 if ok == len(files) else 1


if __name__ == "__main__":
    sys.exit(main())
