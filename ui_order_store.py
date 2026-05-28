"""
サイドバーのボード並び順を Google Sheets に永続化するストア。

- 保存先: ikusei用スプレッドシート内の `ui_order_data` ワークシートのA1セル
- 全ユーザー共有（st.cache_resource）
- マスタで並び順を変更するたびに保存される
- ロード時、現在の METRICS と整合を取る（追加削除されたカテゴリ/アイテムを補正）
"""

import json
import time

import streamlit as st
import gspread

from talk_template_store import (
    _get_writable_client,
    _IKUSEI_SHEET_ID_FALLBACK,
)


UI_ORDER_WORKSHEET = "ui_order_data"
UI_ORDER_CELL = "A1"

# デフォルトのカテゴリ表示順
DEFAULT_CATEGORY_ORDER = ["TOTAL", "1週間後FC", "促進", "ツール", "タイミー", "責任者用", "SECRET", "資料"]

# 保存済み order を読む際に、特定アイテムを強制的に指定カテゴリへ移すマイグレーション
# (key=item ラベル, value=移動先カテゴリ)
FORCED_CATEGORY = {
    "開通前対応": "資料",
    "工事取得FC資料": "資料",
    "ソネット光AU・UQ 1次停滞理由": "資料",
    "不備停滞 切り捨て判定資料(エリア別)": "資料",
    "不備停滞 切り捨て判定資料(リスト別)": "資料",
}


def _get_ws():
    client = _get_writable_client()
    try:
        sheet_id = st.secrets["ikusei"]["spreadsheet_id"]
    except Exception:
        sheet_id = _IKUSEI_SHEET_ID_FALLBACK
    sh = client.open_by_key(sheet_id)
    try:
        return sh.worksheet(UI_ORDER_WORKSHEET)
    except gspread.exceptions.WorksheetNotFound:
        return sh.add_worksheet(title=UI_ORDER_WORKSHEET, rows=2, cols=2)


@st.cache_resource
def _shared_order_cache() -> dict:
    """全ユーザー共有のboard_orderキャッシュ。dictで包んで参照を共有。"""
    try:
        ws = _get_ws()
        raw = ws.acell(UI_ORDER_CELL).value
        if raw:
            return {"order": json.loads(raw)}
    except Exception:
        pass
    return {"order": None}  # 未保存


def get_saved_order() -> list | None:
    """保存済みのboard_orderを返す。未保存なら None。"""
    return _shared_order_cache().get("order")


def build_initial_board_order(metrics_list) -> list:
    """
    現在のMETRICSから board_order を構築。
    保存済み順があればそれを尊重し、不足分はデフォルトで補完する。
    metrics_list: METRICS のリスト (Metric オブジェクト)
    ※ ツール カテゴリの items は メンバー名 一覧として扱う（並び替え対象）
    """
    from tool_members_store import get_member_names  # 動的メンバー名

    # 現在のカテゴリ→ラベル一覧
    current_cats: dict[str, list[str]] = {}
    for m in metrics_list:
        if m.category == "ツール" and m.key.startswith("talk_script_"):
            continue  # ツール配下のメンバー別ボードは別管理
        current_cats.setdefault(m.category, []).append(m.label)
    # ツールはアクティブなメンバー名一覧で管理
    current_cats["ツール"] = get_member_names()

    saved = get_saved_order()

    if not saved:
        # 初回 or 失敗時 → デフォルト順で構築
        order = []
        for cat in DEFAULT_CATEGORY_ORDER:
            if cat in current_cats:
                order.append({"header": cat, "items": current_cats[cat]})
        for cat, items in current_cats.items():
            if cat not in DEFAULT_CATEGORY_ORDER:
                order.append({"header": cat, "items": items})
        return order

    # 保存済み順をベースに、現在のMETRICSと整合を取る
    # ※ ボードはユーザーが任意のカテゴリに移動できるため、m.category（デフォルト所属）に
    #   縛らずグローバルなアイテムプールで判定する（旧実装は移動後リロードで元カテゴリに
    #   戻ってしまうバグがあった）
    all_items: set[str] = set()
    for items in current_cats.values():
        all_items.update(items)

    order = []
    used_cats: set[str] = set()
    placed_items: set[str] = set()
    for entry in saved:
        cat = entry.get("header")
        if cat is None or cat not in current_cats:
            continue
        saved_items = entry.get("items", []) or []
        # 全カテゴリ集合に存在し、まだ他カテゴリで配置していないアイテムを採用
        # ただし FORCED_CATEGORY に登録されたアイテムは、所属が異なる場合スキップ
        merged = [
            i for i in saved_items
            if i in all_items and i not in placed_items
            and (FORCED_CATEGORY.get(i) is None or FORCED_CATEGORY[i] == cat)
        ]
        placed_items.update(merged)
        order.append({"header": cat, "items": merged})
        used_cats.add(cat)

    # まだ配置されていないアイテムをデフォルト所属カテゴリの末尾に補完
    for cat, items in current_cats.items():
        leftover = [i for i in items if i not in placed_items]
        if not leftover:
            continue
        if cat in used_cats:
            for entry in order:
                if entry["header"] == cat:
                    entry["items"].extend(leftover)
                    break
        else:
            order.append({"header": cat, "items": leftover})
            used_cats.add(cat)
        placed_items.update(leftover)

    return order


_last_save = {"t": 0.0}


def save_order(board_order: list) -> tuple[bool, str]:
    """board_orderをGoogle Sheetsに保存（5秒スロットリング）。"""
    now = time.time()
    if now - _last_save["t"] < 5:
        return False, "保存スキップ（5秒以内の連続保存）"
    try:
        ws = _get_ws()
        ws.update_acell(UI_ORDER_CELL, json.dumps(board_order, ensure_ascii=False))
        # キャッシュも更新
        cache = _shared_order_cache()
        cache["order"] = board_order
        _last_save["t"] = now
        return True, "並び順を保存しました"
    except Exception as e:
        return False, f"並び順保存エラー: {e}"


def clear_order_cache():
    """共有キャッシュをクリア（次回読み込みで再取得）。"""
    _shared_order_cache.clear()
