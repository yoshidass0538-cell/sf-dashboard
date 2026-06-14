# -*- coding: utf-8 -*-
"""NURO消セン抑止FC 日報を Chatwork ルーム(415594816)へ送信（当日分）。

GitHub Actions から毎日19:00(JST)に実行する想定。
streamlit 非依存にするため chatwork_client は介さず、トークンは環境変数から直接読む。
"""
import os
from datetime import datetime, timezone, timedelta

import requests

from sf_client import get_sf
from nuro_daily_report import build_report

ROOM_ID = "415594816"
API_URL = "https://api.chatwork.com/v2"
JST = timezone(timedelta(hours=9))


def main() -> None:
    token = os.environ.get("CHATWORK_API_TOKEN", "")
    if not token:
        raise SystemExit("CHATWORK_API_TOKEN が未設定です")

    today = datetime.now(JST).date()  # 当日分
    body = build_report(get_sf(), today)

    resp = requests.post(
        f"{API_URL}/rooms/{ROOM_ID}/messages",
        headers={
            "X-ChatWorkToken": token,
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        },
        data={"body": body, "self_unread": 1},
        timeout=20,
    )
    print(f"sent to room {ROOM_ID} ({today}): {resp.status_code} {resp.text[:200]}")
    resp.raise_for_status()


if __name__ == "__main__":
    main()
