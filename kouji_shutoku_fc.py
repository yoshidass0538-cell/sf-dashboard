"""工事取得FC資料用の集計ロジック（読み取り専用・Salesforce参照のみ）。

目的:
  「工事取得FC」(Task.Field2_del__c='フォローコール（工事取得）') の架電回数別に
  開通率・限界効用・累積開通率を算出し、適正架電回数を可視化する。

母集団:
  - ソネット光 (Account.Field76__r.Name LIKE '%So-net%')
  - 直近 LOOKBACK_DAYS 日にエントリ (Field156__c) または開通 (Field130__c) した結果確定案件
  - 結果確定 = 開通済み (Field130__c) または キャンセル済み (Field119__c)
  - 工事取得FC回数 = Account.Field194__c（SFが直接保持する集計値）

データ:
  - dist0: 工事取得FC回数=0 を含む全体分布（開通/CX/進行中の集計用）
  - dist:  工事取得FC回数>0 のみの分布（平均・限界効用の主分析）
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from collections import defaultdict

JST = timezone(timedelta(hours=9))

LOOKBACK_DAYS = 180
PRODUCT_LIKE = "LIKE '%So-net%'"


def compute(sf, now: datetime | None = None) -> dict:
    now = now or datetime.now(JST)

    # 1. 結果確定 (開通 or キャンセル)・直近180日エントリのソネット光
    soql_outcome = (
        "SELECT Id, Field194__c, Field130__c, Field119__c, Field156__c "
        "FROM Account "
        f"WHERE Field76__r.Name {PRODUCT_LIKE} "
        f"AND Field156__c = LAST_N_DAYS:{LOOKBACK_DAYS} "
        "AND (Field130__c != null OR Field119__c != null)"
    )
    rec_out = sf.query_all(soql_outcome)["records"]

    # 2. 直近180日開通ソネット光（開通から見た平均算出用 — Field194__c > 0 のみ抽出は描画側で）
    soql_kaitsu = (
        "SELECT Id, Field194__c, Field130__c "
        "FROM Account "
        f"WHERE Field76__r.Name {PRODUCT_LIKE} "
        f"AND Field130__c = LAST_N_DAYS:{LOOKBACK_DAYS}"
    )
    rec_k = sf.query_all(soql_kaitsu)["records"]

    # ====== 回数別 開通/CX バケット (母集団=結果確定案件) ======
    bucket: dict[int, dict[str, int]] = defaultdict(lambda: {"開通": 0, "CX": 0})
    for r in rec_out:
        n = int(r.get("Field194__c") or 0)
        if r.get("Field130__c"):
            bucket[n]["開通"] += 1
        elif r.get("Field119__c"):
            bucket[n]["CX"] += 1
    total_out = len(rec_out)
    total_open = sum(v["開通"] for v in bucket.values())
    total_cx = sum(v["CX"] for v in bucket.values())

    # ====== 開通案件の Field194__c 分布（>0 のみ）======
    fc_counts_pos: list[int] = []  # >0 のみ
    fc_counts_all: list[int] = []  # 0 含む全件
    for r in rec_k:
        n = int(r.get("Field194__c") or 0)
        fc_counts_all.append(n)
        if n > 0:
            fc_counts_pos.append(n)

    avg_pos = (sum(fc_counts_pos) / len(fc_counts_pos)) if fc_counts_pos else 0.0
    avg_all = (sum(fc_counts_all) / len(fc_counts_all)) if fc_counts_all else 0.0
    sorted_pos = sorted(fc_counts_pos)
    med_pos = _median(sorted_pos)
    p75 = _percentile(sorted_pos, 75)
    p90 = _percentile(sorted_pos, 90)

    kaitsu_total = len(rec_k)
    kaitsu_zero = sum(1 for v in fc_counts_all if v == 0)

    # 回数別件数（開通案件・>0のみ）
    dist_pos: dict[int, int] = defaultdict(int)
    for v in fc_counts_pos:
        dist_pos[v] += 1

    # ====== 集約バケット（開通率） ======
    def _bk(n: int) -> str:
        if n == 0: return "0回"
        if n <= 2: return "1〜2回"
        if n <= 4: return "3〜4回"
        if n <= 6: return "5〜6回"
        if n <= 9: return "7〜9回"
        return "10回以上"

    agg: dict[str, dict[str, int]] = defaultdict(lambda: {"開通": 0, "CX": 0})
    for n, v in bucket.items():
        b = _bk(n)
        agg[b]["開通"] += v["開通"]
        agg[b]["CX"] += v["CX"]

    # ====== N回目の限界効用 ======
    # N回到達群 = Field194__c >= N の母集団（結果確定案件のみ）
    # ちょうどN回で開通 = bucket[N]["開通"]
    marginal = []
    nmax = max(bucket.keys()) if bucket else 0
    for N in range(1, min(nmax, 15) + 1):
        reach = sum(bucket[k]["開通"] + bucket[k]["CX"] for k in bucket if k >= N)
        exact_open = bucket[N]["開通"]
        rate = (exact_open / reach * 100) if reach else 0.0
        marginal.append({"N": N, "reach": reach, "exact_open": exact_open, "rate": rate})

    # ====== 累積開通率（1回以上母集団基準） ======
    # 「N回までに開通した件数 / 1回以上架電された総案件数」
    pos_total = sum(bucket[k]["開通"] + bucket[k]["CX"] for k in bucket if k >= 1)
    cumulative = []
    cum_open = 0
    for N in sorted([k for k in bucket if k >= 1]):
        cum_open += bucket[N]["開通"]
        cumulative.append({
            "N": N, "cum_open": cum_open,
            "rate": (cum_open / pos_total * 100) if pos_total else 0.0,
        })

    return {
        "asof": now.strftime("%Y/%m/%d %H:%M"),
        "lookback_days": LOOKBACK_DAYS,
        # KPI 4 数字
        "kpi": {
            "kaitsu_total": kaitsu_total,
            "fc_zero_rate": (kaitsu_zero / kaitsu_total * 100) if kaitsu_total else 0.0,
            "fc_zero_count": kaitsu_zero,
            "avg_pos": avg_pos,
            "median_pos": med_pos,
        },
        "outcome_total": total_out,
        "outcome_open": total_open,
        "outcome_cx": total_cx,
        "bucket": dict(bucket),     # 回数 → {開通, CX}
        "agg": dict(agg),           # 集約バケット
        "marginal": marginal,       # N回目の限界効用
        "cumulative": cumulative,   # 累積開通率
        "dist_pos": dict(dist_pos), # 開通案件の>0分布
        "avg_pos": avg_pos,
        "avg_all": avg_all,
        "median_pos": med_pos,
        "p75_pos": p75,
        "p90_pos": p90,
        "kaitsu_zero": kaitsu_zero,
        "kaitsu_zero_rate": (kaitsu_zero / kaitsu_total * 100) if kaitsu_total else 0.0,
        "kaitsu_total": kaitsu_total,
        "pos_total": pos_total,
    }


def _median(sorted_vals: list[int]) -> float:
    n = len(sorted_vals)
    if not n:
        return 0.0
    if n % 2 == 1:
        return float(sorted_vals[n // 2])
    return (sorted_vals[n // 2 - 1] + sorted_vals[n // 2]) / 2


def _percentile(sorted_vals: list[int], p: int) -> float:
    if not sorted_vals:
        return 0.0
    k = (len(sorted_vals) - 1) * p / 100
    f = int(k)
    c = min(f + 1, len(sorted_vals) - 1)
    if f == c:
        return float(sorted_vals[f])
    return sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f)
