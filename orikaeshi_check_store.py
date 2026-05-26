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

# 旧ラベル(折り返し希望(○○)) → 新ラベル((○○)) 移行マップ
_LABEL_MIGRATION = {
    "折り返し希望(開通前)": "(開通前)",
    "折り返し希望(1週間後)": "(1週間後)",
    "折り返し希望(工事取得)": "(工事取得)",
    "折り返し希望(新設FC)": "(新設FC)",
}


def _migrate_keys(checks: dict) -> tuple[dict, bool]:
    out: dict = {}
    changed = False
    for k, v in checks.items():
        parts = k.split("|")
        if len(parts) == 3 and parts[1] in _LABEL_MIGRATION:
            parts[1] = _LABEL_MIGRATION[parts[1]]
            changed = True
        out["|".join(parts)] = v
    return out, changed


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
            loaded = json.loads(raw)
            migrated, changed = _migrate_keys(loaded)
            if changed:
                try:
                    ws.update_acell(CELL, json.dumps(migrated, ensure_ascii=False))
                except Exception:
                    pass
            return {"checks": migrated}
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


# --- 操作ログ（誰が・いつ・どのセルをチェック/解除したか）---
# 追記専用。既存行は絶対に消さない（履歴系の方針）。
LOG_WORKSHEET_NAME = "orikaeshi_check_log"
_LOG_HEADER = ["日時", "操作", "ユーザー", "対象"]


def _get_log_ws():
    client = _get_writable_client()
    try:
        sheet_id = st.secrets["ikusei"]["spreadsheet_id"]
    except Exception:
        sheet_id = _IKUSEI_SHEET_ID_FALLBACK
    sh = client.open_by_key(sheet_id)
    try:
        return sh.worksheet(LOG_WORKSHEET_NAME)
    except gspread.exceptions.WorksheetNotFound:
        ws = sh.add_worksheet(title=LOG_WORKSHEET_NAME, rows=1000, cols=4)
        ws.update("A1:D1", [_LOG_HEADER])
        return ws


def append_log(entries: list[dict]) -> tuple[bool, str]:
    """操作ログを追記。entries: [{"at","action","by","key"}]。既存行は保持。"""
    if not entries:
        return True, ""
    try:
        ws = _get_log_ws()
        rows = [
            [e.get("at", ""), e.get("action", ""), e.get("by", ""), e.get("key", "")]
            for e in entries
        ]
        ws.append_rows(rows, value_input_option="USER_ENTERED")
        return True, "OK"
    except Exception as e:
        return False, f"ログ保存エラー: {e}"


def get_log(limit: int = 500) -> list[dict]:
    """操作ログを新しい順で返す（表示専用）。読込失敗時は空list。"""
    try:
        ws = _get_log_ws()
        vals = ws.get_all_values()
        if len(vals) <= 1:
            return []
        out = []
        for r in vals[1:]:
            out.append({
                "at": r[0] if len(r) > 0 else "",
                "action": r[1] if len(r) > 1 else "",
                "by": r[2] if len(r) > 2 else "",
                "key": r[3] if len(r) > 3 else "",
            })
        return out[-limit:][::-1]
    except Exception:
        return []
