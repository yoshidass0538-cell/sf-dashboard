"""ソネット光 × 利用携帯AU/UQ の1次ダイコン理由(=1次停滞理由)分析。

母集団:
  - 取次商材情報: ソネット光 (Field76__r.Name LIKE '%So-net%')
  - 利用携帯&利用台数(Field373__c): AU または UQ を含む（大小無視）
  - エリア(Field43__c): '東' または '西'
  - 1次ダイコン理由(Field242__c): 値あり（空欄除外）
  - エントリ日(Field156__c): 直近 LOOKBACK_DAYS 日

集計:
  - 1次ダイコン理由の値別に
    - 件数（その理由の発生数）
    - 開通数（Field130__c があるもの）
    - 開通率 = 開通数 / 件数 * 100
    - 発生率 = 件数 / その範囲の全件数 * 100
  - エリア: 東 / 西 / 合算
  - 期間: 直近半年合算 + エントリ月別（直近6ヶ月）
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from collections import defaultdict

JST = timezone(timedelta(hours=9))

LOOKBACK_DAYS = 180
PRODUCT_LIKE = "LIKE '%So-net%'"


def _ym(y: int, m: int) -> str:
    return f"{y:04d}-{m:02d}"


def _add_months(y: int, m: int, delta: int) -> tuple[int, int]:
    idx = (y * 12 + (m - 1)) + delta
    return idx // 12, idx % 12 + 1


def compute(sf, now: datetime | None = None) -> dict:
    now = now or datetime.now(JST)

    # SOQL: 母集団取得（AU/UQ判定はSOQLで一次絞り、Python側でcase-insensitive再判定）
    soql = (
        "SELECT Id, Field373__c, Field242__c, Field43__c, "
        "Field156__c, Field130__c "
        "FROM Account "
        f"WHERE Field76__r.Name {PRODUCT_LIKE} "
        f"AND Field156__c = LAST_N_DAYS:{LOOKBACK_DAYS} "
        "AND Field242__c != null "
        "AND Field43__c IN ('東', '西') "
        "AND Field373__c != null "
        "AND (Field373__c LIKE '%AU%' OR Field373__c LIKE '%UQ%')"
    )
    records = sf.query_all(soql)["records"]

    # Python側 case-insensitive 再判定
    def _is_au_uq(s: str | None) -> bool:
        if not s:
            return False
        u = s.upper()
        return ("AU" in u) or ("UQ" in u)

    filtered = []
    for r in records:
        if not _is_au_uq(r.get("Field373__c")):
            continue
        ymd = (r.get("Field156__c") or "")[:7]  # "YYYY-MM"
        if len(ymd) < 7:
            continue
        filtered.append({
            "ym": ymd,
            "area": r["Field43__c"],
            "reason": r["Field242__c"],
            "opened": bool(r.get("Field130__c")),
        })

    # エントリ月リスト（直近6ヶ月 = 当月含む）
    months = []
    for i in range(6):
        y, m = _add_months(now.year, now.month, -(5 - i))
        months.append(_ym(y, m))
    months_set = set(months)

    AREAS = ["東", "西", "合算"]

    # 集計テーブル: { (area, ym): { reason: {"count":x, "open":y} } }
    table: dict[tuple[str, str], dict[str, dict[str, int]]] = defaultdict(
        lambda: defaultdict(lambda: {"count": 0, "open": 0})
    )

    def _add(area_key: str, ym_key: str, reason: str, opened: bool):
        cell = table[(area_key, ym_key)][reason]
        cell["count"] += 1
        if opened:
            cell["open"] += 1

    for f in filtered:
        ar = f["area"]
        ym = f["ym"]
        rs = f["reason"]
        op = f["opened"]
        # 全期間
        _add(ar, "全期間", rs, op)
        _add("合算", "全期間", rs, op)
        # 月別（直近6ヶ月内のみ）
        if ym in months_set:
            _add(ar, ym, rs, op)
            _add("合算", ym, rs, op)

    # 理由は合算全期間の件数降順
    reasons_order = sorted(
        table[("合算", "全期間")].keys(),
        key=lambda k: -table[("合算", "全期間")][k]["count"],
    )

    # 各 (area, ym) の合計（発生率の分母）
    totals = {k: sum(v["count"] for v in d.values()) for k, d in table.items()}

    return {
        "asof": now.strftime("%Y/%m/%d %H:%M"),
        "lookback_days": LOOKBACK_DAYS,
        "areas": AREAS,
        "months": months,
        "reasons_order": reasons_order,
        "table": {f"{a}|{ym}": dict(d) for (a, ym), d in table.items()},
        "totals": {f"{a}|{ym}": v for (a, ym), v in totals.items()},
        "n_filtered": len(filtered),
    }
