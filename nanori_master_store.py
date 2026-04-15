"""
商流別名乗りマスタ

取次商材情報 × 商流 → 名乗り文字列 のマスタを保持する。
トークスクリプト本文の `{{名乗}}` を顧客の取次商材情報＋商流で解決して差し込む。

保存先: ikusei用スプレッドシート内の `nanori_master_data` ワークシートA1セルにJSON。
全ユーザー共有（st.cache_resource）。
"""

import json
import time

import streamlit as st
import gspread

from talk_template_store import (
    _get_writable_client,
    _IKUSEI_SHEET_ID_FALLBACK,
)


WORKSHEET_NAME = "nanori_master_data"
STORAGE_CELL = "A1"

PLACEHOLDER = "{{名乗}}"
MISSING_MARKER = "⚠名乗り未登録⚠"
DEFAULT_TRIGGER = PLACEHOLDER


def _get_storage_worksheet():
    client = _get_writable_client()
    try:
        sheet_id = st.secrets["ikusei"]["spreadsheet_id"]
    except Exception:
        sheet_id = _IKUSEI_SHEET_ID_FALLBACK
    spreadsheet = client.open_by_key(sheet_id)
    try:
        return spreadsheet.worksheet(WORKSHEET_NAME)
    except gspread.exceptions.WorksheetNotFound:
        return spreadsheet.add_worksheet(title=WORKSHEET_NAME, rows=2, cols=2)


def _normalize_rows(rows) -> list[dict]:
    out = []
    if not isinstance(rows, list):
        return out
    for r in rows:
        if not isinstance(r, dict):
            continue
        out.append({
            "取次商材情報": str(r.get("取次商材情報", "")).strip(),
            "商流": str(r.get("商流", "")).strip(),
            "名乗り": str(r.get("名乗り", "")).strip(),
            "トリガー": str(r.get("トリガー", "")).strip(),
        })
    return out


@st.cache_resource
def _shared_master() -> dict:
    """全ユーザー共有の名乗りマスタ。{'rows': [...]} 形式。"""
    try:
        ws = _get_storage_worksheet()
        raw = ws.acell(STORAGE_CELL).value
        if raw:
            data = json.loads(raw)
            return {"rows": _normalize_rows(data.get("rows", []))}
    except Exception:
        pass
    return {"rows": []}


def get_rows() -> list[dict]:
    """マスタ行一覧（参照可変）。"""
    return _shared_master()["rows"]


def set_rows(rows: list[dict]):
    """メモリ上のマスタ行を差し替え（save_master で永続化）。"""
    _shared_master()["rows"] = _normalize_rows(rows)


_last_save = {"t": 0.0}


def save_master() -> tuple[bool, str]:
    """マスタをGoogle Sheetsへ保存（5秒スロットリング）。"""
    now = time.time()
    if now - _last_save["t"] < 5:
        return False, "連続保存はできません（5秒間隔）"
    try:
        data = {"rows": _normalize_rows(get_rows())}
        ws = _get_storage_worksheet()
        ws.update_acell(STORAGE_CELL, json.dumps(data, ensure_ascii=False))
        _last_save["t"] = now
        return True, "保存しました"
    except Exception as e:
        return False, f"保存エラー: {e}"


def clear_cache():
    _shared_master.clear()


def resolve_row(shozai: str, shoryu: str) -> dict | None:
    """取次商材情報＋商流で一致する行を返す。無ければNone。"""
    s1 = (shozai or "").strip()
    s2 = (shoryu or "").strip()
    if not s1 or not s2:
        return None
    for r in get_rows():
        if r["取次商材情報"] == s1 and r["商流"] == s2:
            return r
    return None


def apply_nanori_substitution(body: str, info: dict) -> str:
    """
    本文内の置換トリガー文字列（行ごとに設定。未設定時は `{{名乗}}`）を
    顧客の取次商材情報＋商流で解決した名乗り文言に置換する。

    一致行が無い場合は、デフォルトのプレースホルダー `{{名乗}}` を
    未登録マーカーに置換して誤送出を防ぐ。
    """
    if not body:
        return body
    shozai = (info.get("取次商材情報") or "").strip()
    shoryu = (info.get("商流（引用）") or "").strip()
    row = resolve_row(shozai, shoryu)

    if row is None:
        # 未登録: デフォルトトリガーが本文中にあればマーカーに置換
        if PLACEHOLDER in body:
            return body.replace(PLACEHOLDER, MISSING_MARKER)
        return body

    trigger = row.get("トリガー") or DEFAULT_TRIGGER
    nanori = row.get("名乗り") or ""
    if not trigger or trigger not in body:
        return body
    replacement = nanori if nanori else MISSING_MARKER
    return body.replace(trigger, replacement)
