#!/usr/bin/env python3
"""One-time Google OAuth for the Drive/Docs helpers (upload_gdrive.py, download_gdrive.py, md2gdoc.py).

1. Google Cloud Console → APIs & Services: enable Google Drive API and Google Docs API.
2. Credentials → Create credentials → OAuth client ID → Desktop app → download JSON.
3. python google_auth.py --client-secret /abs/client_secret.json
   A browser opens; allow access and the local redirect finishes by itself.
   Headless server: --port 8765 --no-browser, forward the port (ssh -L 8765:localhost:8765 server),
   then open the printed URL on your computer.
Writes ~/.config/media-skills/google-token.json (chmod 600) or GOOGLE_TOKEN_PATH. Prints no secrets.
"""
import argparse
import os
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ['https://www.googleapis.com/auth/drive', 'https://www.googleapis.com/auth/documents']
TOKEN = Path(os.getenv('GOOGLE_TOKEN_PATH', Path.home() / '.config/media-skills/google-token.json')).expanduser()


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--client-secret', required=True, type=Path, help='OAuth client JSON (Desktop app)')
    p.add_argument('--port', type=int, default=0, help='fixed local port for the redirect (for SSH forwarding)')
    p.add_argument('--no-browser', action='store_true', help='print the URL instead of opening a browser')
    a = p.parse_args()
    flow = InstalledAppFlow.from_client_secrets_file(str(a.client_secret), SCOPES)
    creds = flow.run_local_server(port=a.port, open_browser=not a.no_browser)
    TOKEN.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    TOKEN.write_text(creds.to_json())
    TOKEN.chmod(0o600)
    print(f'Token saved: {TOKEN}')


if __name__ == '__main__':
    main()
