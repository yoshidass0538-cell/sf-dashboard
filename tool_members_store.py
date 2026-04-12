"""
ツールカテゴリのメンバー＆トーク割当を Google Sheets に永続化するストア。

- 保存先: ikusei用スプレッドシート内の `tool_members_data` ワークシートのA1セル
- 全ユーザー共有（st.cache_resource）
- 5秒スロットリング
- soft-delete: active=false で非表示にしてインデックス安定性を保つ
"""

import json
import time

import streamlit as st
import gspread

from talk_template_store import (
    _get_writable_client,
    _IKUSEI_SHEET_ID_FALLBACK,
)

WORKSHEET_NAME = "tool_members_data"
CELL = "A1"

# 初期メンバー（初回デプロイ時のシード）
_DEFAULT_MEMBERS = [
    {"name": "室谷 慧", "assignments": ["fc1week"], "active": True},
    {"name": "原田 綾子", "assignments": ["fc1week"], "active": True},
    {"name": "金澤 駿平", "assignments": ["fc1week"], "active": True},
    {"name": "吉本 将吾", "assignments": ["fc1week"], "active": True},
    {"name": "大滝 紀香", "assignments": ["fc1week"], "active": True},
    {"name": "堀田 輝斗", "assignments": ["fc1week"], "active": True},
    {"name": "角田 心華", "assignments": ["fc1week"], "active": True},
    {"name": "佐々木 彩乃", "assignments": ["fc1week"], "active": True},
    {"name": "葛西 翼", "assignments": ["fc1week"], "active": True},
    {"name": "雨貝 一生", "assignments": ["fc1week"], "active": True},
    {"name": "半田 さくら", "assignments": ["fc1week"], "active": True},
    {"name": "菊地 隆真", "assignments": ["fc1week"], "active": True},
    {"name": "栗田 優衣", "assignments": ["fc1week"], "active": True},
    {"name": "高橋 真友香", "assignments": ["fc1week"], "active": True},
]


def _get_ws():
    client = _get_writable_client()
    try:
        sheet_id = st.secrets["ikusei"]["spreadsheet_id"]
    except Exception:
        sheet_id = _IKUSEI_SHEET_ID_FALLBACK
    sh = client.open_by_key(sheet_id)
    try:
        return sh.worksheet(WORKSHEET_NAME)
    except gspread.exceptions.WorksheetNotFound:
        return sh.add_worksheet(title=WORKSHEET_NAME, rows=2, cols=2)


@st.cache_resource
def _shared_members_cache() -> dict:
    """全ユーザー共有のメンバーキャッシュ。"""
    try:
        ws = _get_ws()
        raw = ws.acell(CELL).value
        if raw:
            data = json.loads(raw)
            if isinstance(data, dict) and "members" in data:
                return {"members": data["members"]}
    except Exception:
        pass
    return {"members": None}  # None = 未保存（デフォルト使用）


def get_members() -> list[dict]:
    """全メンバー（非アクティブ含む）を返す。未保存ならデフォルト。"""
    cached = _shared_members_cache().get("members")
    if cached is None:
        return [m.copy() for m in _DEFAULT_MEMBERS]
    return cached


def get_active_members() -> list[dict]:
    """アクティブなメンバーのみ返す。"""
    return [m for m in get_members() if m.get("active", True)]


def get_member_names() -> list[str]:
    """アクティブなメンバー名のリスト（サイドバー表示用）。"""
    return [m["name"] for m in get_active_members()]


def get_all_member_names() -> list[str]:
    """全メンバー名のリスト（インデックス対応、非アクティブ含む）。"""
    return [m["name"] for m in get_members()]


def get_member_assignments(name: str) -> list[str]:
    """指定メンバーのトーク割当サフィックスリストを返す。"""
    for m in get_members():
        if m["name"] == name:
            return m.get("assignments", [])
    return []


_last_save = {"t": 0.0}


def save_members(members: list[dict]) -> tuple[bool, str]:
    """メンバーリストをGoogle Sheetsに保存（5秒スロットリング）。"""
    now = time.time()
    if now - _last_save["t"] < 5:
        return False, "保存スキップ（5秒以内の連続保存）"
    try:
        ws = _get_ws()
        ws.update_acell(CELL, json.dumps({"members": members}, ensure_ascii=False))
        cache = _shared_members_cache()
        cache["members"] = members
        _last_save["t"] = now
        return True, "メンバー設定を保存しました"
    except Exception as e:
        return False, f"保存エラー: {e}"


def clear_members_cache():
    """共有キャッシュをクリア。"""
    _shared_members_cache.clear()
