# -*- coding: utf-8 -*-
"""NURO消セン抑止FC 日報の本文を組み立てる（Chatwork送信用）。

対象日(1日分)の 吉田 颯/室谷 慧/原田 綾子/ALL について、対応ステータス区分別の
合計コール数・完了数/率・留守数/率 を抜粋して整形する。
  - 対応区分=架電(Field3_del__c) / 対応ステータス=Field2_del__c / コール結果=Field4_del__c
  - 合計コール数 = 完了+留守+再コール
  - 率 = 各数 ÷ 合計コール数
  - 完了平均対話時間 = 完了コールの Zoom Phone 発信ログ(duration)を電話番号+時刻(±20分)で
    突合した平均。Zoom資格情報(ZOOM_*)が無い/失敗時は「-」（日報送信は継続）。
"""
import os
import re
import base64
from datetime import date, datetime, timezone, timedelta

import requests

# (対応ステータス値, 表示名)
CATS = [
    ("フォローコール（その他）", "フォローコール(その他)"),
    ("対応", "開通前対応"),
    ("フォローコール（1週間後FC）", "フォローコール(1週間後FC)"),
    ("フォローコール（代コン）", "フォローコール(代コン)"),
    ("フォローコール（工事取得）", "フォローコール(工事取得)"),
]
MEMBERS = [("吉田 颯", "吉田 颯"), ("室谷 慧", "室谷"), ("原田 綾子", "原田")]

# 日報の宛先(Chatwork TO)
TO_HEADER = (
    "[To:4051103]沖中　駿也(火土休み)さん\n"
    "[To:11168638]原田　綾子さん\n"
    "[To:11172420]室谷　慧さん\n"
)

_WIN = 20 * 60  # Zoom突合の時刻許容(秒)
_UTC = timezone.utc


def _pct(n: int, d: int) -> str:
    return f"{n / d * 100:.0f}%" if d else "-"


def _e164(p: str | None) -> str | None:
    d = re.sub(r"\D", "", p or "")
    return "+81" + d[1:] if d.startswith("0") and len(d) >= 10 else None


def _fmt_talk(sec) -> str:
    if sec is None:
        return "-"
    m = int(sec // 60)
    s = int(round(sec % 60))
    if s == 60:
        m += 1
        s = 0
    return f"{m}分{s:02d}秒"


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


def _kanryo_records(sf, uid_list: list, date_iso: str) -> dict:
    """完了コールの {対応ステータス値: [(e164, dt_utc), ...]} を返す（Zoom突合用）。"""
    if not uid_list:
        return {}
    ids_in = ", ".join(f"'{u}'" for u in uid_list)
    cats_in = ", ".join(f"'{s}'" for s, _ in CATS)
    out: dict = {}
    for r in sf.query_all(
        "SELECT Account.X1__c, Field1_del__c, Field2_del__c FROM Task "
        f"WHERE OwnerId IN ({ids_in}) AND ActivityDate = {date_iso} "
        f"AND Field3_del__c = '架電' AND Field2_del__c IN ({cats_in}) "
        "AND Field4_del__c = '完了'"
    )["records"]:
        ph = (r.get("Account") or {}).get("X1__c")
        dt = r.get("Field1_del__c")
        sval = r.get("Field2_del__c")
        n = _e164(ph)
        if n and dt:
            out.setdefault(sval, []).append(
                (n, datetime.fromisoformat(dt.replace("Z", "+00:00")).astimezone(_UTC))
            )
    return out


def _build_zoom_index(date_iso: str) -> dict:
    """指定日の Zoom Phone outbound 発信ログを {callee_number: [(dt_utc, duration秒)]} で返す。"""
    aid = os.environ["ZOOM_ACCOUNT_ID"]
    cid = os.environ["ZOOM_CLIENT_ID"]
    cs = os.environ["ZOOM_CLIENT_SECRET"]
    at = requests.post(
        "https://zoom.us/oauth/token",
        params={"grant_type": "account_credentials", "account_id": aid},
        headers={"Authorization": "Basic " + base64.b64encode(f"{cid}:{cs}".encode()).decode()},
        timeout=30,
    ).json()["access_token"]
    H = {"Authorization": "Bearer " + at}
    zidx: dict = {}
    tok = None
    while True:
        pr = {"from": date_iso, "to": date_iso, "page_size": 300}
        if tok:
            pr["next_page_token"] = tok
        j = requests.get("https://api.zoom.us/v2/phone/call_logs", headers=H, params=pr, timeout=60).json()
        for c in j.get("call_logs", []):
            if c.get("direction") != "outbound":
                continue
            cn = c.get("callee_number")
            cdt = datetime.fromisoformat(c["date_time"].replace("Z", "+00:00")).astimezone(_UTC)
            zidx.setdefault(cn, []).append((cdt, int(c.get("duration") or 0)))
        tok = j.get("next_page_token")
        if not tok:
            break
    return zidx


def _safe_zoom_index(date_iso: str) -> dict:
    """Zoom取得を試み、資格情報無し/失敗時は空dict（日報は継続）。"""
    if not all(os.environ.get(k) for k in ("ZOOM_ACCOUNT_ID", "ZOOM_CLIENT_ID", "ZOOM_CLIENT_SECRET")):
        return {}
    try:
        return _build_zoom_index(date_iso)
    except Exception as e:
        print(f"[warn] Zoom取得失敗のため平均対話時間は'-': {type(e).__name__}: {e}")
        return {}


def _avg_talk(records: list, zidx: dict):
    """完了レコード群を Zoom と ±20分で突合し、duration平均(秒)を返す。突合0なら None。"""
    durs = []
    for (n, sd) in records:
        best = None
        bd = None
        for (zd, dur) in zidx.get(n, []):
            df = abs((zd - sd).total_seconds())
            if df <= _WIN and (bd is None or df < bd):
                bd = df
                best = dur
        if best is not None:
            durs.append(best)
    return (sum(durs) / len(durs)) if durs else None


def _total_calls(cnt: dict) -> int:
    return sum(
        cnt.get(s, {}).get("完了", 0) + cnt.get(s, {}).get("留守", 0) + cnt.get(s, {}).get("再コール", 0)
        for s, _ in CATS
    )


def _cat_lines(disp: str, cnt: dict, recs: dict, sval: str, zidx: dict) -> list:
    c = cnt.get(sval, {})
    kan, rus, sai = c.get("完了", 0), c.get("留守", 0), c.get("再コール", 0)
    total = kan + rus + sai
    avg = _avg_talk(recs.get(sval, []), zidx)
    return [
        f"▼{disp}",
        f"合計コール数：{total}",
        f"完了数：{kan}",
        f"完了率：{_pct(kan, total)}",
        f"※完了平均対話時間：{_fmt_talk(avg)}",
        f"留守数：{rus}",
        f"留守率：{_pct(rus, total)}",
    ]


def _member_section(sf, label: str, uid_list: list, with_extras: bool, zidx: dict, date_iso: str) -> str:
    cnt = _counts(sf, uid_list, date_iso)
    recs = _kanryo_records(sf, uid_list, date_iso)
    out = [f"【{label}】", f"トータルコール数：{_total_calls(cnt)}"]
    out += _cat_lines("フォローコール(その他)", cnt, recs, "フォローコール（その他）", zidx)
    if with_extras:
        for sval, disp in CATS:
            if sval == "フォローコール（その他）":
                continue
            c = cnt.get(sval, {})
            if (c.get("完了", 0) + c.get("留守", 0) + c.get("再コール", 0)) > 0:
                out += _cat_lines(disp, cnt, recs, sval, zidx)
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
    zidx = _safe_zoom_index(date_iso)  # Zoom発信ログ(1日分)を一度だけ取得

    sections = [_member_section(sf, "ALL", all_ids, False, zidx, date_iso)]
    for lbl, _ in MEMBERS:
        u = uids[lbl]
        sections.append(_member_section(sf, lbl, [u] if u else [], True, zidx, date_iso))

    return (
        TO_HEADER
        + f"[info][title]NURO消セン抑止FC 日報 ({md})[/title]\n"
        + "\n\n".join(sections)
        + "\n[/info]"
    )
