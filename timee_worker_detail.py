"""
タイミー「ワーカー管理」配下の各ワーカー詳細ページから

  - 平均Good率（直近30回の評価）
  - 直前キャンセル率
  - 管理用メモ

を取得するスクリプト。

GitHub Actions の timee_sync.yml に組み込んで、
1回の同期につき最大 N 名分だけ間引き取得させる想定。

認証情報は環境変数:
- TIMEE_EMAIL
- TIMEE_PASSWORD

使い方（CLI / 単体テスト）:
    python timee_worker_detail.py --max 5

使い方（モジュール）:
    from timee_worker_detail import fetch_worker_details
    # targets: [(氏名, カナ), ...]
    detail_map = fetch_worker_details([("高崎 雅朗", "タカサキ マサアキ")])
    # detail_map: {"氏名|カナ": {"good_rate": "100%", "cancel_rate": "0%", "timee_memo": "..."}}

DOM変更時は ./tmp/ にスクショ＋HTML を保存。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

LOGIN_URL = "https://app-new.taimee.co.jp/login"
CLIENT_ID = "340847"
DEFAULT_TIMEOUT_MS = 30000


def _key(name: str, kana: str) -> str:
    """氏名+カナの正規化キー（空白除去）。timee_master_store と同じ仕様。"""
    n = (name or "").replace(" ", "").replace("　", "").strip()
    k = (kana or "").replace(" ", "").replace("　", "").strip()
    return f"{n}|{k}"


def _dump(page, tag: str) -> None:
    Path("./tmp").mkdir(parents=True, exist_ok=True)
    ts = int(time.time())
    try:
        page.screenshot(path=f"./tmp/timee_workerdtl_{tag}_{ts}.png", full_page=True)
    except Exception:
        pass
    try:
        Path(f"./tmp/timee_workerdtl_{tag}_{ts}.html").write_text(
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


# ---------------------------------------------------------------- ワーカー一覧→URL収集
_LIST_EXTRACTOR_JS = r"""
() => {
  // ワーカー一覧の行を収集。
  // ナビバーのリンクを除外するため、サイドバー(<nav>, [data-testid="sidebar"])配下は無視。
  const rows = [];
  // 除外領域
  const sidebar = document.querySelector('[data-testid="sidebar"], nav');
  function isInSidebar(el) {
    return sidebar && sidebar.contains(el);
  }

  // パターン1: <a href> でクライアント配下のIDっぽいリンク（サイドバー外）
  const links = Array.from(document.querySelectorAll('a[href]'));
  for (const a of links) {
    if (isInSidebar(a)) continue;
    const href = a.getAttribute('href') || '';
    if (!href || href.startsWith('#') || href.startsWith('javascript:')) continue;
    if (!/\/clients\/\d+\//.test(href)) continue;
    // /clients/{cid}/users (一覧URL自身) は除外。/users/{id} のようにIDっぽいパスを採用
    const path = href.split('?')[0].split('#')[0];
    const seg = path.split('/').filter(s => s.length > 0);
    // 最低 4 セグメント (clients, {cid}, {section}, {id}) 以上
    if (seg.length < 4) continue;
    const row = a.closest('tr, [role="row"], li, [class*="row"], [class*="Row"]') || a.parentElement;
    const text = (row && row.textContent || a.textContent || '').replace(/\s+/g, ' ').trim();
    rows.push({ href: href, text: text.slice(0, 300) });
  }

  // パターン2: <tr> や [role=row] 等で onClick 動作の行（hrefなし）→ 行テキストだけ収集
  if (rows.length === 0) {
    const trs = Array.from(document.querySelectorAll('tbody tr, [role="row"]'));
    for (const tr of trs) {
      if (isInSidebar(tr)) continue;
      const text = (tr.textContent || '').replace(/\s+/g, ' ').trim();
      if (!text) continue;
      // data-* 属性に ID が入っている可能性
      let dataId = '';
      const attrs = tr.attributes;
      for (let i = 0; i < attrs.length; i++) {
        const an = attrs[i].name;
        if (an.startsWith('data-') && /id|user|worker/i.test(an)) {
          dataId = attrs[i].value;
          break;
        }
      }
      rows.push({ href: dataId ? '#data:' + dataId : '#row', text: text.slice(0, 300) });
    }
  }
  return rows;
}
"""


def _collect_worker_urls(page) -> List[Dict]:
    """ワーカー管理画面（一覧）から (行テキスト → 詳細URL) を収集。

    タイミーのURL構造が事前に分からないため、ナビリンク「ワーカー管理」を
    クリックしてから、画面内の /clients/{id}/... へのリンクを全部拾う。
    """
    # ナビ「ワーカー管理」をクリック
    try:
        page.goto(f"https://app-new.taimee.co.jp/clients/{CLIENT_ID}/", wait_until="domcontentloaded")
        page.get_by_role("link", name=re.compile(r"^ワーカー管理$|ワーカー管理")).first.click(timeout=5000)
        page.wait_for_load_state("domcontentloaded")
        print(f"[stage] _collect_worker_urls navigated to: {page.url}", flush=True)
    except Exception as e:
        print(f"[stage] _collect_worker_urls nav failed: {e}", flush=True)
        _dump(page, "list_nav_fail")

    # 一覧描画待ち（行データのレンダリングを待つ）
    try:
        page.wait_for_function(
            r"""() => {
                // メインコンテンツ領域に <tr> や [role=row] が複数あればOK
                const rows = document.querySelectorAll('tbody tr, [role="row"]');
                return rows.length >= 3;
            }""",
            timeout=12000,
        )
    except Exception:
        pass
    page.wait_for_timeout(800)
    # 構造調査用に常にダンプ（成功時も）
    _dump(page, "list_inspect")

    out: List[Dict] = []
    seen = set()
    for _page_idx in range(50):
        rows = page.evaluate(_LIST_EXTRACTOR_JS) or []
        added = 0
        for r in rows:
            href = r.get("href")
            if not href or href in seen:
                continue
            seen.add(href)
            out.append(r)
            added += 1
        print(f"[stage] _collect_worker_urls page {_page_idx+1}: +{added} (total {len(out)}) url={page.url}", flush=True)
        # 初回ページのサンプルURLを最大3件出力（URL構造確認用）
        if _page_idx == 0:
            for s in out[:3]:
                print(f"[stage]   sample href={s.get('href')} text={s.get('text','')[:80]}", flush=True)
            if added == 0:
                _dump(page, f"list_empty_page{_page_idx+1}")

        # ページネーション: 複数パターンを試す
        clicked = False
        # 1) 矢印 / 次へボタン
        next_btn_locators = [
            'xpath=//button[normalize-space()="次へ" or @aria-label="次へ" or contains(@aria-label, "次のページ") or @aria-label="Next" or contains(@aria-label, "next")]',
            'xpath=//a[normalize-space()="次へ" or @aria-label="次へ" or @aria-label="Next" or contains(@aria-label, "next")]',
            # 矢印アイコン
            'xpath=//button[contains(., "›") or contains(., "▶") or contains(., "»")]',
            # rel=next
            'xpath=//a[@rel="next"]',
        ]
        for loc in next_btn_locators:
            try:
                btn = page.locator(loc).first
                if btn.count() == 0:
                    continue
                # disabled なら次ページなし
                try:
                    if not btn.is_enabled():
                        continue
                except Exception:
                    pass
                btn.scroll_into_view_if_needed(timeout=2000)
                btn.click(timeout=3000)
                page.wait_for_load_state("domcontentloaded")
                page.wait_for_timeout(700)
                clicked = True
                print(f"[stage]   pagination clicked via {loc[:60]}...", flush=True)
                break
            except Exception:
                continue
        # 2) 数字ページネーション（「{次のページ}」リンク）
        if not clicked:
            try:
                cur_page = _page_idx + 1
                next_page = cur_page + 1
                # 「2」「3」などの数字ボタン/リンク
                num_loc = f'xpath=(//button[normalize-space()="{next_page}"] | //a[normalize-space()="{next_page}"])[1]'
                btn = page.locator(num_loc).first
                if btn.count():
                    btn.click(timeout=3000)
                    page.wait_for_load_state("domcontentloaded")
                    page.wait_for_timeout(700)
                    clicked = True
                    print(f"[stage]   pagination clicked number {next_page}", flush=True)
            except Exception:
                pass
        # 3) 無限スクロール: 末尾までスクロール
        if not clicked:
            try:
                prev_height = page.evaluate("() => document.body.scrollHeight")
                page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(1500)
                new_height = page.evaluate("() => document.body.scrollHeight")
                if new_height > prev_height:
                    clicked = True
                    print(f"[stage]   pagination via scroll (height {prev_height}->{new_height})", flush=True)
            except Exception:
                pass
        if not clicked:
            print(f"[stage] _collect_worker_urls: no more pages after {_page_idx+1}", flush=True)
            break
    return out


def _name_kana_match(text: str, name: str, kana: str) -> bool:
    """text に name と kana の両方が含まれていれば true。空白は無視。"""
    norm_text = (text or "").replace(" ", "").replace("　", "")
    n = (name or "").replace(" ", "").replace("　", "")
    k = (kana or "").replace(" ", "").replace("　", "")
    return (n and n in norm_text) and (k and k in norm_text)


# ---------------------------------------------------------------- 詳細ページからフィールド抽出
_DETAIL_EXTRACTOR_JS = r"""
() => {
  const out = { good_rate: '', cancel_rate: '', timee_memo: '' };

  // ゼロ幅文字 (U+200B..U+200D, U+FEFF) を空白扱いするための正規化
  function strip(s) { return (s || '').replace(/[​-‍﻿]/g, '').trim(); }
  function norm(s) { return strip(s).replace(/\s+/g, ''); }

  function findLabelLeaf(labels) {
    // 「ラベル文字列と完全一致(空白除去後)」の葉ノード(子要素なし)を返す
    const candidates = Array.from(document.querySelectorAll('*'));
    for (const lab of labels) {
      const n = norm(lab);
      const leaf = candidates.find(el => el.children.length === 0 && norm(el.textContent) === n);
      if (leaf) return { leaf, label: lab };
    }
    return null;
  }

  // 詳細ページに現れる既知ラベル(これらは値として誤採用しないように除外)
  const KNOWN_LABELS = [
    '平均Good率（直近30回の評価）', '平均Good率',
    '直前キャンセル率', 'この店舗で働いた回数', '働いた回数',
    '働いた合計時間', '今週働ける残り時間', '管理用メモ',
    'バッジ', '所属グループ', 'ブロック設定', 'グループの変更'
  ];
  const KNOWN_LABELS_NORM = KNOWN_LABELS.map(norm);

  function isKnownLabel(t) {
    const tn = norm(t);
    return KNOWN_LABELS_NORM.some(k => k === tn);
  }

  function valueFor(labels) {
    const found = findLabelLeaf(labels);
    if (!found) return '';
    const { leaf, label } = found;
    const lnorm = norm(label);
    // 親(行コンテナ)を最大4段上まで辿り、ラベル以外の葉テキストを探す
    let parent = leaf.parentElement;
    for (let depth = 0; depth < 4 && parent; depth++) {
      const leaves = Array.from(parent.querySelectorAll('*')).filter(e => e.children.length === 0);
      for (const cand of leaves) {
        if (cand === leaf) continue;
        // ゼロ幅/空白のみのセルは値として無効
        const t = strip(cand.textContent);
        if (!t) continue;
        if (norm(t) === lnorm) continue;
        // 隣の行の見出しに行ってしまった場合は無視して次の候補へ
        if (isKnownLabel(t)) continue;
        return t;
      }
      parent = parent.parentElement;
    }
    return '';
  }

  out.good_rate = valueFor(['平均Good率（直近30回の評価）', '平均Good率']);
  out.cancel_rate = valueFor(['直前キャンセル率']);

  // 管理用メモ: ラベルが「管理用メモ」+ 注意書き「※ワーカーには公開されません」の隣に値領域。
  // - <textarea> がある場合はそれを優先
  // - 無ければラベル要素の親(または祖父)内で、
  //   ラベルおよび注意書き以外の長めのテキストノードを採用
  const memoFound = findLabelLeaf(['管理用メモ']);
  if (memoFound) {
    const memoLeaf = memoFound.leaf;
    // textarea の場合（編集モード時など）
    let parent = memoLeaf.parentElement;
    let memoVal = '';
    for (let depth = 0; depth < 4 && parent && !memoVal; depth++) {
      const ta = parent.querySelector('textarea');
      if (ta) {
        memoVal = ta.value || ta.textContent || '';
        break;
      }
      // ラベル/注意書きでない長文(改行を含む)テキストを探す
      const leaves = Array.from(parent.querySelectorAll('*')).filter(e => e.children.length === 0);
      let bestText = '';
      for (const cand of leaves) {
        if (cand === memoLeaf) continue;
        const raw = cand.textContent || '';
        const t = strip(raw);
        if (!t) continue;
        if (/^管理用メモ/.test(t)) continue;
        if (/ワーカーには公開されません/.test(t)) continue;
        // 既知ラベル(=隣の行の見出し) は除外
        if (isKnownLabel(t)) continue;
        // 長めのものを採用
        if (t.length > bestText.length) bestText = raw;
      }
      if (bestText) memoVal = bestText;
      parent = parent.parentElement;
    }
    out.timee_memo = strip(memoVal) ? memoVal : '';
  }

  return out;
}
"""


_DETAIL_DEBUG_DUMPED = {"once": False}


def _extract_detail_fields(page) -> Dict[str, str]:
    """詳細ページから3項目を抽出。"""
    # 構造調査用に最初の1ページだけ詳細ダンプを残す
    if not _DETAIL_DEBUG_DUMPED["once"]:
        _DETAIL_DEBUG_DUMPED["once"] = True
        _dump(page, "detail_inspect")
    try:
        result = page.evaluate(_DETAIL_EXTRACTOR_JS) or {}
    except Exception as e:
        print(f"[stage] _extract_detail_fields evaluate failed: {e}", flush=True)
        result = {}
    # 後処理:
    # - ゼロ幅文字(U+200B-U+200D, U+FEFF)を除去
    # - % / 数字 を抽出
    def _zw_strip(s: str) -> str:
        return "".join(c for c in (s or "") if c not in "​‌‍﻿").strip()

    good_raw = _zw_strip(result.get("good_rate") or "")
    cancel_raw = _zw_strip(result.get("cancel_rate") or "")
    memo_raw = _zw_strip(result.get("timee_memo") or "")

    # 「※ワーカーには公開されません」(=Timee側で統計非開示) は空文字 + non_disclosed フラグ
    non_disclosed = False
    if "公開されません" in good_raw or "公開されません" in cancel_raw:
        non_disclosed = True

    good = good_raw if not non_disclosed else ""
    if not non_disclosed:
        m = re.search(r"\d+\s*%", good_raw)
        if m:
            good = m.group(0).replace(" ", "")

    cancel = cancel_raw if not non_disclosed else ""
    if not non_disclosed:
        m = re.search(r"\d+\s*%", cancel_raw)
        if m:
            cancel = m.group(0).replace(" ", "")

    out = {
        "good_rate": good,
        "cancel_rate": cancel,
        "timee_memo": memo_raw,
    }
    if non_disclosed:
        out["_status"] = "non_disclosed"
    elif not good and not cancel:
        # ラベルは見えているのに値が両方空 = DOM変化/タイムアウトなどの抽出失敗。
        # 既存値を「空文字で上書きして消す」事故を防ぐため明示フラグ。
        # Why: 過去にこの上書きでほぼ全ワーカーの値が消える事故が発生
        out["_status"] = "extract_failed"
    return out


# ---------------------------------------------------------------- メインAPI
def _search_and_open_worker(page, name: str, kana: str):
    """ワーカー管理トップで kana 検索→結果から該当ワーカーをクリックして詳細ページへ。

    返り値:
      - True       : 詳細ページに到達
      - "no_match" : 検索したが「該当するワーカーがいません」(=未稼働ワーカー)
      - False      : その他の失敗 (検索失敗 / 結果クリック失敗 / 詳細未読込)
    """
    target_key = _key(name, kana)
    kana_q = (kana or "").replace(" ", "").replace("　", "")
    if not kana_q:
        return False

    # ワーカー管理トップ
    try:
        page.goto(f"https://app-new.taimee.co.jp/clients/{CLIENT_ID}/users",
                  wait_until="domcontentloaded")
        page.wait_for_selector('input#nameKana', timeout=10000)
    except Exception as e:
        print(f"[stage] search nav failed for {target_key}: {e}", flush=True)
        return False

    # カナを入力
    try:
        inp = page.locator('input#nameKana')
        inp.fill("")
        inp.fill(kana_q)
    except Exception as e:
        print(f"[stage] search fill failed for {target_key}: {e}", flush=True)
        return False

    # 「検索」ボタンをクリック
    clicked = False
    for loc in [
        'xpath=//button[normalize-space()="検索"]',
        'xpath=//button[contains(., "検索")]',
    ]:
        try:
            btn = page.locator(loc).first
            btn.click(timeout=3000)
            clicked = True
            break
        except Exception:
            continue
    if not clicked:
        # Enter キーで送信を試す
        try:
            inp.press("Enter")
            clicked = True
        except Exception:
            pass
    if not clicked:
        print(f"[stage] search submit failed for {target_key}", flush=True)
        return False

    # 結果描画待ち
    try:
        page.wait_for_load_state("networkidle", timeout=10000)
    except Exception:
        pass
    page.wait_for_timeout(700)

    # 「該当するワーカーがいません」検知 → no_match を返して呼び出し側で処理
    try:
        no_match_present = page.evaluate(
            r"""() => /該当するワーカーがいません/.test(document.body.innerText || '')"""
        )
    except Exception:
        no_match_present = False
    if no_match_present:
        print(f"[stage] no match in worker list for {target_key}", flush=True)
        return "no_match"

    # 該当ワーカーをクリック
    # 実DOM: 検索結果は <div data-testid="user-list-item"> 等で描画。
    # テキストに「光井 香織」「ミツイ カオリ」のようにスペース有り文字列が入るため、
    # 空白除去後の比較を JS で行う。
    norm_kana = kana.replace(" ", "").replace("　", "")
    norm_name = name.replace(" ", "").replace("　", "")
    clicked_result = False

    # 戦略1: JS で空白除去マッチした行(またはその祖先)をクリック
    try:
        clicked_via_js = page.evaluate(
            r"""
            ([norm_name, norm_kana]) => {
              function norm(s) { return (s || '').replace(/\s+/g, ''); }
              // 候補: user-list-item / tr / [role=row]
              const cands = Array.from(document.querySelectorAll(
                '[data-testid="user-list-item"], tbody tr, [role="row"]'
              ));
              for (const el of cands) {
                const t = norm(el.textContent);
                if ((norm_kana && t.includes(norm_kana)) || (norm_name && t.includes(norm_name))) {
                  // クリック対象優先順: 内部の <a> → 親<tr> → 自身
                  const a = el.querySelector('a[href]') || (el.closest('tr') ? el.closest('tr').querySelector('a[href]') : null);
                  if (a) { a.click(); return 'a:' + (a.getAttribute('href') || ''); }
                  let target = el.closest('tr') || el;
                  target.click();
                  return 'el:' + (target.tagName || '');
                }
              }
              return null;
            }
            """,
            [norm_name, norm_kana],
        )
        if clicked_via_js:
            print(f"[stage] search result clicked via JS for {target_key} ({clicked_via_js})", flush=True)
            try:
                page.wait_for_load_state("domcontentloaded", timeout=5000)
            except Exception:
                pass
            clicked_result = True
    except Exception as e:
        print(f"[stage] search result JS click error for {target_key}: {e}", flush=True)

    # 戦略2: 結果が1件しかない前提で先頭の user-list-item の中の<a>をクリック
    if not clicked_result:
        for loc in [
            'xpath=(//*[@data-testid="user-list-item"]//a[@href])[1]',
            'xpath=(//tbody//tr//a[@href])[1]',
            'xpath=//*[@data-testid="user-list-item"]',
            'xpath=//tbody//tr[1]',
        ]:
            try:
                el = page.locator(loc).first
                if el.count() == 0:
                    continue
                el.scroll_into_view_if_needed(timeout=2000)
                el.click(timeout=3000)
                clicked_result = True
                print(f"[stage] search result clicked via fallback {loc[:60]}... for {target_key}", flush=True)
                break
            except Exception:
                continue

    if not clicked_result:
        print(f"[stage] search result row click failed for {target_key}", flush=True)
        _dump(page, f"search_noclick_{target_key.replace('|', '_')}")
        return False

    # 詳細ページの描画待ち
    try:
        page.wait_for_load_state("domcontentloaded", timeout=5000)
    except Exception:
        pass
    try:
        page.wait_for_selector(
            'xpath=//*[contains(text(), "平均Good率") or contains(text(), "管理用メモ")]',
            timeout=15000,
        )
        page.wait_for_timeout(400)
    except Exception:
        print(f"[stage] detail not loaded for {target_key} url={page.url}", flush=True)
        _dump(page, f"detail_fail_{target_key.replace('|', '_')}")
        return False
    return True


def _open_offerings_calendar(page) -> None:
    """求人一覧カレンダーへ遷移。"""
    page.goto(f"https://app-new.taimee.co.jp/clients/{CLIENT_ID}/offerings",
              wait_until="domcontentloaded")
    page.wait_for_timeout(1500)
    try:
        page.wait_for_selector('time[datetime]', timeout=15000, state="attached")
    except Exception:
        pass


def _navigate_offerings_to_month(page, year: int, month: int) -> None:
    """求人カレンダーで指定月へ移動 (timee_job_calendar と同じ実装の縮小版)。"""
    target_text = f"{year}年{month}月"
    for _step in range(24):
        try:
            res = page.evaluate(
                r"""() => {
                    const re = /^(\d{4})\s*年\s*(\d{1,2})\s*月\s*$/;
                    const all = Array.from(document.querySelectorAll('div, span, h1, h2, h3, h4, p'));
                    for (const el of all) {
                      const t = (el.textContent || '').trim();
                      if (t.length > 12) continue;
                      if (re.test(t)) return t;
                    }
                    return '';
                }"""
            )
            heading = (res or "").strip()
        except Exception:
            heading = ""
        if heading == target_text:
            return
        m = re.search(r"(\d{4})\s*年\s*(\d{1,2})\s*月", heading)
        forward = True
        if m:
            cy, cm = int(m.group(1)), int(m.group(2))
            forward = (cy, cm) < (year, month)
        sel = ('xpath=//button[.//*[@aria-label="次の月"]]' if forward
               else 'xpath=//button[.//*[@aria-label="前の月"]]')
        try:
            page.locator(sel).first.click(timeout=2000)
            page.wait_for_timeout(400)
        except Exception:
            return


def _fetch_via_posting_path(page, name: str, kana: str, shift_iso: str) -> bool:
    """求人カレンダー → 日付クリック → 初回ワーカー限定公開求人 → ワーカー確認 →
    ワーカー名クリック → 詳細ページ到達。

    shift_iso: 'YYYY-MM-DD' 形式。ワーカーの就業予定日。
    成功時 True。
    """
    target_key = _key(name, kana)
    print(f"[stage] _fetch_via_posting_path target={target_key} date={shift_iso}", flush=True)
    try:
        y, mo, da = shift_iso.split("-")
        y, mo, da = int(y), int(mo), int(da)
    except Exception:
        return False

    # 求人カレンダー → 該当月へ
    _open_offerings_calendar(page)
    _navigate_offerings_to_month(page, y, mo)
    page.wait_for_timeout(500)

    # 該当日のセル <time datetime="YYYY-MM-DD"> をクリック → popup or 詳細遷移
    try:
        date_el = page.locator(f'time[datetime="{shift_iso}"]').first
        date_el.scroll_into_view_if_needed(timeout=2000)
        date_el.click(timeout=3000)
        page.wait_for_timeout(800)
    except Exception as e:
        print(f"[stage] posting path: date cell click failed: {e}", flush=True)
        _dump(page, f"posting_date_fail_{target_key.replace('|','_')}")
        return False

    # popup の各<section>(求人ブロック)のうち、textContentに「初回ワーカー限定公開」を
    # 含むセクションの<a href="/offerings/...">をクリック。
    # 実DOM: <span>初回ワーカー</span><span>限定公開</span> と分割表示されているため
    # leaf完全一致では探せない。section配下の連結テキストで判定する。
    try:
        clicked = page.evaluate(
            r"""() => {
              function norm(s) { return (s || '').replace(/\s+/g, ''); }
              // 1) <section> 単位を優先
              const sections = Array.from(document.querySelectorAll('section'));
              for (const sec of sections) {
                if (norm(sec.textContent).includes('初回ワーカー限定公開')) {
                  const link = sec.querySelector('a[href*="/offerings/"]');
                  if (link) { link.click(); return link.getAttribute('href'); }
                }
              }
              // 2) section が無い場合: 求人カード単位の親をdialog内で探す
              const dlg = document.querySelector('[role="dialog"]') || document.body;
              // dialog 内の各 a[href*=/offerings/] を辿り、その祖先のtextContentで判定
              const links = Array.from(dlg.querySelectorAll('a[href*="/offerings/"]'));
              for (const a of links) {
                let p = a.parentElement;
                for (let i = 0; i < 8 && p; i++) {
                  if (norm(p.textContent).includes('初回ワーカー限定公開')) {
                    a.click(); return a.getAttribute('href');
                  }
                  p = p.parentElement;
                }
              }
              return null;
            }"""
        )
        if not clicked:
            print(f"[stage] posting path: 初回ワーカー限定公開 link not found", flush=True)
            _dump(page, f"posting_initial_fail_{target_key.replace('|','_')}")
            return False
        print(f"[stage] posting path: clicked posting -> {clicked}", flush=True)
        page.wait_for_load_state("domcontentloaded", timeout=8000)
        page.wait_for_timeout(700)
    except Exception as e:
        print(f"[stage] posting path: initial-only link click failed: {e}", flush=True)
        _dump(page, f"posting_initial_exc_{target_key.replace('|','_')}")
        return False

    # 求人詳細ページの「ワーカーを確認」ボタンをクリック
    clicked_confirm = False
    for loc in [
        'xpath=//a[contains(., "ワーカーを確認")]',
        'xpath=//button[contains(., "ワーカーを確認")]',
    ]:
        try:
            el = page.locator(loc).first
            if el.count() == 0:
                continue
            el.click(timeout=3000)
            clicked_confirm = True
            break
        except Exception:
            continue
    if not clicked_confirm:
        print(f"[stage] posting path: ワーカーを確認 click failed", flush=True)
        _dump(page, f"posting_confirm_fail_{target_key.replace('|','_')}")
        return False
    page.wait_for_load_state("domcontentloaded", timeout=8000)
    page.wait_for_timeout(700)

    # ワーカー名リンクは新規タブで開く仕様 (target=_blank/外部リンクアイコン)。
    # click では同タブが遷移しないので href を取り出して page.goto で同タブ移動する。
    try:
        href = page.evaluate(
            r"""([norm_name, norm_kana]) => {
              function norm(s) { return (s || '').replace(/\s+/g, ''); }
              const links = Array.from(document.querySelectorAll('a[href*="/users/"]'));
              for (const a of links) {
                const row = a.closest('tr, [role="row"], li, [class*="row"]') || a.parentElement;
                const t = norm((row && row.textContent) || a.textContent || '');
                if ((norm_kana && t.includes(norm_kana)) || (norm_name && t.includes(norm_name))) {
                  return a.getAttribute('href');
                }
              }
              return null;
            }""",
            [name.replace(" ", "").replace("　", ""), kana.replace(" ", "").replace("　", "")],
        )
        if not href:
            print(f"[stage] posting path: worker name href not found", flush=True)
            _dump(page, f"posting_worker_fail_{target_key.replace('|','_')}")
            return False
        full_url = href if href.startswith("http") else f"https://app-new.taimee.co.jp{href}"
        print(f"[stage] posting path: goto worker detail {full_url}", flush=True)
        page.goto(full_url, wait_until="domcontentloaded", timeout=15000)
        page.wait_for_selector(
            'xpath=//*[contains(text(), "平均Good率") or contains(text(), "管理用メモ")]',
            timeout=15000,
        )
        page.wait_for_timeout(400)
        return True
    except Exception as e:
        print(f"[stage] posting path: worker goto/load failed: {e}", flush=True)
        _dump(page, f"posting_worker_load_fail_{target_key.replace('|','_')}")
        return False


def fetch_worker_details(
    targets: List[Tuple[str, str, Optional[str]]],
    email: Optional[str] = None,
    password: Optional[str] = None,
    headless: bool = True,
) -> Dict[str, Dict[str, str]]:
    """指定された (氏名, カナ, 就業日(任意)) のリストについて 3項目を取得。

    検索パス → no_match なら 求人パス (shift_iso が指定されていれば) を試す。
    返り値: {"氏名|カナ": {"good_rate": "...", "cancel_rate": "...", "timee_memo": "..."}}
    """
    from playwright.sync_api import sync_playwright

    if not targets:
        return {}

    # (name, kana) のみで来た場合の互換
    norm_targets: List[Tuple[str, str, Optional[str]]] = []
    for t in targets:
        if len(t) == 2:
            norm_targets.append((t[0], t[1], None))
        else:
            norm_targets.append((t[0], t[1], t[2]))

    email = email or os.environ.get("TIMEE_EMAIL", "")
    password = password or os.environ.get("TIMEE_PASSWORD", "")
    if not email or not password:
        raise RuntimeError("TIMEE_EMAIL / TIMEE_PASSWORD が未設定です")

    out: Dict[str, Dict[str, str]] = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(locale="ja-JP")
        page = context.new_page()
        page.set_default_timeout(DEFAULT_TIMEOUT_MS)
        try:
            _login(page, email, password)
            for name, kana, shift_iso in norm_targets:
                target_key = _key(name, kana)
                ret = _search_and_open_worker(page, name, kana)

                # no_match (=未稼働) かつ就業予定日がある場合、求人経由で再挑戦
                if ret == "no_match" and shift_iso:
                    print(f"[stage] {target_key} no_match → posting path試行", flush=True)
                    ok = _fetch_via_posting_path(page, name, kana, shift_iso)
                    if ok:
                        fields = _extract_detail_fields(page)
                        print(f"[stage] (posting) {target_key}: {fields}", flush=True)
                        out[target_key] = fields
                        continue
                    # 求人経由でも失敗 → no_match扱い
                    out[target_key] = {
                        "good_rate": "", "cancel_rate": "", "timee_memo": "",
                        "_status": "no_match",
                    }
                    continue

                if ret == "no_match":
                    out[target_key] = {
                        "good_rate": "", "cancel_rate": "", "timee_memo": "",
                        "_status": "no_match",
                    }
                    continue
                if not ret:
                    continue
                fields = _extract_detail_fields(page)
                print(f"[stage] {target_key}: {fields}", flush=True)
                out[target_key] = fields
        except Exception:
            _dump(page, "fatal")
            raise
        finally:
            context.close()
            browser.close()

    return out


# ---------------------------------------------------------------- CLI
def _cli():
    parser = argparse.ArgumentParser()
    parser.add_argument("--max", type=int, default=5,
                        help="一覧の最初N名を取得（テスト用）")
    parser.add_argument("--no-headless", action="store_true")
    args = parser.parse_args()

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not args.no_headless)
        context = browser.new_context(locale="ja-JP")
        page = context.new_page()
        page.set_default_timeout(DEFAULT_TIMEOUT_MS)
        try:
            _login(page, os.environ["TIMEE_EMAIL"], os.environ["TIMEE_PASSWORD"])
            url_rows = _collect_worker_urls(page)
        finally:
            context.close()
            browser.close()
    print(json.dumps(url_rows[: args.max], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    _cli()
