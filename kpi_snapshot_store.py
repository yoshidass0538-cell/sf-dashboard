"""時間効率表の日次「着地」スナップショットを Google Sheets（外部）に保存するストア。

- 保存先: ikusei用スプレッドシート内の `kpi_snapshot_data` ワークシート（行形式）
- append-only（履歴系の方針）。同じ(date,person)が複数行になるので、読み出し側で
  updated_at が最新の行を「その日の着地」として採用する。
- 列: date, person, work, talk, proc, ring, blank, eff, rusu, calls, kyukei, updated_at
- 用途: 1日 / 週間 / 月間 の資料作成（時間効率レポート）。
"""

import streamlit as st
import gspread

from talk_template_store import (
    _get_writable_client,
    _IKUSEI_SHEET_ID_FALLBACK,
)

WORKSHEET_NAME = "kpi_snapshot_data"
HEADER = [
    "date", "person", "work", "talk", "proc", "ring", "blank",
    "eff", "rusu", "calls", "kyukei", "updated_at",
]
_NUM_FIELDS = {"work", "talk", "proc", "ring", "blank", "eff", "rusu", "calls", "kyukei"}


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
        ws = sh.add_worksheet(title=WORKSHEET_NAME, rows=2000, cols=len(HEADER))
        ws.update("A1", [HEADER])
        return ws


def append_rows(rows: list[dict]) -> tuple[bool, str]:
    """スナップショット行を追記（append-only）。rows: HEADERキーのdictのリスト。"""
    if not rows:
        return True, ""
    try:
        ws = _get_ws()
        data = [[r.get(h, "") for h in HEADER] for r in rows]
        ws.append_rows(data, value_input_option="USER_ENTERED")
        return True, "OK"
    except Exception as e:
        return False, f"スナップ保存エラー: {e}"


@st.cache_data(ttl=300, show_spinner=False)
def _get_all_rows(v: int = 1) -> list[dict]:
    try:
        ws = _get_ws()
        vals = ws.get_all_values()
        if len(vals) <= 1:
            return []
        out = []
        for r in vals[1:]:
            d = dict(zip(HEADER, r))
            for f in _NUM_FIELDS:
                try:
                    d[f] = float(d.get(f) or 0)
                except (ValueError, TypeError):
                    d[f] = 0.0
            out.append(d)
        return out
    except Exception:
        return []


def get_landings() -> list[dict]:
    """各 (date, person) の「着地」= updated_at が最新の1行のみを返す。"""
    latest: dict = {}
    for r in _get_all_rows():
        key = (r.get("date"), r.get("person"))
        cur = latest.get(key)
        if cur is None or str(r.get("updated_at", "")) >= str(cur.get("updated_at", "")):
            latest[key] = r
    return list(latest.values())


def clear_cache():
    _get_all_rows.clear()
