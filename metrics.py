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
    key: str                          # 一意なID
    label: str                        # 画面表示名
    description: str                  # 補足説明
    fetch: Callable[[Salesforce], FetchResult]
    group_col: Optional[str] = None   # 棒グラフのカテゴリ軸
    value_col: Optional[str] = None   # 棒グラフの値軸
    category: str = "活動"             # サイドバーのグルーピング用
    list_label: str = "一覧"           # 一覧セクションの見出し（単一表のとき）


# ======================================================================
# 活動 / 1週間後FC ボード
# ======================================================================
def _fetch_1week_pivot(sf: Salesforce, call_result: str) -> pd.DataFrame:
    """対応ステータス=フォローコール（1週間後FC）かつ コール結果=指定値 を
    今月分、日付×担当者でピボット集計。"""
    soql = (
        "SELECT ActivityDate, OwnerId, Owner.Name oname, COUNT(Id) cnt "
        "FROM Task "
        "WHERE Field2_del__c = 'フォローコール（1週間後FC）' "
        f"AND Field4_del__c = '{call_result}' "
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


def fetch_fc_1week(sf: Salesforce) -> Dict[str, pd.DataFrame]:
    return {
        "1週間後FC完了数": _fetch_1week_pivot(sf, "完了"),
        "1週間後FC留守数": _fetch_1week_pivot(sf, "留守"),
    }


# ----------------------------------------------------------------------
# 指標レジストリ
# ----------------------------------------------------------------------
METRICS: list[Metric] = [
    Metric(
        key="fc_1week",
        label="1週間後FC",
        description="対応ステータス='フォローコール（1週間後FC）' の Task を今月分、コール結果別に日付×担当者で集計",
        fetch=fetch_fc_1week,
        category="活動",
    ),
]


def get_metric(key: str) -> Metric:
    for m in METRICS:
        if m.key == key:
            return m
    raise KeyError(key)
