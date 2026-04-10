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


import time

_last_save_time = {"t": 0}


def save_store():
    """共有ストアをGoogle Sheetsに保存（最低5秒間隔）。"""
    now = time.time()
    if now - _last_save_time["t"] < 5:
        return
    try:
        store = _shared_store()
        ws = _get_worksheet()
        ws.update_acell(DATA_CELL, _serialize(store))
        _last_save_time["t"] = now
    except Exception as e:
        st.toast(f"保存エラー: {e}", icon="⚠️")
