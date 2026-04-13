"""
Chatwork API 連携クライアント

折返し件数ボードのチェック状態に応じて通知を送信する。
- 即時通知: チェックを入れたタイミングで送信
- 定期サマリー: 1時間に1回、チェック状況をまとめて送信
"""

import os
import time
import logging
from datetime import datetime, timezone, timedelta

import requests
import streamlit as st

logger = logging.getLogger(__name__)

# 送信先ルームID（本番用はリリース時に切り替え）
# _PRODUCTION_ROOM_IDS = ["398296862", "398125674", "260721357", "380105765"]
ROOM_IDS = [
    "425326390",  # テスト用ルーム
]

API_URL = "https://api.chatwork.com/v2"
JST = timezone(timedelta(hours=9))


def _get_token() -> str:
    """APIトークンを取得。st.secrets優先、.envフォールバック。"""
    try:
        return st.secrets["chatwork"]["api_token"]
    except Exception:
        pass
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    token = os.environ.get("CHATWORK_API_TOKEN", "")
    if not token:
        logger.warning("CHATWORK_API_TOKEN が設定されていません")
    return token


def send_message(body: str, room_ids: list[str] | None = None) -> list[dict]:
    """指定ルーム（デフォルト全4室）にメッセージを送信。"""
    token = _get_token()
    if not token:
        return []
    targets = room_ids or ROOM_IDS
    results = []
    headers = {
        "X-ChatWorkToken": token,
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    }
    for rid in targets:
        try:
            resp = requests.post(
                f"{API_URL}/rooms/{rid}/messages",
                headers=headers,
                data={"body": body, "self_unread": 1},
                timeout=10,
            )
            results.append({"room_id": rid, "status": resp.status_code, "body": resp.text})
        except Exception as e:
            results.append({"room_id": rid, "status": 0, "body": str(e)})
    return results


def build_immediate_message(date_str: str, time_slot: str, category: str) -> str:
    """チェック時の即時通知メッセージを組み立てる。"""
    return (
        f"[toall]\n"
        f"[info][title]折返し件数チェック[/title]"
        f"{time_slot}台の{category}は他時間もしくは翌日以降での時設をお願いします。[/info]"
    )


def send_immediate(date_str: str, time_slot: str, category: str) -> list[dict]:
    """チェック時の即時通知を全ルームに送信。"""
    body = build_immediate_message(date_str, time_slot, category)
    return send_message(body)


def send_all_checked(date_str: str, category: str) -> list[dict]:
    """ALL列チェック時（全時間帯埋まり）の通知を1通で送信。"""
    body = (
        f"[toall]\n"
        f"[info][title]折返し件数チェック[/title]"
        f"{category}は翌日以降に時設お願いします。[/info]"
    )
    return send_message(body)


def build_summary_message(checks: dict, date_str: str, all_time_slots: list[str], all_categories: list[str]) -> str:
    """
    定期サマリーメッセージを組み立てる。
    種別ごとにチェック済みの時間帯を表示。
    全時間チェック済みの場合は翌日以降を案内。
    """
    now = datetime.now(JST)
    lines = [f"[toall]\n[info][title]折返し件数 状況アナウンス ({now.strftime('%H:%M')}時点)[/title]"]
    lines.append(f"対象日: {date_str}\n")

    for cat in all_categories:
        checked = []
        unchecked = []
        for ts in all_time_slots:
            key = f"{date_str}|{cat}|{ts}"
            if checks.get(key, False):
                checked.append(ts)
            else:
                unchecked.append(ts)

        if not checked:
            lines.append(f"■ {cat}")
            lines.append("  チェックなし（全時間帯 空き）\n")
        elif not unchecked:
            lines.append(f"■ {cat}")
            lines.append("  全時間帯チェック済み → 翌日以降でお願いします\n")
        else:
            lines.append(f"■ {cat}")
            lines.append(f"  チェック済み: {', '.join(checked)}")
            lines.append(f"  空き: {', '.join(unchecked)}\n")

    lines.append("[/info]")
    return "\n".join(lines)


def send_summary(checks: dict, date_str: str, all_time_slots: list[str], all_categories: list[str]) -> list[dict]:
    """定期サマリーを全ルームに送信。"""
    body = build_summary_message(checks, date_str, all_time_slots, all_categories)
    return send_message(body)


# --- 定期送信管理（1時間に1回） ---

@st.cache_resource
def _summary_state() -> dict:
    """最終送信時刻を全ユーザー共有で管理。"""
    return {"last_sent_hour": -1, "last_sent_date": ""}


def should_send_summary() -> bool:
    """現在時刻に基づいて定期送信すべきか判定。"""
    now = datetime.now(JST)
    state = _summary_state()
    current_hour = now.hour
    current_date = now.strftime("%Y/%m/%d")
    # 同日・同時間帯に既に送信済みならスキップ
    if state["last_sent_date"] == current_date and state["last_sent_hour"] == current_hour:
        return False
    # 営業時間内 (9:00-20:00) のみ送信
    if current_hour < 9 or current_hour > 20:
        return False
    return True


def mark_summary_sent():
    """送信済みマークを更新。"""
    now = datetime.now(JST)
    state = _summary_state()
    state["last_sent_hour"] = now.hour
    state["last_sent_date"] = now.strftime("%Y/%m/%d")
