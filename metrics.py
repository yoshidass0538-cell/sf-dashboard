"""
集計指標の定義

新しい指標を追加するには:
  1. fetch 関数を1つ書く（引数: sf, 戻り値: pandas.DataFrame）
  2. METRICS リストに Metric(...) を追加するだけ

DataFrame は最低 1 つのカテゴリ列と 1 つの数値列を持つこと。
group_col / value_col で明示すれば棒グラフが自動描画される。
"""

from dataclasses import dataclass
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
    list_label: str = "一覧"           # 一覧セクションの見出し


# ======================================================================
# 活動 / 1週間後FC ボード
#   対応ステータス='フォローコール（1週間後FC）' かつ
#   コール結果='完了' の Task を今月分、日付×担当者で集計
# ======================================================================
def fetch_fc_1week(sf: Salesforce) -> pd.DataFrame:
    soql = (
        "SELECT ActivityDate, OwnerId, Owner.Name oname, COUNT(Id) cnt "
        "FROM Task "
        "WHERE Field2_del__c = 'フォローコール（1週間後FC）' "
        "AND Field4_del__c = '完了' "
        "AND ActivityDate = THIS_MONTH "
        "GROUP BY ActivityDate, OwnerId, Owner.Name "
        "ORDER BY ActivityDate"
    )
    res = sf.query(soql)
    rows = [
        {
            "日付": str(r["ActivityDate"]),
            "担当者": r.get("oname") or r["OwnerId"],
            "件数": r["cnt"],
        }
        for r in res["records"]
    ]
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    pivot = df.pivot_table(
        index="日付", columns="担当者", values="件数", fill_value=0
    )
    pivot["合計"] = pivot.sum(axis=1)
    return pivot.reset_index()


# ----------------------------------------------------------------------
# 指標レジストリ
# ----------------------------------------------------------------------
METRICS: list[Metric] = [
    Metric(
        key="fc_1week",
        label="1週間後FC",
        description="対応ステータス='フォローコール（1週間後FC）' かつ コール結果='完了' の Task を今月分、日付×担当者で集計",
        fetch=fetch_fc_1week,
        group_col="日付",
        value_col=None,
        category="活動",
        list_label="1週間後FC完了数",
    ),
]


def get_metric(key: str) -> Metric:
    for m in METRICS:
        if m.key == key:
            return m
    raise KeyError(key)
