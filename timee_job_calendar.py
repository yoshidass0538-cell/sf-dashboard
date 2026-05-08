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
    # まずクライアントトップに行ってからナビをクリック（実績パターン）
    try:
        page.goto(f"https://app-new.taimee.co.jp/clients/{CLIENT_ID}/", wait_until="domcontentloaded")
        # ナビ要素のレンダリング待ち
        page.wait_for_timeout(800)
        # 「求人一覧」リンクをクリック（role=link, button, テキストの順で試す）
        clicked = False
        for getter_name, getter in [
            ("link-strict", lambda: page.get_by_role("link", name="求人一覧").first),
            ("link-regex", lambda: page.get_by_role("link", name=re.compile(r"求人一覧")).first),
            ("button-regex", lambda: page.get_by_role("button", name=re.compile(r"求人一覧")).first),
            ("text", lambda: page.get_by_text("求人一覧").first),
        ]:
            try:
                el = getter()
                el.click(timeout=5000)
                page.wait_for_load_state("domcontentloaded")
                clicked = True
                print(f"[stage] _navigate_to_jobs_calendar clicked via {getter_name} -> {page.url}", flush=True)
                break
            except Exception as e:
                print(f"[stage] _navigate_to_jobs_calendar {getter_name} failed: {e}", flush=True)
        if not clicked:
            print("[stage] _navigate_to_jobs_calendar: could not click 求人一覧 nav", flush=True)
            _dump(page, "nav_fail")
    except Exception as e:
        print(f"[stage] _navigate_to_jobs_calendar nav exception: {e}", flush=True)
        _dump(page, "nav_exception")

    # Reactレンダリング・カレンダー描画待ち
    page.wait_for_timeout(1500)
    print(f"[stage] _navigate_to_jobs_calendar landed url={page.url}", flush=True)
    # カレンダー領域が描画されるまで待つ: <time datetime="YYYY-MM-DD"> が現れたらOK
    try:
        page.wait_for_selector('time[datetime]', timeout=15000, state="attached")
        print("[stage] _navigate_to_jobs_calendar: calendar rendered (time[datetime] found)", flush=True)
    except Exception:
        print("[stage] _navigate_to_jobs_calendar: time[datetime] NOT detected within 15s, dumping", flush=True)
        _dump(page, "no_time_elem")


def _navigate_to_month(page, year: int, month: int) -> None:
    """カレンダーの表示月を target に合わせる。

    実DOM:
      - 月ヘッダ: <div class="css-..."> 「2026年5月」</div>
      - 矢印: <button><span aria-label="前の月">arrow_back_ios</span></button>
              <button><span aria-label="次の月">arrow_forward_ios</span></button>
    """
    target_text = f"{year}年{month}月"
    print(f"[stage] _navigate_to_month target={target_text} url={page.url}", flush=True)

    def _read_heading() -> str:
        """body内テキストから 'YYYY年M月' (日が後続しない) を抽出"""
        try:
            res = page.evaluate(
                r"""
                () => {
                  // 候補: 子供のいない要素 or テキスト自体が短い要素
                  const re = /^(\d{4})\s*年\s*(\d{1,2})\s*月\s*$/;
                  const all = Array.from(document.querySelectorAll('div, span, h1, h2, h3, h4, p'));
                  for (const el of all) {
                    const t = (el.textContent || '').trim();
                    if (t.length > 12) continue;
                    if (re.test(t)) return t;
                  }
                  // 緩く: 含まれていれば
                  const m = (document.body.innerText || '').match(/(\d{4})\s*年\s*(\d{1,2})\s*月(?!\s*\d)/);
                  return m ? m[0] : '';
                }
                """
            )
            return (res or "").strip()
        except Exception:
            return ""

    for _step in range(24):
        heading = _read_heading()
        print(f"[stage] _navigate_to_month current heading='{heading}'", flush=True)
        if target_text == heading.strip() or (heading and target_text == heading.replace(" ", "")):
            return
        # 進む方向判定
        m = re.search(r"(\d{4})\s*年\s*(\d{1,2})\s*月", heading)
        forward = True
        if m:
            cy, cm = int(m.group(1)), int(m.group(2))
            forward = (cy, cm) < (year, month)

        # 実DOM: <button><span aria-label="次の月">...</span></button>
        if forward:
            arrow_locators = [
                'xpath=//button[.//*[@aria-label="次の月"]]',
                'xpath=//button[.//*[contains(@aria-label, "次")]]',
                'xpath=//*[@aria-label="次の月"]/ancestor-or-self::button[1]',
            ]
        else:
            arrow_locators = [
                'xpath=//button[.//*[@aria-label="前の月"]]',
                'xpath=//button[.//*[contains(@aria-label, "前")]]',
                'xpath=//*[@aria-label="前の月"]/ancestor-or-self::button[1]',
            ]
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
            print(f"[stage] _navigate_to_month: arrow not found (forward={forward})", flush=True)
            return


# ---------------------------------------------------------------- 抽出
_EXTRACTOR_JS = r"""
() => {
  // タイミー求人カレンダーの実DOM:
  //   <td>
  //     <time datetime="2026-05-08" aria-label="5/8">8</time>
  //     <ul>
  //       <li>
  //         <span><span>10:00~</span><span>19:00</span></span>
  //         <span><img alt="状態:稼働終了" />3/3</span>
  //       </li>
  //       ...
  //     </ul>
  //   </td>
  const out = [];
  const times = document.querySelectorAll('time[datetime]');
  times.forEach(t => {
    const dateAttr = t.getAttribute('datetime') || '';
    if (!/^\d{4}-\d{2}-\d{2}$/.test(dateAttr)) return;

    // 日付セルコンテナ: 親<td>を探し、なければ <ul> を内包する祖先を辿る
    let cell = t.closest('td');
    if (!cell) {
      let node = t.parentElement;
      while (node && !node.querySelector('ul')) node = node.parentElement;
      cell = node;
    }
    if (!cell) return;

    const items = cell.querySelectorAll('li');
    items.forEach(li => {
      const text = (li.textContent || '').replace(/\s+/g, '').trim();
      const tm = text.match(/(\d{1,2}:\d{2})[～~\-](\d{1,2}:\d{2})/);
      const nm = text.match(/(\d+)\/(\d+)/);
      if (!tm || !nm) return;
      const img = li.querySelector('img[alt]');
      const statusAlt = img ? (img.getAttribute('alt') || '') : '';
      // 状態を分類
      let status = 'unknown';
      if (/確定|稼働終了/.test(statusAlt)) status = 'confirmed';
      else if (/求人中/.test(statusAlt)) status = 'recruiting';
      else if (/不足|末/.test(statusAlt)) status = 'shortage';
      out.push({
        date_attr: dateAttr,
        start: tm[1],
        end: tm[2],
        matched: parseInt(nm[1], 10),
        required: parseInt(nm[2], 10),
        status: status,
        status_alt: statusAlt,
        text: text.slice(0, 120),
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

    target_prefix = f"{year:04d}-{month:02d}"
    out: List[Dict] = []
    for r in rows:
        date_attr = r.get("date_attr", "")
        # ターゲット月のレコードに絞る（前後月の余白セルを除外）
        if not date_attr.startswith(target_prefix):
            continue
        out.append({
            "日付": date_attr,
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
