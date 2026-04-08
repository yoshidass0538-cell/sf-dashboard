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

    tables: Dict[str, pd.DataFrame] = {}

    # 総コール数（結果問わず）
    if raw.empty:
        total = pd.DataFrame()
    else:
        total = raw.groupby(["担当者", "日付"], as_index=False)["件数"].sum()
    tables["1週間後FC総コール数"] = _pivot_owner_date(total)

    # 結果別件数
    result_specs = [
        ("完了", "1週間後FC完了数"),
        ("留守", "1週間後FC留守数"),
        ("再コール", "1週間後FC再コール数"),
        ("対応依頼", "1週間後FC対応依頼数"),
    ]
    counts_by_result: Dict[str, pd.DataFrame] = {}
    for result_value, title in result_specs:
        sub = raw[raw["結果"] == result_value][["担当者", "日付", "件数"]] if not raw.empty else raw
        counts_by_result[result_value] = sub
        tables[title] = _pivot_owner_date(sub)

    # 率（担当者×日付セル単位で 結果件数 / 総コール件数）
    if not raw.empty:
        total_cell = raw.groupby(["担当者", "日付"], as_index=False)["件数"].sum()
        total_cell = total_cell.rename(columns={"件数": "総"})
        rate_specs = [
            ("完了", "1週間後FC完了率"),
            ("留守", "1週間後FC留守率"),
            ("対応依頼", "1週間後FC対応依頼率"),
            ("再コール", "1週間後FC再コール率"),
        ]
        for result_value, title in rate_specs:
            sub = counts_by_result[result_value]
            if sub.empty:
                tables[title] = pd.DataFrame()
                continue
            merged = sub.merge(total_cell, on=["担当者", "日付"], how="right").fillna(0)
            merged["率"] = (merged["件数"] / merged["総"] * 100).round(1)
            pivot = merged.pivot_table(
                index="担当者", columns="日付", values="率", fill_value=0
            )
            # 担当者ごとの全期間平均率（合計件数ベース）
            owner_total = (
                merged.groupby("担当者")[["件数", "総"]].sum()
            )
            pivot["合計"] = (
                (owner_total["件数"] / owner_total["総"] * 100).round(1)
            )
            pivot = pivot.reset_index()
            # 表示を "12.3%" にする
            for col in pivot.columns:
                if col == "担当者":
                    continue
                pivot[col] = pivot[col].map(lambda v: f"{v}%")
            tables[title] = pivot
    else:
        for _, title in [
            ("完了", "1週間後FC完了率"),
            ("留守", "1週間後FC留守率"),
            ("対応依頼", "1週間後FC対応依頼率"),
            ("再コール", "1週間後FC再コール率"),
        ]:
            tables[title] = pd.DataFrame()

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
