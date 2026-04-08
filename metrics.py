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
    return _build_fc_1week(sf, "THIS_MONTH", board_label="1週間後FC")


def fetch_fc_1week_today(sf: Salesforce) -> Dict[str, pd.DataFrame]:
    return _build_fc_1week(sf, "TODAY", board_label="1週間後FC（本日）")


def _build_fc_1week(sf: Salesforce, date_literal: str, board_label: str) -> Dict[str, pd.DataFrame]:
    soql = (
        "SELECT ActivityDate, OwnerId, Owner.Name oname, "
        "Field4_del__c result, COUNT(Id) cnt "
        "FROM Task "
        "WHERE Field2_del__c IN ('フォローコール（1週間後FC）','フォローコール（その他）') "
        f"AND ActivityDate = {date_literal} "
        "AND Owner.UserRole.Name IN ('推進部','推進部AP') "
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

    cancel_tables = _fetch_1week_cancel_reasons(sf, date_literal)
    return {board_label: df, **cancel_tables}


def _fetch_1week_cancel_reasons(sf: Salesforce, date_literal: str = "THIS_MONTH") -> Dict[str, pd.DataFrame]:
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
PROGRESS_START = "2026-02-01"  # エントリ日 >= この日付


def _fetch_progress(sf: Salesforce, product_keyword: str, header: str, with_settlement: bool) -> pd.DataFrame:
    soql = (
        "SELECT Field156__c, Field130__c, Field128__c, Field131__c, Field119__c "
        "FROM Account "
        f"WHERE Field76__r.Name LIKE '%{product_keyword}%' "
        f"AND Field156__c >= {PROGRESS_START}"
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
        row["キャンセル数"] = int(cancel_n)
        row["キャンセル率"] = pct(cancel_n)
        row["7日以内キャンセル数"] = int(cancel7_n)
        row["7日以内キャンセル率"] = pct(cancel7_n)
        out_rows.append(row)

    return pd.DataFrame(out_rows)


def fetch_progress(sf: Salesforce) -> Dict[str, pd.DataFrame]:
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


def fetch_cs_shift(sf: Salesforce) -> Dict[str, pd.DataFrame]:
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
        return {"CS促進シフト": pd.DataFrame()}

    def _fmt(t):
        if not t:
            return ""
        # "HH:MM:SS.000Z" → "HH:MM"
        return str(t)[:5]

    rows = []
    for r in rs:
        owner = (r.get("Field128__r") or {}).get("Name") or "(不明)"
        row = {"担当者": owner}
        for day, sf_, ef in SHIFT_DAY_FIELDS:
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
    return {f"CS促進 シフト ({year_label}{month_label})": df}


def fetch_list_volume(sf: Salesforce) -> Dict[str, pd.DataFrame]:
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
        rows.append(
            {
                "日付": d.strftime("%Y-%m-%d"),
                "ソネット(GIFT/5日経過)": so_cnt,
                "NURO(非GIFT/4日経過)": nuro_cnt,
                "合計": so_cnt + nuro_cnt,
            }
        )
    return {"リスト体積": pd.DataFrame(rows)}


METRICS: list[Metric] = [
    Metric(
        key="today",
        label="TODAY",
        description="本日分: 1週間後FCの集計（担当者別）",
        fetch=fetch_fc_1week_today,
        category="TODAY",
    ),
    Metric(
        key="cs_shift",
        label="CS促進シフト（今月）",
        description="稼働実績(CS促進)の今月シフト一覧",
        fetch=fetch_cs_shift,
        category="シフト",
    ),
    Metric(
        key="list_volume",
        label="リスト体積",
        description="1週間後FCの架電対象数を当日〜30日後まで日別に予測",
        fetch=fetch_list_volume,
        category="リスト体積",
    ),
    Metric(
        key="progress",
        label="開通進捗",
        description="取次商材別の月次進捗（エントリ日2月以降）",
        fetch=fetch_progress,
        category="開通進捗",
    ),
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
