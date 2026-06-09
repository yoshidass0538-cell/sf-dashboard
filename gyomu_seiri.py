# -*- coding: utf-8 -*-
"""業務整理資料 — ソネット光×新設の不備停滞対応 業務量/開通率 整理（読み取り専用）。

PART A: リスト別×停滞理由別 開通率（確定値: 過去半年=直近180日/直近90日除外）
PART B: リスト別×月(3/4/5) 現場時間（代コン系FC架電。留守3分/有効対話13分）
PART C: シミュレーション（不備停滞5理由のみ運用 / 工事取得系20回キャップ）

時間モデル（1架電あたり）:
  - 留守(Field4_del__c='留守'): 3分（事務処理のみ）
  - 有効対話(留守以外)        : 通話10分 + 事務処理3分 = 13分

リスト判定は利用携帯Ⅰ(Field12__c)主判定で排他:
  AU=KDDI/UQモバイル, SB=Softbank/Y!mobile, docomo=ドコモ
"""
from __future__ import annotations

import calendar
from collections import defaultdict
from datetime import datetime, timezone, timedelta

JST = timezone(timedelta(hours=9))

RUSU_MIN = 3.0              # 留守1架電の所要(分): 事務処理のみ
EFF_MIN = 13.0             # 有効対話1架電の所要(分): 通話10分 + 事務処理3分
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


def _call_min(result: str | None) -> float:
    """通話結果から1架電の所要(分)を返す。留守=3分 / それ以外=13分。"""
    return RUSU_MIN if (result or "") == "留守" else EFF_MIN


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

    # ---------- B: 月別架電（現場時間。留守/有効対話で分単位集計）----------
    # B[ym][lst][bucket] = [calls, minutes]
    B = {ym: {lst: defaultdict(lambda: [0, 0.0]) for lst in LISTS} for ym in MONTHS}
    for ym in MONTHS:
        y, m = map(int, ym.split("-"))
        last = calendar.monthrange(y, m)[1]
        soql = (
            f"SELECT WhatId,Field4_del__c FROM Task WHERE Field2_del__c IN ({','.join(DAICON_FC)}) "
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
            cell = B[ym][lst][_bucket(cat)]
            cell[0] += 1
            cell[1] += _call_min(t.get("Field4_del__c"))

    # ---------- C: 案件ごとの架電（A母集団・通年。回数と分）----------
    case_calls = defaultdict(int)
    case_min = defaultdict(float)
    soql_tot = (
        f"SELECT WhatId,Field4_del__c FROM Task WHERE Field2_del__c IN ({','.join(DAICON_FC)}) "
        f"AND WhatId IN (SELECT Id FROM Account WHERE {A_where})"
    )
    for t in sf.query_all(soql_tot)["records"]:
        wid = t.get("WhatId")
        if not wid:
            continue
        case_calls[wid] += 1
        case_min[wid] += _call_min(t.get("Field4_del__c"))

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

        # PART B 月別（分→時間）
        month_time = {}
        for ym in MONTHS:
            b = B[ym][lst]
            kc, km = b["kouji"]
            f5c, f5m = b["keep5"]
            oc, om = b["other"]
            month_time[ym] = {
                "kouji_calls": kc, "keep5_calls": f5c, "other_calls": oc,
                "kouji_h": km / 60, "keep5_h": f5m / 60, "other_h": om / 60,
                "total_h": (km + f5m + om) / 60,
            }
        # 月平均(時間)
        avg_kouji_h = sum(B[ym][lst]["kouji"][1] for ym in MONTHS) / 3 / 60
        avg_keep5_h = sum(B[ym][lst]["keep5"][1] for ym in MONTHS) / 3 / 60
        avg_other_h = sum(B[ym][lst]["other"][1] for ym in MONTHS) / 3 / 60
        avg = {
            "kouji_h": avg_kouji_h,
            "keep5_h": avg_keep5_h,
            "other_h": avg_other_h,
            "total_h": avg_kouji_h + avg_keep5_h + avg_other_h,
        }

        # S1: 不備停滞5理由のみ追う（その他不備切り捨て）
        lost_open_s1 = sum(op for c, (n, op) in A[lst].items()
                           if c not in KOUJI and c not in KEEP5 and c != "(停滞なし)")
        lost_n_s1 = sum(n for c, (n, op) in A[lst].items()
                        if c not in KOUJI and c not in KEEP5 and c != "(停滞なし)")
        s1 = {
            "keep_h": avg_kouji_h + avg_keep5_h,   # 今後月必要(工取+5理由)
            "cut_h": avg_other_h,                  # 月削減(その他不備)
            "cut_n": lost_n_s1,                    # 切り捨て母数(対象期間)
            "lost_open": lost_open_s1,             # 失う開通(対象期間)
        }

        # S2: 工事取得系20回キャップ（分ベースで超過分を算出）
        kouji_ids = [r["Id"] for r in accA
                     if list_of(r.get("Field12__c")) == lst and (r.get("Field242__c") or "") in KOUJI]
        tot_min_k = sum(case_min.get(i, 0.0) for i in kouji_ids)
        capped_min_k = 0.0
        for i in kouji_ids:
            c = case_calls.get(i, 0)
            if c <= 0:
                continue
            capped_min_k += case_min.get(i, 0.0) * min(CAP / c, 1.0)
        ratio_kept = (capped_min_k / tot_min_k) if tot_min_k else 1.0
        s2_cut_h = avg_kouji_h * (1 - ratio_kept)   # 月削減(工取キャップ分・月活動ベース)
        open_now = sum(1 for i in kouji_ids if attr.get(i, (None, "", False))[2])
        lost_open_s2 = sum(1 for i in kouji_ids
                           if attr.get(i, (None, "", False))[2] and case_calls.get(i, 0) > CAP)
        s2 = {
            "kouji_n": len(kouji_ids),
            "kouji_open": open_now,
            "lost_open": lost_open_s2,
            "cut_h": s2_cut_h,
        }

        # ── 新フローでの「エントリ1件あたり必要時間」係数 ──
        _after_h = max(0.0, s1["keep_h"] - s2["cut_h"])
        monthly_entries_now = total / 3.0  # 母集団は約3ヶ月幅(180日前〜90日前)
        per_entry_h = (_after_h / monthly_entries_now) if monthly_entries_now else 0.0

        # ── 前後比較サマリー（今までのフロー → 新フロー[5理由のみ＋工取20回キャップ]）──
        total_open = sum(op for _, (n, op) in A[lst].items())
        before_h = avg["total_h"]
        after_h = _after_h
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
        "rusu_min": RUSU_MIN,
        "eff_min": EFF_MIN,
        "time_model": f"留守{RUSU_MIN:.0f}分／有効対話{EFF_MIN:.0f}分(通話10分+事務3分)",
        "cap": CAP,
        "months": MONTHS,
        "kouji": list(KOUJI),
        "keep5": list(KEEP5),
        "lists": out_lists,
    }
