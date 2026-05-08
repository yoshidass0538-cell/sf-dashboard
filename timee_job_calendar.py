"""
タイミー「求人一覧」カレンダーページをスクレイピング。

目的: 各日付の求人ブロックごとに (日付, 開始, 終了, 募集人数, マッチ数, ステータス)
を取得し、ボード側カレンダーで「10:00～19:00 N/M」を表示できるようにする。

GitHub Actions の timee_sync.yml に組み込んで5分おきに同期させる想定。

認証情報は環境変数:
- TIMEE_EMAIL
- TIMEE_PASSWORD

使い方（CLI / 単体テスト）:
    python timee_job_calendar.py --year 2026 --month 5

使い方（モジュール）:
    from timee_job_calendar import fetch_month_postings
    postings = fetch_month_postings(2026, 5)

DOM変更時は ./tmp/ にスクショ＋HTML を保存。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import date as _date
from pathlib import Path
from typing import List, Dict, Optional

LOGIN_URL = "https://app-new.taimee.co.jp/login"
CLIENT_ID = "340847"
DEFAULT_TIMEOUT_MS = 30000


# ---------------------------------------------------------------- 共通
def _dump(page, tag: str) -> None:
    Path("./tmp").mkdir(parents=True, exist_ok=True)
    ts = int(time.time())
    try:
        page.screenshot(path=f"./tmp/timee_jobcal_{tag}_{ts}.png", full_page=True)
    except Exception:
        pass
    try:
        Path(f"./tmp/timee_jobcal_{tag}_{ts}.html").write_text(
            page.content(), encoding="utf-8"
        )
    except Exception:
        pass


def _login(page, email: str, password: str) -> None:
    page.goto(LOGIN_URL, wait_until="domcontentloaded")
    email_input = page.locator('input[type="email"], input[name*="mail" i]').first
    email_input.wait_for(state="visible", timeout=DEFAULT_TIMEOUT_MS)
    email_input.fill(email)
    page.locator('input[type="password"]').first.fill(password)
    page.get_by_role("button", name=re.compile(r"ログイン")).click()
    page.wait_for_url(lambda url: "/login" not in url, timeout=DEFAULT_TIMEOUT_MS)


# ---------------------------------------------------------------- ナビゲーション
def _navigate_to_jobs_calendar(page) -> None:
    """左ナビ「求人一覧」をクリックして求人カレンダー画面へ。"""
    page.goto(f"https://app-new.taimee.co.jp/clients/{CLIENT_ID}/", wait_until="domcontentloaded")
    nav = page.get_by_role("link", name=re.compile(r"^求人一覧$|求人一覧"))
    if nav.count():
        nav.first.click()
    else:
        # フォールバック: 「求人」を含むリンク
        page.get_by_role("link", name=re.compile(r"求人")).first.click(timeout=5000)
    page.wait_for_load_state("domcontentloaded")
    # カレンダー描画待ち（年月ヘッダ or "+" の出現を待つ）
    try:
        page.wait_for_selector(
            'xpath=//*[contains(text(), "年") and contains(text(), "月")]',
            timeout=DEFAULT_TIMEOUT_MS,
        )
    except Exception:
        pass


def _navigate_to_month(page, year: int, month: int) -> None:
    """カレンダーの表示月を target に合わせる（◀ ▶ ボタンで移動）。"""
    target_text = f"{year}年{month}月"
    print(f"[stage] _navigate_to_month target={target_text}", flush=True)
    for _step in range(24):
        try:
            heading = page.locator(
                'xpath=//*[contains(text(), "年") and contains(text(), "月")][1]'
            ).first.inner_text(timeout=3000).strip()
        except Exception:
            heading = ""
        print(f"[stage] _navigate_to_month current heading='{heading}'", flush=True)
        if target_text in heading:
            return
        # 進む方向判定
        m = re.search(r"(\d{4})\s*年\s*(\d{1,2})\s*月", heading)
        forward = True
        if m:
            cy, cm = int(m.group(1)), int(m.group(2))
            forward = (cy, cm) < (year, month)

        # 矢印ボタン候補（aria-label / テキスト各種）
        arrow_locators = (
            [
                'xpath=//button[@aria-label="次の月" or contains(@aria-label, "次") or contains(., "›") or contains(., "▶") or contains(., ">")]',
            ]
            if forward
            else [
                'xpath=//button[@aria-label="前の月" or contains(@aria-label, "前") or contains(., "‹") or contains(., "◀") or contains(., "<")]',
            ]
        )
        clicked = False
        for loc in arrow_locators:
            try:
                btn = page.locator(loc).first
                btn.click(timeout=2000)
                clicked = True
                page.wait_for_timeout(400)
                break
            except Exception:
                continue
        if not clicked:
            print(f"[stage] _navigate_to_month: arrow not found", flush=True)
            return


# ---------------------------------------------------------------- 抽出
_EXTRACTOR_JS = r"""
() => {
  const out = [];
  const slotRe = /(\d{1,2}:\d{2})\s*[～~\-]\s*(\d{1,2}:\d{2}).*?(\d+)\s*\/\s*(\d+)/s;

  // 候補: 日付セル単位で走査。
  // タイミーの calendar セルは role="gridcell" を持つことが多いが念のため複数候補。
  let cells = document.querySelectorAll('[role="gridcell"]');
  if (!cells.length) cells = document.querySelectorAll('[data-date]');
  if (!cells.length) cells = document.querySelectorAll('[class*="day"][class*="cell"], [class*="DayCell"], [class*="CalendarCell"]');

  cells.forEach(cell => {
    // 日付
    let dateAttr = cell.getAttribute('data-date') || cell.getAttribute('aria-label') || '';
    // セル内の日付数字（先頭の <time> or 数字テキスト）を取得
    let dayNum = null;
    const timeEl = cell.querySelector('time[datetime]');
    if (timeEl) {
      const dt = timeEl.getAttribute('datetime');
      if (dt) dateAttr = dt;
      const t = timeEl.textContent && timeEl.textContent.match(/\d+/);
      if (t) dayNum = parseInt(t[0], 10);
    }
    if (!dayNum) {
      const m0 = cell.textContent.match(/^\s*(\d{1,2})/);
      if (m0) dayNum = parseInt(m0[1], 10);
    }

    // 求人ブロックを抽出: テキストに "HH:MM～HH:MM N/M" を含む子要素
    const slotEls = Array.from(cell.querySelectorAll('*')).filter(el => {
      if (!el.children || el.children.length > 12) return false;
      const t = el.textContent || '';
      return slotRe.test(t);
    });
    // 子孫を含むと重複するので「自身でも親でも親が同じパターンを持つ」要素を除く
    const leafs = slotEls.filter(el => {
      return !slotEls.some(other => other !== el && el.contains(other));
    });
    leafs.forEach(el => {
      const t = (el.textContent || '').replace(/\s+/g, ' ').trim();
      const m = t.match(slotRe);
      if (!m) return;
      const status =
        /確定/.test(t) ? 'confirmed'
        : /末|不足/.test(t) ? 'shortage'
        : /求人中/.test(t) ? 'recruiting'
        : 'unknown';
      out.push({
        date_attr: dateAttr,
        day: dayNum,
        start: m[1],
        end: m[2],
        matched: parseInt(m[3], 10),
        required: parseInt(m[4], 10),
        status: status,
        text: t.slice(0, 200),
      });
    });
  });

  return out;
}
"""


def _extract_postings(page, year: int, month: int) -> List[Dict]:
    """ページ上の求人カレンダーから求人ブロック一覧を抽出。"""
    rows = page.evaluate(_EXTRACTOR_JS) or []
    print(f"[stage] _extract_postings raw rows={len(rows)}", flush=True)

    out: List[Dict] = []
    for r in rows:
        day = r.get("day")
        if not day:
            # date_attr が "YYYY-MM-DD" 形式なら拾う
            date_attr = r.get("date_attr") or ""
            mm = re.search(r"(\d{4})-(\d{2})-(\d{2})", date_attr)
            if mm:
                date_str = f"{int(mm.group(1)):04d}-{int(mm.group(2)):02d}-{int(mm.group(3)):02d}"
            else:
                continue
        else:
            date_str = f"{year:04d}-{month:02d}-{int(day):02d}"
        out.append({
            "日付": date_str,
            "開始時間": r.get("start", ""),
            "終了時間": r.get("end", ""),
            "マッチ数": int(r.get("matched", 0)),
            "募集人数": int(r.get("required", 0)),
            "状態": r.get("status", "unknown"),
        })
    return out


# ---------------------------------------------------------------- メインAPI
def fetch_month_postings(
    year: int,
    month: int,
    email: Optional[str] = None,
    password: Optional[str] = None,
    headless: bool = True,
) -> List[Dict]:
    """指定年月の求人カレンダーから (日付, 開始, 終了, マッチ数, 募集人数, 状態) を返す。"""
    from playwright.sync_api import sync_playwright

    email = email or os.environ.get("TIMEE_EMAIL", "")
    password = password or os.environ.get("TIMEE_PASSWORD", "")
    if not email or not password:
        raise RuntimeError("TIMEE_EMAIL / TIMEE_PASSWORD が未設定です")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(locale="ja-JP")
        page = context.new_page()
        page.set_default_timeout(DEFAULT_TIMEOUT_MS)
        try:
            _login(page, email, password)
            _navigate_to_jobs_calendar(page)
            _navigate_to_month(page, year, month)
            # 描画完了の余裕
            page.wait_for_timeout(800)
            postings = _extract_postings(page, year, month)
            if not postings:
                # 1件も取れなかったらDOM構造が想定外の可能性 → ダンプ
                _dump(page, f"empty_{year}_{month:02d}")
            print(f"[stage] fetch_month_postings {year}-{month:02d} got {len(postings)}件", flush=True)
            return postings
        except Exception:
            _dump(page, f"err_{year}_{month:02d}")
            raise
        finally:
            context.close()
            browser.close()


# ---------------------------------------------------------------- CLI
def _cli():
    today = _date.today()
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, default=today.year)
    parser.add_argument("--month", type=int, default=today.month)
    parser.add_argument("--no-headless", action="store_true")
    args = parser.parse_args()
    postings = fetch_month_postings(args.year, args.month, headless=not args.no_headless)
    print(json.dumps(postings, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    _cli()
