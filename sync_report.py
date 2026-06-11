"""
Salesforceレポート → Google Sheets 自動同期スクリプト（GitHub Actions用）

1. SFレポート「SO新設プリティーダービー用」の全データを取得
2. スプレッドシート「SO新設プリティーダービー用」タブに全量上書き
3. 必要列だけ抽出して「1週間後FC該当案件」タブに上書き
"""

import os
import json
import sys
import time

import gspread
import requests
from google.oauth2.service_account import Credentials
from simple_salesforce import Salesforce

# --- 設定 ---
SF_REPORT_ID = "00OTL00000CG9LN2A1"

# 貼り付け先スプレッドシート
DERBY_SHEET_ID = "1iNtEakg4U4C3p7uQlVcJIzojnUd8uW5Ykl8swQRQD5U"
DERBY_TAB = "SO新設プリティーダービー用"

# lookup用 → プリティーダービー用シート内に同居
LOOKUP_SHEET_ID = "1iNtEakg4U4C3p7uQlVcJIzojnUd8uW5Ykl8swQRQD5U"
LOOKUP_TAB = "1週間後FC該当案件"

# 代コン不備該当案件 lookup用
DAICON_LOOKUP_TAB = "代コン不備該当案件"

# So-net光 案件 lookup用（タイミー工事取得トークのフォールバック検索先）
SONET_KAITSU_LOOKUP_TAB = "So-net光案件"

# 「1週間後FC該当案件」に引用する列（レポートのラベル名で指定）
LOOKUP_COLUMNS = [
    "取引先名",
    "申込者氏名",
    "申込者氏名（フリガナ）",
    "申込時工事取得状況",
    "案件進捗管理: エントリ日",
    "工事予定日（引用）",
    "開通日（引用）",
    "決済登録日（引用）",
    "status大区分（引用）",
    "【Lｽﾃｯﾌﾟ】突合完了日（引用）",
    "利用回線",
    "開通後ホーム電話案内",
    "ダイコンステータス",
    "取次商材情報",
    # 新規追加項目
    "年齢",
    "利用携帯＆利用台数",
    "商流（引用）",
    "住所結合",
    "郵便番号(設置先)",
    "エリア（東西）",
    # 前確OKコメント引用用
    "取引先 ID",
    # 代コンデータ連携11/1〜 との結合キー（不備解消の顧客固有補足の参照用）
    "申込受付番号",
]

GS_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def get_sf() -> Salesforce:
    """Salesforce接続。環境変数から認証。"""
    return Salesforce(
        username=os.environ.get("SF_USERNAME", ""),
        password=os.environ.get("SF_PASSWORD", ""),
        security_token=os.environ.get("SF_TOKEN", ""),
        domain=os.environ.get("SF_DOMAIN", "login"),
    )


def get_gspread_client():
    import base64
    sa_json = os.environ.get("GCP_SERVICE_ACCOUNT_JSON", "")
    if sa_json:
        try:
            decoded = base64.b64decode(sa_json)
            creds_dict = json.loads(decoded)
        except Exception:
            creds_dict = json.loads(sa_json)
        creds = Credentials.from_service_account_info(creds_dict, scopes=GS_SCOPES)
    else:
        creds = Credentials.from_service_account_file(
            "yoshida0538-f46ce1eea153.json", scopes=GS_SCOPES
        )
    return gspread.authorize(creds)


# レポートと同等のフィールド (APIフィールド名, 表示ラベル)
_SOQL_FIELDS = [
    ("Name", "取引先名"),
    ("Field29__c", "申込者氏名"),
    ("Field32__c", "申込者氏名（フリガナ）"),
    ("Field63__c", "申込受付番号"),
    ("Field76__r.Name", "取次商材情報"),
    ("Field183__c", "申込時工事取得状況"),
    ("Field118__c", "申込日（引用）"),
    ("Field128__c", "工事予定日（引用）"),
    ("Field130__c", "開通日（引用）"),
    ("Field131__c", "決済登録日（引用）"),
    ("Field119__c", "キャンセル日（引用）"),
    ("Field80__c", "キャンセル理由（中区分）"),
    ("status__c", "status大区分（引用）"),
    ("Ltotugo__c", "【Lｽﾃｯﾌﾟ】突合完了日（引用）"),
    ("Field97__c", "次回コール"),
    ("Field9__c", "利用回線"),
    ("Field43__c", "エリア（東西）"),
    ("Field6__c", "建物区分（設置先）"),
    ("Field228__c", "開通後ホーム電話案内"),
    ("Field113__c", "開通ステータス"),
    ("Id", "取引先 ID"),
    ("Field109__c", "対応ステータス"),
    ("Field144__c", "促進ステータス"),
    ("Field225__c", "ダイコンステータス"),
    ("Field242__c", "1次ダイコン理由"),
    ("Field224__c", "1次ダイコン備考"),
    ("Field243__c", "2次ダイコン理由"),
    ("Field247__c", "2次ダイコン備考"),
    ("Field244__c", "3次ダイコン理由"),
    ("Field248__c", "3次ダイコン備考"),
    ("Field245__c", "4次ダイコン理由"),
    ("Field249__c", "4次ダイコン備考"),
    ("Field246__c", "5次ダイコン理由"),
    ("Field250__c", "5次ダイコン備考"),
    ("Field341__c", "6次ダイコン理由"),
    ("Field346__c", "6次ダイコン備考"),
    ("Field342__c", "7次ダイコン理由"),
    ("Field347__c", "7次ダイコン備考"),
    ("Field343__c", "8次ダイコン理由"),
    ("Field348__c", "8次ダイコン備考"),
    ("Field344__c", "9次ダイコン理由"),
    ("Field349__c", "9次ダイコン備考"),
    ("Field345__c", "10次ダイコン理由"),
    ("Field350__c", "10次ダイコン備考"),
    ("Field24__c", "次回コール日"),
    ("Field25__c", "次回コール時間"),
    ("Field42__c", "年齢"),
    ("Field373__c", "利用携帯＆利用台数"),
    ("Field138__c", "商流（引用）"),
    ("Field134__c", "住所結合"),
    ("Field257__c", "住所結合（建物名＋部屋番号）"),
    ("Field139__c", "住所フリガナ"),
    ("BillingPostalCode", "郵便番号(設置先)"),
    # 促進用トーク（代コン不備）用の補足情報
    ("Field210__c", "工事Ⅰ状況（引用）"),
    ("Field362__c", "初回取次(API取得工事日)"),
    ("Field194__c", "工事取得FC回数"),
    ("Field288__c", "API取次対象"),
    ("Field290__c", "代理店コンサル希望"),
    ("Field56__c", "固定申込"),
    ("Field170__c", "固定電話1（引用）"),
    ("Field268__c", "おでん案内フラグ"),
]


def _get_nested(rec, field):
    """ドット区切りのフィールド（例: Field76__r.Name）から値を取得。"""
    parts = field.split(".")
    val = rec
    for p in parts:
        if val is None:
            return ""
        if isinstance(val, dict):
            val = val.get(p)
        else:
            return ""
    return val


def fetch_entry_map(sf: Salesforce) -> dict:
    """Account ID → エントリ日マッピング（最新を1件）。重いクエリなので使い回す。"""
    print("  エントリ日を取得中...")
    entry_soql = (
        "SELECT Field13__c, Field46__c "
        "FROM CustomObject3__c "
        "WHERE Field13__c != null "
        "ORDER BY Field13__c, Field46__c DESC"
    )
    entry_result = sf.query_all(entry_soql)
    entry_map = {}
    for r in entry_result.get("records", []):
        acc_id = r.get("Field13__c", "") or ""
        entry_date = r.get("Field46__c", "") or ""
        if acc_id and acc_id not in entry_map:
            entry_map[acc_id] = entry_date
    return entry_map


def fetch_report(
    sf: Salesforce,
    kubun_list: tuple[str, ...] = ("新設",),
    entry_map: dict | None = None,
) -> tuple[list[str], list[list[str]]]:
    """
    レポートと同等のデータをSOQLで全件取得（2000件制限なし）。
    フィルター: 申込区分 IN kubun_list, 申込日 2025-04-01 〜 当日(TODAY)
    entry_map を渡すとエントリ日の重いクエリを省略（複数区分で使い回す用）。

    ※ 上限はかつて 2026-05-31 固定だったが、それを過ぎると新規申込が丸ごと
       除外され（1週間後FCトーク等のlookupに載らない）不具合になるため、
       当日まで自動で含むよう TODAY に変更。
    """
    field_names = [f[0] for f in _SOQL_FIELDS]
    field_str = ", ".join(field_names)

    kubun_in = ", ".join(f"'{k}'" for k in kubun_list)
    soql = (
        f"SELECT {field_str} FROM Account "
        f"WHERE Field78__c IN ({kubun_in}) "
        f"AND Field118__c >= 2025-04-01 AND Field118__c <= TODAY "
        f"ORDER BY Name"
    )

    print(f"  SOQL実行中（申込区分={kubun_list} 全件取得）...")
    result = sf.query_all(soql)
    records = result.get("records", [])

    headers = [f[1] for f in _SOQL_FIELDS]
    # エントリ日を追加（子オブジェクトから別途取得）
    headers.append("案件進捗管理: エントリ日")

    if entry_map is None:
        entry_map = fetch_entry_map(sf)

    all_rows = []
    for rec in records:
        row = []
        for api_name, _ in _SOQL_FIELDS:
            val = _get_nested(rec, api_name)
            row.append(str(val) if val not in (None, "") else "")
        acc_id = rec.get("Id", "")
        row.append(entry_map.get(acc_id, ""))
        all_rows.append(row)

    print(f"  取得行数: {len(all_rows)}")
    return headers, all_rows


def _retry_sheets(fn, *, what: str, max_attempts: int = 5):
    """Google Sheets APIの一時障害(5xx/429)に指数バックオフでリトライ。"""
    for attempt in range(1, max_attempts + 1):
        try:
            return fn()
        except gspread.exceptions.APIError as e:
            msg = str(e)
            transient = any(code in msg for code in ["[500]", "[502]", "[503]", "[504]", "[429]"])
            if not transient or attempt == max_attempts:
                raise
            wait = min(60, 2 ** attempt)
            print(f"  WARN: {what} 失敗(attempt {attempt}/{max_attempts}) → {wait}s 待機して再試行: {msg.splitlines()[0]}")
            time.sleep(wait)


def write_to_sheet(client, sheet_id: str, tab_name: str, headers: list[str], rows: list[list[str]]):
    """スプレッドシートのタブに全量上書き。"""
    sh = client.open_by_key(sheet_id)
    try:
        ws = sh.worksheet(tab_name)
    except gspread.exceptions.WorksheetNotFound:
        ws = sh.add_worksheet(title=tab_name, rows=max(len(rows) + 1, 100), cols=max(len(headers), 30))

    _retry_sheets(lambda: ws.clear(), what=f"{tab_name} clear")

    needed_rows = max(len(rows) + 1, 100)
    needed_cols = max(len(headers), 1)

    # 必要サイズちょうどにresize（バッファ追加は workbook 10Mセル上限を圧迫するので避ける）
    # cols は基本縮む方向 → 先に縮めて空きセルを稼いでから rows を確保する
    if ws.col_count != needed_cols:
        try:
            _retry_sheets(lambda: ws.resize(cols=needed_cols), what=f"{tab_name} cols resize")
        except gspread.exceptions.APIError as e:
            if "10000000 cells" not in str(e):
                raise
            print(f"  WARN: cols resize失敗: {e}")
    if ws.row_count != needed_rows:
        _retry_sheets(lambda: ws.resize(rows=needed_rows), what=f"{tab_name} rows resize")

    # ヘッダー
    _retry_sheets(lambda: ws.update(range_name="A1", values=[headers]), what=f"{tab_name} header update")

    # データ本体はチャンク分割（Sheets API のリクエストサイズ制限を回避）
    CHUNK = 1000
    total = len(rows)
    for start in range(0, total, CHUNK):
        chunk = rows[start:start + CHUNK]
        cell_row = start + 2  # 1行目はヘッダー
        _retry_sheets(
            lambda c=chunk, r=cell_row: ws.update(range_name=f"A{r}", values=c),
            what=f"{tab_name} rows {cell_row}-",
        )
        print(f"  {tab_name}: {start + len(chunk)}/{total} 行書込")

    print(f"  {tab_name}: {len(rows)}行 x {len(headers)}列 書込完了")


def extract_lookup_data(headers: list[str], rows: list[list[str]]) -> tuple[list[str], list[list[str]]]:
    """
    全データからLOOKUP_COLUMNSだけ抽出。
    フィルター:
      - エントリ日が過去60日以内
      - status大区分が 95 キャンセル済み / 96 解約済み は除外
      - キャンセル日（引用）が入っている案件は除外
    """
    from datetime import datetime, timezone, timedelta
    JST = timezone(timedelta(hours=9))
    now = datetime.now(JST)
    date_from = (now - timedelta(days=60)).date()

    col_indices = []
    found_headers = []
    for col_name in LOOKUP_COLUMNS:
        if col_name in headers:
            col_indices.append(headers.index(col_name))
            found_headers.append(col_name)
        else:
            print(f"  WARNING: 列 '{col_name}' がレポートに見つかりません（スキップ）")

    # フィルター用の列インデックス
    entry_idx = headers.index("案件進捗管理: エントリ日") if "案件進捗管理: エントリ日" in headers else -1
    status_idx = headers.index("status大区分（引用）") if "status大区分（引用）" in headers else -1
    shozai_idx = headers.index("取次商材情報") if "取次商材情報" in headers else -1
    cancel_idx = headers.index("キャンセル日（引用）") if "キャンセル日（引用）" in headers else -1
    EXCLUDE_STATUS = {"95 キャンセル済み", "96 解約済み", "キャンセル"}
    EXCLUDE_SHOZAI = {"AU光_010"}

    extracted = []
    skipped = 0
    for row in rows:
        # status除外
        if status_idx >= 0 and status_idx < len(row):
            st = row[status_idx].strip()
            if st in EXCLUDE_STATUS:
                skipped += 1
                continue

        # 取次商材除外
        if shozai_idx >= 0 and shozai_idx < len(row):
            sz = row[shozai_idx].strip()
            if sz in EXCLUDE_SHOZAI:
                skipped += 1
                continue

        # キャンセル日が入っていたら除外
        if cancel_idx >= 0 and cancel_idx < len(row):
            if row[cancel_idx].strip():
                skipped += 1
                continue

        # エントリ日フィルター（過去60日以内）
        if entry_idx >= 0 and entry_idx < len(row):
            entry_str = row[entry_idx].strip()
            if entry_str:
                entry_date = None
                for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
                    try:
                        entry_date = datetime.strptime(entry_str[:10], fmt).date()
                        break
                    except ValueError:
                        continue
                if entry_date and entry_date < date_from:
                    skipped += 1
                    continue

        extracted.append([row[i] if i < len(row) else "" for i in col_indices])

    print(f"  フィルター: エントリ日>={date_from}, キャンセル日空, status除外={EXCLUDE_STATUS}, 商材除外={EXCLUDE_SHOZAI}")
    print(f"  → {len(extracted)}行（除外: {skipped}行）")
    return found_headers, extracted


DAICON_LOOKUP_COLUMNS = [
    "取引先名",
    "申込者氏名",
    "申込者氏名（フリガナ）",
    "申込時工事取得状況",
    "案件進捗管理: エントリ日",
    "工事予定日（引用）",
    "開通日（引用）",
    "決済登録日（引用）",
    "status大区分（引用）",
    "開通ステータス",
    "【Lｽﾃｯﾌﾟ】突合完了日（引用）",
    "利用回線",
    "開通後ホーム電話案内",
    "ダイコンステータス",
    "1次ダイコン理由", "1次ダイコン備考",
    "2次ダイコン理由", "2次ダイコン備考",
    "3次ダイコン理由", "3次ダイコン備考",
    "4次ダイコン理由", "4次ダイコン備考",
    "5次ダイコン理由", "5次ダイコン備考",
    "6次ダイコン理由", "6次ダイコン備考",
    "7次ダイコン理由", "7次ダイコン備考",
    "8次ダイコン理由", "8次ダイコン備考",
    "9次ダイコン理由", "9次ダイコン備考",
    "10次ダイコン理由", "10次ダイコン備考",
    "取次商材情報",
    "年齢",
    "利用携帯＆利用台数",
    "商流（引用）",
    "住所結合",
    "郵便番号(設置先)",
    "エリア（東西）",
    "取引先 ID",
    # 促進用トーク 補足情報
    "工事Ⅰ状況（引用）",
    "初回取次(API取得工事日)",
    "工事取得FC回数",
    "API取次対象",
    "代理店コンサル希望",
    "固定申込",
    "固定電話1（引用）",
    "おでん案内フラグ",
]


def extract_daicon_fubi_data(headers: list[str], rows: list[list[str]]) -> tuple[list[str], list[list[str]]]:
    """
    代コン不備解消用の抽出。
    条件:
      - ダイコンステータス or 1〜10次ダイコン理由のいずれかに値
      - キャンセル日（引用）が空欄
      - 開通ステータスが「キャンセル」ではない
      - status大区分 が 95 キャンセル済み / 88 退会受付済み(回線廃止手続き中) / 50 開通済み ではない
    """
    col_indices = []
    found_headers = []
    for col_name in DAICON_LOOKUP_COLUMNS:
        if col_name in headers:
            col_indices.append(headers.index(col_name))
            found_headers.append(col_name)
        else:
            print(f"  WARNING: 列 '{col_name}' がレポートに見つかりません（スキップ）")

    daikon_idx = headers.index("ダイコンステータス") if "ダイコンステータス" in headers else -1
    reason_idxs = [headers.index(f"{n}次ダイコン理由") for n in range(1, 11) if f"{n}次ダイコン理由" in headers]
    cancel_idx = headers.index("キャンセル日（引用）") if "キャンセル日（引用）" in headers else -1
    kaitsu_idx = headers.index("開通ステータス") if "開通ステータス" in headers else -1
    status_idx = headers.index("status大区分（引用）") if "status大区分（引用）" in headers else -1

    EXCLUDE_STATUS = {
        "95 キャンセル済み",
        "88 退会受付済み(回線廃止手続き中)",
        "50 開通済み",
    }

    extracted = []
    skipped = 0
    for row in rows:
        # キャンセル日が入っていたら除外
        if cancel_idx >= 0 and cancel_idx < len(row) and row[cancel_idx].strip():
            skipped += 1
            continue

        # 開通ステータスがキャンセルなら除外
        if kaitsu_idx >= 0 and kaitsu_idx < len(row) and row[kaitsu_idx].strip() == "キャンセル":
            skipped += 1
            continue

        # status大区分が除外対象なら除外
        if status_idx >= 0 and status_idx < len(row) and row[status_idx].strip() in EXCLUDE_STATUS:
            skipped += 1
            continue

        # ダイコンステータス or 1〜10次ダイコン理由のいずれかに値
        has_daikon = False
        if daikon_idx >= 0 and daikon_idx < len(row) and row[daikon_idx].strip():
            has_daikon = True
        else:
            for ri in reason_idxs:
                if ri < len(row) and row[ri].strip():
                    has_daikon = True
                    break
        if not has_daikon:
            skipped += 1
            continue

        extracted.append([row[i] if i < len(row) else "" for i in col_indices])

    print(f"  フィルター: ダイコン値あり & キャンセル日空 & 開通ST≠キャンセル & status大区分除外={EXCLUDE_STATUS}")
    print(f"  → {len(extracted)}行（除外: {skipped}行）")
    return found_headers, extracted


def extract_sonet_kaitsu_data(headers: list[str], rows: list[list[str]]) -> tuple[list[str], list[list[str]]]:
    """
    So-net光 案件のフォールバック検索用抽出。
    条件:
      - 取次商材情報 が 'So-net光' で始まる（前方一致）
      - キャンセル日（引用）が空
      - status大区分 が 95/96/キャンセル 以外
      - 開通日（引用）が空（未開通のみ）
    抽出列は 1週間後FC該当案件 と同じ（LOOKUP_COLUMNS）。
    """
    col_indices = []
    found_headers = []
    for col_name in LOOKUP_COLUMNS:
        if col_name in headers:
            col_indices.append(headers.index(col_name))
            found_headers.append(col_name)
        else:
            print(f"  WARNING: 列 '{col_name}' がレポートに見つかりません（スキップ）")

    shozai_idx = headers.index("取次商材情報") if "取次商材情報" in headers else -1
    cancel_idx = headers.index("キャンセル日（引用）") if "キャンセル日（引用）" in headers else -1
    status_idx = headers.index("status大区分（引用）") if "status大区分（引用）" in headers else -1
    kaitsu_idx = headers.index("開通日（引用）") if "開通日（引用）" in headers else -1
    EXCLUDE_STATUS = {"95 キャンセル済み", "96 解約済み", "キャンセル"}

    extracted = []
    skipped = 0
    for row in rows:
        # 取次商材情報が 'So-net光' で始まる
        if shozai_idx < 0:
            break
        sz = row[shozai_idx].strip() if shozai_idx < len(row) else ""
        if not sz.startswith("So-net光"):
            skipped += 1
            continue

        # キャンセル日が入っていたら除外
        if cancel_idx >= 0 and cancel_idx < len(row) and row[cancel_idx].strip():
            skipped += 1
            continue

        # status大区分除外
        if status_idx >= 0 and status_idx < len(row) and row[status_idx].strip() in EXCLUDE_STATUS:
            skipped += 1
            continue

        # 開通日が入っていたら除外（未開通のみ）
        if kaitsu_idx >= 0 and kaitsu_idx < len(row) and row[kaitsu_idx].strip():
            skipped += 1
            continue

        extracted.append([row[i] if i < len(row) else "" for i in col_indices])

    print(f"  フィルター: 取次商材LIKE 'So-net光%' & キャンセル日空 & status除外={EXCLUDE_STATUS} & 開通日空")
    print(f"  → {len(extracted)}行（除外: {skipped}行）")
    return found_headers, extracted


def main():
    print("=== SF Report → Google Sheets Sync ===")

    # 1. Salesforceレポート取得
    print("1. Salesforceレポート取得中...")
    sf = get_sf()
    entry_map = fetch_entry_map(sf)  # 重いので1回だけ取得し使い回す
    # 他タブ（デービー/代コン/So-net）用は従来どおり「新設」のみ
    headers, rows = fetch_report(sf, ("新設",), entry_map=entry_map)
    print(f"   列数: {len(headers)}, 行数: {len(rows)}")
    # 1週間後FC該当案件タブ用に「事業者変更」も追加取得（このタブにだけ反映）
    _, rows_jigyo = fetch_report(sf, ("事業者変更",), entry_map=entry_map)
    print(f"   事業者変更 行数: {len(rows_jigyo)}")

    # 2. プリティーダービー用タブに全量書込（新設のみ・従来どおり）
    print("2. プリティーダービー用タブに書込中...")
    client = get_gspread_client()
    write_to_sheet(client, DERBY_SHEET_ID, DERBY_TAB, headers, rows)

    # API制限回避
    time.sleep(3)

    # 3. lookup用タブに必要列だけ書込（新設＋事業者変更）
    print("3. 1週間後FC該当案件タブに必要列を書込中...")
    lookup_headers, lookup_rows = extract_lookup_data(headers, rows + rows_jigyo)
    write_to_sheet(client, LOOKUP_SHEET_ID, LOOKUP_TAB, lookup_headers, lookup_rows)

    # API制限回避
    time.sleep(3)

    # 4. 代コン不備該当案件タブに書込
    print("4. 代コン不備該当案件タブに必要列を書込中...")
    daicon_headers, daicon_rows = extract_daicon_fubi_data(headers, rows)
    write_to_sheet(client, LOOKUP_SHEET_ID, DAICON_LOOKUP_TAB, daicon_headers, daicon_rows)

    # API制限回避
    time.sleep(3)

    # 5. So-net光案件タブに書込（タイミー工事取得トークのフォールバック検索用）
    print("5. So-net光案件タブに必要列を書込中...")
    sonet_headers, sonet_rows = extract_sonet_kaitsu_data(headers, rows)
    write_to_sheet(client, LOOKUP_SHEET_ID, SONET_KAITSU_LOOKUP_TAB, sonet_headers, sonet_rows)

    print("=== 完了 ===")


if __name__ == "__main__":
    main()
