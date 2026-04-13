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
    "住所結合（建物名＋部屋番号）",
    "住所フリガナ",
    "郵便番号(設置先)",
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


def fetch_report(sf: Salesforce) -> tuple[list[str], list[list[str]]]:
    """
    レポートと同等のデータをSOQLで全件取得（2000件制限なし）。
    レポートのフィルター: 申込区分=新設, 申込日=2025-04-01～2026-05-31
    """
    field_names = [f[0] for f in _SOQL_FIELDS]
    field_str = ", ".join(field_names)

    soql = (
        f"SELECT {field_str} FROM Account "
        f"WHERE Field78__c = '新設' "
        f"AND Field118__c >= 2025-04-01 AND Field118__c <= 2026-05-31 "
        f"ORDER BY Name"
    )

    print("  SOQL実行中（全件取得）...")
    result = sf.query_all(soql)
    records = result.get("records", [])

    headers = [f[1] for f in _SOQL_FIELDS]
    # エントリ日を追加（子オブジェクトから別途取得）
    headers.append("案件進捗管理: エントリ日")

    # Account ID → エントリ日マッピング（最新を1件）
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


def write_to_sheet(client, sheet_id: str, tab_name: str, headers: list[str], rows: list[list[str]]):
    """スプレッドシートのタブに全量上書き。"""
    sh = client.open_by_key(sheet_id)
    try:
        ws = sh.worksheet(tab_name)
    except gspread.exceptions.WorksheetNotFound:
        ws = sh.add_worksheet(title=tab_name, rows=max(len(rows) + 10, 100), cols=max(len(headers) + 5, 30))

    # 全データをクリアして書き込み
    ws.clear()
    all_data = [headers] + rows
    # バッチ書き込み（大量データ対応）
    if len(all_data) > ws.row_count:
        ws.add_rows(len(all_data) - ws.row_count + 100)
    if len(headers) > ws.col_count:
        ws.add_cols(len(headers) - ws.col_count + 5)

    # 一括書き込み
    ws.update(range_name="A1", values=all_data)
    print(f"  {tab_name}: {len(rows)}行 x {len(headers)}列 書込完了")


def extract_lookup_data(headers: list[str], rows: list[list[str]]) -> tuple[list[str], list[list[str]]]:
    """全データからLOOKUP_COLUMNSだけ抽出。レポート側でフィルター済みのためそのまま使用。"""
    col_indices = []
    found_headers = []
    for col_name in LOOKUP_COLUMNS:
        if col_name in headers:
            col_indices.append(headers.index(col_name))
            found_headers.append(col_name)
        else:
            print(f"  WARNING: 列 '{col_name}' がレポートに見つかりません（スキップ）")

    extracted = []
    for row in rows:
        extracted.append([row[i] if i < len(row) else "" for i in col_indices])

    return found_headers, extracted


def main():
    print("=== SF Report → Google Sheets Sync ===")

    # 1. Salesforceレポート取得
    print("1. Salesforceレポート取得中...")
    sf = get_sf()
    headers, rows = fetch_report(sf)
    print(f"   列数: {len(headers)}, 行数: {len(rows)}")

    # 2. プリティーダービー用タブに全量書込
    print("2. プリティーダービー用タブに書込中...")
    client = get_gspread_client()
    write_to_sheet(client, DERBY_SHEET_ID, DERBY_TAB, headers, rows)

    # API制限回避
    time.sleep(3)

    # 3. lookup用タブに必要列だけ書込
    print("3. 1週間後FC該当案件タブに必要列を書込中...")
    lookup_headers, lookup_rows = extract_lookup_data(headers, rows)
    write_to_sheet(client, LOOKUP_SHEET_ID, LOOKUP_TAB, lookup_headers, lookup_rows)

    print("=== 完了 ===")


if __name__ == "__main__":
    main()
