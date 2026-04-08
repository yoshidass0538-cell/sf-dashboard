"""
集計指標の定義

新しい指標を追加するには:
  1. fetch 関数を1つ書く（引数: sf, 戻り値: DataFrame もしくは dict[str, DataFrame]）
  2. METRICS リストに Metric(...) を追加するだけ

fetch が dict を返した場合、ボード上に複数の表として並べて表示される。
"""

from dataclasses import dataclass
from typing import Callable, Optional, Union, Dict
import pandas as pd
from simple_salesforce import Salesforce

FetchResult = Union[pd.DataFrame, Dict[str, pd.DataFrame]]


@dataclass
class Metric:
    key: str
    label: str
    description: str
    fetch: Callable[[Salesforce], FetchResult]
    group_col: Optional[str] = None
    value_col: Optional[str] = None
    category: str = "活動"
    list_label: str = "一覧"


# ======================================================================
# 活動 / 1週間後FC ボード
# ======================================================================
def _pivot_owner_date(df: pd.DataFrame, value_col: str = "件数") -> pd.DataFrame:
    """担当者を行、日付を列にしたピボット表に整形し、合計列を付与する。"""
    if df.empty:
        return df
    pivot = df.pivot_table(
        index="担当者", columns="日付", values=value_col, fill_value=0
    )
    pivot["合計"] = pivot.sum(axis=1)
    return pivot.reset_index()


METRIC_ORDER = [
    ("総コール数", None,    "count"),
    ("完了数",     "完了",   "count"),
    ("完了率",     "完了",   "rate"),
    ("留守数",     "留守",   "count"),
    ("留守率",     "留守",   "rate"),
    ("再コール数", "再コール", "count"),
    ("再コール率", "再コール", "rate"),
    ("対応依頼数", "対応依頼", "count"),
    ("対応依頼率", "対応依頼", "rate"),
]


def fetch_fc_1week(sf: Salesforce) -> Dict[str, pd.DataFrame]:
    soql = (
        "SELECT ActivityDate, OwnerId, Owner.Name oname, "
        "Field4_del__c result, COUNT(Id) cnt "
        "FROM Task "
        "WHERE Field2_del__c = 'フォローコール（1週間後FC）' "
        "AND ActivityDate = THIS_MONTH "
        "GROUP BY ActivityDate, OwnerId, Owner.Name, Field4_del__c"
    )
    res = sf.query(soql)
    rows = [
        {
            "日付": str(r["ActivityDate"]),
            "担当者": r.get("oname") or r["OwnerId"],
            "結果": r.get("result") or "(未設定)",
            "件数": r["cnt"],
        }
        for r in res["records"]
    ]
    raw = pd.DataFrame(rows)
    if raw.empty:
        return {"1週間後FC": pd.DataFrame()}

    dates = sorted(raw["日付"].unique().tolist())
    owners = sorted(raw["担当者"].unique().tolist())

    # (担当者, 日付) → 総件数
    total_cell = raw.groupby(["担当者", "日付"])["件数"].sum().unstack(fill_value=0)
    total_cell = total_cell.reindex(index=owners, columns=dates, fill_value=0)
    total_owner = total_cell.sum(axis=1)

    out_rows = []
    for owner in owners:
        for label, result_value, kind in METRIC_ORDER:
            row = {"担当者": owner, "指標": label}
            if result_value is None:
                # 総コール数
                for d in dates:
                    row[d] = int(total_cell.loc[owner, d])
                row["合計"] = int(total_owner.loc[owner])
            else:
                sub = raw[(raw["担当者"] == owner) & (raw["結果"] == result_value)]
                by_date = sub.groupby("日付")["件数"].sum()
                if kind == "count":
                    for d in dates:
                        row[d] = int(by_date.get(d, 0))
                    row["合計"] = int(by_date.sum())
                else:  # rate
                    for d in dates:
                        denom = total_cell.loc[owner, d]
                        num = by_date.get(d, 0)
                        row[d] = f"{round(num / denom * 100, 1)}%" if denom else "-"
                    denom_total = total_owner.loc[owner]
                    num_total = by_date.sum()
                    row["合計"] = f"{round(num_total / denom_total * 100, 1)}%" if denom_total else "-"
            out_rows.append(row)

    df = pd.DataFrame(out_rows, columns=["担当者", "指標", *dates, "合計"])
    for col in df.columns:
        if col in ("担当者", "指標"):
            continue
        df[col] = df[col].map(lambda v: "" if v == 0 else str(v))
    df["担当者"] = df["担当者"].mask(df["担当者"].duplicated(), "")

    cancel_tables = _fetch_1week_cancel_reasons(sf)
    return {"1週間後FC": df, **cancel_tables}


def _fetch_1week_cancel_reasons(sf: Salesforce) -> Dict[str, pd.DataFrame]:
    """今月1週間後FCを行った案件のうち、その後キャンセル対応に至ったものを
    担当者(FC実施者)×キャンセル理由(Account.Field234__c) で集計。"""
    fc_records = sf.query_all(
        "SELECT WhatId, Owner.Name, ActivityDate "
        "FROM Task "
        "WHERE Field2_del__c = 'フォローコール（1週間後FC）' "
        "AND ActivityDate = THIS_MONTH "
        "AND WhatId != null"
    )["records"]
    # WhatId が Account(001) のもののみ
    fc_map: Dict[str, list] = {}
    for r in fc_records:
        wid = r["WhatId"]
        if not wid or not wid.startswith("001"):
            continue
        fc_map.setdefault(wid, []).append(
            (r["Owner"]["Name"] if r.get("Owner") else "(不明)", r["ActivityDate"])
        )
    if not fc_map:
        return {}

    what_ids = list(fc_map.keys())
    cancel_set = set()
    for i in range(0, len(what_ids), 200):
        chunk = what_ids[i : i + 200]
        ids_str = ",".join(f"'{x}'" for x in chunk)
        rs = sf.query_all(
            f"SELECT WhatId, ActivityDate FROM Task "
            f"WHERE Field2_del__c = 'キャンセル対応' AND WhatId IN ({ids_str})"
        )["records"]
        for r in rs:
            wid = r["WhatId"]
            if wid not in fc_map:
                continue
            for _owner, fc_date in fc_map[wid]:
                if (
                    not fc_date
                    or not r["ActivityDate"]
                    or r["ActivityDate"] >= fc_date
                ):
                    cancel_set.add(wid)
                    break
    if not cancel_set:
        return {}

    reason_map: Dict[str, dict] = {}
    cw = list(cancel_set)
    for i in range(0, len(cw), 200):
        chunk = cw[i : i + 200]
        ids_str = ",".join(f"'{x}'" for x in chunk)
        rs = sf.query_all(
            f"SELECT Id, Field234__c, Field80__c, Field235__c "
            f"FROM Account WHERE Id IN ({ids_str})"
        )["records"]
        for r in rs:
            reason_map[r["Id"]] = {
                "大": r.get("Field234__c") or "(理由未設定)",
                "中": r.get("Field80__c") or "(中区分未設定)",
                "小": r.get("Field235__c") or "(小区分未設定)",
            }

    rows = []
    for wid in cancel_set:
        r = reason_map.get(wid, {"大": "(理由未設定)", "中": "(中区分未設定)", "小": "(小区分未設定)"})
        for owner in {o for o, _ in fc_map[wid]}:
            rows.append({"担当者": owner, **r, "件数": 1})
    if not rows:
        return {}
    base = pd.DataFrame(rows)

    def _pivot(df: pd.DataFrame, col: str) -> pd.DataFrame:
        if df.empty:
            return df
        g = df.groupby(["担当者", col], as_index=False)["件数"].sum()
        p = g.pivot_table(index="担当者", columns=col, values="件数", fill_value=0)
        p["合計"] = p.sum(axis=1)
        return p.sort_values("合計", ascending=False).reset_index()

    tables = {
        "1週間後FC後のキャンセル理由（大区分）": _pivot(base, "大"),
        "└ 意思無し系 内訳（中区分）": _pivot(base[base["大"] == "意思無し系"], "中"),
        "　 意思無し系 内訳（小区分）": _pivot(base[base["大"] == "意思無し系"], "小"),
        "└ 認識相違系 内訳（中区分）": _pivot(base[base["大"] == "認識相違系"], "中"),
        "　 認識相違系 内訳（小区分）": _pivot(base[base["大"] == "認識相違系"], "小"),
    }
    return tables


# ----------------------------------------------------------------------
# 指標レジストリ
# ----------------------------------------------------------------------
METRICS: list[Metric] = [
    Metric(
        key="fc_1week",
        label="1週間後FC",
        description="対応ステータス='フォローコール（1週間後FC）' の Task を今月分、コール結果別に担当者×日付で集計（率は日別に算出）",
        fetch=fetch_fc_1week,
        category="活動",
    ),
]


def get_metric(key: str) -> Metric:
    for m in METRICS:
        if m.key == key:
            return m
    raise KeyError(key)
