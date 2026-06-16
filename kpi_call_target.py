# -*- coding: utf-8 -*-
"""適正コール数KPI資料（読み取り専用）。

現場の実架電時間モデルと、コール結果別の所要時間から、4種別それぞれの
「1時間あたり適正コール数」「1コール所要時間」を算出する。

KPI第1フェーズ＝架電数/コール数（量）。量を指標化することで必要リソースの圧縮・
人件費等のコスト削減判断が可能。品質は第2フェーズで後付け。

集計: 直近30日 / 対象: CS促進メンバー(User.Department='CS促進' AND IsActive=true)

算出式:
  1コール所要(分) = ( 有効対話数×(平均通話+事務処理) + 留守数×事務処理 ) ÷ 総コール数
  適正コール/h    = 60 ÷ 1コール所要
  1日適正コール    = 実架電420分 ÷ 1コール所要 ( = 適正/h × 7 )
  - 平均通話: Zoom Phone発信ログ(duration)を電話番号+時刻(±20分)で突合した実測平均
  - 事務処理 = 3分（留守も完了も1コールにつき3分）

フィールド: 対応区分=Field3_del__c / 対応ステータス=Field2_del__c /
            コール結果=Field4_del__c / 開通日=Account.Field130__c
"""
from __future__ import annotations

PROC_MIN = 3.0          # 事務処理(分)/コール
CALLING_MIN_PER_DAY = 420   # 実架電時間/日(分) = 在席8h - 10分休憩×6
TALK_ASOF = "2026-06-16"    # 平均通話(Zoom実測)の算出日

# 種別: (表示名, SOQL条件, 条件の説明文, Zoom実測の平均通話(分))
TYPES = [
    ("開通前対応架電（開通日空欄）",
     "Field3_del__c='架電' AND Field2_del__c='対応' AND Account.Field130__c=null",
     "対応区分=架電／対応ステータス=対応／開通日(Field130__c)が空欄",
     4.6),
    ("フォローコール(その他)",
     "Field3_del__c='架電' AND Field2_del__c='フォローコール（その他）'",
     "対応区分=架電／対応ステータス=フォローコール(その他)",
     3.2),
    ("フォローコール(代コン)",
     "Field3_del__c='FC' AND Field2_del__c='フォローコール（代コン）'",
     "対応区分=FC／対応ステータス=フォローコール(代コン)",
     3.8),
    ("フォローコール(工事取得)",
     "Field3_del__c='FC' AND Field2_del__c='フォローコール（工事取得）'",
     "対応区分=FC／対応ステータス=フォローコール(工事取得)",
     5.7),
]


def compute(sf) -> dict:
    cs = [r["Id"] for r in sf.query_all(
        "SELECT Id FROM User WHERE Department='CS促進' AND IsActive=true"
    )["records"]]
    ids_in = ", ".join(f"'{u}'" for u in cs)

    def _cnt(extra: str) -> int:
        return sf.query_all(
            f"SELECT COUNT(Id) n FROM Task WHERE OwnerId IN ({ids_in}) "
            f"AND ActivityDate = LAST_N_DAYS:30 AND {extra}"
        )["records"][0]["n"]

    rows = []
    for name, cond, desc, talk in TYPES:
        tot = _cnt(cond)
        rusu = _cnt(cond + " AND Field4_del__c='留守'")
        eff = tot - rusu
        per_call = ((eff * (talk + PROC_MIN) + rusu * PROC_MIN) / tot) if tot else 0.0
        per_h = (60 / per_call) if per_call else 0.0
        per_day = (CALLING_MIN_PER_DAY / per_call) if per_call else 0.0
        rows.append({
            "name": name,
            "desc": desc,
            "total": tot,
            "rusu": rusu,
            "eff": eff,
            "rusu_rate": (rusu / tot * 100) if tot else 0.0,
            "talk_min": talk,
            "per_call_min": per_call,
            "per_hour": per_h,
            "per_day": per_day,
        })

    return {
        "member_count": len(cs),
        "proc_min": PROC_MIN,
        "calling_min_per_day": CALLING_MIN_PER_DAY,
        "talk_asof": TALK_ASOF,
        "rows": rows,
    }
