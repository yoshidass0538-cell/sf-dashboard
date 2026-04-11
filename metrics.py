"""
集計指標の定義

新しい指標を追加するには:
  1. fetch 関数を1つ書く（引数: sf, 戻り値: DataFrame もしくは dict[str, DataFrame]）
  2. METRICS リストに Metric(...) を追加するだけ

fetch が dict を返した場合、ボード上に複数の表として並べて表示される。
"""

from dataclasses import dataclass
from typing import Callable, Optional, Union
import pandas as pd
from simple_salesforce import Salesforce

FetchResult = Union[pd.DataFrame, dict[str, pd.DataFrame]]


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


def fetch_fc_1week(sf: Salesforce) -> dict[str, pd.DataFrame]:
    return _build_fc_board(sf, "THIS_MONTH", board_label="1週間後FC",
        activities=("フォローコール（1週間後FC）", "フォローコール（その他）"))


def fetch_fc_1week_today(sf: Salesforce) -> dict[str, pd.DataFrame]:
    return _build_fc_board(sf, "TODAY", board_label="1週間後FC（本日）",
        activities=("フォローコール（1週間後FC）", "フォローコール（その他）"))


SHINSETSU_FC_NAMES = {
    n.replace(" ", "").replace("\u3000", "")
    for n in ["佐々木彩乃", "葛西翼", "雨貝一生", "半田さくら", "菊地隆真", "栗田優衣", "高橋真友香"]
}


def fetch_shinsetsu_fc_today(sf: Salesforce) -> dict[str, pd.DataFrame]:
    return _build_fc_board(sf, "TODAY", board_label="新設FC TODAY",
        activities=("フォローコール（代コン）", "フォローコール（代コン窓口）", "フォローコール（工事取得）"),
        owner_filter=SHINSETSU_FC_NAMES)


def fetch_sokushin_monthly(sf: Salesforce) -> dict[str, pd.DataFrame]:
    return _build_fc_board(sf, "THIS_MONTH", board_label="促進 月間CRデータ",
        activities=("フォローコール（代コン）", "フォローコール（代コン窓口）", "フォローコール（工事取得）"),
        owner_filter=SHINSETSU_FC_NAMES)


def _build_fc_board(
    sf: Salesforce,
    date_literal: str,
    board_label: str,
    activities: tuple = ("フォローコール（1週間後FC）", "フォローコール（その他）"),
    owner_filter: set = None,
) -> dict[str, pd.DataFrame]:
    act_str = ", ".join(f"'{a}'" for a in activities)
    soql = (
        "SELECT ActivityDate, OwnerId, Owner.Name oname, "
        "Field4_del__c result, COUNT(Id) cnt "
        "FROM Task "
        f"WHERE Field2_del__c IN ({act_str}) "
        f"AND ActivityDate = {date_literal} "
        "AND Owner.UserRole.Name IN ('推進部','推進部AP') "
        "GROUP BY ActivityDate, OwnerId, Owner.Name, Field4_del__c"
    )
    EXCLUDE_OWNERS = {"CS1", "CS2", "CS3", "CS4", "CS5", "CS6", "CS7"}
    res = sf.query(soql)
    rows = []
    for r in res["records"]:
        owner_name = r.get("oname") or r["OwnerId"]
        owner_norm = owner_name.replace(" ", "").replace("\u3000", "")
        if owner_norm in EXCLUDE_OWNERS:
            continue
        if owner_filter:
            norm = owner_name.replace(" ", "").replace("\u3000", "")
            if norm not in owner_filter:
                continue
        rows.append({
            "日付": str(r["ActivityDate"]),
            "担当者": owner_name,
            "結果": r.get("result") or "(未設定)",
            "件数": r["cnt"],
        })
    raw = pd.DataFrame(rows)
    if raw.empty:
        return {board_label: pd.DataFrame()}

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

    if not owner_filter:
        cancel_tables = _fetch_1week_cancel_reasons(sf, date_literal)
        return {board_label: df, **cancel_tables}
    return {board_label: df}


def _fetch_1week_cancel_reasons(sf: Salesforce, date_literal: str = "THIS_MONTH") -> dict[str, pd.DataFrame]:
    """指定期間に1週間後FCを行った案件のうち、その後キャンセル対応に至ったものを
    担当者(FC実施者)×キャンセル理由(Account.Field234__c) で集計。"""
    fc_records = sf.query_all(
        "SELECT WhatId, Owner.Name, ActivityDate "
        "FROM Task "
        "WHERE Field2_del__c IN ('フォローコール（1週間後FC）','フォローコール（その他）') "
        f"AND ActivityDate = {date_literal} "
        "AND Owner.UserRole.Name IN ('推進部','推進部AP') "
        "AND WhatId != null"
    )["records"]
    # WhatId が Account(001) のもののみ
    fc_map: dict[str, list] = {}
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

    reason_map: dict[str, dict] = {}
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
def _progress_start() -> str:
    """6ヶ月前の1日を YYYY-MM-DD で返す。"""
    today = pd.Timestamp.today()
    dt = today - pd.DateOffset(months=6)
    return dt.replace(day=1).strftime("%Y-%m-%d")


def _fetch_progress(sf: Salesforce, product_keyword: str, header: str, with_settlement: bool) -> pd.DataFrame:
    start = _progress_start()
    soql = (
        "SELECT Field156__c, Field130__c, Field128__c, Field131__c, Field119__c "
        "FROM Account "
        f"WHERE Field76__r.Name LIKE '%{product_keyword}%' "
        f"AND Field156__c >= {start}"
    )
    rs = sf.query_all(soql)["records"]
    if not rs:
        return pd.DataFrame()
    df = pd.DataFrame([
        {
            "entry": r.get("Field156__c"),
            "kaitsu": r.get("Field130__c"),
            "yotei": r.get("Field128__c"),
            "kessai": r.get("Field131__c"),
            "cancel": r.get("Field119__c"),
        }
        for r in rs
    ])
    for c in ["entry", "kaitsu", "yotei", "kessai", "cancel"]:
        df[c] = pd.to_datetime(df[c], errors="coerce")
    df = df.dropna(subset=["entry"])
    df["月"] = df["entry"].dt.strftime("%Y-%m")
    today = pd.Timestamp(pd.Timestamp.today().date())

    out_rows = []
    for month, sub in df.groupby("月", sort=True):
        entry_n = len(sub)
        kaitsu_n = sub["kaitsu"].notna().sum()
        yotei_n = ((sub["yotei"] > today) & sub["kaitsu"].isna()).sum()
        cancel_n = sub["cancel"].notna().sum()
        diff = (sub["cancel"] - sub["entry"]).dt.days
        cancel7_n = ((diff >= 0) & (diff <= 7)).sum()

        def pct(n):
            return f"{round(n / entry_n * 100, 1)}%" if entry_n else "-"

        row = {
            "月": month,
            "エントリー数": int(entry_n),
            "工事完了数": int(kaitsu_n),
            "工事完了率": pct(kaitsu_n),
            "工事待ち数": int(yotei_n),
            "工事待ち率": pct(yotei_n),
        }
        if with_settlement:
            kessai_n = sub["kessai"].notna().sum()
            row["決済登録数"] = int(kessai_n)
            row["決済登録率"] = pct(kessai_n)
            nyukin_n = int((sub["kaitsu"].notna() & sub["kessai"].notna()).sum())
            row["入金数"] = nyukin_n
            row["入金率"] = pct(nyukin_n)
        row["キャンセル数"] = int(cancel_n)
        row["キャンセル率"] = pct(cancel_n)
        row["7日以内キャンセル数"] = int(cancel7_n)
        row["7日以内キャンセル率"] = pct(cancel7_n)
        out_rows.append(row)

    result = pd.DataFrame(out_rows)
    return result.iloc[::-1].reset_index(drop=True) if not result.empty else result


def fetch_progress(sf: Salesforce) -> dict[str, pd.DataFrame]:
    return {
        "NURO開通進捗": _fetch_progress(sf, "NURO", "NURO開通進捗", False),
        "ソネット開通進捗": _fetch_progress(sf, "So-net", "ソネット開通進捗", True),
    }


# 稼働実績(CustomObject11__c) の 1日〜31日の (開始,終了) フィールド
SHIFT_DAY_FIELDS = [
    (1, "Field3__c", "Field4__c"),
    (2, "Field7__c", "Field8__c"),
    (3, "Field11__c", "Field12__c"),
    (4, "Field15__c", "Field16__c"),
    (5, "Field27__c", "Field20__c"),
    (6, "Field23__c", "Field28__c"),
    (7, "Field31__c", "Field24__c"),
    (8, "Field32__c", "Field33__c"),
    (9, "Field36__c", "Field37__c"),
    (10, "Field40__c", "Field41__c"),
    (11, "Field44__c", "Field45__c"),
    (12, "Field48__c", "Field49__c"),
    (13, "Field52__c", "Field53__c"),
    (14, "Field56__c", "Field57__c"),
    (15, "Field60__c", "Field61__c"),
    (16, "Field64__c", "Field65__c"),
    (17, "Field68__c", "Field69__c"),
    (18, "Field72__c", "Field73__c"),
    (19, "Field76__c", "Field77__c"),
    (20, "Field80__c", "Field81__c"),
    (21, "Field84__c", "Field85__c"),
    (22, "Field88__c", "Field89__c"),
    (23, "Field92__c", "Field93__c"),
    (24, "Field96__c", "Field97__c"),
    (25, "Field100__c", "Field101__c"),
    (26, "Field104__c", "Field105__c"),
    (27, "Field108__c", "Field109__c"),
    (28, "Field112__c", "Field113__c"),
    (29, "Field116__c", "Field117__c"),
    (30, "Field120__c", "Field121__c"),
    (31, "Field124__c", "Field125__c"),
]


def fetch_cs_shift(sf: Salesforce) -> dict[str, pd.DataFrame]:
    today = pd.Timestamp.today()
    year_label = f"{today.year}年"
    month_label = f"{today.month}月"

    field_list = ["Field128__r.Name"]
    for _, s, e in SHIFT_DAY_FIELDS:
        field_list += [s, e]
    soql = (
        f"SELECT {', '.join(field_list)} FROM CustomObject11__c "
        f"WHERE Field1__c = '{year_label}' AND Field2__c = '{month_label}' "
        f"AND Field128__r.Field13__c = 'CS促進' "
        f"ORDER BY Field128__r.Name"
    )
    rs = sf.query_all(soql)["records"]
    if not rs:
        return {"1週間FCシフト": pd.DataFrame()}

    # 今月1週間後FCを記録した担当者のみに絞る
    active_rs = sf.query_all(
        "SELECT Owner.Name FROM Task "
        "WHERE Field2_del__c IN ('フォローコール（1週間後FC）','フォローコール（その他）') "
        "AND ActivityDate = THIS_MONTH"
    )["records"]
    active_names = {
        ((r.get("Owner") or {}).get("Name") or "").replace(" ", "").replace("\u3000", "")
        for r in active_rs
    }
    active_names.discard("")

    def _fmt(t):
        if not t:
            return ""
        # "HH:MM:SS.000Z" → "HH:MM"
        return str(t)[:5]

    today_day = today.day
    visible_days = [t for t in SHIFT_DAY_FIELDS if t[0] >= today_day]

    rows = []
    for r in rs:
        owner = (r.get("Field128__r") or {}).get("Name") or "(不明)"
        normalized = owner.replace(" ", "").replace("\u3000", "")
        if normalized not in active_names:
            continue
        row = {"担当者": owner}
        for day, sf_, ef in visible_days:
            s = _fmt(r.get(sf_))
            e = _fmt(r.get(ef))
            if s and e:
                row[f"{day}"] = f"{s}-{e}"
            elif s:
                row[f"{day}"] = s
            else:
                row[f"{day}"] = ""
        rows.append(row)
    df = pd.DataFrame(rows)
    # 指定順で並び替え（該当しない人は末尾）
    order = ["原田綾子", "室谷慧", "堀田輝斗", "大滝紀香", "角田心華", "金澤", "吉本"]
    def _rank(name: str) -> int:
        norm = (name or "").replace(" ", "").replace("\u3000", "")
        for i, key in enumerate(order):
            if key in norm:
                return i
        return len(order)
    if not df.empty:
        df = df.assign(_o=df["担当者"].map(_rank)).sort_values("_o", kind="stable").drop(columns="_o").reset_index(drop=True)
    return {f"1週間FCシフト ({year_label}{month_label})": df}


SHINSETSU_FC_OWNERS = {
    n.replace(" ", "").replace("\u3000", "")
    for n in ["佐々木彩乃", "葛西翼", "雨貝一生", "半田さくら", "菊地隆真", "栗田優衣", "高橋真友香"]
}

SHINSETSU_FC_ORDER = ["佐々木彩乃", "葛西翼", "雨貝一生", "半田さくら", "菊地隆真", "栗田優衣", "高橋真友香"]


def fetch_shinsetsu_fc_shift(sf: Salesforce) -> dict[str, pd.DataFrame]:
    today = pd.Timestamp.today()
    year_label = f"{today.year}年"
    month_label = f"{today.month}月"

    field_list = ["Field128__r.Name"]
    for _, s, e in SHIFT_DAY_FIELDS:
        field_list += [s, e]
    soql = (
        f"SELECT {', '.join(field_list)} FROM CustomObject11__c "
        f"WHERE Field1__c = '{year_label}' AND Field2__c = '{month_label}' "
        f"AND Field128__r.Field13__c = 'CS促進' "
        f"ORDER BY Field128__r.Name"
    )
    rs = sf.query_all(soql)["records"]
    if not rs:
        return {"新設FCシフト": pd.DataFrame()}

    def _fmt(t):
        if not t:
            return ""
        return str(t)[:5]

    today_day = today.day
    visible_days = [t for t in SHIFT_DAY_FIELDS if t[0] >= today_day]

    rows = []
    for r in rs:
        owner = (r.get("Field128__r") or {}).get("Name") or "(不明)"
        normalized = owner.replace(" ", "").replace("\u3000", "")
        if normalized not in SHINSETSU_FC_OWNERS:
            continue
        row = {"担当者": owner}
        for day, sf_, ef in visible_days:
            s = _fmt(r.get(sf_))
            e = _fmt(r.get(ef))
            if s and e:
                row[f"{day}"] = f"{s}-{e}"
            elif s:
                row[f"{day}"] = s
            else:
                row[f"{day}"] = ""
        rows.append(row)
    df = pd.DataFrame(rows)

    def _rank(name: str) -> int:
        norm = (name or "").replace(" ", "").replace("\u3000", "")
        for i, key in enumerate(SHINSETSU_FC_ORDER):
            if key in norm:
                return i
        return len(SHINSETSU_FC_ORDER)
    if not df.empty:
        df = df.assign(_o=df["担当者"].map(_rank)).sort_values("_o", kind="stable").drop(columns="_o").reset_index(drop=True)
    return {f"新設FCシフト ({year_label}{month_label})": df}


def _shift_hours(start: str, end: str) -> float:
    """"HH:MM" 形式の開始/終了から稼働時間(h)を返す。14:00-15:00 を跨ぐ場合は休憩-1h。"""
    if not start or not end:
        return 0.0
    try:
        sh, sm = int(start[:2]), int(start[3:5])
        eh, em = int(end[:2]), int(end[3:5])
    except Exception:
        return 0.0
    s = sh + sm / 60
    e = eh + em / 60
    if e <= s:
        return 0.0
    h = e - s
    # 14:00-15:00 を跨ぐ
    if s < 15 and e > 14:
        h -= 1
    return max(h, 0.0)


CONSUME_OWNERS = {
    n.replace(" ", "").replace("\u3000", "")
    for n in ["角田心華", "原田綾子", "室谷慧", "大滝紀香", "堀田輝斗"]
}


def _owner_shift_hours_by_day(sf: Salesforce) -> dict[str, dict[pd.Timestamp, float]]:
    """{担当者(正規化): {date: hours}} を返す（今月分、CONSUME_OWNERSのみ）。"""
    today = pd.Timestamp.today()
    year_label = f"{today.year}年"
    month_label = f"{today.month}月"
    fields = ["Field128__r.Name"]
    for _, s, e in SHIFT_DAY_FIELDS:
        fields += [s, e]
    rs = sf.query_all(
        f"SELECT {', '.join(fields)} FROM CustomObject11__c "
        f"WHERE Field1__c = '{year_label}' AND Field2__c = '{month_label}' "
        f"AND Field128__r.Field13__c = 'CS促進'"
    )["records"]
    result: dict[str, dict[pd.Timestamp, float]] = {}
    for r in rs:
        owner = (r.get("Field128__r") or {}).get("Name") or ""
        norm = owner.replace(" ", "").replace("\u3000", "")
        if not norm or norm not in CONSUME_OWNERS:
            continue
        per_day: dict[pd.Timestamp, float] = {}
        for day, sf_, ef in SHIFT_DAY_FIELDS:
            s = str(r.get(sf_) or "")[:5]
            e = str(r.get(ef) or "")[:5]
            h = _shift_hours(s, e)
            if h > 0:
                try:
                    d = pd.Timestamp(year=today.year, month=today.month, day=day)
                except ValueError:
                    continue
                per_day[d] = h
        if per_day:
            result[norm] = per_day
    return result


def _owner_call_stats(sf: Salesforce) -> dict[str, dict[str, float]]:
    """個人別の {担当者(正規化): {"calls_per_h": x, "complete_rate": y}} を今月実績から算出。"""
    soql = (
        "SELECT Owner.Name oname, Field4_del__c result, COUNT(Id) cnt "
        "FROM Task "
        "WHERE Field2_del__c IN ('フォローコール（1週間後FC）','フォローコール（その他）') "
        "AND ActivityDate = THIS_MONTH "
        "AND Owner.UserRole.Name IN ('推進部','推進部AP') "
        "GROUP BY Owner.Name, Field4_del__c"
    )
    rs = sf.query_all(soql)["records"]
    totals: dict[str, int] = {}
    completes: dict[str, int] = {}
    for r in rs:
        owner = r.get("oname") or ""
        norm = owner.replace(" ", "").replace("\u3000", "")
        if not norm:
            continue
        cnt = int(r.get("cnt") or 0)
        totals[norm] = totals.get(norm, 0) + cnt
        if r.get("result") == "完了":
            completes[norm] = completes.get(norm, 0) + cnt

    shifts = _owner_shift_hours_by_day(sf)
    today = pd.Timestamp(pd.Timestamp.today().date())
    out: dict[str, dict[str, float]] = {}
    for norm, total in totals.items():
        # 今月開始から今日までの稼働実績h
        per_day = shifts.get(norm, {})
        worked_h = sum(h for d, h in per_day.items() if d <= today)
        if worked_h <= 0 or total <= 0:
            continue
        out[norm] = {
            "calls_per_h": total / worked_h,
            "complete_rate": (completes.get(norm, 0) / total) if total else 0.0,
        }
    return out


def _avg_daily_6th_fc(sf: Salesforce) -> float:
    """今月、累計6回目の1週間後FCに到達したAccount件数の日平均。"""
    rs = sf.query_all(
        "SELECT WhatId, ActivityDate FROM Task "
        "WHERE Field2_del__c IN ('フォローコール（1週間後FC）','フォローコール（その他）') "
        "AND WhatId != null "
        "AND ActivityDate = THIS_MONTH"
    )["records"]
    # WhatId 別に Task を集める（過去分含めず今月内通算でカウント）
    counts: dict[str, int] = {}
    reached = 0
    # 日付昇順にソートして「6回目に達した瞬間」をカウント
    items = [
        (r["WhatId"], r["ActivityDate"]) for r in rs if r.get("WhatId") and r["WhatId"].startswith("001")
    ]
    items.sort(key=lambda x: x[1] or "")
    for wid, _d in items:
        counts[wid] = counts.get(wid, 0) + 1
        if counts[wid] == 6:
            reached += 1
    today = pd.Timestamp.today()
    days_elapsed = today.day
    return reached / days_elapsed if days_elapsed else 0.0


def fetch_list_volume(sf: Salesforce) -> dict[str, pd.DataFrame]:
    # ===== ソネット (リストビュー仕様) =====
    so_soql = (
        "SELECT Field156__c, Field128__c, Field253__c "
        "FROM Account "
        "WHERE Field232__c LIKE 'So-net光_004新設%' "
        "AND Field113__c != 'キャンセル' "
        "AND Field233__c = false "
        "AND (Field101__c != '後確NG' OR Field101__c = null) "
        "AND Field398__c = false "
        "AND ("
        "  (Field253__c IN (1,2,3,4,5) AND Field156__c >= 2026-03-01) "
        "  OR (Field253__c = 0 AND Field156__c >= 2026-04-01)"
        ")"
    )
    so_records = sf.query_all(so_soql)["records"]
    so_df = pd.DataFrame(
        [
            {
                "entry": pd.to_datetime(r.get("Field156__c"), errors="coerce"),
                "yotei": pd.to_datetime(r.get("Field128__c"), errors="coerce"),
            }
            for r in so_records
        ]
    )

    # ===== NURO (リストビュー仕様) =====
    nuro_soql = (
        "SELECT Field156__c, Field253__c, Field130__c "
        "FROM Account "
        "WHERE Field232__c LIKE 'NURO光_004新設%' "
        "AND Field113__c != 'キャンセル' "
        "AND RecordType.Name = '顧客情報' "
        "AND Field233__c = false "
        "AND (Field101__c != '後確NG' OR Field101__c = null) "
        "AND Field108__c != '株式会社GIFT' "
        "AND ("
        "  Field253__c IN (1,2,3,4,5) "
        "  OR (Field253__c = 0 AND Field130__c = null)"
        ")"
    )
    nuro_records = sf.query_all(nuro_soql)["records"]
    nuro_df = pd.DataFrame(
        [
            {"entry": pd.to_datetime(r.get("Field156__c"), errors="coerce")}
            for r in nuro_records
        ]
    )

    today = pd.Timestamp(pd.Timestamp.today().date())
    days = [today + pd.Timedelta(days=i) for i in range(31)]

    # ===== 消化スピード用データ =====
    owner_shifts = _owner_shift_hours_by_day(sf)  # {owner: {date: h}}
    owner_stats = _owner_call_stats(sf)           # {owner: {calls_per_h, complete_rate}}
    avg_6th = _avg_daily_6th_fc(sf)               # 月平均(日次)
    cumulative = 0.0

    rows = []
    for d in days:
        if so_df.empty:
            so_cnt = 0
        else:
            so_cnt = int(
                (
                    (so_df["entry"].notna())
                    & (so_df["entry"] <= d - pd.Timedelta(days=5))
                    & ((so_df["yotei"].isna()) | (so_df["yotei"] > d))
                ).sum()
            )
        if nuro_df.empty:
            nuro_cnt = 0
        else:
            nuro_cnt = int(
                (
                    nuro_df["entry"].notna()
                    & (nuro_df["entry"] <= d - pd.Timedelta(days=4))
                ).sum()
            )
        # --- 消化見込み計算 ---
        total_h = 0.0
        complete_calls = 0.0
        for owner, per_day in owner_shifts.items():
            h = per_day.get(d, 0.0)
            if h <= 0:
                continue
            total_h += h
            stat = owner_stats.get(owner)
            if not stat:
                continue
            complete_calls += h * stat["calls_per_h"] * stat["complete_rate"]
        consumed = complete_calls + avg_6th
        cumulative += consumed
        remain = max((so_cnt + nuro_cnt) - cumulative, 0.0)

        rows.append(
            {
                "日付": d.strftime("%Y-%m-%d"),
                "ソネット(GIFT/5日経過)": so_cnt,
                "NURO(非GIFT/4日経過)": nuro_cnt,
                "合計": so_cnt + nuro_cnt,
                "シフト人時": round(total_h, 1),
                "消化見込み": round(consumed, 1),
                "累計消化": round(cumulative, 1),
                "残体積": round(remain, 1),
            }
        )
    return {"リスト体積": pd.DataFrame(rows)}


# ======================================================================
# 停滞別開通率
# ======================================================================
DAIKON_REASON_FIELDS = [
    (1, "Field242__c"),
    (2, "Field243__c"),
    (3, "Field244__c"),
    (4, "Field245__c"),
    (5, "Field246__c"),
    (6, "Field341__c"),
    (7, "Field342__c"),
    (8, "Field343__c"),
    (9, "Field344__c"),
    (10, "Field345__c"),
]


def fetch_daikon_kaitsu(sf: Salesforce) -> dict[str, pd.DataFrame]:
    """全次数のダイコン理由を統合し、理由ごとの発生率・開通率を集計。
    1次ダイコン理由が1件もない月は母数から除外。"""
    reason_fields = ", ".join(f[1] for f in DAIKON_REASON_FIELDS)
    soql = (
        f"SELECT Id, Field130__c, Field43__c, Field156__c, {reason_fields} "
        "FROM Account "
        "WHERE Field232__c LIKE 'So-net光%'"
    )
    all_records = sf.query_all(soql)["records"]
    if not all_records:
        return {"停滞別開通率": pd.DataFrame()}

    # 月別に1次ダイコン理由(Field242__c)が1件でもある月を特定
    from collections import defaultdict
    month_has_daikon: dict[str, bool] = defaultdict(bool)
    month_map: dict[str, str] = {}  # record Id -> YYYY-MM
    for r in all_records:
        entry = r.get("Field156__c") or ""
        ym = entry[:7] if len(entry) >= 7 else "unknown"
        month_map[r["Id"]] = ym
        if r.get("Field242__c"):
            month_has_daikon[ym] = True

    valid_months = {ym for ym, has in month_has_daikon.items() if has}
    records = [r for r in all_records if month_map.get(r["Id"], "") in valid_months]
    total_accounts = len(records)
    if total_accounts == 0:
        return {"停滞別開通率": pd.DataFrame()}

    def _build_table(recs, total):
        counts: dict[str, dict[str, int]] = {}
        for r in recs:
            seen: set = set()
            for _, field in DAIKON_REASON_FIELDS:
                reason = r.get(field)
                if not reason or reason in seen:
                    continue
                seen.add(reason)
                if reason not in counts:
                    counts[reason] = {"発生": 0, "開通": 0}
                counts[reason]["発生"] += 1
                if r.get("Field130__c"):
                    counts[reason]["開通"] += 1
        if not counts:
            return pd.DataFrame()
        rows = []
        for reason, c in sorted(counts.items(), key=lambda x: -x[1]["発生"]):
            rate = round(c["発生"] / total * 100, 1)
            kaitsu_rate = round(c["開通"] / c["発生"] * 100, 1) if c["発生"] else 0.0
            rows.append({
                "理由": reason,
                "発生件数": c["発生"],
                f"発生率(母数{total})": f"{rate}%",
                "開通件数": c["開通"],
                "開通率": f"{kaitsu_rate}%",
            })
        return pd.DataFrame(rows)

    # 全体
    tables: dict[str, pd.DataFrame] = {}
    tables["停滞別開通率（全体）"] = _build_table(records, total_accounts)

    # エリア別
    east = [r for r in records if r.get("Field43__c") == "東"]
    west = [r for r in records if r.get("Field43__c") == "西"]
    if east:
        tables["停滞別開通率（東）"] = _build_table(east, len(east))
    if west:
        tables["停滞別開通率（西）"] = _build_table(west, len(west))

    return tables


# ======================================================================
# トータルコール数集計
# ======================================================================
TOTAL_CALL_OWNERS = [
    "室谷慧", "原田綾子", "金澤駿平", "吉本将吾", "大滝紀香", "堀田輝斗", "角田心華",
    "葛西翼", "雨貝一生", "半田さくら", "菊地隆真", "栗田優衣", "高橋真友香", "佐々木彩乃",
]
TOTAL_CALL_OWNERS_SET = {n.replace(" ", "").replace("\u3000", "") for n in TOTAL_CALL_OWNERS}


def fetch_total_calls(sf: Salesforce) -> dict[str, pd.DataFrame]:
    """指定メンバーの全活動記録を日付別に集計。"""
    soql = (
        "SELECT ActivityDate, Owner.Name oname, COUNT(Id) cnt "
        "FROM Task "
        "WHERE ActivityDate = THIS_MONTH "
        "AND Owner.UserRole.Name IN ('推進部','推進部AP') "
        "GROUP BY ActivityDate, Owner.Name"
    )
    res = sf.query_all(soql)
    rows = []
    for r in res["records"]:
        owner = r.get("oname") or ""
        norm = owner.replace(" ", "").replace("\u3000", "")
        if norm not in TOTAL_CALL_OWNERS_SET:
            continue
        rows.append({
            "日付": str(r["ActivityDate"]),
            "担当者": owner,
            "件数": int(r["cnt"]),
        })
    raw = pd.DataFrame(rows)
    if raw.empty:
        return {"トータルコール数集計": pd.DataFrame()}

    dates = sorted(raw["日付"].unique().tolist())

    # 指定順で担当者を並べる
    owner_norm_map: dict = {}
    for _, row in raw.iterrows():
        norm = row["担当者"].replace(" ", "").replace("\u3000", "")
        owner_norm_map[norm] = row["担当者"]
    ordered_owners = [owner_norm_map[n] for n in TOTAL_CALL_OWNERS if n in owner_norm_map]

    pivot = raw.pivot_table(index="担当者", columns="日付", values="件数", aggfunc="sum", fill_value=0)
    pivot = pivot.reindex(index=ordered_owners, columns=dates, fill_value=0)
    pivot["合計"] = pivot.sum(axis=1)
    df = pivot.reset_index()
    return {"トータルコール数集計": df}


# ======================================================================
# DAYコール数（本日・CS促進・対応ステータス別）
# ======================================================================
TIMEE_MEMBERS = {"CS1", "CS2", "CS3", "CS4", "CS5", "CS6", "CS7"}
DAY_CALLS_EXCLUDE = {"太田海斗", "杉山敏樹", "柳原", "対馬", "対馬拓人", "早瀬太一"}


def fetch_day_calls(sf: Salesforce) -> dict[str, pd.DataFrame]:
    """本日のCS促進メンバー + タイミーの対応ステータス別コール数を集計。"""
    # CS促進メンバー名を取得
    members_rs = sf.query_all(
        "SELECT Name FROM CustomObject10__c WHERE Field13__c = 'CS促進'"
    )["records"]
    cs_names = {
        (r.get("Name") or "").replace(" ", "").replace("\u3000", "")
        for r in members_rs
    }
    cs_names.discard("")
    cs_names = {n for n in cs_names if not any(ex in n for ex in DAY_CALLS_EXCLUDE)}

    # 本日のTask集計
    soql = (
        "SELECT Owner.Name oname, Field2_del__c status, COUNT(Id) cnt "
        "FROM Task "
        "WHERE ActivityDate = TODAY "
        "GROUP BY Owner.Name, Field2_del__c"
    )
    rs = sf.query_all(soql)["records"]
    cs_rows = []
    timee_rows = []
    for r in rs:
        owner = (r.get("oname") or "")
        norm = owner.replace(" ", "").replace("\u3000", "")
        status = r.get("status")
        if not status:
            continue
        row = {"担当者": owner, "対応ステータス": status, "コール数": int(r["cnt"])}
        if norm in cs_names:
            cs_rows.append(row)
        elif norm in TIMEE_MEMBERS:
            timee_rows.append(row)

    empty = pd.DataFrame(columns=["担当者", "対応ステータス", "コール数"])
    return {
        "DAYコール数": pd.DataFrame(cs_rows) if cs_rows else empty.copy(),
        "タイミーコール数": pd.DataFrame(timee_rows) if timee_rows else empty.copy(),
    }


def fetch_kari_keisan(sf: Salesforce) -> dict[str, pd.DataFrame]:
    """
    仮計算: 2025/12以降の月別で、商材別(ソネット/NURO)に
    [1週間後FC完了フラグ=true] vs [留守 + 完了フラグ=false] の
    開通率・CX率を比較するための表を構築する。

    集計仕様:
      - 期間: Field156__c (エントリ日) >= 2025-12-01
      - 商材: Field232__c LIKE 'So-net光_%' / 'NURO光_%'
      - 完了グループ: Field233__c = true
      - 留守グループ: Field233__c = false AND 任意のTask(Field2_del__c IN
        ['フォローコール（1週間後FC）','フォローコール（その他）'] AND
        Field4_del__c='留守') がそのアカウントに存在
      - 開通: Field130__c (開通日) が入っている
      - CX:  Field130__c (開通日) が空 AND Field119__c (キャンセル日) に日付あり
    """
    from collections import defaultdict
    from datetime import datetime

    PERIOD_START = "2025-12-01"

    # 1) 1週間後FC系 留守タスクを持つアカウントID集合
    task_query = (
        "SELECT WhatId FROM Task "
        "WHERE Field2_del__c IN ('フォローコール（1週間後FC）', 'フォローコール（その他）') "
        "AND Field4_del__c = '留守'"
    )
    try:
        task_records = sf.query_all(task_query)["records"]
    except Exception as e:
        return {"エラー": pd.DataFrame({"メッセージ": [f"Task取得失敗: {e}"]})}
    rusu_account_ids = {r["WhatId"] for r in task_records if r.get("WhatId")}

    # 2) 対象期間の Sonet/NURO アカウント
    account_query = (
        "SELECT Id, Field156__c, Field130__c, Field119__c, Field232__c, Field233__c "
        "FROM Account "
        f"WHERE Field156__c >= {PERIOD_START} "
        "AND (Field232__c LIKE 'NURO光_%' OR Field232__c LIKE 'So-net光_%')"
    )
    try:
        account_records = sf.query_all(account_query)["records"]
    except Exception as e:
        return {"エラー": pd.DataFrame({"メッセージ": [f"Account取得失敗: {e}"]})}

    # 3) 集計
    def _new_stat():
        return {
            "complete_total": 0, "complete_kaitsu": 0, "complete_cx": 0,
            "rusu_total": 0, "rusu_kaitsu": 0, "rusu_cx": 0,
        }
    stats: dict[str, dict] = {
        "ソネット": defaultdict(_new_stat),
        "NURO": defaultdict(_new_stat),
    }

    for r in account_records:
        entry_date_str = r.get("Field156__c")
        if not entry_date_str:
            continue
        try:
            d = datetime.strptime(entry_date_str, "%Y-%m-%d").date()
        except (ValueError, TypeError):
            continue
        month_key = f"{d.year}/{d.month:02d}"

        shozai = r.get("Field232__c") or ""
        if shozai.startswith("NURO光_"):
            kind = "NURO"
        elif shozai.startswith("So-net光_"):
            kind = "ソネット"
        else:
            continue

        flag = r.get("Field233__c")
        is_kaitsu = bool(r.get("Field130__c"))
        # CX = 開通日が空 かつ キャンセル日に日付あり
        is_cancel = (not is_kaitsu) and bool(r.get("Field119__c"))

        if flag is True:
            s = stats[kind][month_key]
            s["complete_total"] += 1
            if is_kaitsu:
                s["complete_kaitsu"] += 1
            if is_cancel:
                s["complete_cx"] += 1
        elif r.get("Id") in rusu_account_ids:
            s = stats[kind][month_key]
            s["rusu_total"] += 1
            if is_kaitsu:
                s["rusu_kaitsu"] += 1
            if is_cancel:
                s["rusu_cx"] += 1

    def _pct(num: int, denom: int) -> str:
        return f"{num * 100 / denom:.1f}%" if denom else "—"

    def _build_df(kind: str) -> pd.DataFrame:
        rows = []
        for month_key in sorted(stats[kind].keys(), reverse=True):
            s = stats[kind][month_key]
            ct, rt = s["complete_total"], s["rusu_total"]
            rows.append({
                "月": month_key,
                "完了件数": ct,
                "完了開通率": _pct(s["complete_kaitsu"], ct),
                "完了CX率": _pct(s["complete_cx"], ct),
                "留守件数": rt,
                "留守開通率": _pct(s["rusu_kaitsu"], rt),
                "留守CX率": _pct(s["rusu_cx"], rt),
            })
        if not rows:
            return pd.DataFrame({"月": ["—"], "完了件数": ["データなし"]})
        return pd.DataFrame(rows)

    return {
        "ソネット": _build_df("ソネット"),
        "NURO": _build_df("NURO"),
    }


def fetch_orikaeshi_kensu(sf: Salesforce) -> dict[str, pd.DataFrame]:
    """
    後確待ち確認用スプレッドシートから、最新の BY用_* シートを読んで
    今日と明日の時間帯×種別の折返件数を表示用に整形する。
    対象種別:
      - 折返CS開通前 → 折り返し希望(開通前)
      - 折返新設FC → 折り返し希望(新設FC)
      - 折返１週間FC → 折り返し希望(1週間後)
      - 折返工事取得 → 折り返し希望(工事取得)
    """
    from talk_script_store import _get_gspread_client
    BY_SHEET_ID = "1Xg2oxrIrXy3oju8s9POm8RRHW6RWqqbj7ALTBjAzkvA"

    TARGET_CATEGORIES = {
        "折返CS開通前": "折り返し希望(開通前)",
        "折返新設FC": "折り返し希望(新設FC)",
        "折返１週間FC": "折り返し希望(1週間後)",
        "折返工事取得": "折り返し希望(工事取得)",
    }

    try:
        client = _get_gspread_client()
        sh = client.open_by_key(BY_SHEET_ID)
    except Exception as e:
        return {"エラー": pd.DataFrame({"メッセージ": [f"シート取得失敗: {e}"]})}

    # BY用_NNNNNNNN 形式の最新シートを取得
    by_titles = [
        ws.title for ws in sh.worksheets()
        if ws.title.startswith("BY用_") and ws.title[4:].lstrip("_").isdigit()
    ]
    if not by_titles:
        return {"エラー": pd.DataFrame({"メッセージ": ["BY用_* シートが見つかりません"]})}
    by_titles.sort(reverse=True)
    target_ws = sh.worksheet(by_titles[0])
    all_vals = target_ws.get_all_values()
    if len(all_vals) < 2:
        return {"エラー": pd.DataFrame({"メッセージ": ["データがありません"]})}

    # R1: 時間帯ヘッダー（F=合計、I=10:00、L=11:00、...と3列ずつ）
    time_header = all_vals[0]
    time_slots: list[tuple[int, str]] = []  # (start_col_idx, label)
    for col_idx in range(5, len(time_header), 3):
        label = (time_header[col_idx] or "").strip()
        if not label:
            continue
        # "10:00:00" → "10:00"
        if ":" in label:
            parts = label.split(":")
            label = f"{parts[0]}:{parts[1]}"
        time_slots.append((col_idx, label))

    # 日付別に対象種別の行を収集
    data_by_date: dict[str, dict[str, list[str]]] = {}
    for row in all_vals:
        if len(row) < 5:
            continue
        date_str = (row[3] or "").strip()
        cat_str = (row[4] or "").strip()
        if not date_str or cat_str not in TARGET_CATEGORIES:
            continue
        data_by_date.setdefault(date_str, {})[TARGET_CATEGORIES[cat_str]] = row

    if not data_by_date:
        return {"エラー": pd.DataFrame({"メッセージ": ["対象種別のデータがありません"]})}

    # JST 今日 〜 1週間後 の範囲のみ表示
    from datetime import datetime, timezone, timedelta
    jst = timezone(timedelta(hours=9))
    today = datetime.now(jst).date()
    one_week_later = today + timedelta(days=7)
    target_dates: list[str] = []
    for date_str in sorted(data_by_date.keys()):
        try:
            d = datetime.strptime(date_str, "%Y/%m/%d").date()
        except ValueError:
            continue
        if today <= d <= one_week_later:
            target_dates.append(date_str)
    if not target_dates:
        # 範囲内に無ければとりあえず先頭から最大8日分
        target_dates = sorted(data_by_date.keys())[:8]

    # 表示順（ユーザー指定の4種類）
    display_order = [
        "折り返し希望(開通前)",
        "折り返し希望(1週間後)",
        "折り返し希望(工事取得)",
        "折り返し希望(新設FC)",
    ]

    def _to_int(v: str) -> int:
        try:
            return int((v or "0").strip() or "0")
        except ValueError:
            return 0

    result: dict[str, pd.DataFrame] = {}
    for d in target_dates:
        rows = []
        for cat_label in display_order:
            if cat_label not in data_by_date[d]:
                continue
            src_row = data_by_date[d][cat_label]
            row_dict: dict[str, int] = {"種別": cat_label}
            for col_idx, time_label in time_slots:
                # 新規/改め/留守 の3列を合算
                shinki = _to_int(src_row[col_idx]) if col_idx < len(src_row) else 0
                arata = _to_int(src_row[col_idx + 1]) if col_idx + 1 < len(src_row) else 0
                rusu = _to_int(src_row[col_idx + 2]) if col_idx + 2 < len(src_row) else 0
                row_dict[time_label] = shinki + arata + rusu
            rows.append(row_dict)
        if rows:
            result[d] = pd.DataFrame(rows)

    if not result:
        return {"エラー": pd.DataFrame({"メッセージ": ["表示可能なデータがありません"]})}
    return result


METRICS: list[Metric] = [
    # --- TOTAL ---
    Metric(
        key="day_calls",
        label="DAYコール数",
        description="本日のCS促進メンバーの対応ステータス別コール数（帯グラフ）",
        fetch=fetch_day_calls,
        category="TOTAL",
    ),
    Metric(
        key="total_calls",
        label="トータルコール数集計",
        description="指定メンバーの全活動記録を日付別に集計",
        fetch=fetch_total_calls,
        category="TOTAL",
    ),
    Metric(
        key="orikaeshi_kensu",
        label="折返し件数",
        description="後確待ち管理シートから今日と明日の時間別折返件数を表示",
        fetch=fetch_orikaeshi_kensu,
        category="TOTAL",
    ),
    Metric(
        key="kari_keisan",
        label="FC完了CX率",
        description="2025/12以降の月別 1週間後FC完了 vs 留守(完了フラグなし) の開通率・CX率比較",
        fetch=fetch_kari_keisan,
        category="1週間後FC",
    ),
    # --- 1週間後FC ---
    Metric(
        key="today",
        label="1週間後FC TODAY",
        description="本日分: 1週間後FCの集計（担当者別）",
        fetch=fetch_fc_1week_today,
        category="1週間後FC",
    ),
    Metric(
        key="cs_shift",
        label="1週間FCシフト",
        description="稼働実績(CS促進)の今月シフト一覧",
        fetch=fetch_cs_shift,
        category="1週間後FC",
    ),
    Metric(
        key="fc_1week",
        label="1週間後FC 月間CRデータ",
        description="対応ステータス='フォローコール（1週間後FC）' の Task を今月分、コール結果別に担当者×日付で集計（率は日別に算出）",
        fetch=fetch_fc_1week,
        category="1週間後FC",
    ),
    Metric(
        key="list_volume",
        label="1週間後FC リスト体積",
        description="1週間後FCの架電対象数を当日〜30日後まで日別に予測",
        fetch=fetch_list_volume,
        category="1週間後FC",
    ),
    # --- 促進 ---
    Metric(
        key="shinsetsu_today",
        label="新設FC TODAY",
        description="本日分: 新設FC（代コン/代コン窓口/工事取得）の集計（担当者別）",
        fetch=fetch_shinsetsu_fc_today,
        category="促進",
    ),
    Metric(
        key="shinsetsu_shift",
        label="新設FCシフト",
        description="新設FC担当の今月シフト一覧",
        fetch=fetch_shinsetsu_fc_shift,
        category="促進",
    ),
    Metric(
        key="sokushin_monthly",
        label="促進 月間CRデータ",
        description="代コン/代コン窓口/工事取得の月間コール結果を担当者×日付で集計",
        fetch=fetch_sokushin_monthly,
        category="促進",
    ),
    # --- 促進 ---
    Metric(
        key="progress",
        label="開通進捗",
        description="取次商材別の月次進捗（エントリ日2月以降）",
        fetch=fetch_progress,
        category="TOTAL",
    ),
    Metric(
        key="daikon_kaitsu",
        label="停滞別開通率",
        description="1次〜10次ダイコン理由ごとの発生率・開通率",
        fetch=fetch_daikon_kaitsu,
        category="促進",
    ),
    # --- 責任者用 ---
    Metric(
        key="ikusei_kpi",
        label="育成KPI",
        description="育成KPI（準備中）",
        fetch=lambda sf: pd.DataFrame(),
        category="責任者用",
    ),
]


# --- ツール: メンバー別トークスクリプト（14名 × 各ボード） ---
TALK_SCRIPT_MEMBERS = [
    "室谷 慧",
    "原田 綾子",
    "金澤 駿平",
    "吉本 将吾",
    "大滝 紀香",
    "堀田 輝斗",
    "角田 心華",
    "佐々木 彩乃",
    "葛西 翼",
    "雨貝 一生",
    "半田 さくら",
    "菊地 隆真",
    "栗田 優衣",
    "高橋 真友香",
]

# 各メンバーが持つボード一覧（将来複数追加可）
# (suffix, label) のタプルリスト
TALK_SCRIPT_BOARDS = [
    ("fc1week", "1週間後FCトーク"),
]

for _i, _member in enumerate(TALK_SCRIPT_MEMBERS):
    for _suffix, _board_label in TALK_SCRIPT_BOARDS:
        METRICS.append(Metric(
            key=f"talk_script_{_i:02d}_{_suffix}",
            label=_board_label,
            description=f"{_member} の {_board_label}",
            fetch=lambda sf: pd.DataFrame(),
            category="ツール",
        ))


def parse_talk_script_key(key: str) -> tuple[str, str] | None:
    """
    talk_script_NN_xxx 形式のキーから (メンバー名, ボードラベル) を返す。
    パースできなければ None。
    """
    if not key.startswith("talk_script_"):
        return None
    parts = key.split("_", 3)
    # ['talk', 'script', 'NN', 'suffix']
    if len(parts) < 4:
        return None
    try:
        idx = int(parts[2])
    except ValueError:
        return None
    if idx >= len(TALK_SCRIPT_MEMBERS):
        return None
    suffix = parts[3]
    label = next((lbl for sfx, lbl in TALK_SCRIPT_BOARDS if sfx == suffix), suffix)
    return TALK_SCRIPT_MEMBERS[idx], label


def get_metric(key: str) -> Metric:
    for m in METRICS:
        if m.key == key:
            return m
    raise KeyError(key)
