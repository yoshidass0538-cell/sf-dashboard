"""
周知ボード用データストア。

保存先: ikusei用スプレッドシート内の shuchi_data ワークシート A1セルに JSON。
マルチユーザー・リアルタイム編集を想定し、キャッシュは使わず毎回 Sheets から読む。
書き込みは即座に反映（スロットリングなし）。

データ構造:
{
  "rows": [
    {
      "id": "uuid",
      "shuchi_date": "2026-04-22",
      "content": "...",
      "confirmations": {
        "吉田": {"checked": true, "confirmed_at": "2026-04-22"},
        ...
      }
    }
  ]
}
"""

import json
import uuid
from datetime import date as _date

import streamlit as st
import gspread

from talk_template_store import (
    _get_writable_client,
    _IKUSEI_SHEET_ID_FALLBACK,
)


WORKSHEET_NAME = "shuchi_data"
STORAGE_CELL = "A1"


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


def _normalize_rows(rows) -> list[dict]:
    out = []
    if not isinstance(rows, list):
        return out
    for r in rows:
        if not isinstance(r, dict):
            continue
        confirmations = r.get("confirmations") or {}
        if not isinstance(confirmations, dict):
            confirmations = {}
        clean_conf = {}
        for name, c in confirmations.items():
            if isinstance(c, dict):
                clean_conf[str(name)] = {
                    "checked": bool(c.get("checked", False)),
                    "confirmed_at": str(c.get("confirmed_at", "")).strip(),
                }
        out.append({
            "id": str(r.get("id") or uuid.uuid4().hex),
            "shuchi_date": str(r.get("shuchi_date", "")).strip(),
            "content": str(r.get("content", "")),
            "confirmations": clean_conf,
        })
    return out


def load_rows() -> list[dict]:
    """常にGoogle Sheetsから読み直す（リアルタイム整合性優先）。"""
    try:
        ws = _get_ws()
        raw = ws.acell(STORAGE_CELL).value
        if raw:
            data = json.loads(raw)
            return _normalize_rows(data.get("rows", []))
    except Exception:
        pass
    return []


def _save_rows(rows: list[dict]) -> tuple[bool, str]:
    try:
        data = {"rows": _normalize_rows(rows)}
        ws = _get_ws()
        ws.update_acell(STORAGE_CELL, json.dumps(data, ensure_ascii=False))
        return True, "保存しました"
    except Exception as e:
        return False, f"保存エラー: {e}"


def add_row(shuchi_date: str = "", content: str = "") -> tuple[bool, str]:
    if not shuchi_date:
        shuchi_date = _date.today().isoformat()
    rows = load_rows()
    rows.append({
        "id": uuid.uuid4().hex,
        "shuchi_date": shuchi_date,
        "content": content,
        "confirmations": {},
    })
    return _save_rows(rows)


def delete_row(row_id: str) -> tuple[bool, str]:
    rows = load_rows()
    rows = [r for r in rows if r["id"] != row_id]
    return _save_rows(rows)


def update_row(row_id: str, shuchi_date: str | None = None, content: str | None = None) -> tuple[bool, str]:
    rows = load_rows()
    for r in rows:
        if r["id"] == row_id:
            if shuchi_date is not None:
                r["shuchi_date"] = shuchi_date
            if content is not None:
                r["content"] = content
            break
    return _save_rows(rows)


def toggle_confirmation(row_id: str, member_name: str, checked: bool) -> tuple[bool, str]:
    rows = load_rows()
    for r in rows:
        if r["id"] == row_id:
            if checked:
                r["confirmations"][member_name] = {
                    "checked": True,
                    "confirmed_at": _date.today().isoformat(),
                }
            else:
                r["confirmations"][member_name] = {
                    "checked": False,
                    "confirmed_at": "",
                }
            break
    return _save_rows(rows)
