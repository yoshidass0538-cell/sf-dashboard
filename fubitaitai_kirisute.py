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


def _analyze(records: list) -> dict:
    """recordsを集計して理由別の経験数・開通数を返す。"""
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
        op = len(opened_set[reason])
        rows.append({
            "reason": reason,
            "n": n,
            "open": op,
            "open_rate": op / n * 100,
            "occur_rate": n / total * 100 if total else 0.0,
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
        by_period[days] = _analyze(rec)

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
