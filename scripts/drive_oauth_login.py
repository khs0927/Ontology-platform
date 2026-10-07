"""One-time Google Drive OAuth login for personal accounts.

Usage:
    python scripts/drive_oauth_login.py CLIENT_SECRET.json TOKEN_OUT.json

Opens a browser consent page, then writes an authorized-user token JSON.
Point SION_DRIVE_OAUTH_TOKEN at TOKEN_OUT.json. Keep both files out of git.
"""

from __future__ import annotations

import sys
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/drive"]


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__)
        return 2
    flow = InstalledAppFlow.from_client_secrets_file(argv[1], SCOPES)
    creds = flow.run_local_server(port=0, open_browser=True)
    Path(argv[2]).write_text(creds.to_json(), encoding="utf-8")
    print(f"token written to {argv[2]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
