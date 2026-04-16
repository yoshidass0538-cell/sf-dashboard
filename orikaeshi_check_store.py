"""
折返し件数ボードのチェックボックス状態を Google Sheets に永続化するストア。

- 保存先: ikusei用スプレッドシート内の `orikaeshi_check_data` ワークシートのA1セル
- 全ユーザー共有（st.cache_resource）
- キー形式: "日付|種別|時間帯" → true
"""

import json

import streamlit as st
import gspread

from talk_template_store import (
    _get_writable_client,
    _IKUSEI_SHEET_ID_FALLBACK,
)

WORKSHEET_NAME = "orikaeshi_check_data"
CELL = "A1"


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
def _shared_check_cache() -> dict:
    """全ユーザー共有のチェック状態キャッシュ。"""
    try:
        ws = _get_ws()
        raw = ws.acell(CELL).value
        if raw:
            return {"checks": json.loads(raw)}
    except Exception:
        pass
    return {"checks": {}}


def get_checks() -> dict:
    """保存済みチェック状態を返す。キー: "日付|種別|時間帯" → True。"""
    return _shared_check_cache().get("checks", {})


def save_checks(checks: dict) -> tuple[bool, str]:
    """チェック状態をGoogle Sheetsに保存。"""
    try:
        ws = _get_ws()
        ws.update_acell(CELL, json.dumps(checks, ensure_ascii=False))
        cache = _shared_check_cache()
        cache["checks"] = checks
        return True, "保存完了"
    except Exception as e:
        return False, f"保存エラー: {e}"


def clear_check_cache():
    """共有キャッシュをクリア（次回読み込みで再取得）。"""
    _shared_check_cache.clear()
