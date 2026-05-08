"""
タイミー就業予定表のマスタJSONストア。

保存先: ikusei用スプレッドシート内の `timee_data` ワークシート
- A1セル: ワーカーマスタ JSON (dictキー=6桁ID)
- A2セル: 直近スナップショット JSON (list of {id, 就業日, 出勤回数, 開始時間, 終了時間, 求人タイトル, グループ})
- A3セル: メタ情報 JSON (最終翌月取得日など)

GitHub Actions と Streamlit の両方から呼ばれるため、認証は
- Streamlit 側: st.secrets["gcp_service_account"]
- GH Actions 側: 環境変数 GCP_SERVICE_ACCOUNT_JSON (base64 or 生JSON)
の両方をサポート。

ワーカー識別キーは「氏名+カナ」(同姓同名でカナ違いは別人扱い)。
6桁ID（数字のみ）は新規ワーカー追加時に衝突回避で発行。

データ構造:
  workers: {
    "123456": {
      "氏名": "...", "カナ": "...", "性別": "男", "年齢": 47,
      "初回登録日": "2026-05-07",
      "メモ": "", "タグ": [], "直雇勧誘済": false, "チェック日": null,
      "キャンセル履歴": [{"検知日": "2026-05-08", "元就業日": "2026-05-15"}],
    }
  }
  snapshot: [
    {"id": "123456", "就業日": "2026-05-15", "出勤回数": 9, "開始時間": "10:00",
     "終了時間": "19:00", "求人タイトル": "...", "グループ": "通常求人"}
  ]
  meta: {"last_next_month_fetch": "2026-05-07"}
"""

from __future__ import annotations

import base64
import json
import os
import random
from datetime import date, datetime
from typing import Optional

import gspread
from google.oauth2.service_account import Credentials


WORKSHEET_NAME = "timee_data"
WORKERS_CELL = "A1"
SNAPSHOT_CELL = "A2"
META_CELL = "A3"
POSTINGS_CELL = "A4"  # 求人一覧スナップショット (list of {日付, 開始時間, 終了時間, マッチ数, 募集人数, 状態})

# 過去アーカイブ（同期では触らない・容量制限を避けるため別ワークシート＋行ベース保存）
ARCHIVE_WORKSHEET = "timee_archive"
ARCHIVE_HEADERS = ["id", "就業日", "出勤回数", "開始時間", "終了時間",
                   "求人タイトル", "グループ", "バッジ"]

GS_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

_IKUSEI_SHEET_ID_FALLBACK = "1aXKoCL_bppzw60ddYmtaGjqHHYCRRLyVU6z3ZxB7JbY"
_LOCAL_KEY_FILE = "yoshida0538-f46ce1eea153.json"


def _get_client():
    """gspreadクライアントを取得。Streamlit secrets / 環境変数 / ローカルJSON の順に試行。"""
    # 1. Streamlit secrets
    try:
        import streamlit as st
        try:
            creds_dict = dict(st.secrets["gcp_service_account"])
            creds = Credentials.from_service_account_info(creds_dict, scopes=GS_SCOPES)
            return gspread.authorize(creds)
        except Exception:
            pass
    except ImportError:
        pass

    # 2. 環境変数 (GitHub Actions)
    sa_json = os.environ.get("GCP_SERVICE_ACCOUNT_JSON", "")
    if sa_json:
        try:
            decoded = base64.b64decode(sa_json)
            creds_dict = json.loads(decoded)
        except Exception:
            creds_dict = json.loads(sa_json)
        creds = Credentials.from_service_account_info(creds_dict, scopes=GS_SCOPES)
        return gspread.authorize(creds)

    # 3. ローカル JSON
    if os.path.exists(_LOCAL_KEY_FILE):
        creds = Credentials.from_service_account_file(_LOCAL_KEY_FILE, scopes=GS_SCOPES)
        return gspread.authorize(creds)

    raise RuntimeError(
        "Google Sheets 認証情報が見つかりません。"
        "st.secrets['gcp_service_account'] / 環境変数 GCP_SERVICE_ACCOUNT_JSON / "
        f"{_LOCAL_KEY_FILE} のいずれかを用意してください。"
    )


def _get_sheet_id() -> str:
    try:
        import streamlit as st
        return st.secrets["ikusei"]["spreadsheet_id"]
    except Exception:
        pass
    return os.environ.get("IKUSEI_SHEET_ID", _IKUSEI_SHEET_ID_FALLBACK)


def _get_ws():
    client = _get_client()
    sh = client.open_by_key(_get_sheet_id())
    try:
        return sh.worksheet(WORKSHEET_NAME)
    except gspread.exceptions.WorksheetNotFound:
        return sh.add_worksheet(title=WORKSHEET_NAME, rows=10, cols=2)


def _load_cell(cell: str, default):
    try:
        ws = _get_ws()
        raw = ws.acell(cell).value
        if not raw:
            return default
        return json.loads(raw)
    except json.JSONDecodeError as e:
        # 破損データを空で上書きしないよう例外伝播
        raise RuntimeError(f"{cell} のJSONパースに失敗: {e}") from e


def _save_cell(cell: str, value) -> None:
    ws = _get_ws()
    ws.update_acell(cell, json.dumps(value, ensure_ascii=False))


# ----------------------------------------------------------------------
# ワーカーマスタ
# ----------------------------------------------------------------------
def load_workers() -> dict[str, dict]:
    """ワーカーマスタを読み込み。失敗時は例外を伝播（空dictで上書き事故を防ぐ）。"""
    return _load_cell(WORKERS_CELL, {})


def save_workers(workers: dict[str, dict]) -> None:
    _save_cell(WORKERS_CELL, workers)


def generate_new_id(existing: dict[str, dict]) -> str:
    """既存IDと衝突しない6桁数字IDを生成。"""
    used = set(existing.keys())
    for _ in range(1000):
        candidate = f"{random.randint(0, 999999):06d}"
        if candidate not in used:
            return candidate
    raise RuntimeError("6桁ID発行に失敗（既存IDが多すぎる）")


def make_worker_key(name: str, kana: str) -> str:
    """氏名+カナの正規化キー（空白除去）。"""
    n = (name or "").replace(" ", "").replace("　", "").strip()
    k = (kana or "").replace(" ", "").replace("　", "").strip()
    return f"{n}|{k}"


def build_key_to_id(workers: dict[str, dict]) -> dict[str, str]:
    """既存ワーカーから氏名+カナ → ID の逆引き辞書を構築。"""
    out = {}
    for wid, w in workers.items():
        out[make_worker_key(w.get("氏名", ""), w.get("カナ", ""))] = wid
    return out


def upsert_worker(workers: dict[str, dict], record: dict, today_iso: str) -> tuple[str, bool]:
    """
    Excel 1行(record)からワーカーを upsert。返り値: (id, is_new)。
    既存ワーカーは年齢・性別を最新で上書き＋初回登録日を最古日に更新。
    新規ワーカーは初回登録日 = recordの就業日（同期実行日ではなく実際の初稼働日）。
    """
    key = make_worker_key(record.get("氏名", ""), record.get("カナ", ""))
    key_to_id = build_key_to_id(workers)
    rec_date = record.get("就業日") or today_iso

    if key in key_to_id:
        wid = key_to_id[key]
        w = workers[wid]
        # 軽微なメタ更新
        if record.get("性別"):
            w["性別"] = record["性別"]
        if record.get("年齢") is not None:
            w["年齢"] = record["年齢"]
        # 初回登録日は「より古い就業日を見つけたら遡る」
        cur = w.get("初回登録日", "")
        if rec_date and (not cur or rec_date < cur):
            w["初回登録日"] = rec_date
        return wid, False

    wid = generate_new_id(workers)
    workers[wid] = {
        "氏名": record.get("氏名", ""),
        "カナ": record.get("カナ", ""),
        "性別": record.get("性別", ""),
        "年齢": record.get("年齢"),
        "初回登録日": rec_date,
        "メモ": "",
        "タグ": [],
        "直雇勧誘済": False,
        "チェック日": None,
        "キャンセル履歴": [],
    }
    return wid, True


def update_worker_field(wid: str, field: str, value) -> None:
    """ボードからの編集（メモ/タグ/直雇勧誘済/チェック日）。"""
    workers = load_workers()
    if wid not in workers:
        raise KeyError(f"未登録ID: {wid}")
    workers[wid][field] = value
    save_workers(workers)


# ----------------------------------------------------------------------
# スナップショット（差分検知用）
# ----------------------------------------------------------------------
def load_snapshot() -> list[dict]:
    return _load_cell(SNAPSHOT_CELL, [])


def save_snapshot(snapshot: list[dict]) -> None:
    _save_cell(SNAPSHOT_CELL, snapshot)


# ----------------------------------------------------------------------
# メタ情報
# ----------------------------------------------------------------------
def load_meta() -> dict:
    return _load_cell(META_CELL, {})


def save_meta(meta: dict) -> None:
    _save_cell(META_CELL, meta)


# ----------------------------------------------------------------------
# 求人一覧スナップショット（タイミー求人カレンダーから取得・全置換）
# ----------------------------------------------------------------------
def load_postings() -> list[dict]:
    """求人一覧スナップショットを読み込み。
    要素: {日付, 開始時間, 終了時間, マッチ数, 募集人数, 状態}
    """
    return _load_cell(POSTINGS_CELL, [])


def save_postings(postings: list[dict]) -> None:
    """求人一覧スナップショットを全置換保存。"""
    _save_cell(POSTINGS_CELL, postings)


# ----------------------------------------------------------------------
# アーカイブ（過去月データ・行ベース・容量制限なし）
# ----------------------------------------------------------------------
def _get_archive_ws():
    client = _get_client()
    sh = client.open_by_key(_get_sheet_id())
    try:
        ws = sh.worksheet(ARCHIVE_WORKSHEET)
    except gspread.exceptions.WorksheetNotFound:
        ws = sh.add_worksheet(title=ARCHIVE_WORKSHEET,
                              rows=2, cols=len(ARCHIVE_HEADERS))
        ws.update(values=[ARCHIVE_HEADERS], range_name="A1")
        return ws
    # 既存だがヘッダー欠損なら設定
    try:
        first = ws.row_values(1)
        if first[: len(ARCHIVE_HEADERS)] != ARCHIVE_HEADERS:
            ws.update(values=[ARCHIVE_HEADERS], range_name="A1")
    except Exception:
        pass
    return ws


def load_archive() -> list[dict]:
    """過去アーカイブを全件返す（id 6桁文字列に正規化）。"""
    ws = _get_archive_ws()
    try:
        records = ws.get_all_records()
    except Exception:
        return []
    out = []
    for r in records:
        wid = r.get("id")
        if wid in (None, ""):
            continue
        try:
            wid = f"{int(wid):06d}"
        except (TypeError, ValueError):
            wid = str(wid)
        out.append({
            "id": wid,
            "就業日": str(r.get("就業日", "")).strip(),
            "出勤回数": int(r["出勤回数"]) if str(r.get("出勤回数", "")).strip() not in ("",) else 0,
            "開始時間": str(r.get("開始時間", "")).strip(),
            "終了時間": str(r.get("終了時間", "")).strip(),
            "求人タイトル": str(r.get("求人タイトル", "")).strip(),
            "グループ": str(r.get("グループ", "")).strip(),
            "バッジ": str(r.get("バッジ", "")).strip(),
        })
    return out


def append_archive(entries: list[dict]) -> int:
    """新エントリをアーカイブに追記（既存(id, 就業日)ペアは無視）。返り値=追記件数。"""
    if not entries:
        return 0
    existing_keys = {(e["id"], e["就業日"]) for e in load_archive()}
    rows = []
    for e in entries:
        key = (e.get("id"), e.get("就業日"))
        if key in existing_keys:
            continue
        existing_keys.add(key)
        rows.append([
            e.get("id", ""),
            e.get("就業日", ""),
            e.get("出勤回数", 0),
            e.get("開始時間", ""),
            e.get("終了時間", ""),
            e.get("求人タイトル", ""),
            e.get("グループ", ""),
            e.get("バッジ", ""),
        ])
    if not rows:
        return 0
    ws = _get_archive_ws()
    ws.append_rows(rows, value_input_option="USER_ENTERED")
    return len(rows)


# ----------------------------------------------------------------------
# 差分検知
# ----------------------------------------------------------------------
def _parse_date(s: str) -> Optional[date]:
    """'2026-05-15' / '2026/05/15' / '05月15日' などを date に変換。"""
    if not s:
        return None
    s = str(s).strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def diff_snapshots(prev: list[dict], curr: list[dict], today: date) -> tuple[list[dict], list[dict]]:
    """
    新規マッチング(curr-prev) と キャンセル(prev-curr, 未来日のみ) を抽出。
    キーは (id, 就業日) のペア。
    """
    def _key(r):
        return (r.get("id"), r.get("就業日"))

    prev_map = {_key(r): r for r in prev}
    curr_map = {_key(r): r for r in curr}

    new_matches = [curr_map[k] for k in curr_map.keys() - prev_map.keys()]
    # キャンセル判定：消失したペアのうち、就業日が「今日以降」のものだけ
    cancellations = []
    for k in prev_map.keys() - curr_map.keys():
        d = _parse_date(prev_map[k].get("就業日", ""))
        if d is None:
            continue
        if d >= today:
            cancellations.append(prev_map[k])
    return new_matches, cancellations


def record_cancellations(workers: dict[str, dict], cancellations: list[dict], detected_date_iso: str) -> None:
    """キャンセルをワーカーマスタの履歴に追記（同一日同一就業日の重複は排除）。"""
    for c in cancellations:
        wid = c.get("id")
        if wid not in workers:
            continue
        history = workers[wid].setdefault("キャンセル履歴", [])
        entry = {"検知日": detected_date_iso, "元就業日": c.get("就業日", "")}
        if entry not in history:
            history.append(entry)
