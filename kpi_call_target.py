# -*- coding: utf-8 -*-
"""適正コール数KPI資料（読み取り専用）。

現場の実架電時間モデルと、コール結果別の所要時間から、各コール種別ごとの
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

import re

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
    ("フォローコール(1週間後)",
     "Field3_del__c='FC' AND Field2_del__c='フォローコール（1週間後FC）'",
     "対応区分=FC／対応ステータス=フォローコール(1週間後FC)",
     5.2),
    ("フォローコール(代コン)",
     "Field3_del__c='FC' AND Field2_del__c='フォローコール（代コン）'",
     "対応区分=FC／対応ステータス=フォローコール(代コン)",
     3.8),
    ("フォローコール(工事取得)",
     "Field3_del__c='FC' AND Field2_del__c='フォローコール（工事取得）'",
     "対応区分=FC／対応ステータス=フォローコール(工事取得)",
     5.7),
    ("キャンセル対応",
     "Field3_del__c='架電' AND Field2_del__c='キャンセル対応'",
     "対応区分=架電／対応ステータス=キャンセル対応",
     3.47),
    ("決済促進",
     "Field3_del__c='FC' AND Field2_del__c='フォローコール（決済促進）'",
     "対応区分=FC／対応ステータス=フォローコール(決済促進)",
     3.22),
    ("開通後①",
     "Field3_del__c='FC' AND Field2_del__c='フォローコール（開通後①）'",
     "対応区分=FC／対応ステータス=フォローコール(開通後①)",
     3.61),
    ("開通後②",
     "Field3_del__c='FC' AND Field2_del__c='フォローコール（開通後②）'",
     "対応区分=FC／対応ステータス=フォローコール(開通後②)",
     3.72),
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


def compute_individual(sf, date_filter: str = "ActivityDate = LAST_N_DAYS:30") -> dict:
    """個人別のコール種別集計（合算＋日別）。各種別を 有効対話/留守 に分けて集計。

    date_filter: SOQLの日付条件（既定=直近30日。⑤の月タブは月範囲を渡す）。

    per_type[種別名] = (有効対話数, 留守数, 合計)。
    想定所要 = Σ種別( 有効対話×(平均通話+事務3分) + 留守×事務3分 )（各人の実有効/留守で算出）。
    充足率 = 想定所要/日 ÷ 実架電420分。対象種別が標準ペースで実架電時間をどれだけ
    埋めているかの目安（他業務は含まない）。CS1〜CS7（共有アカウント）は非表示。
    """
    cs = sf.query_all(
        "SELECT Id, Name FROM User WHERE Department='CS促進' AND IsActive=true"
    )["records"]
    names = {
        r["Id"]: r["Name"] for r in cs
        if not re.fullmatch(r"CS[1-7]", (r["Name"] or "").strip())
    }
    if not names:
        return {"type_names": [t[0] for t in TYPES], "members": [], "daily": {}}
    ids_in = ", ".join(f"'{u}'" for u in names)
    type_names = [t[0] for t in TYPES]
    talk_of = {t[0]: t[3] for t in TYPES}

    # cell[(uid, date, 種別名)] = [総数, 留守数]
    cell: dict = {}
    dates: set = set()
    for tname, cond, _desc, _talk in TYPES:
        for r in sf.query_all(
            f"SELECT OwnerId oid, ActivityDate d, COUNT(Id) n FROM Task "
            f"WHERE OwnerId IN ({ids_in}) AND {date_filter} AND {cond} "
            "GROUP BY OwnerId, ActivityDate"
        )["records"]:
            cell.setdefault((r["oid"], r["d"], tname), [0, 0])[0] = r["n"]
            dates.add(r["d"])
        for r in sf.query_all(
            f"SELECT OwnerId oid, ActivityDate d, COUNT(Id) n FROM Task "
            f"WHERE OwnerId IN ({ids_in}) AND {date_filter} AND {cond} "
            "AND Field4_del__c='留守' GROUP BY OwnerId, ActivityDate"
        )["records"]:
            cell.setdefault((r["oid"], r["d"], tname), [0, 0])[1] = r["n"]
            dates.add(r["d"])

    # 全架電/FC（5種別以外も含む）コール数（参考＝シェア算出用）
    all_calls: dict = {}
    for r in sf.query_all(
        f"SELECT OwnerId oid, COUNT(Id) n FROM Task "
        f"WHERE OwnerId IN ({ids_in}) AND {date_filter} "
        "AND Field3_del__c IN ('架電','FC') GROUP BY OwnerId"
    )["records"]:
        all_calls[r["oid"]] = r["n"]

    def _er(uid, d, tn):
        c = cell.get((uid, d, tn), [0, 0])
        return c[0] - c[1], c[1]  # (有効, 留守)

    def _est(uid, d):
        e = 0.0
        for tn in type_names:
            eff, rus = _er(uid, d, tn)
            e += eff * (talk_of[tn] + PROC_MIN) + rus * PROC_MIN
        return e

    members = []
    for uid, name in names.items():
        per_type = {}
        for tn in type_names:
            tot = sum(cell.get((uid, d, tn), [0, 0])[0] for d in dates)
            rus = sum(cell.get((uid, d, tn), [0, 0])[1] for d in dates)
            per_type[tn] = (tot - rus, rus, tot)  # (有効, 留守, 合計)
        total = sum(v[2] for v in per_type.values())
        if total == 0:
            continue
        workdays = len({d for d in dates if any(cell.get((uid, d, tn), [0, 0])[0] for tn in type_names)})
        est_min = sum(_est(uid, d) for d in dates)
        per_day_min = (est_min / workdays) if workdays else 0.0
        rate = (per_day_min / CALLING_MIN_PER_DAY * 100) if workdays else 0.0
        allc = all_calls.get(uid, 0)
        members.append({
            "uid": uid, "name": name, "per_type": per_type, "total": total,
            "all_calls": allc, "share": (total / allc * 100) if allc else 0.0,
            "workdays": workdays, "est_min": est_min, "per_day_min": per_day_min, "rate": rate,
        })
    members.sort(key=lambda m: -m["total"])

    daily: dict = {}
    for uid in names:
        rs = []
        for d in sorted(dates):
            pt = {}
            for tn in type_names:
                c = cell.get((uid, d, tn), [0, 0])
                pt[tn] = (c[0] - c[1], c[1], c[0])  # (有効, 留守, 合計)
            tcalls = sum(v[2] for v in pt.values())
            if tcalls == 0:
                continue
            est = _est(uid, d)
            rs.append({
                "date": d, "per_type": pt, "total": tcalls,
                "est_min": est, "rate": est / CALLING_MIN_PER_DAY * 100,
            })
        if rs:
            daily[uid] = rs

    return {"type_names": type_names, "members": members, "daily": daily}
