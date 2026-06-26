"""時間効率表の休憩ボタン記録を Google Sheets（外部）に永続化するストア。

- 保存先: ikusei用スプレッドシート内の `kyukei_data` ワークシートのA1セル（JSON）
- 全ユーザー共有（st.cache_resource）
- データ構造: { "YYYY-MM-DD": { "正規化氏名": [ {"s": 開始epoch, "e": 終了epoch|null}, ... ] } }
- 休憩は「記録のみ」（業務経過時間の固定スケジュールには影響しない＝案B）
- 履歴は append-only 方針: 過去日のデータは消さない（月次資料の元データになるため）
"""

import json

import streamlit as st
import gspread

from talk_template_store import (
    _get_writable_client,
    _IKUSEI_SHEET_ID_FALLBACK,
)

WORKSHEET_NAME = "kyukei_data"
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
def _shared_kyukei_cache() -> dict:
    """全ユーザー共有の休憩記録キャッシュ。"""
    try:
        ws = _get_ws()
        raw = ws.acell(CELL).value
        if raw:
            return {"data": json.loads(raw)}
    except Exception:
        pass
    return {"data": {}}


def get_all() -> dict:
    """全期間の休憩記録を返す。{date: {name: [{"s","e"}]}}。"""
    return _shared_kyukei_cache().get("data", {})


def get_day(date_str: str) -> dict:
    """指定日の休憩記録を返す。{name: [{"s","e"}]}。"""
    return dict(get_all().get(date_str, {}))


def _save(data: dict) -> tuple[bool, str]:
    try:
        ws = _get_ws()
        ws.update_acell(CELL, json.dumps(data, ensure_ascii=False))
        _shared_kyukei_cache()["data"] = data
        return True, "OK"
    except Exception as e:
        return False, f"保存エラー: {e}"


def _reload() -> dict:
    """Sheetsから最新を読み直す（書き込み前のレース対策）。"""
    _shared_kyukei_cache.clear()
    return get_all()


def has_open(date_str: str, name: str) -> bool:
    """指定日・氏名に「終了していない休憩」があるか。"""
    for b in get_day(date_str).get(name, []):
        if b.get("e") is None:
            return True
    return False


def start_break(date_str: str, name: str, ts: float) -> tuple[bool, str]:
    """休憩開始を記録（既に開始中なら何もしない）。ts=開始epoch。"""
    data = _reload()
    day = data.setdefault(date_str, {})
    lst = day.setdefault(name, [])
    if any(b.get("e") is None for b in lst):
        return True, "既に休憩中"
    lst.append({"s": ts, "e": None})
    return _save(data)


def end_break(date_str: str, name: str, ts: float) -> tuple[bool, str]:
    """進行中の休憩を終了（ts=終了epoch）。"""
    data = _reload()
    lst = data.get(date_str, {}).get(name, [])
    for b in reversed(lst):
        if b.get("e") is None:
            b["e"] = ts
            return _save(data)
    return True, "進行中の休憩なし"


def clear_cache():
    _shared_kyukei_cache.clear()
