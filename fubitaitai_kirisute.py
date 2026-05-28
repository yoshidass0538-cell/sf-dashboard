"""不備停滞切り捨て判定資料 — ソネット光・経験ベース集計（読み取り専用）。

母集団:
  - 取次商材: ソネット光 (Field76__r.Name LIKE '%So-net%')
  - エントリ日: 直近180日 と 直近365日 の両期間

集計方式: 経験ベース
  - 1次〜10次のいずれかのダイコン理由(Field242〜246/341〜345)に該当理由を含む案件をカウント
  - ⚠️ CX率は使わない (CX完了後にも追記される運用のため因果分析に使えない)
  - 開通率(Field130__c IS NOT NULL)のみを切り捨て判断指標として使用

判定基準:
  - 切り捨て推奨: 開通率 < 20%
  - グレーゾーン: 20% <= 開通率 < 35%
  - 介入価値大: 35% <= 開通率
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from collections import defaultdict

JST = timezone(timedelta(hours=9))

PRODUCT_LIKE = "LIKE '%So-net%'"
PERIODS = [180, 365]  # 直近半年 / 直近1年
MIN_OCCURRENCES = 30  # 母数のカットオフ

# 1次〜10次のダイコン理由フィールド
DAIKON_FIELDS = [
    "Field242__c",  # 1次
    "Field243__c",  # 2次
    "Field244__c",  # 3次
    "Field245__c",  # 4次
    "Field246__c",  # 5次
    "Field341__c",  # 6次
    "Field342__c",  # 7次
    "Field343__c",  # 8次
    "Field344__c",  # 9次
    "Field345__c",  # 10次
]


def _analyze(records: list, fc_count_map: dict[str, int] | None = None) -> dict:
    """recordsを集計して理由別の経験数・開通数・平均FC回数を返す。
    fc_count_map: { AccountId: 代コン系FC回数 } (なければ平均FCは0)
    """
    fc_count_map = fc_count_map or {}
    total = len(records)
    total_open = sum(1 for r in records if r.get("Field130__c"))

    exp_set: dict[str, set] = defaultdict(set)
    opened_set: dict[str, set] = defaultdict(set)
    for r in records:
        rid = r["Id"]
        opened = bool(r.get("Field130__c"))
        seen = set()
        for f in DAIKON_FIELDS:
            v = r.get(f)
            if v:
                seen.add(v)
        for reason in seen:
            exp_set[reason].add(rid)
            if opened:
                opened_set[reason].add(rid)

    rows = []
    for reason, ids in exp_set.items():
        n = len(ids)
        if n < MIN_OCCURRENCES:
            continue
        op_ids = opened_set[reason]
        op = len(op_ids)
        # 開通済み案件の代コン系FC回数（0回含む全平均）
        fc_counts_open = [fc_count_map.get(rid, 0) for rid in op_ids]
        fc_avg_open = (sum(fc_counts_open) / len(fc_counts_open)) if fc_counts_open else 0.0
        # 0回除外平均（実際にコールされた案件のみ）
        fc_pos = [c for c in fc_counts_open if c > 0]
        fc_avg_pos = (sum(fc_pos) / len(fc_pos)) if fc_pos else 0.0
        rows.append({
            "reason": reason,
            "n": n,
            "open": op,
            "open_rate": op / n * 100,
            "occur_rate": n / total * 100 if total else 0.0,
            "fc_avg_open": fc_avg_open,       # 開通案件全体の平均FC回数（0回含む）
            "fc_avg_pos": fc_avg_pos,         # うちFC>0のみの平均
            "fc_open_with_call": len(fc_pos), # うちFCを1回以上受けた数
        })
    rows.sort(key=lambda x: -x["n"])
    return {"total": total, "total_open": total_open, "rows": rows}


def compute(sf, now: datetime | None = None, area: str | None = None) -> dict:
    """area: None=全件, '東' / '西' でエリア(Field43__c)絞り込み"""
    now = now or datetime.now(JST)

    select_cols = "Id, Field130__c, Field119__c, Field43__c, " + ", ".join(DAIKON_FIELDS)
    area_filter = ""
    if area in ("東", "西"):
        area_filter = f" AND Field43__c = '{area}'"

    # 代コン系FC（不備停滞対応の架電群）
    DAICON_FC_LABELS = (
        "'フォローコール（代コン）'",
        "'フォローコール（代コン窓口）'",
        "'フォローコール（工事取得）'",
    )

    by_period: dict[int, dict] = {}
    for days in PERIODS:
        soql = (
            f"SELECT {select_cols} "
            "FROM Account "
            f"WHERE Field76__r.Name {PRODUCT_LIKE} "
            f"AND Field156__c = LAST_N_DAYS:{days}"
            f"{area_filter}"
        )
        rec = sf.query_all(soql)["records"]

        # 同じ母集団に対する代コン系FCの回数を案件IDごとに集計
        # ※ GROUP BY 付きクエリは query_all() ページング不可のため、WhatId だけ
        #   取得して Python 側でカウントする。
        soql_task = (
            "SELECT WhatId FROM Task "
            f"WHERE Field2_del__c IN ({', '.join(DAICON_FC_LABELS)}) "
            "AND WhatId IN ("
            "  SELECT Id FROM Account "
            f"  WHERE Field76__r.Name {PRODUCT_LIKE} "
            f"  AND Field156__c = LAST_N_DAYS:{days}"
            f"  {area_filter}"
            ")"
        )
        fc_count_map: dict[str, int] = defaultdict(int)
        for t in sf.query_all(soql_task)["records"]:
            wid = t.get("WhatId")
            if wid:
                fc_count_map[wid] += 1

        by_period[days] = _analyze(rec, fc_count_map)

    # 全理由の和集合（両期間に出てくるもの）
    all_reasons = set()
    for d in PERIODS:
        for row in by_period[d]["rows"]:
            all_reasons.add(row["reason"])

    # 並び順: 365日経験数の多い順
    base = {row["reason"]: row for row in by_period[365]["rows"]}
    base180 = {row["reason"]: row for row in by_period[180]["rows"]}
    reasons_order = sorted(
        all_reasons,
        key=lambda r: -(base.get(r, {}).get("n") or base180.get(r, {}).get("n", 0))
    )

    return {
        "asof": now.strftime("%Y/%m/%d %H:%M"),
        "periods": PERIODS,
        "by_period": by_period,
        "reasons_order": reasons_order,
        "min_occurrences": MIN_OCCURRENCES,
        "area": area,  # None / '東' / '西'
    }


def classify(open_rate: float) -> str:
    """開通率から切り捨て区分を返す。"""
    if open_rate < 20:
        return "切り捨て推奨"
    if open_rate < 35:
        return "グレーゾーン"
    return "介入価値大"
