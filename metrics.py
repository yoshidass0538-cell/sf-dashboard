"""
集計指標の定義

新しい指標を追加するには:
  1. fetch 関数を1つ書く（引数: sf, 戻り値: pandas.DataFrame）
  2. METRICS リストに Metric(...) を追加するだけ

DataFrame は最低 1 つのカテゴリ列と 1 つの数値列を持つこと。
group_col / value_col で明示すれば棒グラフが自動描画される。
"""

from dataclasses import dataclass, field
from typing import Callable, Optional
import pandas as pd
from simple_salesforce import Salesforce


@dataclass
class Metric:
    key: str                          # 一意なID
    label: str                        # 画面表示名
    description: str                  # 補足説明
    fetch: Callable[[Salesforce], pd.DataFrame]
    group_col: Optional[str] = None   # 棒グラフのカテゴリ軸
    value_col: Optional[str] = None   # 棒グラフの値軸
    category: str = "活動"             # サイドバーのグルーピング用


# ----------------------------------------------------------------------
# 指標 1: 今月の FC 件数（担当者別）
# ----------------------------------------------------------------------
def fetch_fc_this_month(sf: Salesforce) -> pd.DataFrame:
    soql = (
        "SELECT OwnerId, Owner.Name oname, COUNT(Id) cnt "
        "FROM Task "
        "WHERE Subject = 'FC' AND ActivityDate = THIS_MONTH "
        "GROUP BY OwnerId, Owner.Name "
        "ORDER BY COUNT(Id) DESC"
    )
    res = sf.query(soql)
    rows = [
        {"担当者": r.get("oname") or r["OwnerId"], "件数": r["cnt"]}
        for r in res["records"]
    ]
    return pd.DataFrame(rows)


# ----------------------------------------------------------------------
# 指標レジストリ
#   ↓ ここに追記していくだけで画面に増えます
# ----------------------------------------------------------------------
METRICS: list[Metric] = [
    Metric(
        key="fc_this_month",
        label="今月のFC件数（担当者別）",
        description="Subject='FC' かつ ActivityDate が今月の Task を担当者別に集計",
        fetch=fetch_fc_this_month,
        group_col="担当者",
        value_col="件数",
        category="活動",
    ),
]


def get_metric(key: str) -> Metric:
    for m in METRICS:
        if m.key == key:
            return m
    raise KeyError(key)
