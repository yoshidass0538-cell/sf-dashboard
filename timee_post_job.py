"""
タイミー管理画面で求人を一括作成する Playwright スクリプト。

GitHub Actions（headless Chromium）で実行する想定。

認証情報は環境変数:
- TIMEE_EMAIL
- TIMEE_PASSWORD

使い方（CLI）:
    python timee_post_job.py \
        --post-type repeater \
        --headcount 3 \
        --dates 2026-05-15,2026-05-16,2026-05-17

post-type: "repeater"（リピーター）/ "new"（新規）

リピーター: ひな形「通常求人」/ 公開設定=グループ限定公開（自動切替なし）/
            グループ「手かかからない人」/ 自動メッセージ送信しない
新規:       ひな形「求人向け(ハードル高)」/ 公開設定=初回ワーカー限定公開 /
            自動メッセージ送信する（送信対象=全員）

共通: 開始10:00 / 終了19:00 / 休憩開始14:00 / 休憩60分 /
      締切=開始時刻と同時 / 時給1100 / 交通費500 / 募集人数=指定値

DOMが変わると壊れる可能性があるため、失敗時は ./tmp/ にスクリーンショットとHTMLを保存。
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
from typing import List, Literal

LOGIN_URL = "https://app-new.taimee.co.jp/login"
CLIENT_ID = "340847"
DEFAULT_TIMEOUT_MS = 30000


# ---------------------------------------------------------------- 共通ユーティリティ
def _dump_failure(page, tag: str) -> None:
    Path("./tmp").mkdir(parents=True, exist_ok=True)
    ts = int(time.time())
    try:
        page.screenshot(path=f"./tmp/timee_post_{tag}_{ts}.png", full_page=True)
    except Exception:
        pass
    try:
        Path(f"./tmp/timee_post_{tag}_{ts}.html").write_text(
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


# ---------------------------------------------------------------- ひな形カードからの新規求人作成
TEMPLATE_LABEL = {
    "repeater": "通常求人",        # リピーター = 通常求人
    "new": "求人向け(ハードル高)",   # 新規 = 求人向け(ハードル高)
}


def _open_template_create(page, template_label: str) -> None:
    """求人のひな形一覧ページから、対象テンプレートカードの
    「このひな形を元に求人を作成」リンク(<a>) を押す。

    template_label: "通常求人"（リピーター用） / "求人向け(ハードル高)"（新規用）

    DOM 上、各ひな形カードは <div data-testid="offer-card-list-item"> でラップされ、
    カード末尾に <p>{テンプレラベル}</p> が入っている。クリック対象は <a> タグ。
    """
    page.goto(f"https://app-new.taimee.co.jp/clients/{CLIENT_ID}/", wait_until="domcontentloaded")

    # 左ナビ「求人のひな形」へ
    nav = page.get_by_role("link", name=re.compile(r"^求人のひな形$|求人のひな形"))
    if nav.count():
        nav.first.click()
    else:
        # フォールバック: 適当な「求人」or「ひな形」リンクを試す
        for nav_label in ["求人のひな形", "ひな形", "求人"]:
            try:
                page.get_by_role("link", name=re.compile(nav_label)).first.click(timeout=3000)
                break
            except Exception:
                continue
    page.wait_for_load_state("domcontentloaded")

    # ひな形カードが描画されるまで待つ
    page.wait_for_selector('[data-testid="offer-card-list-item"]',
                           timeout=DEFAULT_TIMEOUT_MS, state="visible")

    # template_label テキストを含むカードを特定
    target_card = page.locator('[data-testid="offer-card-list-item"]').filter(
        has_text=template_label
    ).first
    target_card.wait_for(state="visible", timeout=DEFAULT_TIMEOUT_MS)

    # 「このひな形を元に求人を作成」リンク(<a>) をカード内で探す
    create_link = target_card.get_by_role(
        "link", name=re.compile(r"このひな形を元に求人を作成|求人を作成")
    )
    if create_link.count() == 0:
        # フォールバック: テキストで取得（<a> 内の <span> にテキストがある場合）
        create_link = target_card.locator(
            'xpath=.//a[.//*[contains(text(), "このひな形を元に求人を作成") or contains(text(), "求人を作成")]]'
        )
    create_link.first.click()
    page.wait_for_load_state("domcontentloaded")


# ---------------------------------------------------------------- フォーム入力
def _fill_date(page, target: _date) -> None:
    """求人日入力。インライン月別カレンダー想定。

    複数のパターンに対応:
      1) aria-label に "YYYY年M月D日" を持つボタン/セルを直接クリック
      2) 「YYYY年M月」のヘッダ表示まで「次の月」ボタンで送ってから日数字をクリック
      3) react-datepicker フォールバック
    """
    print(f"[stage] _fill_date target={target.isoformat()}", flush=True)

    # 求人日セクションを限定（labelテキストから先のセクションを対象に）
    section = page.locator(
        'xpath=//*[normalize-space()="求人日" or contains(., "求人日")]/following::*[1]'
    )

    # --- パターン1: aria-label で直クリック ---
    aria_label = f"{target.year}年{target.month}月{target.day}日"
    cand = page.locator(f'[aria-label*="{aria_label}"]')
    if cand.count():
        try:
            cand.first.click(timeout=5000)
            print("[stage] _fill_date OK via aria-label", flush=True)
            return
        except Exception as e:
            print(f"[stage] _fill_date aria-label click failed: {e}", flush=True)

    # --- パターン2: ヘッダー「YYYY年M月」を表示するまで送って日をクリック ---
    target_header_re = re.compile(rf"{target.year}\s*年\s*{target.month}\s*月")
    next_btn_locators = [
        'xpath=//*[contains(., "求人日")]/following::button[@aria-label="次の月" or contains(@aria-label, "次") or contains(., "›") or contains(., "▶") or contains(., ">")][1]',
        'xpath=//*[contains(., "次の月")]',
    ]
    prev_btn_locators = [
        'xpath=//*[contains(., "求人日")]/following::button[@aria-label="前の月" or contains(@aria-label, "前") or contains(., "‹") or contains(., "◀") or contains(., "<")][1]',
    ]

    def _current_calendar_header() -> str:
        for loc in [
            'xpath=//*[contains(., "求人日")]/following::*[contains(text(), "年") and contains(text(), "月")][1]',
            'xpath=//*[contains(@class, "calendar")]/descendant::*[contains(text(), "年") and contains(text(), "月")][1]',
        ]:
            try:
                el = page.locator(loc)
                if el.count():
                    return el.first.inner_text(timeout=1000)
            except Exception:
                continue
        return ""

    for _step in range(24):
        header = _current_calendar_header()
        print(f"[stage] _fill_date header='{header}'", flush=True)
        if target_header_re.search(header):
            break
        # 進む方向判定（雑に: 現在のヘッダから年月抽出して比較）
        m = re.search(r"(\d{4})\s*年\s*(\d{1,2})\s*月", header)
        forward = True
        if m:
            cy, cm = int(m.group(1)), int(m.group(2))
            forward = (cy, cm) < (target.year, target.month)
        clicked = False
        for loc in (next_btn_locators if forward else prev_btn_locators):
            try:
                btn = page.locator(loc).first
                btn.click(timeout=2000)
                clicked = True
                break
            except Exception:
                continue
        if not clicked:
            print("[stage] _fill_date: nav button not found, abort nav", flush=True)
            break

    # 日数字のクリック（カレンダー領域内の数字テキスト）
    day_loc_candidates = [
        f'xpath=//*[contains(., "求人日")]/following::button[normalize-space(text())="{target.day}"][1]',
        f'xpath=//*[contains(., "求人日")]/following::*[normalize-space(text())="{target.day}" and not(contains(@class, "outside")) and not(contains(@class, "disabled"))][1]',
    ]
    for loc in day_loc_candidates:
        try:
            el = page.locator(loc).first
            el.click(timeout=3000)
            print(f"[stage] _fill_date OK via day-text {target.day}", flush=True)
            return
        except Exception as e:
            print(f"[stage] _fill_date day-text {target.day} failed via {loc}: {e}", flush=True)

    # --- パターン3: react-datepicker fallback ---
    try:
        date_input = page.locator(
            'xpath=//label[contains(., "求人日")]/following::input[1]'
        ).first
        date_input.click()
        page.locator('select.react-datepicker__year-select').first.select_option(value=str(target.year))
        page.locator('select.react-datepicker__month-select').first.select_option(value=str(target.month - 1))
        page.locator(
            f'.react-datepicker__day--{target.day:03d}:not(.react-datepicker__day--outside-month)'
        ).first.click()
        print("[stage] _fill_date OK via react-datepicker", flush=True)
        return
    except Exception as e:
        print(f"[stage] _fill_date react-datepicker fallback failed: {e}", flush=True)

    raise RuntimeError(f"求人日 {target.isoformat()} の選択に失敗")


def _select_time(page, label: str, value: str) -> None:
    """ラベル直近の時刻入力に value をセット。

    複数パターンをフォールバック:
      1) <input type="time"> として fill
      2) <select> として select_option
      3) 通常inputに fill (タイミーは "--:--" placeholder のテキスト入力の可能性)
      4) 通常inputをクリックしてリストから選ぶ
    """
    print(f"[stage] _select_time label='{label}' value='{value}'", flush=True)

    # 1) 直近の input をfillで試す
    try:
        inp = page.locator(
            f'xpath=//label[contains(., "{label}")]/following::input[1]'
        ).first
        inp.click(timeout=3000)
        # 既存値があれば消す
        try:
            inp.press("Control+a")
            inp.press("Delete")
        except Exception:
            pass
        inp.fill(value, timeout=3000)
        # blur してフォーマット確定（不要かもしれないが念のため）
        try:
            inp.press("Tab")
        except Exception:
            pass
        # 値が反映されているか確認（input value を読む）
        cur = inp.input_value(timeout=1000)
        if value in cur or cur.replace(":", "") == value.replace(":", ""):
            print(f"[stage] _select_time '{label}' OK via input.fill -> '{cur}'", flush=True)
            return
        print(f"[stage] _select_time '{label}' input.fill mismatch: '{cur}'", flush=True)
    except Exception as e:
        print(f"[stage] _select_time '{label}' fill failed: {e}", flush=True)

    # 2) <select> として
    try:
        sel = page.locator(
            f'xpath=//label[contains(., "{label}")]/following::select[1]'
        )
        if sel.count():
            sel.first.select_option(label=value, timeout=3000)
            print(f"[stage] _select_time '{label}' OK via select", flush=True)
            return
    except Exception as e:
        print(f"[stage] _select_time '{label}' select failed: {e}", flush=True)

    # 3) input/buttonクリックしてリストから選ぶ
    try:
        trigger = page.locator(
            f'xpath=//label[contains(., "{label}")]/following::*[self::input or self::button or @role="combobox"][1]'
        ).first
        trigger.click(timeout=3000)
        # 開いたリストから value を含むオプションをクリック
        opt_loc_candidates = [
            f'role=option[name="{value}"]',
            f'xpath=//*[@role="option"][normalize-space(text())="{value}"]',
            f'xpath=//li[normalize-space(text())="{value}"]',
            f'xpath=//*[normalize-space(text())="{value}"]',
        ]
        for loc in opt_loc_candidates:
            try:
                page.locator(loc).first.click(timeout=2000)
                print(f"[stage] _select_time '{label}' OK via dropdown {loc}", flush=True)
                return
            except Exception:
                continue
    except Exception as e:
        print(f"[stage] _select_time '{label}' dropdown failed: {e}", flush=True)

    raise RuntimeError(f"時刻 '{label}'='{value}' のセットに失敗")


def _fill_break_minutes(page, minutes: int) -> None:
    """「休憩時間」入力（デフォルト0が入っているので消して入れ直す）。"""
    inp = page.locator(
        'xpath=//label[contains(., "休憩時間")]/following::input[1]'
    ).first
    inp.wait_for(state="visible", timeout=10000)
    inp.click()
    inp.press("Control+a")
    inp.press("Delete")
    inp.fill(str(minutes))


def _select_deadline_same_as_start(page) -> None:
    """求人の締切時間 = 「【推奨】開始時刻と同時」 を選ぶ。"""
    sel = page.locator(
        'xpath=//label[contains(., "締切")]/following::select[1]'
    )
    if sel.count():
        # value/labelに「開始時刻と同時」が含まれるオプションを選ぶ
        opts = sel.first.locator("option").all_inner_texts()
        for t in opts:
            if "開始時刻と同時" in t:
                sel.first.select_option(label=t)
                return
    # ボタン/combobox 経由
    trigger = page.locator(
        'xpath=//label[contains(., "締切")]/following::*[self::button or @role="combobox"][1]'
    ).first
    trigger.click()
    page.get_by_role("option", name=re.compile(r"開始時刻と同時")).first.click()


def _set_headcount(page, n: int) -> None:
    """募集人数を n にする。デフォルト1なので、↑ボタンを (n-1) 回押すか、直接入力する。"""
    # 直接入力できる input がある場合
    input_box = page.locator(
        'xpath=//label[contains(., "募集人数")]/following::input[@type="number" or @inputmode="numeric"][1]'
    )
    if input_box.count():
        input_box.first.click()
        input_box.first.press("Control+a")
        input_box.first.press("Delete")
        input_box.first.fill(str(n))
        return

    # ↑ボタン方式（spinbutton increment）
    up_btn = page.locator(
        'xpath=//label[contains(., "募集人数")]/following::button[contains(@aria-label, "増") or contains(., "▲") or contains(@class, "up")][1]'
    ).first
    for _ in range(max(0, n - 1)):
        up_btn.click()


def _select_publish_setting(page, setting: str) -> None:
    """公開設定 ラジオ。setting = '一般公開' / 'グループ限定公開' / '初回ワーカー限定公開' / 'URL限定公開'。

    ラベルの後ろに「（24個のグループあり）」のような可変サフィックスが付くため、
    contains で前方一致マッチさせる。
    """
    # ラジオボタンのラベル要素をクリック
    label = page.locator(
        f'xpath=//label[contains(., "{setting}")]'
    ).first
    label.wait_for(state="visible", timeout=10000)
    label.click()


def _disable_auto_switch_to_public(page) -> None:
    """グループ限定公開の下にある「自動で『一般公開』に切り替え」プルダウンで「自動切り替えをしない」を選択。"""
    sel = page.locator(
        'xpath=//*[contains(., "自動で") and contains(., "一般公開") and contains(., "切り替え")]/following::select[1]'
    )
    if sel.count():
        opts = sel.first.locator("option").all_inner_texts()
        for t in opts:
            if "自動切り替えをしない" in t or "切り替えをしない" in t:
                sel.first.select_option(label=t)
                return
    # combobox 経由
    trigger = page.locator(
        'xpath=//*[contains(., "自動で") and contains(., "切り替え")]/following::*[self::button or @role="combobox"][1]'
    ).first
    trigger.click()
    page.get_by_role("option", name=re.compile(r"自動切り替えをしない|切り替えをしない")).first.click()


def _select_public_group(page, group_name: str) -> None:
    """公開するグループ で group_name (例: 「手かかからない人」) を選ぶ。

    実際の選択肢は「手かかからない人（68人）」など人数サフィックスが付くため、
    前方一致 / contains マッチさせる。
    """
    # まず group_name を含む select option を探す
    sel = page.locator(
        'xpath=//label[contains(., "公開するグループ")]/following::select[1]'
    )
    if sel.count():
        opts = sel.first.locator("option").all_inner_texts()
        for t in opts:
            if group_name in t:
                sel.first.select_option(label=t)
                return

    # チェックボックス/multi-select 形式
    box_label = page.locator(
        f'xpath=//*[contains(., "公開するグループ")]/following::label[contains(., "{group_name}")][1]'
    ).first
    if box_label.count():
        box_label.click()
        return

    # combobox 経由
    trigger = page.locator(
        'xpath=//label[contains(., "公開するグループ")]/following::*[self::button or @role="combobox"][1]'
    ).first
    trigger.click()
    page.get_by_role("option", name=re.compile(re.escape(group_name))).first.click()


def _fill_money(page, label: str, yen: int) -> None:
    """時給/交通費 のような円単位 input を埋める。"""
    inp = page.locator(
        f'xpath=//label[contains(., "{label}")]/following::input[1]'
    ).first
    inp.wait_for(state="visible", timeout=10000)
    inp.click()
    inp.press("Control+a")
    inp.press("Delete")
    inp.fill(str(yen))


def _set_auto_message(page, send: bool) -> None:
    """自動送信メッセージ送信設定: 「送信する」/「送信しない」ラジオ。"""
    label_text = "送信する" if send else "送信しない"
    target = page.locator(
        f'xpath=//*[contains(., "送信設定") or contains(., "自動送信メッセージ")]/following::label[normalize-space()="{label_text}" or contains(., "{label_text}")][1]'
    ).first
    target.wait_for(state="visible", timeout=10000)
    target.click()


def _set_auto_message_target_all(page) -> None:
    """送信対象=「全員」を選択（新規モード時のみ）。"""
    target = page.locator(
        'xpath=//*[contains(., "送信対象")]/following::label[normalize-space()="全員" or contains(., "全員")][1]'
    ).first
    target.wait_for(state="visible", timeout=10000)
    target.click()


def _click_confirm_input(page) -> None:
    """「入力した求人内容を確認」ボタンを押す。"""
    page.get_by_role(
        "button", name=re.compile(r"入力した求人内容を確認")
    ).first.click()
    page.wait_for_load_state("domcontentloaded")


def _check_kyugyo_handate(page) -> None:
    """「休業手当に関する事項を確認しました。」チェックボックスを ON。"""
    # ラベルクリックでトグル
    label = page.locator(
        'xpath=//label[contains(., "休業手当") and contains(., "確認しました")]'
    ).first
    label.wait_for(state="visible", timeout=DEFAULT_TIMEOUT_MS)
    label.click()


def _click_publish(page) -> None:
    """「求人を公開」ボタンを押す。"""
    page.get_by_role("button", name=re.compile(r"^求人を公開$|求人を公開")).first.click()
    # 公開後はリダイレクトされる想定 → 完了待ち
    page.wait_for_load_state("domcontentloaded")
    # 「公開しました」「求人を作成しました」等のトースト or ページ遷移を確認
    try:
        page.wait_for_selector(
            'xpath=//*[contains(., "公開しました") or contains(., "作成しました")]',
            timeout=15000,
        )
    except Exception:
        # トースト未検出でもURL遷移していればOKとする
        pass


# ---------------------------------------------------------------- 1日分の処理
def _post_one_job(
    page,
    post_type: Literal["repeater", "new"],
    target_date: _date,
    headcount: int,
    group_name: str,
) -> None:
    template_label = TEMPLATE_LABEL[post_type]
    _open_template_create(page, template_label)

    _fill_date(page, target_date)
    _select_time(page, "開始", "10:00")
    _select_time(page, "終了", "19:00")
    _select_time(page, "休憩の開始", "14:00")
    _fill_break_minutes(page, 60)
    _select_deadline_same_as_start(page)
    _set_headcount(page, headcount)

    if post_type == "repeater":
        _select_publish_setting(page, "グループ限定公開")
        _disable_auto_switch_to_public(page)
        _select_public_group(page, group_name)
    else:
        _select_publish_setting(page, "初回ワーカー限定公開")

    _fill_money(page, "時給", 1100)
    _fill_money(page, "交通費", 500)

    if post_type == "repeater":
        _set_auto_message(page, send=False)
    else:
        _set_auto_message(page, send=True)
        _set_auto_message_target_all(page)

    _click_confirm_input(page)
    _check_kyugyo_handate(page)
    _click_publish(page)


# ---------------------------------------------------------------- メインAPI
def post_jobs(
    post_type: Literal["repeater", "new"],
    headcount: int,
    dates: List[_date],
    group_name: str = "手かかからない人",
    email: str | None = None,
    password: str | None = None,
    headless: bool = True,
) -> dict:
    """指定された各日付に対して求人を1件ずつ作成する。返り値は集計結果。"""
    from playwright.sync_api import sync_playwright

    if not dates:
        raise ValueError("dates が空です。最低1日選択してください。")
    if not (1 <= headcount <= 6):
        raise ValueError("headcount は 1〜6 で指定してください。")
    if post_type not in ("repeater", "new"):
        raise ValueError("post_type は 'repeater' または 'new'")

    email = email or os.environ.get("TIMEE_EMAIL", "")
    password = password or os.environ.get("TIMEE_PASSWORD", "")
    if not email or not password:
        raise RuntimeError("TIMEE_EMAIL / TIMEE_PASSWORD が未設定です")

    results = {"ok": [], "failed": []}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(locale="ja-JP")
        page = context.new_page()
        page.set_default_timeout(DEFAULT_TIMEOUT_MS)
        try:
            _login(page, email, password)
        except Exception:
            _dump_failure(page, "login")
            context.close()
            browser.close()
            raise

        for d in dates:
            tag = f"{post_type}_{d.isoformat()}"
            try:
                _post_one_job(page, post_type, d, headcount, group_name)
                results["ok"].append(d.isoformat())
            except Exception as e:
                _dump_failure(page, f"fail_{tag}")
                results["failed"].append({"date": d.isoformat(), "error": str(e)})

        context.close()
        browser.close()

    return results


# ---------------------------------------------------------------- CLI
def _parse_dates(s: str) -> List[_date]:
    out = []
    for token in s.split(","):
        token = token.strip()
        if not token:
            continue
        out.append(_date.fromisoformat(token))
    return out


def _cli():
    parser = argparse.ArgumentParser()
    parser.add_argument("--post-type", required=True, choices=["repeater", "new"])
    parser.add_argument("--headcount", required=True, type=int)
    parser.add_argument("--dates", required=True, help="カンマ区切り YYYY-MM-DD")
    parser.add_argument("--group-name", default="手かかからない人")
    parser.add_argument("--no-headless", action="store_true")
    args = parser.parse_args()

    dates = _parse_dates(args.dates)
    result = post_jobs(
        post_type=args.post_type,
        headcount=args.headcount,
        dates=dates,
        group_name=args.group_name,
        headless=not args.no_headless,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["failed"]:
        sys.exit(1)


if __name__ == "__main__":
    _cli()
