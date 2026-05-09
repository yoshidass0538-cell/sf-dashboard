"""
スキルツリーのデータを Google Sheets に永続化するストア。

- 保存先: ikusei用スプレッドシート内の `skill_tree_data` ワークシートのA1セル
- 全ユーザー共有（st.cache_resource）

データ構造:
{
  "start_label": "新人入社",
  "branches": [
    {"id": 1, "label": "受信", "color": "#22c55e",
     "stages": ["受信基礎", "受信応用", "受信マスター"]},
    ...
  ]
}
"""

import json

import streamlit as st
import gspread

from talk_template_store import (
    _get_writable_client,
    _IKUSEI_SHEET_ID_FALLBACK,
)

WORKSHEET_NAME = "skill_tree_data"
CELL = "A1"

def _linear_nodes(labels: list[str]) -> list[dict]:
    nodes = []
    parent = None
    for i, lab in enumerate(labels):
        nid = i + 1
        nodes.append({"id": nid, "label": lab, "parent": parent, "checked": False})
        parent = nid
    return nodes


_DEFAULT_DATA = {
    "start_labels": ["新人入社"],
    "branches": [
        {"id": 1, "label": "受信", "color": "#22c55e",
         "nodes": _linear_nodes(["受信基礎", "受信応用", "受信マスター"])},
        {"id": 2, "label": "発信", "color": "#eab308",
         "nodes": _linear_nodes(["発信基礎", "発信応用", "発信マスター"])},
        {"id": 3, "label": "事務", "color": "#ef4444",
         "nodes": _linear_nodes(["事務基礎", "事務応用", "事務マスター"])},
        {"id": 4, "label": "育成", "color": "#3b82f6",
         "nodes": _linear_nodes(["育成基礎", "育成応用", "育成マスター"])},
    ],
}


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
def _shared_cache() -> dict:
    """全ユーザー共有キャッシュ。

    取得失敗(認証/通信エラー)時は例外を伝播させる。
    シート未作成・空セルは default を使う。
    """
    ws = _get_ws()
    raw = ws.acell(CELL).value
    if not raw:
        return {"data": None}
    data = json.loads(raw)
    if isinstance(data, dict) and isinstance(data.get("branches"), list):
        return {"data": data}
    return {"data": None}


def get_skill_tree() -> dict:
    """スキルツリーデータを返す。未保存ならデフォルト。"""
    cached = _shared_cache().get("data")
    if cached is None:
        return json.loads(json.dumps(_DEFAULT_DATA))  # deep copy
    data = json.loads(json.dumps(cached))
    # 後方互換: 旧フォーマット (start_label: str) → 新 (start_labels: list[str])
    if "start_labels" not in data:
        old = data.pop("start_label", None) or "新人入社"
        data["start_labels"] = [old]
    if not isinstance(data.get("start_labels"), list):
        data["start_labels"] = [str(data.get("start_labels") or "新人入社")]
    # 後方互換: 旧 stages(list[str]) → nodes(list[{id,label,parent}]) 直線ツリー
    for b in data.get("branches", []):
        if "nodes" not in b:
            stages = b.pop("stages", []) or []
            b["nodes"] = _linear_nodes([str(s) for s in stages if str(s).strip()])
        # checked / memo フィールドのデフォルト
        for n in b.get("nodes", []):
            if "checked" not in n:
                n["checked"] = False
            if "memo" not in n:
                n["memo"] = ""
    return data


def save_skill_tree(data: dict) -> tuple[bool, str]:
    """スキルツリーをSheetsに保存。失敗時は例外伝播。

    cache はクリアせず in-place で更新する（クリアすると次の get で
    Sheets 再読込が走り read quota を圧迫するため）。
    """
    if not isinstance(data, dict) or not isinstance(data.get("branches"), list):
        raise ValueError("invalid skill_tree data")
    ws = _get_ws()
    ws.update(CELL, [[json.dumps(data, ensure_ascii=False)]])
    # キャッシュを直接更新
    cache = _shared_cache()
    cache["data"] = json.loads(json.dumps(data))
    return True, "スキルツリーを保存しました。"


def clear_skill_tree_cache():
    _shared_cache.clear()


def next_branch_id(branches: list[dict]) -> int:
    if not branches:
        return 1
    return max(int(b.get("id", 0) or 0) for b in branches) + 1
