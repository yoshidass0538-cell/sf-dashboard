"""
シフト変更不可日（各人の調整不可日）を Google Sheets に永続化するストア。

- 保存先: ikusei用スプレッドシート内の `shift_forbidden_data` ワークシートのA1セル
- 全ユーザー共有（st.cache_resource）
- スキーマ: {"YYYY-MM": {"姓キー": [day, day, ...]}}
- 読込失敗時は例外を伝播（silently 空を返さない＝誤上書き防止）
"""

import json

import streamlit as st
import gspread

from talk_template_store import (
    _get_writable_client,
    _IKUSEI_SHEET_ID_FALLBACK,
)

WORKSHEET_NAME = "shift_forbidden_data"
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
def _shared_forbidden_cache() -> dict:
    """全ユーザー共有の変更不可日キャッシュ。
    失敗時は例外を伝播してキャッシュさせない（次回呼出で再試行）。
    """
    ws = _get_ws()
    raw = ws.acell(CELL).value
    if raw:
        return {"data": json.loads(raw)}
    return {"data": {}}


def _month_key(year: int, month: int) -> str:
    return f"{year:04d}-{month:02d}"


def get_forbidden(year: int, month: int) -> dict[str, set[int]]:
    """指定月の変更不可日を {姓キー: {日, 日, ...}} で返す。"""
    cache = _shared_forbidden_cache()
    raw = cache.get("data", {}).get(_month_key(year, month), {})
    return {k: set(v) for k, v in raw.items() if v}


def save_forbidden(year: int, month: int, data: dict[str, set[int]]) -> None:
    """指定月の変更不可日を保存。空集合のキーは自動で削除。失敗時は例外を伝播。"""
    cache = _shared_forbidden_cache()
    store = cache.get("data", {})
    mk = _month_key(year, month)
    normalized = {k: sorted(int(d) for d in v) for k, v in data.items() if v}
    if normalized:
        store[mk] = normalized
    else:
        store.pop(mk, None)
    ws = _get_ws()
    ws.update_acell(CELL, json.dumps(store, ensure_ascii=False))
    cache["data"] = store


def clear_forbidden_cache():
    """共有キャッシュをクリア（次回読み込みで再取得）。"""
    _shared_forbidden_cache.clear()
