# -*- coding: utf-8 -*-
"""NURO消セン抑止FC 日報の本文を組み立てる（Chatwork送信用）。

対象日(1日分)の 吉田 颯/室谷 慧/原田 綾子/ALL について、対応ステータス区分別の
合計コール数・完了数/率・留守数/率 を抜粋して整形する。
  - 対応区分=架電(Field3_del__c) / 対応ステータス=Field2_del__c / コール結果=Field4_del__c
  - 合計コール数 = 完了+留守+再コール
  - 率 = 各数 ÷ 合計コール数
"""
from datetime import date

# (対応ステータス値, 表示名)
CATS = [
    ("フォローコール（その他）", "フォローコール(その他)"),
    ("対応", "開通前対応"),
    ("フォローコール（1週間後FC）", "フォローコール(1週間後FC)"),
    ("フォローコール（代コン）", "フォローコール(代コン)"),
    ("フォローコール（工事取得）", "フォローコール(工事取得)"),
]
MEMBERS = [("吉田 颯", "吉田 颯"), ("室谷 慧", "室谷"), ("原田 綾子", "原田")]


def _pct(n: int, d: int) -> str:
    return f"{n / d * 100:.0f}%" if d else "-"


def _counts(sf, uid_list: list, date_iso: str) -> dict:
    """{対応ステータス値: {完了,留守,再コール: 件数}} を返す。"""
    if not uid_list:
        return {}
    ids_in = ", ".join(f"'{u}'" for u in uid_list)
    cats_in = ", ".join(f"'{s}'" for s, _ in CATS)
    out: dict = {}
    for r in sf.query_all(
        "SELECT Field2_del__c s, Field4_del__c k, COUNT(Id) n FROM Task "
        f"WHERE OwnerId IN ({ids_in}) AND ActivityDate = {date_iso} "
        f"AND Field3_del__c = '架電' AND Field2_del__c IN ({cats_in}) "
        "AND Field4_del__c IN ('完了','留守','再コール') "
        "GROUP BY Field2_del__c, Field4_del__c"
    )["records"]:
        out.setdefault(r["s"], {})[r["k"]] = r["n"]
    return out


def _cat_block(cnt: dict, sval: str) -> tuple:
    c = cnt.get(sval, {})
    kan, rus, sai = c.get("完了", 0), c.get("留守", 0), c.get("再コール", 0)
    total = kan + rus + sai
    lines = [
        f"合計コール数：{total}",
        f"完了数：{kan}",
        f"完了率：{_pct(kan, total)}",
        f"留守数：{rus}",
        f"留守率：{_pct(rus, total)}",
    ]
    return total, lines


def _total_calls(cnt: dict) -> int:
    return sum(
        cnt.get(s, {}).get("完了", 0) + cnt.get(s, {}).get("留守", 0) + cnt.get(s, {}).get("再コール", 0)
        for s, _ in CATS
    )


def _member_section(label: str, cnt: dict, with_extras: bool) -> str:
    out = [f"【{label}】", f"トータルコール数：{_total_calls(cnt)}", "▼フォローコール(その他)"]
    _, l = _cat_block(cnt, "フォローコール（その他）")
    out += l
    if with_extras:
        for sval, disp in CATS:
            if sval == "フォローコール（その他）":
                continue
            t, l = _cat_block(cnt, sval)
            if t > 0:  # コール数があるときだけ表示
                out.append(f"▼{disp}")
                out += l
    return "\n".join(out)


def build_report(sf, target_date: date) -> str:
    date_iso = target_date.isoformat()
    md = f"{target_date.month}/{target_date.day}"

    def _uid(like: str):
        rs = sf.query(
            f"SELECT Id FROM User WHERE Name LIKE '{like}%' AND IsActive = true ORDER BY Name"
        )["records"]
        return rs[0]["Id"] if rs else None

    uids = {lbl: _uid(like) for lbl, like in MEMBERS}
    all_ids = [u for u in uids.values() if u]

    sections = [_member_section("ALL", _counts(sf, all_ids, date_iso), with_extras=False)]
    for lbl, _ in MEMBERS:
        u = uids[lbl]
        sections.append(_member_section(lbl, _counts(sf, [u] if u else [], date_iso), with_extras=True))

    return (
        f"[info][title]NURO消セン抑止FC 日報 ({md})[/title]\n"
        + "\n\n".join(sections)
        + "\n[/info]"
    )
