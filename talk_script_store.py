"""
トークスクリプト用 Google Sheets リーダー

電話番号で顧客情報を引き当て、商材別のトークスクリプト本文を取得する。
（既存のスプレッドシート運用を Streamlit に取り込んだもの）
"""

import os
import re
import pandas as pd
import streamlit as st
import gspread
from google.oauth2.service_account import Credentials


SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]

# トークスクリプト用スプレッドシート（トーク本文ソース）
TALK_SCRIPT_SHEET_ID = "15kqCJoZYQSrkvqwecmLgeS9aJBlJAVdoSOP1j822zS0"

# 顧客データシート（sync_report.pyで自動同期される先）
LOOKUP_SHEET_ID = "1iNtEakg4U4C3p7uQlVcJIzojnUd8uW5Ykl8swQRQD5U"
LOOKUP_SHEET = "1週間後FC該当案件"
DAICON_LOOKUP_SHEET = "代コン不備該当案件"
SONET_KAITSU_LOOKUP_SHEET = "So-net光案件"  # タイミー工事取得トーク フォールバック検索先
RENKEI_TAB = "代コンデータ連携11/1～"  # 不備停滞の顧客固有データ（1停滞1行・申込受付番号で複数行）

# suffix → ワークシート名 のマッピング
LOOKUP_SHEETS_BY_SUFFIX = {
    "fc1week": LOOKUP_SHEET,
    "fc0601": LOOKUP_SHEET,
    "shiryou": LOOKUP_SHEET,
    "sokushin": DAICON_LOOKUP_SHEET,
    "timee_kouji": LOOKUP_SHEET,
    "kouji_oritsugi": LOOKUP_SHEET,
}

# タイミー工事取得トーク用スプレッドシート（A列1セル1行のトーク本文、【セクション】見出し付き）
TIMEE_KOUJI_SHEET_ID = "1H1vquKw-em6FN-F0zOme0gwUEvgC_5OiJGIrFSTCQ7s"
TIMEE_KOUJI_TABS = {
    "et7_10":  "ET+7-10",     # エントリ日から10日以内
    "et11":    "ET+11以降",    # エントリ日から11日以上経過
}

# 商材種別 → トークシート名
SCRIPT_SHEETS = {
    "Sonet": "1週間後FCトーク0314",
    "NURO": "NURO1週間後FCトーク0402",
}

# ローカル開発用フォールバック JSON
_LOCAL_KEY_FILE = "yoshida0538-f46ce1eea153.json"


@st.cache_resource
def _get_gspread_client():
    """gspread認証クライアントを返す。st.secrets優先、ローカルJSONフォールバック。"""
    try:
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    except Exception:
        # ローカル: JSONファイル直読み
        if not os.path.exists(_LOCAL_KEY_FILE):
            raise RuntimeError(
                "Google Sheets認証情報が見つかりません。"
                "st.secrets['gcp_service_account'] か "
                f"{_LOCAL_KEY_FILE} を用意してください。"
            )
        creds = Credentials.from_service_account_file(_LOCAL_KEY_FILE, scopes=SCOPES)
    return gspread.authorize(creds)


def normalize_phone(phone: str) -> str:
    """電話番号を正規化（数字以外を除去）。"""
    if phone is None:
        return ""
    return re.sub(r"[^0-9]", "", str(phone))


@st.cache_data(ttl=1800, show_spinner="顧客データを取得中...")
def load_customer_data(sheet_name: str = LOOKUP_SHEET) -> pd.DataFrame:
    """指定したワークシートを丸ごとDataFrameで読み込み、電話番号正規化列を付与。
    TTL 30分（API制限回避のため長め）。
    """
    import time as _time
    from talk_template_store import _get_writable_client
    try:
        client = _get_writable_client()
    except Exception:
        client = _get_gspread_client()

    # リトライ付きで取得（429/レート制限対策）
    last_err = None
    for attempt in range(4):
        try:
            sh = client.open_by_key(LOOKUP_SHEET_ID)
            ws = sh.worksheet(sheet_name)
            values = ws.get_all_values()
            break
        except Exception as e:
            last_err = e
            msg = str(e)
            if "429" in msg or "quota" in msg.lower() or "rate" in msg.lower() or "limit" in msg.lower():
                _time.sleep(2 ** attempt)  # 1, 2, 4, 8秒
                continue
            raise
    else:
        raise last_err

    if not values or len(values) < 2:
        return pd.DataFrame()
    header = values[0]
    rows = values[1:]
    # 列数差吸収（行ごとに長さが違う場合）
    width = len(header)
    rows = [r + [""] * (width - len(r)) if len(r) < width else r[:width] for r in rows]
    df = pd.DataFrame(rows, columns=header)
    if "取引先名" in df.columns:
        df["_phone_normalized"] = df["取引先名"].map(normalize_phone)
    else:
        df["_phone_normalized"] = ""
    return df


def get_lookup_columns(sheet_name: str = LOOKUP_SHEET) -> list[str]:
    """顧客lookupシートのヘッダー列名一覧を返す（内部列を除外）。"""
    df = load_customer_data(sheet_name)
    if df.empty:
        return []
    return [c for c in df.columns if not c.startswith("_")]


def resolve_lookup_sheet(suffix: str) -> str:
    """ボードsuffixからワークシート名を解決。未登録なら1週間後FC（後方互換）。"""
    return LOOKUP_SHEETS_BY_SUFFIX.get(suffix, LOOKUP_SHEET)


def lookup_customer(phone: str, sheet_name: str = LOOKUP_SHEET) -> dict | None:
    """
    電話番号で顧客情報を引き当て。複数ヒット時は申込日（案件進捗管理: エントリ日）が
    最も新しい1件を返す。
    """
    phone_n = normalize_phone(phone)
    if not phone_n:
        return None
    df = load_customer_data(sheet_name)
    if df.empty:
        return None
    hit = df[df["_phone_normalized"] == phone_n]
    if hit.empty:
        return None
    # エントリ日で降順ソート（不正値は最後）
    date_col = "案件進捗管理: エントリ日"
    if date_col in hit.columns:
        hit = hit.copy()
        hit["_entry_dt"] = pd.to_datetime(hit[date_col], errors="coerce")
        hit = hit.sort_values("_entry_dt", ascending=False, na_position="last")
    return hit.iloc[0].to_dict()


@st.cache_data(ttl=1800, show_spinner="代コン連携データを取得中...")
def load_renkei_index() -> dict:
    """代コンデータ連携11/1～ を読み、申込受付番号ごとに「最新の1停滞」を返す。

    1停滞=1行で、同じ申込受付番号が複数行ある（再停滞のたびに追記）。
    対応依頼日(G列)が最大の行を採用。G欠損時は データ入力日(I) → 登録日(A) でフォールバック。

    返り値: { 申込受付番号: {
        "事務局コンサル理由": str(E列), "補足": str(F列・顧客固有メモ),
        "対応方針": str(N列・代コンマスタ準拠の解決済み手順),
        "代コン備考": str(L列), "対応依頼日": str(G列) } }
    TTL 30分（API制限回避）。
    """
    import time as _time
    from talk_template_store import _get_writable_client
    try:
        client = _get_writable_client()
    except Exception:
        client = _get_gspread_client()

    last_err = None
    for attempt in range(4):
        try:
            sh = client.open_by_key(LOOKUP_SHEET_ID)
            ws = sh.worksheet(RENKEI_TAB)
            values = ws.get_all_values()
            break
        except Exception as e:
            last_err = e
            msg = str(e)
            if "429" in msg or "quota" in msg.lower() or "rate" in msg.lower() or "limit" in msg.lower():
                _time.sleep(2 ** attempt)
                continue
            raise
    else:
        raise last_err

    if not values or len(values) < 2:
        return {}

    # 列index(0始まり): A登録日=0 B受付番号=1 E理由=4 F補足=5 G対応依頼日=6 I入力日=8 L代コン備考=11 N対応方針=13
    I_UKE, I_RIYU, I_HOSOKU, I_IRAI, I_NYU, I_BIKO, I_HOUSHIN = 1, 4, 5, 6, 8, 11, 13

    def _to_dt(s):
        s = (s or "").strip()
        return pd.to_datetime(s, errors="coerce") if s else None

    result: dict = {}
    for row in values[1:]:
        if len(row) <= I_HOUSHIN:
            row = row + [""] * (I_HOUSHIN + 1 - len(row))
        uke = (row[I_UKE] or "").strip()
        if not uke:
            continue
        rank = _to_dt(row[I_IRAI])
        if rank is None or pd.isna(rank):
            rank = _to_dt(row[I_NYU])
        if rank is None or pd.isna(rank):
            rank = _to_dt(row[0])
        rec = {
            "事務局コンサル理由": (row[I_RIYU] or "").strip(),
            "補足": (row[I_HOSOKU] or "").strip(),
            "対応方針": (row[I_HOUSHIN] or "").strip(),
            "代コン備考": (row[I_BIKO] or "").strip(),
            "対応依頼日": (row[I_IRAI] or "").strip(),
            "_rank": rank,
        }
        prev = result.get(uke)
        if prev is None:
            result[uke] = rec
        else:
            p = prev.get("_rank")
            if rank is not None and not pd.isna(rank) and (p is None or pd.isna(p) or rank >= p):
                result[uke] = rec
    for v in result.values():
        v.pop("_rank", None)
    return result


def get_customer_hosoku(uketuke: str) -> dict | None:
    """申込受付番号から最新停滞の補足情報を返す。該当なし/取得失敗時は None。"""
    uketuke = (uketuke or "").strip()
    if not uketuke:
        return None
    try:
        idx = load_renkei_index()
    except Exception:
        return None
    return idx.get(uketuke)


@st.cache_data(ttl=600, show_spinner="トークスクリプトを取得中...")
def load_talk_script(kind: str) -> list[str]:
    """商材種別のトークスクリプト本文（B列）を行ごとのリストで取得。"""
    sheet_name = SCRIPT_SHEETS.get(kind)
    if not sheet_name:
        return []
    client = _get_gspread_client()
    sh = client.open_by_key(TALK_SCRIPT_SHEET_ID)
    ws = sh.worksheet(sheet_name)
    return ws.col_values(2)  # B列


@st.cache_data(ttl=600, show_spinner="LINEテンプレを取得中...")
def load_line_templates(kind: str) -> dict[str, str]:
    """
    LINEテンプレ（完了LINE / 留守LINE / 留守完了LINE）を取得。
    Sonet: D/E/F列に分かれている
    NURO:  B列の末尾にインライン格納（完了LINE / 留守LINE / 留守完了LINE のヘッダーで区切り）
    """
    sheet_name = SCRIPT_SHEETS.get(kind)
    if not sheet_name:
        return {}
    client = _get_gspread_client()
    sh = client.open_by_key(TALK_SCRIPT_SHEET_ID)
    ws = sh.worksheet(sheet_name)

    if kind == "Sonet":
        col_d = ws.col_values(4)
        col_e = ws.col_values(5)
        col_f = ws.col_values(6)

        def _extract_col(col_values: list[str], header: str) -> str:
            try:
                start = col_values.index(header) + 1
            except ValueError:
                return ""
            body = col_values[start:]
            while body and not body[-1].strip():
                body.pop()
            return "\n".join(body)

        return {
            "完了LINE": _extract_col(col_d, "完了LINE"),
            "留守LINE": _extract_col(col_e, "留守LINE"),
            "留守完了LINE": _extract_col(col_f, "留守完了LINE"),
        }

    # NURO: B列内のヘッダー区切り
    col_b = ws.col_values(2)
    headers = ["完了LINE", "留守LINE", "留守完了LINE"]
    positions: list[tuple[str, int]] = []
    for i, v in enumerate(col_b):
        if v.strip() in headers:
            positions.append((v.strip(), i))

    result: dict[str, str] = {h: "" for h in headers}
    for idx, (h, start) in enumerate(positions):
        end = positions[idx + 1][1] if idx + 1 < len(positions) else len(col_b)
        body = col_b[start + 1:end]
        while body and not body[-1].strip():
            body.pop()
        while body and not body[0].strip():
            body.pop(0)
        result[h] = "\n".join(body)
    return result


def detect_kind(shozai: str) -> str:
    """取次商材情報からトーク種別を判定。"""
    s = (shozai or "").upper()
    if "NURO" in s:
        return "NURO"
    return "Sonet"


@st.cache_data(ttl=1800, show_spinner="タイミー工事取得トークを取得中...")
def load_timee_kouji_script(tab_name: str) -> list[dict]:
    """タイミー工事取得トークスプレッドシートの指定タブのA列を読み取り、
    【セクション】見出し行と本文行に分けて返す。

    Returns:
        [{"section": "アプローチ", "body": "本文1\\n本文2\\n..."}, ...]
    """
    import time as _time
    from talk_template_store import _get_writable_client
    try:
        client = _get_writable_client()
    except Exception:
        client = _get_gspread_client()

    last_err = None
    for attempt in range(4):
        try:
            sh = client.open_by_key(TIMEE_KOUJI_SHEET_ID)
            ws = sh.worksheet(tab_name)
            col_a = ws.col_values(1)
            break
        except Exception as e:
            last_err = e
            msg = str(e)
            if "429" in msg or "quota" in msg.lower() or "rate" in msg.lower() or "limit" in msg.lower():
                _time.sleep(2 ** attempt)
                continue
            raise
    else:
        raise last_err

    sections: list[dict] = []
    current_section = None
    current_body: list[str] = []

    def _flush():
        if current_section is not None:
            body_lines = current_body[:]
            while body_lines and not body_lines[-1].strip():
                body_lines.pop()
            while body_lines and not body_lines[0].strip():
                body_lines.pop(0)
            sections.append({"section": current_section, "body": "\n".join(body_lines)})

    for raw in col_a:
        line = (raw or "").rstrip()
        stripped = line.strip()
        # 【...】で始まる行をセクション見出しとして扱う
        if stripped.startswith("【") and "】" in stripped:
            _flush()
            current_section = stripped
            current_body = []
        else:
            if current_section is None:
                # 見出しより前の本文は破棄
                continue
            current_body.append(line)
    _flush()
    return sections


def clear_caches():
    """キャッシュクリア（サイドバーの🔄ボタンから呼ぶ用）。"""
    load_customer_data.clear()
    load_talk_script.clear()
    load_timee_kouji_script.clear()
