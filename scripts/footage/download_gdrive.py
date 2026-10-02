#!/usr/bin/env python3
"""
download_gdrive.py — скачать файлы из папки Google Drive через Drive API (авторизованно,
токеном пользователя). Надёжнее gdown: не упирается в анонимный rate-limit/quota.

  python download_gdrive.py --folder-id 19aUd... --out-dir sources/<клиент> [--skip-existing]
"""
import argparse
import os
import sys

from googleapiclient.http import MediaIoBaseDownload

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from upload_gdrive import get_drive  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--folder-id", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--skip-existing", action="store_true")
    a = ap.parse_args()
    os.makedirs(a.out_dir, exist_ok=True)
    drive = get_drive()

    files, tok = [], None
    while True:
        r = drive.files().list(
            q=f"'{a.folder_id}' in parents and trashed = false",
            fields="nextPageToken, files(id,name,size)", pageSize=200, pageToken=tok,
        ).execute()
        files += r.get("files", [])
        tok = r.get("nextPageToken")
        if not tok:
            break
    print(f"в папке {len(files)} файлов", file=sys.stderr)

    ok = 0
    for f in files:
        out = os.path.join(a.out_dir, f["name"])
        if a.skip_existing and os.path.exists(out):
            continue
        req = drive.files().get_media(fileId=f["id"])
        with open(out, "wb") as fh:
            dl = MediaIoBaseDownload(fh, req, chunksize=8 * 1024 * 1024)
            done = False
            while not done:
                _, done = dl.next_chunk()
        print(f"✅ {f['name']}")
        ok += 1
    print(f"скачано {ok}/{len(files)}")


if __name__ == "__main__":
    main()
