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
    sa_json = os.environ.get("GCP_SERVICE_ACCOUNT_JSON", "")
    if sa_json:
        creds_dict = json.loads(sa_json)
        creds = Credentials.from_service_account_info(creds_dict, scopes=GS_SCOPES)
    else:
        creds = Credentials.from_service_account_file(
            "yoshida0538-f46ce1eea153.json", scopes=GS_SCOPES
        )
    return gspread.authorize(creds)


def fetch_report(sf: Salesforce) -> tuple[list[str], list[list[str]]]:
    """
    SFレポートAPIでデータを取得。
    Returns: (headers, rows)
    """
    # レポート記述を取得してカラム順を把握
    desc = sf.restful(f"analytics/reports/{SF_REPORT_ID}/describe")
    detail_cols = desc["reportMetadata"]["detailColumns"]
    col_info = desc["reportExtendedMetadata"]["detailColumnInfo"]
    headers = [col_info.get(c, {}).get("label", c) for c in detail_cols]

    # レポート実行
    all_rows = []
    result = sf.restful(f"analytics/reports/{SF_REPORT_ID}", params={"includeDetails": "true"})
    fact_map = result.get("factMap", {})

    for key in sorted(fact_map.keys()):
        section = fact_map[key]
        for row_data in section.get("rows", []):
            cells = row_data.get("dataCells", [])
            row = [str(cell.get("label", "")) for cell in cells]
            all_rows.append(row)

    if result.get("allData") is False:
        print(f"  WARNING: レポートが上限(2000件)に達しています。")

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
