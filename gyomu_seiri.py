# -*- coding: utf-8 -*-
"""業務整理資料 — ソネット光×新設の不備停滞対応 業務量/開通率 整理（読み取り専用）。

PART A: リスト別×停滞理由別 開通率（確定値: 過去半年=直近180日/直近90日除外）
PART B: リスト別×月(3/4/5) 現場時間（代コン系FC架電×5分）
PART C: シミュレーション（不備停滞5理由のみ運用 / 工事取得系20回キャップ）

リスト判定は利用携帯Ⅰ(Field12__c)主判定で排他:
  AU=KDDI/UQモバイル, SB=Softbank/Y!mobile, docomo=ドコモ
"""
from __future__ import annotations

import calendar
from collections import defaultdict
from datetime import datetime, timezone, timedelta

JST = timezone(timedelta(hours=9))

MIN_PER_CALL = 5.0          # 1架電あたり想定(分)。Zoom実測の有効対話4-5分+留守・後処理の概算
KOUJI = ("工事日調整希望", "API工事取得")
KEEP5 = ("番ポ不備", "住所確認", "オーナー確認", "詳細確認", "有派遣へ変更必要")
DAICON_FC = ("'フォローコール（代コン）'", "'フォローコール（代コン窓口）'", "'フォローコール（工事取得）'")
MONTHS = ["2026-03", "2026-04", "2026-05"]
LISTS = ["AU", "SB", "docomo"]
CAP = 20


def list_of(f12: str | None) -> str | None:
    v = (f12 or "").strip()
    if v in ("KDDI", "UQモバイル"):
        return "AU"
    if v in ("Softbank", "Y!mobile"):
        return "SB"
    if v == "ドコモ":
        return "docomo"
    return None


def _bucket(cat: str) -> str:
    if cat in KOUJI:
        return "kouji"
    if cat in KEEP5:
        return "keep5"
    if cat == "(停滞なし)":
        return "none"
    return "other"


def compute(sf) -> dict:
    """全リスト分を一括算出して返す（重いTaskクエリを1回で済ませるため）。"""
    now = datetime.now(JST)
    cutoff = (now - timedelta(days=90)).date().isoformat()

    # ---------- A: 開通率確定母集団（過去半年=直近180日/直近90日除外）----------
    # エントリ日が「180日前〜90日前」の確定分のみを対象とする
    A_where = (
        "Field76__r.Name LIKE '%So-net%' AND Field78__c='新設' "
        f"AND Field156__c = LAST_N_DAYS:180 AND Field156__c <= {cutoff}"
    )
    accA = sf.query_all(
        f"SELECT Id,Field130__c,Field12__c,Field242__c FROM Account WHERE {A_where}"
    )["records"]

    # ---------- 属性マップ（時間集計用に広め: 直近400日）----------
    All_where = (
        "Field76__r.Name LIKE '%So-net%' AND Field78__c='新設' "
        "AND Field156__c = LAST_N_DAYS:400"
    )
    accAll = sf.query_all(
        f"SELECT Id,Field130__c,Field12__c,Field242__c FROM Account WHERE {All_where}"
    )["records"]
    attr = {}
    for r in accAll:
        attr[r["Id"]] = (
            list_of(r.get("Field12__c")),
            r.get("Field242__c") or "(停滞なし)",
            bool(r.get("Field130__c")),
        )

    # A集計: list -> cat -> [n, open]
    A = {lst: defaultdict(lambda: [0, 0]) for lst in LISTS}
    for r in accA:
        lst = list_of(r.get("Field12__c"))
        if lst is None:
            continue
        cat = r.get("Field242__c") or "(停滞なし)"
        A[lst][cat][0] += 1
        if r.get("Field130__c"):
            A[lst][cat][1] += 1

    # ---------- B: 月別架電（現場時間）----------
    B = {ym: {lst: defaultdict(int) for lst in LISTS} for ym in MONTHS}
    for ym in MONTHS:
        y, m = map(int, ym.split("-"))
        last = calendar.monthrange(y, m)[1]
        soql = (
            f"SELECT WhatId FROM Task WHERE Field2_del__c IN ({','.join(DAICON_FC)}) "
            f"AND ActivityDate >= {y}-{m:02d}-01 AND ActivityDate <= {y}-{m:02d}-{last:02d} "
            "AND WhatId IN (SELECT Id FROM Account WHERE Field76__r.Name LIKE '%So-net%' AND Field78__c='新設')"
        )
        for t in sf.query_all(soql)["records"]:
            wid = t.get("WhatId")
            if not wid:
                continue
            a = attr.get(wid)
            if not a:
                continue
            lst, cat, _ = a
            if lst is None:
                continue
            B[ym][lst][_bucket(cat)] += 1

    # ---------- C: 案件ごとの総架電（A母集団・通年）----------
    fc_total = defaultdict(int)
    soql_tot = (
        f"SELECT WhatId FROM Task WHERE Field2_del__c IN ({','.join(DAICON_FC)}) "
        f"AND WhatId IN (SELECT Id FROM Account WHERE {A_where})"
    )
    for t in sf.query_all(soql_tot)["records"]:
        wid = t.get("WhatId")
        if wid:
            fc_total[wid] += 1

    # ---------- 整形 ----------
    def cat_order(cat):
        if cat in KOUJI:
            return (0, cat)
        if cat in KEEP5:
            return (1, cat)
        if cat == "(停滞なし)":
            return (3, cat)
        return (2, cat)

    out_lists = {}
    for lst in LISTS:
        total = sum(v[0] for v in A[lst].values())
        # PART A 行
        reasons = []
        for cat, (n, op) in sorted(
            A[lst].items(), key=lambda kv: (cat_order(kv[0])[0], -kv[1][0])
        ):
            reasons.append({
                "reason": cat,
                "n": n,
                "open": op,
                "rate": (op / n * 100) if n else 0.0,
                "occ": (n / total * 100) if total else 0.0,
                "grp": _bucket(cat),
            })

        # PART B 月別
        month_time = {}
        for ym in MONTHS:
            b = B[ym][lst]
            k, f5, ot = b["kouji"], b["keep5"], b["other"]
            month_time[ym] = {
                "kouji_calls": k, "keep5_calls": f5, "other_calls": ot,
                "kouji_h": k * MIN_PER_CALL / 60,
                "keep5_h": f5 * MIN_PER_CALL / 60,
                "other_h": ot * MIN_PER_CALL / 60,
                "total_h": (k + f5 + ot) * MIN_PER_CALL / 60,
            }
        # 月平均
        mk = sum(B[ym][lst]["kouji"] for ym in MONTHS) / 3
        m5 = sum(B[ym][lst]["keep5"] for ym in MONTHS) / 3
        mo = sum(B[ym][lst]["other"] for ym in MONTHS) / 3
        avg = {
            "kouji_h": mk * MIN_PER_CALL / 60,
            "keep5_h": m5 * MIN_PER_CALL / 60,
            "other_h": mo * MIN_PER_CALL / 60,
            "total_h": (mk + m5 + mo) * MIN_PER_CALL / 60,
        }

        # S1: 不備停滞5理由のみ追う（その他不備切り捨て）
        lost_open_s1 = sum(op for c, (n, op) in A[lst].items()
                           if c not in KOUJI and c not in KEEP5 and c != "(停滞なし)")
        lost_n_s1 = sum(n for c, (n, op) in A[lst].items()
                        if c not in KOUJI and c not in KEEP5 and c != "(停滞なし)")
        s1 = {
            "keep_h": (mk + m5) * MIN_PER_CALL / 60,   # 今後月必要(工取+5理由)
            "cut_h": mo * MIN_PER_CALL / 60,           # 月削減(その他不備)
            "cut_n": lost_n_s1,                        # 切り捨て母数(年)
            "lost_open": lost_open_s1,                 # 失う開通(年)
        }

        # S2: 工事取得系20回キャップ
        kouji_ids = [r["Id"] for r in accA
                     if list_of(r.get("Field12__c")) == lst and (r.get("Field242__c") or "") in KOUJI]
        excess = sum(max(0, fc_total.get(i, 0) - CAP) for i in kouji_ids)
        open_now = sum(1 for i in kouji_ids if attr.get(i, (None, "", False))[2])
        lost_open_s2 = sum(1 for i in kouji_ids
                           if attr.get(i, (None, "", False))[2] and fc_total.get(i, 0) > CAP)
        s2 = {
            "kouji_n": len(kouji_ids),
            "kouji_open": open_now,
            "lost_open": lost_open_s2,
            "cut_h": excess * MIN_PER_CALL / 60 / 12,   # 月削減(年間超過/12)
        }

        # ── 新フローでの「エントリ1件あたり必要時間」係数 ──
        # 月の新フロー必要時間(after_h) ÷ 現状の月あたりエントリ件数。
        # エントリ件数 × 係数 = 新フロー必要時間(h/月) となり③結論と整合する。
        _after_h = max(0.0, s1["keep_h"] - s2["cut_h"])
        monthly_entries_now = total / 3.0  # 母集団は約3ヶ月幅(180日前〜90日前)
        per_entry_h = (_after_h / monthly_entries_now) if monthly_entries_now else 0.0

        # ── 前後比較サマリー（今までのフロー → 新フロー[5理由のみ＋工取20回キャップ]）──
        total_open = sum(op for _, (n, op) in A[lst].items())
        before_h = avg["total_h"]
        after_h = max(0.0, s1["keep_h"] - s2["cut_h"])
        lost_total = s1["lost_open"] + s2["lost_open"]
        before_rate = (total_open / total * 100) if total else 0.0
        after_rate = ((total_open - lost_total) / total * 100) if total else 0.0
        summary = {
            "before_h": before_h,
            "after_h": after_h,
            "save_h": before_h - after_h,
            "save_other_h": s1["cut_h"],      # その他不備カット分
            "save_kouji_h": s2["cut_h"],      # 工取20回キャップ分
            "total_open": total_open,
            "lost_total": lost_total,
            "lost_other": s1["lost_open"],
            "lost_kouji": s2["lost_open"],
            "before_rate": before_rate,
            "after_rate": after_rate,
            "drop_pt": before_rate - after_rate,
            "per_entry_h": per_entry_h,           # エントリ1件あたり新フロー必要時間(h)
            "per_entry_min": per_entry_h * 60,    # 同(分)
            "monthly_entries_now": monthly_entries_now,  # 現状の月あたりエントリ目安
        }

        out_lists[lst] = {
            "total": total,
            "total_open": total_open,
            "reasons": reasons,
            "month_time": month_time,
            "avg_month": avg,
            "s1": s1,
            "s2": s2,
            "summary": summary,
        }

    return {
        "asof": now.strftime("%Y/%m/%d %H:%M"),
        "min_per_call": MIN_PER_CALL,
        "cap": CAP,
        "months": MONTHS,
        "kouji": list(KOUJI),
        "keep5": list(KEEP5),
        "lists": out_lists,
    }
