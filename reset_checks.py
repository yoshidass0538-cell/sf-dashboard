"""
折返し件数チェックボックスの自動リセット（GitHub Actions用）

毎朝09:00 JSTに実行し、チェックが入っている項目を全てクリアする。
"""

import os
import json
import sys

import gspread
from google.oauth2.service_account import Credentials

GS_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]
IKUSEI_SHEET_ID = "1aXKoCL_bppzw60ddYmtaGjqHHYCRRLyVU6z3ZxB7JbY"
WORKSHEET_NAME = "orikaeshi_check_data"
CELL = "A1"


def get_gspread_client():
    import base64
    sa_json = os.environ.get("GCP_SERVICE_ACCOUNT_JSON", "")
    if sa_json:
        try:
            decoded = base64.b64decode(sa_json)
            creds_dict = json.loads(decoded)
        except Exception:
            creds_dict = json.loads(sa_json)
        creds = Credentials.from_service_account_info(creds_dict, scopes=GS_SCOPES)
    else:
        creds = Credentials.from_service_account_file(
            "yoshida0538-f46ce1eea153.json", scopes=GS_SCOPES
        )
    return gspread.authorize(creds)


def main():
    client = get_gspread_client()
    sh = client.open_by_key(IKUSEI_SHEET_ID)
    try:
        ws = sh.worksheet(WORKSHEET_NAME)
    except gspread.exceptions.WorksheetNotFound:
        print("Worksheet not found, nothing to reset")
        return

    raw = ws.acell(CELL).value
    if not raw:
        print("No check data found, nothing to reset")
        return

    checks = json.loads(raw)
    if not checks:
        print("Already empty, nothing to reset")
        return

    print(f"Clearing {len(checks)} checks")
    ws.update_acell(CELL, json.dumps({}))
    print("Done - all checks cleared")


if __name__ == "__main__":
    main()
