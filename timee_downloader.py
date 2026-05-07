"""
タイミー管理画面から「就業予定表」Excelを期間指定でダウンロードするスクリプト。

GitHub Actions上のヘッドレスChromiumで実行する想定。

認証情報は環境変数:
- TIMEE_EMAIL
- TIMEE_PASSWORD

使い方（CLI）:
    python timee_downloader.py --year 2026 --month 5 --output ./tmp/timee_2026_05.xlsx

使い方（モジュール）:
    from timee_downloader import download_month_excel, parse_excel_records
    path = download_month_excel(2026, 5, "./tmp/timee_2026_05.xlsx")
    records = parse_excel_records(path)

タイミーのDOMが変わると壊れる可能性があるため、失敗時には
スクリーンショットとHTMLダンプを ./tmp/ に保存する。
"""

from __future__ import annotations

import argparse
import calendar
import os
import re
import sys
import time
from datetime import date
from pathlib import Path
from typing import Optional

import pandas as pd

LOGIN_URL = "https://app-new.taimee.co.jp/login"
CLIENT_ID = "340847"
ATTENDINGS_URL = f"https://app-new.taimee.co.jp/clients/{CLIENT_ID}/users/attendings"

DEFAULT_TIMEOUT_MS = 30000


def _last_day(year: int, month: int) -> int:
    return calendar.monthrange(year, month)[1]


def _dump_failure(page, tag: str) -> None:
    """失敗時のデバッグ情報を保存。"""
    Path("./tmp").mkdir(parents=True, exist_ok=True)
    ts = int(time.time())
    try:
        page.screenshot(path=f"./tmp/timee_fail_{tag}_{ts}.png", full_page=True)
    except Exception:
        pass
    try:
        Path(f"./tmp/timee_fail_{tag}_{ts}.html").write_text(page.content(), encoding="utf-8")
    except Exception:
        pass


def _login(page, email: str, password: str) -> None:
    page.goto(LOGIN_URL, wait_until="domcontentloaded")
    # メールアドレス入力（type=email or label='メールアドレス'）
    email_input = page.locator('input[type="email"], input[name*="mail" i]').first
    email_input.wait_for(state="visible", timeout=DEFAULT_TIMEOUT_MS)
    email_input.fill(email)
    # パスワード入力
    page.locator('input[type="password"]').first.fill(password)
    # ログインボタン
    page.get_by_role("button", name=re.compile(r"ログイン")).click()
    # ログイン完了 = URLが /login から離れる
    page.wait_for_url(lambda url: "/login" not in url, timeout=DEFAULT_TIMEOUT_MS)


def _open_period_modal(page) -> None:
    """就業予定表ページに遷移し、「期間を指定してダウンロード」モーダルを開く。"""
    page.goto(ATTENDINGS_URL, wait_until="domcontentloaded")
    # ページ表示待ち
    page.get_by_role("heading", name=re.compile(r"就業予定表")).wait_for(timeout=DEFAULT_TIMEOUT_MS)
    page.get_by_role("button", name=re.compile(r"期間を指定してダウンロード")).click()
    # モーダル表示確認
    page.get_by_text(re.compile(r"期間を指定してダウンロード")).first.wait_for(timeout=DEFAULT_TIMEOUT_MS)


def _select_period(page, year: int, month: int) -> None:
    """カレンダーで開始日(1日)と終了日(末日)を選択する。"""
    last_day = _last_day(year, month)

    # モーダル領域を絞り込み
    modal = page.locator('div[role="dialog"], [class*="modal" i]').last

    # --- 開始日 ---
    # 開始日入力を開く（既存値がある可能性あり）
    start_btn = modal.locator(
        f'button:has-text("{year}年{month}月1日"), button:has-text("開始日"), '
        'input[placeholder*="開始"]'
    ).first
    try:
        start_btn.click(timeout=5000)
    except Exception:
        # 既に開いている可能性あり
        pass
    _navigate_calendar_to(modal, year, month)
    _click_calendar_day(modal, 1)

    # --- 終了日 ---
    end_btn = modal.locator(
        'button:has-text("終了日"), input[placeholder*="終了"]'
    ).first
    try:
        end_btn.click(timeout=5000)
    except Exception:
        pass
    _navigate_calendar_to(modal, year, month)
    _click_calendar_day(modal, last_day)


def _navigate_calendar_to(modal, year: int, month: int) -> None:
    """カレンダーが目的の年月を表示するように < > ナビ。最大24回まで。"""
    target = f"{year}年{month}月"
    for _ in range(24):
        # カレンダーヘッダ（"2026年 5月" の表示）に近いテキスト
        header = modal.locator('text=/\\d{4}\\s*年\\s*\\d{1,2}\\s*月/').first
        try:
            header_text = header.inner_text(timeout=2000)
        except Exception:
            return  # ヘッダなし→操作スキップ
        # 半角化
        normalized = header_text.replace(" ", "").replace("　", "")
        if f"{year}年{month}月" in normalized:
            return
        # 目的が現在より過去 → ←、未来 → →
        m = re.search(r"(\d{4})年\s*(\d{1,2})月", header_text)
        if not m:
            return
        cur_y, cur_m = int(m.group(1)), int(m.group(2))
        if (year, month) < (cur_y, cur_m):
            modal.locator('button[aria-label*="prev" i], button[aria-label*="前" i]').first.click()
        else:
            modal.locator('button[aria-label*="next" i], button[aria-label*="次" i]').first.click()
        time.sleep(0.2)


def _click_calendar_day(modal, day: int) -> None:
    """カレンダー内の日付セルをクリック。前月/翌月の同番号を避けるため厳格マッチ。"""
    # 数字だけの role=gridcell / button をクリック
    cells = modal.locator(f'button:text-is("{day}"), [role="gridcell"]:text-is("{day}")')
    count = cells.count()
    if count == 0:
        raise RuntimeError(f"カレンダー日付セル {day} が見つかりません")
    # 当月セルは「現在月のセル」のみclickableなはず。複数ヒットなら最初を試行
    for i in range(count):
        try:
            cells.nth(i).click(timeout=2000)
            return
        except Exception:
            continue
    raise RuntimeError(f"カレンダー日付セル {day} がクリックできません")


def _trigger_download(page, output_path: str) -> str:
    """モーダル内「ダウンロード」ボタンを押下し、Excelを保存。"""
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    modal = page.locator('div[role="dialog"], [class*="modal" i]').last
    dl_button = modal.get_by_role("button", name=re.compile(r"^ダウンロード"))
    with page.expect_download(timeout=60000) as dl_info:
        dl_button.click()
    download = dl_info.value
    download.save_as(output_path)
    return output_path


def download_month_excel(year: int, month: int, output_path: str,
                          email: Optional[str] = None,
                          password: Optional[str] = None,
                          headless: bool = True) -> str:
    """指定年月の就業予定表Excelをダウンロード。output_path に保存し、そのパスを返す。"""
    from playwright.sync_api import sync_playwright

    email = email or os.environ.get("TIMEE_EMAIL", "")
    password = password or os.environ.get("TIMEE_PASSWORD", "")
    if not email or not password:
        raise RuntimeError("TIMEE_EMAIL / TIMEE_PASSWORD が未設定です")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(accept_downloads=True, locale="ja-JP")
        page = context.new_page()
        page.set_default_timeout(DEFAULT_TIMEOUT_MS)
        try:
            _login(page, email, password)
            _open_period_modal(page)
            _select_period(page, year, month)
            return _trigger_download(page, output_path)
        except Exception:
            _dump_failure(page, f"{year}_{month:02d}")
            raise
        finally:
            context.close()
            browser.close()


# ----------------------------------------------------------------------
# Excelパース
# ----------------------------------------------------------------------
def parse_excel_records(path: str, default_year: int | None = None,
                        default_month: int | None = None) -> list[dict]:
    """
    Excelの「全ての雛形の予定表」シートからレコードを抽出。
    返り値はワーカー単位×就業日の辞書リスト。
    default_year/month: ファイル名から年月が分かる場合に渡す。
                       「就業日」が "05月08日" 形式かつ前回勤務日が空のワーカー(初稼働)
                       でも正しく YYYY-MM-DD に正規化するために必須。
    """
    df = pd.read_excel(path, sheet_name="全ての雛形の予定表")
    # 先頭の空白列をdrop
    df = df.dropna(axis=1, how="all")
    df.columns = [str(c).strip() for c in df.columns]

    # default_year未指定なら、シート内の前回勤務日のうち最頻の年から推測
    fallback_year = default_year
    if fallback_year is None:
        years = []
        for v in df.get("前回勤務日", []):
            if isinstance(v, str):
                m = re.match(r"(\d{4})", v)
                if m:
                    years.append(int(m.group(1)))
            elif hasattr(v, "year"):
                years.append(v.year)
        if years:
            from collections import Counter
            fallback_year = Counter(years).most_common(1)[0][0]

    def _normalize_date(row) -> str:
        ts = row.get("就業日", "")
        # datetime/pandas Timestamp はそのまま
        if hasattr(ts, "strftime"):
            return ts.strftime("%Y-%m-%d")
        if isinstance(ts, str):
            m = re.match(r"(\d{1,2})月(\d{1,2})日", ts)
            if m:
                mm, dd = int(m.group(1)), int(m.group(2))
                # 1. 同行の「前回勤務日」から年を取得（最も信頼できる）
                prev = row.get("前回勤務日", "")
                if isinstance(prev, str):
                    yr = re.match(r"(\d{4})", prev)
                    if yr:
                        return f"{yr.group(1)}-{mm:02d}-{dd:02d}"
                elif hasattr(prev, "year"):
                    return f"{prev.year}-{mm:02d}-{dd:02d}"
                # 2. 引数の default_year を使う（新規ワーカーは前回勤務日が空）
                if fallback_year is not None:
                    return f"{fallback_year}-{mm:02d}-{dd:02d}"
        return str(ts)

    records = []
    for _, row in df.iterrows():
        name = str(row.get("氏名", "")).strip()
        kana = str(row.get("氏名(カナ)", "")).strip()
        if not name or not kana:
            continue
        records.append({
            "就業日": _normalize_date(row),
            "氏名": name,
            "カナ": kana,
            "性別": str(row.get("性別", "")).strip(),
            "年齢": int(row["年齢"]) if pd.notna(row.get("年齢")) else None,
            "求人タイトル": str(row.get("ひな形の求人タイトル", "")).strip(),
            "開始時間": str(row.get("開始時間", "")).strip(),
            "終了時間": str(row.get("終了時間", "")).strip(),
            "出勤回数": int(row["出勤回数"]) if pd.notna(row.get("出勤回数")) else 0,
            "前回勤務日": str(row.get("前回勤務日", "")).strip(),
            "バッジ": str(row.get("バッジ", "")).strip() if pd.notna(row.get("バッジ")) else "",
            "グループ": str(row.get("グループ", "")).strip() if pd.notna(row.get("グループ")) else "",
            "管理用ラベル": str(row.get("管理用ラベル", "")).strip(),
        })
    return records


# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------
def _cli():
    today = date.today()
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, default=today.year)
    parser.add_argument("--month", type=int, default=today.month)
    parser.add_argument("--output", default=None)
    parser.add_argument("--no-headless", action="store_true")
    args = parser.parse_args()

    output = args.output or f"./tmp/timee_{args.year}_{args.month:02d}.xlsx"
    path = download_month_excel(args.year, args.month, output, headless=not args.no_headless)
    print(f"Downloaded: {path}")
    records = parse_excel_records(path)
    print(f"Records: {len(records)}")


if __name__ == "__main__":
    _cli()
