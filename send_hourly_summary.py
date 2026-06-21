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
# 詳細フォーマット用（従来形式）
ROOM_IDS_DETAILED = ["398296862"]  # 380105765は2026-05-11に配信停止
# コンパクトフォーマット用
# 422217521(スポットバイトル受電共有ルーム)は2026-06-19に配信停止
ROOM_IDS_COMPACT = ["398125674"]
CHATWORK_ROOM_IDS = ROOM_IDS_DETAILED + ROOM_IDS_COMPACT  # 260721357は2026-04-15に配信停止
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
    "折返CS開通前": "(開通前)",
    "折返新設FC": "(新設FC)",
    "折返１週間FC": "(1週間後)",
    "折返工事取得": "(工事取得)",
}

JST = timezone(timedelta(hours=9))

# 18:00・18:30配信時のみ (開通前) の上に挿入する定型文
NOTICE_1840 = "【18：40以降は翌日以降の折り返し案内をお願いいたします】"


def _show_1840_notice(now) -> bool:
    """18:00・18:30配信のときだけTrue（cron発火のずれを考慮し18時台の45分未満）。"""
    return now.hour == 18 and now.minute < 45


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

    _show_notice = _show_1840_notice(now)

    for cat in categories:
        if _show_notice and cat == "(開通前)":
            lines.append(f"{NOTICE_1840}\n")

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
            lines.append("  全時間帯❌ → 翌日以降でお願いします\n")
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
            ng_str = ", ".join(f"{t}台❌" for t in checked)
            lines.append(f"■ {cat}")
            lines.append(f"  対応不可時間: {ng_str}")
            if counts and unchecked:
                ranked = sorted(unchecked, key=lambda t: counts.get((cat, t), 0))
                top = ranked[:3]
                top_with_count = [f"{t}({counts.get((cat, t), 0)}件)" for t in top]
                lines.append(f"  時設推奨時間帯: {', '.join(top_with_count)}")
            lines.append("")

    lines.append("[/info]")
    return "\n".join(lines)


def build_summary_compact(checks, date_str, time_slots, categories, counts):
    """コンパクト版サマリー（ROOM_IDS_COMPACT 向け）。"""
    now = datetime.now(JST)
    current_hour = now.hour

    lines = []
    lines.append(f"対象日: {date_str}　{now.strftime('%H:%M')}配信")
    lines.append("※推奨＝空き多い時間（優先案内）")
    lines.append("")

    def _is_future(ts):
        try:
            return int(ts.split(":")[0]) >= current_hour
        except (ValueError, IndexError):
            return True

    _show_notice = _show_1840_notice(now)

    for cat in categories:
        if _show_notice and cat == "(開通前)":
            lines.append(NOTICE_1840)
            lines.append("")

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

        tops = []
        if counts and unchecked:
            ranked = sorted(unchecked, key=lambda t: counts.get((cat, t), 0))
            tops = sorted(ranked[:3])
        top_str = ", ".join(tops) if tops else ""

        lines.append(f"■ {cat}")
        if not unchecked:
            lines.append("  全時間帯❌ → 翌日以降でお願いします")
            lines.append("  推奨: なし")
        elif not checked:
            lines.append("  全時間帯 対応可能")
            lines.append(f"  推奨:{top_str}" if top_str else "  推奨: なし")
        else:
            ng_str = ", ".join(f"{t}台❌" for t in checked)
            lines.append(f"  {ng_str}")
            lines.append(f"  推奨:{top_str}" if top_str else "  推奨: なし")
        lines.append("")

    return "\n".join(lines).rstrip()


def send_chatwork(bodies_by_room):
    """ルームIDごとに個別メッセージを送信。

    bodies_by_room: dict[str, str] — {room_id: message_body}
    """
    headers = {
        "X-ChatWorkToken": CHATWORK_API_TOKEN,
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    }
    for rid, body in bodies_by_room.items():
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

    body_detailed = build_summary(checks, date_str, time_slots, categories, counts)
    body_compact = build_summary_compact(checks, date_str, time_slots, categories, counts)

    bodies_by_room = {}
    for rid in ROOM_IDS_DETAILED:
        bodies_by_room[rid] = body_detailed
    for rid in ROOM_IDS_COMPACT:
        bodies_by_room[rid] = body_compact

    print("--- Detailed ---")
    print(body_detailed)
    print("--- Compact ---")
    print(body_compact)
    print("--- Sending ---")
    send_chatwork(bodies_by_room)
    print("Done")


if __name__ == "__main__":
    main()
