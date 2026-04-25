"""
育成KPIデータの永続化ストア（Google Sheets）

Google Sheetsの1つのセルにJSON形式で全データを保存・読み込みする。
"""

import json
import pandas as pd
import streamlit as st
import gspread
from google.oauth2.service_account import Credentials


SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# データを保存するセル
DATA_CELL = "A1"
SHEET_NAME = "ikusei_data"

# 全タブから常時除外する担当者（正規化名: 半角/全角空白除去）
EXCLUDED_NAMES_NORM = {"高橋真友香", "大滝紀香"}


def _norm(s: str) -> str:
    return (s or "").replace(" ", "").replace("　", "")


@st.cache_resource
def _get_gspread_client():
    creds_dict = dict(st.secrets["gcp_service_account"])
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    return gspread.authorize(creds)


def _get_worksheet():
    client = _get_gspread_client()
    sheet_id = st.secrets["ikusei"]["spreadsheet_id"]
    spreadsheet = client.open_by_key(sheet_id)
    try:
        return spreadsheet.worksheet(SHEET_NAME)
    except gspread.exceptions.WorksheetNotFound:
        return spreadsheet.add_worksheet(title=SHEET_NAME, rows=1, cols=1)


def _default_data():
    return {
        "order": [
            {"header": "1週間後FC", "items": ["堀田 輝斗", "角田 心華"]},
            {"header": "促進", "items": ["半田 さくら", "菊地 隆真", "栗田 優衣", "高橋 真友香"]},
        ],
        "tabs": {},
        "phase_data": {},
        "memo": {},
    }


def _serialize(store: dict) -> str:
    """ストアをJSON文字列に変換。DataFrameはdict形式に。"""
    out = {
        "order": store["order"],
        "tabs": store["tabs"],
        "memo": store["memo"],
        "phase_data": {},
    }
    for k, v in store["phase_data"].items():
        if isinstance(v, pd.DataFrame):
            out["phase_data"][k] = v.to_dict(orient="records")
        else:
            out["phase_data"][k] = v
    return json.dumps(out, ensure_ascii=False)


def _deserialize(raw: str) -> dict:
    """JSON文字列からストアを復元。"""
    data = json.loads(raw)
    store = {
        "order": data.get("order", _default_data()["order"]),
        "tabs": data.get("tabs", {}),
        "memo": data.get("memo", {}),
        "phase_data": {},
    }
    for k, records in data.get("phase_data", {}).items():
        if isinstance(records, list):
            store["phase_data"][k] = pd.DataFrame(records)
        else:
            store["phase_data"][k] = records
    return store


@st.cache_resource
def _shared_store():
    """アプリ起動時にGoogle Sheetsから読み込み、メモリに保持。"""
    try:
        ws = _get_worksheet()
        raw = ws.acell(DATA_CELL).value
        if raw:
            return _deserialize(raw)
    except Exception:
        pass
    return _default_data()


def get_store() -> dict:
    """共有ストアを取得。"""
    return _shared_store()


def is_excluded_member(name: str) -> bool:
    """全タブから常時除外する担当者か判定。"""
    return _norm(name) in EXCLUDED_NAMES_NORM


import time

_last_save_time = {"t": 0}


def reload_store_from_sheet():
    """Google Sheetsから最新を取り直し、共有メモリへ反映（他PCの編集を取り込む）。"""
    try:
        ws = _get_worksheet()
        raw = ws.acell(DATA_CELL).value
        latest = _deserialize(raw) if raw else _default_data()
        local = _shared_store()
        for k in ("order", "tabs", "memo", "phase_data"):
            local[k] = latest.get(k, local.get(k))
        return True, "最新データを取得しました"
    except Exception as e:
        return False, f"取得エラー: {e}"


def save_store():
    """
    共有ストアをGoogle Sheetsに保存。
    ★Sheetsから最新を再取得→キー単位でマージ→書き戻し（他PCの編集を温存）。
    ★サイレント失敗せずに必ず結果を返す（5秒未満連打は (False, '保存中...') を返す）。
    返り値: (success: bool, message: str)
    """
    now = time.time()
    if now - _last_save_time["t"] < 5:
        return False, "連続保存はできません（5秒間隔）"
    try:
        local = _shared_store()
        ws = _get_worksheet()
        # 1) Sheetsの最新を取得
        raw = ws.acell(DATA_CELL).value
        latest = _deserialize(raw) if raw else _default_data()
        # 2) ローカル編集を最新にマージ
        #    - phase_data / memo: キー単位で上書き（他PCが作った別キーは温存）
        for k, v in local.get("phase_data", {}).items():
            latest.setdefault("phase_data", {})[k] = v
        for k, v in local.get("memo", {}).items():
            latest.setdefault("memo", {})[k] = v
        #    - tabs / order: 構造が複雑なのでローカルを優先（マスタ側で編集）
        if "tabs" in local:
            latest["tabs"] = local["tabs"]
        if "order" in local:
            latest["order"] = local["order"]
        # 3) 書き戻し
        ws.update_acell(DATA_CELL, _serialize(latest))
        # 4) ローカルキャッシュも最新で更新（他PCの別キーが見えるように）
        for k in ("order", "tabs", "memo", "phase_data"):
            local[k] = latest.get(k, local.get(k))
        _last_save_time["t"] = now
        return True, "保存しました"
    except Exception as e:
        return False, f"保存エラー: {e}"
