"""
定期サマリー送信スクリプト（GitHub Actions用）

Streamlit不要。環境変数から認証情報を取得して
折返し件数のチェック状況＋件数データをChatworkに送信する。
"""

import os
import json
import sys
from datetime import datetime, timezone, timedelta

import gspread
import requests
from google.oauth2.service_account import Credentials

# --- 設定 ---
CHATWORK_API_TOKEN = os.environ.get("CHATWORK_API_TOKEN", "")
CHATWORK_ROOM_IDS = ["398296862", "398125674", "260721357", "380105765", "422217521"]
CHATWORK_API_URL = "https://api.chatwork.com/v2"

# Google Sheets
GS_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/drive",
]
IKUSEI_SHEET_ID = "1aXKoCL_bppzw60ddYmtaGjqHHYCRRLyVU6z3ZxB7JbY"
BY_SHEET_ID = "1Xg2oxrIrXy3oju8s9POm8RRHW6RWqqbj7ALTBjAzkvA"

EXCLUDED_TIME_SLOTS = {"14:00", "19:00", "20:00"}

TARGET_CATEGORIES = {
    "折返CS開通前": "折り返し希望(開通前)",
    "折返新設FC": "折り返し希望(新設FC)",
    "折返１週間FC": "折り返し希望(1週間後)",
    "折返工事取得": "折り返し希望(工事取得)",
}

JST = timezone(timedelta(hours=9))


def get_gspread_client():
    """環境変数 GCP_SERVICE_ACCOUNT_JSON からgspreadクライアントを作成（Base64対応）。"""
    import base64
    sa_json = os.environ.get("GCP_SERVICE_ACCOUNT_JSON", "")
    if sa_json:
        # Base64エンコード済みならデコード
        try:
            decoded = base64.b64decode(sa_json)
            creds_dict = json.loads(decoded)
        except Exception:
            creds_dict = json.loads(sa_json)
        creds = Credentials.from_service_account_info(creds_dict, scopes=GS_SCOPES)
    else:
        # ローカルフォールバック
        creds = Credentials.from_service_account_file(
            "yoshida0538-f46ce1eea153.json", scopes=GS_SCOPES
        )
    return gspread.authorize(creds)


def get_checks(client) -> dict:
    """Google Sheetsからチェック状態を取得。"""
    sh = client.open_by_key(IKUSEI_SHEET_ID)
    try:
        ws = sh.worksheet("orikaeshi_check_data")
        raw = ws.acell("A1").value
        if raw:
            return json.loads(raw)
    except Exception:
        pass
    return {}


def get_orikaeshi_data(client) -> tuple[str, list[str], list[str], dict]:
    """
    折返し件数データを取得。
    Returns: (date_str, time_slots, categories, counts)
    """
    sh = client.open_by_key(BY_SHEET_ID)

    # 最新のBY用_*シートを取得
    by_titles = [
        ws.title for ws in sh.worksheets()
        if ws.title.startswith("BY用_") and ws.title[4:].lstrip("_").isdigit()
    ]
    if not by_titles:
        return "", [], [], {}
    by_titles.sort(reverse=True)
    target_ws = sh.worksheet(by_titles[0])
    all_vals = target_ws.get_all_values()
    if len(all_vals) < 2:
        return "", [], [], {}

    # 時間帯ヘッダー解析
    time_header = all_vals[0]
    time_slots_raw = []
    for col_idx in range(5, len(time_header), 3):
        label = (time_header[col_idx] or "").strip()
        if not label:
            continue
        if ":" in label:
            parts = label.split(":")
            label = f"{parts[0]}:{parts[1]}"
        time_slots_raw.append((col_idx, label))

    # 今日の日付
    now = datetime.now(JST)
    today_str = now.strftime("%Y/%m/%d")

    # データ収集
    categories_seen = []
    counts = {}
    for row in all_vals:
        if len(row) < 5:
            continue
        date_str = (row[3] or "").strip()
        cat_str = (row[4] or "").strip()
        if not date_str or cat_str not in TARGET_CATEGORIES:
            continue
        if date_str != today_str:
            continue
        display_cat = TARGET_CATEGORIES[cat_str]
        if display_cat not in categories_seen:
            categories_seen.append(display_cat)
        for col_idx, ts_label in time_slots_raw:
            # 3列（新規/改め/留守）を合算
            total = 0
            for offset in range(3):
                ci = col_idx + offset
                if ci < len(row):
                    try:
                        total += int(row[ci])
                    except (ValueError, TypeError):
                        pass
            counts[(display_cat, ts_label)] = counts.get((display_cat, ts_label), 0) + total

    time_slots = [ts for _, ts in time_slots_raw]

    # カテゴリ順を固定
    ordered_cats = [v for v in TARGET_CATEGORIES.values() if v in categories_seen]

    return today_str, time_slots, ordered_cats, counts


def build_summary(checks, date_str, time_slots, categories, counts):
    """サマリーメッセージを組み立てる。"""
    now = datetime.now(JST)
    current_hour = now.hour
    lines = [f"[toall]\n[info][title]折返し件数 状況アナウンス ({now.strftime('%H:%M')}時点)[/title]"]
    lines.append(f"対象日: {date_str}")
    lines.append("時設推奨時間帯とは：現在ご予約に余裕があるため、可能であれば優先的にご提案ください。\n")

    def _is_future(ts):
        """時間帯が現在時刻以降かどうか。"""
        try:
            return int(ts.split(":")[0]) >= current_hour
        except (ValueError, IndexError):
            return True

    for cat in categories:
        checked = []
        unchecked = []
        for ts in time_slots:
            if ts in EXCLUDED_TIME_SLOTS or not _is_future(ts):
                continue
            key = f"{date_str}|{cat}|{ts}"
            if checks.get(key, False):
                checked.append(ts)
            else:
                unchecked.append(ts)

        if not unchecked:
            lines.append(f"■ {cat}")
            lines.append("  全時間帯 対応不可 → 翌日以降でお願いします\n")
        elif not checked:
            lines.append(f"■ {cat}")
            lines.append("  全時間帯 対応可能")
            if counts and unchecked:
                ranked = sorted(unchecked, key=lambda t: counts.get((cat, t), 0))
                top = ranked[:3]
                top_with_count = [f"{t}({counts.get((cat, t), 0)}件)" for t in top]
                lines.append(f"  時設推奨時間帯: {', '.join(top_with_count)}")
            lines.append("")
        else:
            lines.append(f"■ {cat}")
            lines.append(f"  対応不可時間: {', '.join(checked)}")
            if counts and unchecked:
                ranked = sorted(unchecked, key=lambda t: counts.get((cat, t), 0))
                top = ranked[:3]
                top_with_count = [f"{t}({counts.get((cat, t), 0)}件)" for t in top]
                lines.append(f"  時設推奨時間帯: {', '.join(top_with_count)}")
            lines.append("")

    lines.append("[/info]")
    return "\n".join(lines)


def send_chatwork(body):
    """全ルームにメッセージ送信。"""
    headers = {
        "X-ChatWorkToken": CHATWORK_API_TOKEN,
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    }
    for rid in CHATWORK_ROOM_IDS:
        try:
            resp = requests.post(
                f"{CHATWORK_API_URL}/rooms/{rid}/messages",
                headers=headers,
                data={"body": body, "self_unread": 1},
                timeout=10,
            )
            print(f"Room {rid}: {resp.status_code}")
        except Exception as e:
            print(f"Room {rid}: ERROR {e}")


def main():
    if not CHATWORK_API_TOKEN:
        print("ERROR: CHATWORK_API_TOKEN not set")
        sys.exit(1)

    client = get_gspread_client()
    checks = get_checks(client)
    date_str, time_slots, categories, counts = get_orikaeshi_data(client)

    if not date_str or not categories:
        print("WARNING: No data found for today")
        # データがなくても空メッセージは送らない
        sys.exit(0)

    body = build_summary(checks, date_str, time_slots, categories, counts)
    print("--- Message ---")
    print(body)
    print("--- Sending ---")
    send_chatwork(body)
    print("Done")


if __name__ == "__main__":
    main()
