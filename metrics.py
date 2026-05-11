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


# シフト・集計タブから常に除外する担当者（正規化名: 半角/全角空白除去）
EXCLUDED_OWNERS_NORM = {"高橋真友香", "大滝紀香"}


def fetch_fc_1week(sf: Salesforce) -> dict[str, pd.DataFrame]:
    return _build_fc_board(sf, "THIS_MONTH", board_label="1週間後FC",
        activities=("フォローコール（1週間後FC）", "フォローコール（その他）"))


def fetch_fc_1week_today(sf: Salesforce) -> dict[str, pd.DataFrame]:
    return _build_fc_board(sf, "TODAY", board_label="1週間後FC（本日）",
        activities=("フォローコール（1週間後FC）", "フォローコール（その他）"))


SHINSETSU_FC_NAMES = {
    n.replace(" ", "").replace("\u3000", "")
    for n in ["佐々木彩乃", "葛西翼", "雨貝一生", "半田さくら", "菊地隆真", "栗田優衣"]
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
    EXCLUDE_OWNERS = {"CS1", "CS2", "CS3", "CS4", "CS5", "CS6", "CS7"} | EXCLUDED_OWNERS_NORM
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


_CX_CHECK_COLUMNS = [
    "申込受付番号",
    "担当者",
    "1週間後FC完了履歴日",
    "キャンセル日",
    "キャンセル対応コメント",
    "キャンセル理由（大）",
    "キャンセル理由（中）",
    "キャンセル理由（小）",
]


def fetch_1week_cx_check(sf: Salesforce) -> pd.DataFrame:
    """1週間後CXチェック: 過去3ヶ月で「対応ステータス=フォローコール（1週間後FC）」
    かつ「コール結果=完了」の Task を残した担当者別に、その後キャンセルになった
    Account の一覧を返す。並び順は1週間後FC完了履歴日の降順。"""
    from datetime import datetime, timedelta

    start_date = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")

    empty = pd.DataFrame(columns=_CX_CHECK_COLUMNS)

    users_rs = sf.query_all(
        "SELECT Id FROM User WHERE Department = 'CS促進' AND IsActive = true"
    )["records"]
    cs_user_ids = {r["Id"] for r in users_rs}
    if not cs_user_ids:
        return empty
    ids_literal = ",".join(f"'{u}'" for u in cs_user_ids)

    fc_records = sf.query_all(
        "SELECT WhatId, Owner.Name, ActivityDate "
        "FROM Task "
        "WHERE Field2_del__c = 'フォローコール（1週間後FC）' "
        "AND Field4_del__c = '完了' "
        f"AND ActivityDate >= {start_date} "
        f"AND OwnerId IN ({ids_literal}) "
        "AND WhatId != null"
    )["records"]

    fc_map: dict[str, list] = {}
    for r in fc_records:
        wid = r.get("WhatId")
        if not wid or not wid.startswith("001"):
            continue
        owner_name = r["Owner"]["Name"] if r.get("Owner") else "(不明)"
        fc_map.setdefault(wid, []).append((owner_name, r.get("ActivityDate")))

    if not fc_map:
        return empty

    account_ids = list(fc_map.keys())
    account_map: dict[str, dict] = {}
    for i in range(0, len(account_ids), 200):
        chunk = account_ids[i : i + 200]
        ids_str = ",".join(f"'{x}'" for x in chunk)
        rs = sf.query_all(
            "SELECT Id, Field63__c, Field119__c, Field234__c, Field80__c, Field235__c "
            "FROM Account "
            f"WHERE Id IN ({ids_str}) "
            "AND Field233__c = true "
            "AND Field119__c != null"
        )["records"]
        for r in rs:
            account_map[r["Id"]] = {
                "受付No": r.get("Field63__c") or "",
                "キャンセル日": r.get("Field119__c") or "",
                "大": r.get("Field234__c") or "",
                "中": r.get("Field80__c") or "",
                "小": r.get("Field235__c") or "",
            }

    if not account_map:
        return empty

    valid_rows: list[dict] = []
    for wid, fc_list in fc_map.items():
        acc = account_map.get(wid)
        if not acc:
            continue
        cancel_date = acc["キャンセル日"]
        if not cancel_date:
            continue
        eligible = [
            (owner, fc_date)
            for owner, fc_date in fc_list
            if fc_date and fc_date <= cancel_date
        ]
        if not eligible:
            continue
        eligible.sort(key=lambda x: x[1], reverse=True)
        owner, fc_date = eligible[0]
        valid_rows.append({
            "account_id": wid,
            "owner": owner,
            "fc_date": fc_date,
            "cancel_date": cancel_date,
            "受付No": acc["受付No"],
            "大": acc["大"],
            "中": acc["中"],
            "小": acc["小"],
        })

    if not valid_rows:
        return empty

    valid_ids = [r["account_id"] for r in valid_rows]
    cancel_task_map: dict[str, list] = {}
    for i in range(0, len(valid_ids), 200):
        chunk = valid_ids[i : i + 200]
        ids_str = ",".join(f"'{x}'" for x in chunk)
        rs = sf.query_all(
            "SELECT WhatId, ActivityDate, Description "
            "FROM Task "
            f"WHERE WhatId IN ({ids_str}) "
            "AND Field2_del__c = 'キャンセル対応' "
            "AND Field4_del__c != '留守' "
            "ORDER BY ActivityDate DESC"
        )["records"]
        for r in rs:
            wid = r.get("WhatId")
            if not wid:
                continue
            cancel_task_map.setdefault(wid, []).append(
                (r.get("ActivityDate") or "", r.get("Description") or "")
            )

    rows = []
    for r in valid_rows:
        tasks = cancel_task_map.get(r["account_id"], [])
        top3 = [(d, desc) for d, desc in tasks if desc][:3]
        comment_text = "\n---\n".join(f"[{d}] {desc}" for d, desc in top3)
        rows.append({
            "申込受付番号": r["受付No"],
            "担当者": r["owner"],
            "1週間後FC完了履歴日": r["fc_date"],
            "キャンセル日": r["cancel_date"],
            "キャンセル対応コメント": comment_text,
            "キャンセル理由（大）": r["大"],
            "キャンセル理由（中）": r["中"],
            "キャンセル理由（小）": r["小"],
        })

    df = pd.DataFrame(rows, columns=_CX_CHECK_COLUMNS)
    if not df.empty:
        df = df.sort_values("1週間後FC完了履歴日", ascending=False).reset_index(drop=True)
    return df


# ----------------------------------------------------------------------
# 指標レジストリ
# ----------------------------------------------------------------------
def _progress_start() -> str:
    """6ヶ月前の1日を YYYY-MM-DD で返す。"""
    today = pd.Timestamp.today()
    dt = today - pd.DateOffset(months=6)
    return dt.replace(day=1).strftime("%Y-%m-%d")


def _fetch_progress(sf: Salesforce, like_pattern: str, header: str, with_settlement: bool,
                    extra_sf_fields: list[tuple[str, str]] | None = None,
                    detail_columns: list[str] | None = None):
    """
    extra_sf_fields: 追加でSELECTするSalesforce項目 [(sf_field, 表示名), ...]
    detail_columns: 促進必要件数明細に表示する列名(順序付き)。
                    既定: ["申込受付番号", "電話番号"]
                    特殊ラベル「エントリ日」「工事予定日」はbase項目から抽出される。
    """
    extra_sf_fields = extra_sf_fields or []
    detail_columns = detail_columns or ["申込受付番号", "電話番号"]
    start = _progress_start()
    base_select = "Field156__c, Field130__c, Field128__c, Field131__c, Field119__c, Field63__c, X1__c"
    extra_select = ", ".join(sf_f for sf_f, _ in extra_sf_fields)
    select_clause = base_select + (", " + extra_select if extra_select else "")
    soql = (
        f"SELECT {select_clause} "
        "FROM Account "
        f"WHERE Field76__r.Name LIKE '{like_pattern}' "
        f"AND Field156__c >= {start}"
    )
    rs = sf.query_all(soql)["records"]
    if not rs:
        return pd.DataFrame(), pd.DataFrame(columns=["月"] + detail_columns)
    def _fmt(v):
        if isinstance(v, bool):
            return "✓" if v else ""
        return v if v is not None else ""

    df = pd.DataFrame([
        {
            "entry": r.get("Field156__c"),
            "kaitsu": r.get("Field130__c"),
            "yotei": r.get("Field128__c"),
            "kessai": r.get("Field131__c"),
            "cancel": r.get("Field119__c"),
            "申込受付番号": r.get("Field63__c") or "",
            "電話番号": r.get("X1__c") or "",
            **{label: _fmt(r.get(sf_field)) for sf_field, label in extra_sf_fields},
        }
        for r in rs
    ])
    for c in ["entry", "kaitsu", "yotei", "kessai", "cancel"]:
        df[c] = pd.to_datetime(df[c], errors="coerce")
    df = df.dropna(subset=["entry"])
    df["月"] = df["entry"].dt.strftime("%Y-%m")
    today = pd.Timestamp(pd.Timestamp.today().date())

    out_rows = []
    detail_rows = []
    for month, sub in df.groupby("月", sort=True):
        entry_n = len(sub)
        kaitsu_n = sub["kaitsu"].notna().sum()
        yotei_n = ((sub["yotei"] > today) & sub["kaitsu"].isna()).sum()
        cancel_n = sub["cancel"].notna().sum()
        diff = (sub["cancel"] - sub["entry"]).dt.days
        cancel7_n = ((diff >= 0) & (diff <= 7)).sum()

        def pct(n):
            return f"{round(n / entry_n * 100, 1)}%" if entry_n else "-"

        zanson_n = int(entry_n - cancel_n)
        sokushin_need_n = int(zanson_n - kaitsu_n - yotei_n)
        row = {
            "月": month,
            "エントリー数": int(entry_n),
            "残存件数": zanson_n,
            "残存率": pct(zanson_n),
            "工事完了数": int(kaitsu_n),
            "工事完了率": pct(kaitsu_n),
            "工事待ち数": int(yotei_n),
            "工事待ち率": pct(yotei_n),
            "促進必要件数": sokushin_need_n,
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
        # 申込日からN日目キャンセル（当日=0日目〜7日目）
        for d in range(8):
            label = "当日" if d == 0 else f"{d}日目"
            cx_d = int((diff == d).sum())
            row[f"{label}CX数"] = cx_d
            row[f"{label}CX率"] = pct(cx_d)
        out_rows.append(row)

        # 促進必要 = キャンセル無し AND 工事完了無し AND 工事予定が未来でない
        sokushin_mask = (
            sub["cancel"].isna()
            & sub["kaitsu"].isna()
            & ~(sub["yotei"] > today)
        )
        for _, dr in sub[sokushin_mask].iterrows():
            row_out = {"月": month}
            for col in detail_columns:
                if col == "エントリ日":
                    v = dr.get("entry")
                    row_out[col] = v.strftime("%Y-%m-%d") if pd.notna(v) else ""
                elif col == "工事予定日":
                    v = dr.get("yotei")
                    row_out[col] = v.strftime("%Y-%m-%d") if pd.notna(v) else ""
                else:
                    row_out[col] = dr.get(col, "")
            detail_rows.append(row_out)

    result = pd.DataFrame(out_rows)
    summary = result.iloc[::-1].reset_index(drop=True) if not result.empty else result
    details = pd.DataFrame(detail_rows, columns=["月"] + detail_columns)
    return summary, details


# コードベース・sync_report.pyから判明している label→API名 のハードコードマップ
_KNOWN_ACCOUNT_FIELDS: dict[str, str] = {
    "status大区分（引用）": "status__c",
    "工事Ⅰ状況（引用）": "Field210__c",
    "ダイコンステータス": "Field225__c",
    "促進ステータス": "Field144__c",
}


def _resolve_account_fields_by_label(sf: Salesforce, labels: list[str]) -> dict[str, str]:
    """label → API名 のマップを返す。
    1) コードベースで判明している既知マップを優先
    2) 未解決ぶんを Account.describe() で補完（label/label正規化の両方で照合）
    """
    label_to_api: dict[str, str] = {}
    # 1) known map
    for lab in labels:
        if lab in _KNOWN_ACCOUNT_FIELDS:
            label_to_api[lab] = _KNOWN_ACCOUNT_FIELDS[lab]
    # 2) describe で補完
    remaining = [l for l in labels if l not in label_to_api]
    if not remaining:
        return label_to_api
    try:
        desc = sf.Account.describe()
    except Exception:
        return label_to_api

    def _norm(s: str) -> str:
        return (s or "").replace(" ", "").replace("　", "").strip()

    target_norm = {_norm(l): l for l in remaining}
    for f in desc.get("fields", []):
        api = f.get("name")
        lab = f.get("label") or ""
        nlab = _norm(lab)
        if nlab in target_norm:
            label_to_api[target_norm[nlab]] = api
    return label_to_api


def fetch_progress(sf: Salesforce) -> dict[str, dict]:
    def _pack(pair):
        summary, details = pair
        return {"summary": summary, "details": details}

    # 各商材で必要な追加ラベル
    nuro_extras = ["status大区分（引用）", "プラン名（引用）", "工事Ⅰ状況（引用）", "工事Ⅱ状況（引用）", "status小区分"]
    sonet_extras = ["status大区分（引用）", "ダイコンステータス", "促進ステータス", "工事Ⅰ状況（引用）"]
    au_extras = ["status大区分（引用）", "工事取得FC"]

    label_map = _resolve_account_fields_by_label(
        sf, list(set(nuro_extras + sonet_extras + au_extras))
    )

    def _build(extras):
        return [(label_map[lab], lab) for lab in extras if lab in label_map]

    # 電話番号の右に工事予定日を必ず差し込む
    nuro_detail = ["申込受付番号", "電話番号", "工事予定日"] + [l for l in nuro_extras if l in label_map]
    sonet_detail = ["申込受付番号", "電話番号", "工事予定日"] + [l for l in sonet_extras if l in label_map]
    # AU光: 工事予定日の右に工事取得FCを置く
    au_after_yotei = [l for l in ["工事取得FC"] if l in label_map]
    au_remaining = [l for l in au_extras if l in label_map and l not in au_after_yotei]
    au_detail = ["申込受付番号", "電話番号", "工事予定日"] + au_after_yotei + au_remaining + ["エントリ日"]

    return {
        "NURO開通進捗": _pack(_fetch_progress(
            sf, "%NURO%", "NURO開通進捗", False,
            extra_sf_fields=_build(nuro_extras),
            detail_columns=nuro_detail,
        )),
        "ソネット開通進捗": _pack(_fetch_progress(
            sf, "%So-net%", "ソネット開通進捗", True,
            extra_sf_fields=_build(sonet_extras),
            detail_columns=sonet_detail,
        )),
        "AU光開通進捗": _pack(_fetch_progress(
            sf, "AU光%", "AU光開通進捗", False,
            extra_sf_fields=_build(au_extras),
            detail_columns=au_detail,
        )),
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


def _add_total_hours_column(df: pd.DataFrame) -> pd.DataFrame:
    """シフトDataFrameの担当者列の右横に合計実働時間列を挿入する。"""
    if df.empty:
        return df
    day_cols = [c for c in df.columns if c != "担当者"]
    totals = []
    for _, row in df.iterrows():
        total = 0.0
        for col in day_cols:
            val = str(row.get(col, ""))
            if "-" in val:
                parts = val.split("-", 1)
                total += _shift_hours(parts[0].strip(), parts[1].strip())
        totals.append(f"{total:.1f}h")
    df.insert(1, "合計", totals)
    return df


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
        if normalized in EXCLUDED_OWNERS_NORM:
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
    order = ["原田綾子", "室谷慧", "堀田輝斗", "角田心華", "金澤", "吉本"]
    def _rank(name: str) -> int:
        norm = (name or "").replace(" ", "").replace("\u3000", "")
        for i, key in enumerate(order):
            if key in norm:
                return i
        return len(order)
    if not df.empty:
        df = df.assign(_o=df["担当者"].map(_rank)).sort_values("_o", kind="stable").drop(columns="_o").reset_index(drop=True)
    return {f"1週間FCシフト ({year_label}{month_label})": _add_total_hours_column(df)}


SHINSETSU_FC_OWNERS = {
    n.replace(" ", "").replace("\u3000", "")
    for n in ["佐々木彩乃", "葛西翼", "雨貝一生", "半田さくら", "菊地隆真", "栗田優衣"]
}

SHINSETSU_FC_ORDER = ["佐々木彩乃", "葛西翼", "雨貝一生", "半田さくら", "菊地隆真", "栗田優衣"]


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
    return {f"新設FCシフト ({year_label}{month_label})": _add_total_hours_column(df)}


# --- 翌月シフト（責任者用） ---

# 促進全体メンバー（表示順）
_NEXT_MONTH_ALL_ORDER = [
    "吉田颯", "室谷慧", "原田綾子", "金澤駿平", "吉本将吾",
    "堀田輝斗", "角田心華", "佐々木彩乃", "葛西翼",
    "雨貝一生", "半田さくら", "菊地隆真", "栗田優衣", "勘七瞬",
]
_NEXT_MONTH_ALL_SET = {n for n in _NEXT_MONTH_ALL_ORDER}

# サブグループ（表示順）
_NM_FC_ORDER = ["室谷慧", "原田綾子", "金澤駿平", "吉本将吾", "角田心華", "菊地隆真"]
_NM_FC_SET = {n for n in _NM_FC_ORDER}

_NM_SOKUSHIN_ORDER = ["葛西翼", "雨貝一生", "半田さくら", "栗田優衣", "勘七瞬"]
_NM_SOKUSHIN_SET = {n for n in _NM_SOKUSHIN_ORDER}

_NM_TIMEE_ORDER = ["佐々木彩乃", "堀田輝斗"]
_NM_TIMEE_SET = {n for n in _NM_TIMEE_ORDER}


def _build_shift_df(records, visible_days, member_set, order_list):
    """共通: レコードからシフトDataFrameを構築する。"""
    def _fmt(t):
        if not t:
            return ""
        return str(t)[:5]

    rows = []
    for r in records:
        owner = (r.get("Field128__r") or {}).get("Name") or "(不明)"
        normalized = owner.replace(" ", "").replace("\u3000", "")
        if normalized not in member_set:
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
    if df.empty:
        return df

    def _rank(name: str) -> int:
        norm = (name or "").replace(" ", "").replace("\u3000", "")
        for i, key in enumerate(order_list):
            if key in norm:
                return i
        return len(order_list)
    return _add_total_hours_column(df.assign(_o=df["担当者"].map(_rank)).sort_values("_o", kind="stable").drop(columns="_o").reset_index(drop=True))


# シフト表ボード(cs_shift_calendar)専用の追加除外メンバー
# (退職者ではないが本ボードの表示対象外。EXCLUDED_OWNERS_NORMには含めない)
CS_SHIFT_CALENDAR_EXTRA_EXCLUDED_NORM = {"吉田颯"}


def fetch_cs_shift_for_month(sf: Salesforce, year: int, month: int) -> dict[int, list[tuple[str, str, str]]]:
    """指定月のCS促進全員のシフトを日別に返す。

    返り値: {day_int: [(氏名, 開始 'HH:MM', 終了 'HH:MM'), ...]}
    """
    year_label = f"{year}年"
    month_label = f"{month}月"

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
        return {}

    def _fmt(t):
        if not t:
            return ""
        return str(t)[:5]

    by_day: dict[int, list[tuple[str, str, str]]] = {}
    for r in rs:
        owner = (r.get("Field128__r") or {}).get("Name") or "(不明)"
        normalized = owner.replace(" ", "").replace("　", "")
        if normalized in EXCLUDED_OWNERS_NORM:
            continue
        if normalized in CS_SHIFT_CALENDAR_EXTRA_EXCLUDED_NORM:
            continue
        for day, sf_, ef in SHIFT_DAY_FIELDS:
            s = _fmt(r.get(sf_))
            e = _fmt(r.get(ef))
            if not s and not e:
                continue
            by_day.setdefault(day, []).append((owner, s, e))
    return by_day


def fetch_next_month_shift(sf: Salesforce) -> dict[str, pd.DataFrame]:
    """翌月のシフトを4グループに分けて返す。"""
    today = pd.Timestamp.today()
    # 翌月を算出
    if today.month == 12:
        nm_year, nm_month = today.year + 1, 1
    else:
        nm_year, nm_month = today.year, today.month + 1

    year_label = f"{nm_year}年"
    month_label = f"{nm_month}月"

    import calendar
    last_day = calendar.monthrange(nm_year, nm_month)[1]

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

    # 翌月は全日表示（1日〜末日）
    visible_days = [t for t in SHIFT_DAY_FIELDS if t[0] <= last_day]

    title_prefix = f"{year_label}{month_label}"
    empty = pd.DataFrame()

    if not rs:
        return {
            f"促進全体 ({title_prefix})": empty,
            f"1週間後FCシフト ({title_prefix})": empty,
            f"促進シフト ({title_prefix})": empty,
            f"タイミー部隊シフト ({title_prefix})": empty,
        }

    return {
        f"促進全体 ({title_prefix})": _build_shift_df(rs, visible_days, _NEXT_MONTH_ALL_SET, _NEXT_MONTH_ALL_ORDER),
        f"1週間後FCシフト ({title_prefix})": _build_shift_df(rs, visible_days, _NM_FC_SET, _NM_FC_ORDER),
        f"促進シフト ({title_prefix})": _build_shift_df(rs, visible_days, _NM_SOKUSHIN_SET, _NM_SOKUSHIN_ORDER),
        f"タイミー部隊シフト ({title_prefix})": _build_shift_df(rs, visible_days, _NM_TIMEE_SET, _NM_TIMEE_ORDER),
    }


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
    for n in ["角田心華", "原田綾子", "室谷慧", "堀田輝斗"]
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
    "室谷慧", "原田綾子", "金澤駿平", "吉本将吾", "堀田輝斗", "角田心華",
    "葛西翼", "雨貝一生", "半田さくら", "菊地隆真", "栗田優衣", "佐々木彩乃",
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
DAY_CALLS_EXCLUDE = {"太田海斗", "杉山敏樹", "柳原", "対馬", "対馬拓人", "早瀬太一"} | EXCLUDED_OWNERS_NORM


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


def _phone_to_e164(phone: str) -> str | None:
    """電話番号を Zoom Call Log の E.164 形式（+81xxx）に正規化。"""
    import re
    if not phone:
        return None
    digits = re.sub(r"[^0-9]", "", str(phone))
    if not digits:
        return None
    if digits.startswith("0"):
        return "+81" + digits[1:]
    if not digits.startswith("+"):
        return "+" + digits
    return digits


def _duration_to_sec(dur: str) -> int:
    """'mm:ss' または 'hh:mm:ss' を秒数に変換。"""
    if not dur:
        return 0
    parts = str(dur).split(":")
    try:
        if len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
    except ValueError:
        pass
    return 0


def _sec_to_mmss(sec: int) -> str:
    if sec <= 0:
        return "-"
    return f"{sec // 60:02d}:{sec % 60:02d}"


def fetch_call_history(sf: Salesforce, start_date: str | None = None, end_date: str | None = None) -> pd.DataFrame:
    """CS促進メンバー の架電履歴（留守以外）を期間指定で取得。
    - 対応区分/対応ステータス/コール結果/コメント/通話時間/依頼種別変更 を表示
    - 通話時間: Zoom Call Log (connected) を電話番号で紐付け
    - 依頼種別変更: 同一Accountの「開始日より前」の最新Task Field3__c と比較
    - 省略時: 本日のみ（リアルタイム用途のデフォルト）
    """
    from datetime import date as _date
    _today = _date.today().strftime("%Y-%m-%d")
    if not start_date:
        start_date = _today
    if not end_date:
        end_date = _today
    # 1. 所属部署=CS促進 のユーザーIDを取得（User.Department で厳密絞り込み）
    users_rs = sf.query_all(
        "SELECT Id, Name FROM User WHERE Department = 'CS促進' AND IsActive = true"
    )["records"]
    cs_user_ids = {
        r["Id"]
        for r in users_rs
        if (r.get("Name") or "").replace(" ", "").replace("　", "") not in EXCLUDED_OWNERS_NORM
    }
    if not cs_user_ids:
        return pd.DataFrame(columns=[
            "対応日", "対応日時", "担当者", "電話番号", "対応区分", "対応ステータス",
            "コール結果", "コメント", "通話時間", "依頼種別 変更前", "依頼種別 変更後",
        ])

    # 2. 期間内の Task（CS促進ユーザー、留守以外、コール結果入力済み）
    ids_literal = ",".join(f"'{u}'" for u in cs_user_ids)
    tasks_rs = sf.query_all(
        "SELECT Id, Owner.Name, OwnerId, Field1_del__c, Field2_del__c, Field3_del__c, "
        "Field4_del__c, Field3__c, Description, AccountId, Account.X1__c "
        "FROM Task "
        f"WHERE ActivityDate >= {start_date} "
        f"AND ActivityDate <= {end_date} "
        f"AND OwnerId IN ({ids_literal}) "
        "AND Field4_del__c != null "
        "AND Field4_del__c != '留守' "
        "ORDER BY Field1_del__c DESC NULLS LAST"
    )["records"]

    def _norm(n: str) -> str:
        return (n or "").replace(" ", "").replace("\u3000", "")

    target = tasks_rs
    if not target:
        return pd.DataFrame(columns=[
            "対応日時", "担当者", "電話番号", "対応区分", "対応ステータス",
            "コール結果", "コメント", "通話時間", "依頼種別 変更前", "依頼種別 変更後",
        ])

    # 3. 前回Task（同一Account、ActivityDate < start_date の最新1件）から旧依頼種別を取得
    account_ids = {t.get("AccountId") for t in target if t.get("AccountId")}
    prev_field3: dict[str, str | None] = {}
    if account_ids:
        ids_str = ",".join(f"'{a}'" for a in account_ids)
        prev_rs = sf.query_all(
            f"SELECT AccountId, Field3__c, Field1_del__c "
            f"FROM Task "
            f"WHERE AccountId IN ({ids_str}) "
            f"AND ActivityDate < {start_date} "
            f"AND Field1_del__c != null "
            f"ORDER BY Field1_del__c DESC"
        )["records"]
        # AccountIdごとに最初（= 最新）の値を採用
        for r in prev_rs:
            aid = r.get("AccountId")
            if aid and aid not in prev_field3:
                prev_field3[aid] = r.get("Field3__c")

    # 4. Zoom Call Log (期間内 connected, CS促進ユーザー) を担当者×電話番号でインデックス化
    zoom_rs = sf.query_all(
        "SELECT Owner.Name, OwnerId, ZVC__Callee_Phone_Number__c, ZVC__Call_Duration__c "
        "FROM ZVC__Zoom_Call_Log__c "
        f"WHERE DAY_ONLY(CreatedDate) >= {start_date} "
        f"AND DAY_ONLY(CreatedDate) <= {end_date} "
        f"AND OwnerId IN ({ids_literal}) "
        "AND ZVC__Call_Result__c = 'connected'"
    )["records"]
    # {(担当者norm, phone_e164): [duration_sec, ...]}
    zoom_idx: dict[tuple[str, str], list[int]] = {}
    for z in zoom_rs:
        owner_norm = _norm((z.get("Owner") or {}).get("Name"))
        phone = z.get("ZVC__Callee_Phone_Number__c")
        if not phone:
            continue
        key = (owner_norm, phone)
        zoom_idx.setdefault(key, []).append(_duration_to_sec(z.get("ZVC__Call_Duration__c")))

    # 5. 各Taskの通話時間を引き当て（電話番号の一致件数ぶんの先頭を消費）
    from datetime import datetime, timezone, timedelta as _td
    jst = timezone(_td(hours=9))

    rows = []
    for t in target:
        owner = (t.get("Owner") or {}).get("Name", "")
        owner_norm = _norm(owner)
        acc = t.get("Account") or {}
        phone_e164 = _phone_to_e164(acc.get("X1__c"))

        # 通話時間: 担当者×電話番号の Zoom ログのうち、先頭から1件消費
        talk_sec = 0
        if phone_e164:
            bucket = zoom_idx.get((owner_norm, phone_e164)) or []
            if bucket:
                talk_sec = bucket.pop(0)  # 1件ずつ割り当て
        talk_disp = _sec_to_mmss(talk_sec)

        # 依頼種別変更（変更前/変更後 を分離）
        new_val = t.get("Field3__c")
        old_val = prev_field3.get(t.get("AccountId"))
        def _disp(v):
            return v if v else "-"
        if (new_val or None) == (old_val or None):
            before_disp = "-"
            after_disp = "-"
        else:
            before_disp = _disp(old_val)
            after_disp = _disp(new_val)

        # 対応日時（JSTの YYYY-MM-DD / HH:MM）
        tdt_raw = t.get("Field1_del__c")
        date_disp = ""
        time_disp = ""
        if tdt_raw:
            try:
                dt = datetime.fromisoformat(tdt_raw.replace("Z", "+00:00")).astimezone(jst)
                date_disp = dt.strftime("%Y/%m/%d")
                time_disp = dt.strftime("%H:%M")
            except Exception:
                time_disp = tdt_raw

        # コメントの改行・復帰コードを整形（空行は捨てて / で連結）
        import re as _re
        raw_desc = t.get("Description") or ""
        _lines = [ln.strip() for ln in _re.split(r"[\r\n]+", raw_desc) if ln.strip()]
        desc_clean = " / ".join(_lines)[:200]

        rows.append({
            "対応日": date_disp,
            "対応日時": time_disp,
            "担当者": owner,
            "電話番号": acc.get("X1__c") or "",
            "対応区分": t.get("Field3_del__c") or "",
            "対応ステータス": t.get("Field2_del__c") or "",
            "コール結果": t.get("Field4_del__c") or "",
            "コメント": desc_clean,
            "通話時間": talk_disp,
            "依頼種別 変更前": before_disp,
            "依頼種別 変更後": after_disp,
        })

    return pd.DataFrame(rows, columns=[
        "対応日", "対応日時", "担当者", "電話番号", "対応区分", "対応ステータス",
        "コール結果", "コメント", "通話時間", "依頼種別 変更前", "依頼種別 変更後",
    ])


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


def fetch_kari_keisan_gift_gai(sf: Salesforce) -> dict[str, pd.DataFrame]:
    """
    仮計算: 2026/1-4月エントリで、ソネット/NURO取次のエントリー件数を
    【レコード所有企業 × 月】で集計。
    4シート構成: [ソネット (GIFT外)] [NURO (GIFT外)] [株式会社GIFT ソネット] [株式会社GIFT NURO]
    総計行の下に N日後CX件数(N=3,4,5) と差引件数を月別に追加。
    CX判定: 開通日(Field130__c)空 AND キャンセル日(Field119__c)がエントリ日から丁度N日後。
    """
    from collections import defaultdict
    from datetime import datetime

    PERIOD_START = "2026-01-01"
    PERIOD_END = "2026-05-01"  # exclusive
    MONTH_COLS = ["2026/01エントリー", "2026/02エントリー", "2026/03エントリー", "2026/04エントリー"]
    CX_DAY_THRESHOLDS = [3, 4, 5]
    GIFT = "株式会社GIFT"

    # GIFT / 非GIFT 両方取得
    soql = (
        "SELECT Field156__c, Field232__c, Field108__c, Field119__c, Field130__c "
        "FROM Account "
        f"WHERE Field156__c >= {PERIOD_START} "
        f"AND Field156__c < {PERIOD_END} "
        "AND (Field232__c LIKE 'NURO光_%' OR Field232__c LIKE 'So-net光_%')"
    )
    try:
        records = sf.query_all(soql)["records"]
    except Exception as e:
        err_df = pd.DataFrame({"エラー": [f"取得失敗: {e}"]})
        return {
            "ソネット": err_df, "NURO": err_df,
            "株式会社GIFT ソネット": err_df, "株式会社GIFT NURO": err_df,
        }

    # stats[bucket][kind][company][month_key] = count
    # cx_stats[bucket][kind][month_key][N日] = count
    def _make_stats():
        return {
            "非GIFT": {
                "ソネット": defaultdict(lambda: defaultdict(int)),
                "NURO": defaultdict(lambda: defaultdict(int)),
            },
            "GIFT": {
                "ソネット": defaultdict(lambda: defaultdict(int)),
                "NURO": defaultdict(lambda: defaultdict(int)),
            },
        }
    stats = _make_stats()
    cx_stats: dict[str, dict[str, dict[str, dict[int, int]]]] = {
        "非GIFT": {
            "ソネット": defaultdict(lambda: defaultdict(int)),
            "NURO": defaultdict(lambda: defaultdict(int)),
        },
        "GIFT": {
            "ソネット": defaultdict(lambda: defaultdict(int)),
            "NURO": defaultdict(lambda: defaultdict(int)),
        },
    }

    for r in records:
        entry_date_str = r.get("Field156__c")
        if not entry_date_str:
            continue
        try:
            d = datetime.strptime(entry_date_str, "%Y-%m-%d").date()
        except (ValueError, TypeError):
            continue
        month_key = f"{d.year}/{d.month:02d}エントリー"

        shozai = r.get("Field232__c") or ""
        if shozai.startswith("NURO光_"):
            kind = "NURO"
        elif shozai.startswith("So-net光_"):
            kind = "ソネット"
        else:
            continue

        company = (r.get("Field108__c") or "（未入力）").strip() or "（未入力）"
        bucket = "GIFT" if company == GIFT else "非GIFT"
        stats[bucket][kind][company][month_key] += 1

        # CX判定: 開通日なし AND キャンセル日あり AND 差分日数が閾値と一致
        if r.get("Field130__c"):
            continue
        cancel_date_str = r.get("Field119__c")
        if not cancel_date_str:
            continue
        try:
            cancel_d = datetime.strptime(cancel_date_str, "%Y-%m-%d").date()
        except (ValueError, TypeError):
            continue
        days_diff = (cancel_d - d).days
        if days_diff in CX_DAY_THRESHOLDS:
            cx_stats[bucket][kind][month_key][days_diff] += 1

    def _build_df(bucket: str, kind: str) -> pd.DataFrame:
        data = stats[bucket][kind]
        if not data:
            empty_row = {"レコード所有企業": "—"}
            for m in MONTH_COLS:
                empty_row[m] = 0
            empty_row["合計"] = 0
            return pd.DataFrame([empty_row])

        rows = []
        for company, months in data.items():
            row = {"レコード所有企業": company}
            total = 0
            for m in MONTH_COLS:
                cnt = months.get(m, 0)
                row[m] = cnt
                total += cnt
            row["合計"] = total
            rows.append(row)

        rows.sort(key=lambda x: x["合計"], reverse=True)

        grand = {"レコード所有企業": "総計"}
        for m in MONTH_COLS:
            grand[m] = sum(r[m] for r in rows)
        grand["合計"] = sum(r["合計"] for r in rows)
        rows.append(grand)

        # 差引は前の差引から当該N日後CX件数を累積減算（月別）
        running = {m: grand[m] for m in MONTH_COLS}
        for thresh in CX_DAY_THRESHOLDS:
            cx_row = {"レコード所有企業": f"{thresh}日後CX件数"}
            diff_row = {"レコード所有企業": f"{thresh}日後CX差引件数"}
            cx_total = 0
            for m in MONTH_COLS:
                cx_cnt = cx_stats[bucket][kind].get(m, {}).get(thresh, 0)
                running[m] -= cx_cnt
                cx_row[m] = cx_cnt
                diff_row[m] = running[m]
                cx_total += cx_cnt
            cx_row["合計"] = cx_total
            diff_row["合計"] = sum(running[m] for m in MONTH_COLS)
            rows.append(cx_row)
            rows.append(diff_row)

        return pd.DataFrame(rows)

    return {
        "ソネット": _build_df("非GIFT", "ソネット"),
        "NURO": _build_df("非GIFT", "NURO"),
        "株式会社GIFT ソネット": _build_df("GIFT", "ソネット"),
        "株式会社GIFT NURO": _build_df("GIFT", "NURO"),
    }


def fetch_cx_age_area(
    sf: Salesforce,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, pd.DataFrame]:
    """
    エリア別×年代別のCX内訳を集計。
    CX = 開通日(Field130__c)が空 AND キャンセル日(Field119__c)に日付あり。
    申込日(Field118__c) = エントリ日で期間フィルター。

    「その他」CX理由は集計対象外。
    CX率 = その年代のCX件数 / その年代の申込総数。
    7日以内/以降の区分: エントリ日からキャンセル日までの経過日数で判定。

    start_date / end_date は "YYYY-MM-DD" 文字列。両方未指定なら直近6ヶ月。
    """
    import math

    where_parts = []
    if start_date or end_date:
        if start_date:
            where_parts.append(f"Field118__c >= {start_date}")
        if end_date:
            where_parts.append(f"Field118__c <= {end_date}")
    else:
        where_parts.append("Field118__c >= LAST_N_MONTHS:6")

    # CX率計算のため全申込を取得（CXフラグはPython側で判定）
    soql = (
        "SELECT Field43__c, Field42__c, Field80__c, Field118__c, Field119__c, Field130__c "
        "FROM Account "
        "WHERE " + " AND ".join(where_parts)
    )
    records = sf.query_all(soql).get("records", [])
    if not records:
        return {"エラー": pd.DataFrame({"メッセージ": ["CXデータがありません"]})}

    all_rows = []   # 全申込
    cx_rows = []    # CXのみ（CX理由集計用、「その他」除外）
    for r in records:
        area = (r.get("Field43__c") or "").strip()
        age_raw = r.get("Field42__c")
        reason = (r.get("Field80__c") or "").strip()
        entry_date = r.get("Field118__c")
        cancel_date = r.get("Field119__c")
        open_date = r.get("Field130__c")

        if not area:
            area = "不明"
        try:
            age = int(float(age_raw))
            if age < 20:
                age_group = "10代以下"
            elif age >= 70:
                age_group = "70代以上"
            else:
                age_group = f"{(age // 10) * 10}代"
        except (ValueError, TypeError):
            age_group = "不明"

        is_cx = bool(cancel_date) and not bool(open_date)
        # エントリ日〜キャンセル日の経過日数を計算
        days_to_cancel = None
        if is_cx and entry_date and cancel_date:
            try:
                d_entry = pd.to_datetime(entry_date)
                d_cancel = pd.to_datetime(cancel_date)
                days_to_cancel = (d_cancel - d_entry).days
            except Exception:
                days_to_cancel = None

        all_rows.append({
            "エリア": area,
            "年代": age_group,
            "is_cx": is_cx,
            "days_to_cancel": days_to_cancel,
        })

        # CX理由集計用（その他除外）
        if is_cx and reason and reason != "その他":
            cx_rows.append({"エリア": area, "年代": age_group, "CX理由": reason})

    df_all = pd.DataFrame(all_rows)
    df = pd.DataFrame(cx_rows) if cx_rows else pd.DataFrame(columns=["エリア", "年代", "CX理由"])

    AGE_ORDER = ["10代以下", "20代", "30代", "40代", "50代", "60代", "70代以上", "不明"]

    result = {}

    # --- エリア別×年代別 CX件数 ---
    for area_label, area_filter in [("東日本", "東"), ("西日本", "西"), ("合算", None)]:
        if area_filter:
            sub = df[df["エリア"] == area_filter]
        else:
            sub = df
        pivot = sub.groupby("年代").size().reset_index(name="CX件数")
        total = sub.shape[0]
        pivot["構成比"] = pivot["CX件数"].apply(lambda x: f"{x/total*100:.1f}%" if total else "0%")
        # 年代順にソート
        pivot["_order"] = pivot["年代"].apply(lambda x: AGE_ORDER.index(x) if x in AGE_ORDER else 99)
        pivot = pivot.sort_values("_order").drop(columns="_order").reset_index(drop=True)
        # 合計行
        pivot = pd.concat([pivot, pd.DataFrame([{"年代": "合計", "CX件数": total, "構成比": "100%"}])], ignore_index=True)
        result[f"CX件数（{area_label}）"] = pivot

    # --- エリア別×年代別 7日以内/以降 CX率 ---
    #     CX率 = その年代のCX件数 / その年代の申込総数（全申込ベース）
    for area_label, area_filter in [("東日本", "東"), ("西日本", "西"), ("合算", None)]:
        if area_filter:
            sub_all = df_all[df_all["エリア"] == area_filter]
        else:
            sub_all = df_all
        rows_out = []
        for ag in AGE_ORDER:
            ag_all = sub_all[sub_all["年代"] == ag]
            total_n = ag_all.shape[0]
            if total_n == 0:
                continue
            ag_cx = ag_all[ag_all["is_cx"] == True]
            within_cx = ag_cx[(ag_cx["days_to_cancel"].notna()) & (ag_cx["days_to_cancel"] <= 7)].shape[0]
            after_cx = ag_cx[(ag_cx["days_to_cancel"].notna()) & (ag_cx["days_to_cancel"] > 7)].shape[0]
            rows_out.append({
                "年代": ag,
                "申込数": total_n,
                "7日以内CX": within_cx,
                "7日以内CX率": f"{within_cx/total_n*100:.1f}%" if total_n else "0%",
                "7日以降CX": after_cx,
                "7日以降CX率": f"{after_cx/total_n*100:.1f}%" if total_n else "0%",
            })
        # 合計行
        total_n_all = sub_all.shape[0]
        cx_all = sub_all[sub_all["is_cx"] == True]
        w_all = cx_all[(cx_all["days_to_cancel"].notna()) & (cx_all["days_to_cancel"] <= 7)].shape[0]
        a_all = cx_all[(cx_all["days_to_cancel"].notna()) & (cx_all["days_to_cancel"] > 7)].shape[0]
        if rows_out:
            rows_out.append({
                "年代": "合計",
                "申込数": total_n_all,
                "7日以内CX": w_all,
                "7日以内CX率": f"{w_all/total_n_all*100:.1f}%" if total_n_all else "0%",
                "7日以降CX": a_all,
                "7日以降CX率": f"{a_all/total_n_all*100:.1f}%" if total_n_all else "0%",
            })
            result[f"年代別CX率（7日以内/以降）（{area_label}）"] = pd.DataFrame(rows_out)

    # --- エリア別×「年代×CX理由」組み合わせ全体TOP10（「その他」除外済み） ---
    #     どこの年代のどういうCXが多いのかを俯瞰できる統合テーブル
    for area_label, area_filter in [("東日本", "東"), ("西日本", "西"), ("合算", None)]:
        if area_filter:
            sub = df[df["エリア"] == area_filter]
        else:
            sub = df
        combo_pivot = sub.groupby(["年代", "CX理由"]).size().reset_index(name="件数")
        combo_pivot = combo_pivot.sort_values("件数", ascending=False).head(10)
        _area_total = sub.shape[0]
        combo_rows = []
        for rank, (_, row) in enumerate(combo_pivot.iterrows(), start=1):
            _cnt = int(row["件数"])
            _ratio = f"{_cnt/_area_total*100:.1f}%" if _area_total else "0%"
            combo_rows.append({
                "順位": rank,
                "年代": row["年代"],
                "CX理由": row["CX理由"],
                "件数": _cnt,
                "構成比": _ratio,
            })
        if combo_rows:
            result[f"年代×CX理由 TOP10（{area_label}）"] = pd.DataFrame(combo_rows)

    # --- エリア別×年代別×CX理由 TOP10（「その他」除外済み） ---
    for area_label, area_filter in [("東日本", "東"), ("西日本", "西"), ("合算", None)]:
        if area_filter:
            sub = df[df["エリア"] == area_filter]
        else:
            sub = df
        reason_pivot = sub.groupby(["年代", "CX理由"]).size().reset_index(name="件数")
        # 年代ごとにTOP10のCX理由を表示
        top_rows = []
        for ag in AGE_ORDER:
            ag_data = reason_pivot[reason_pivot["年代"] == ag].sort_values("件数", ascending=False).head(10)
            _age_total = int(ag_data["件数"].sum())
            for rank, (_, row) in enumerate(ag_data.iterrows(), start=1):
                _cnt = int(row["件数"])
                _ratio = f"{_cnt/_age_total*100:.1f}%" if _age_total else "0%"
                top_rows.append({
                    "年代": row["年代"],
                    "順位": rank,
                    "CX理由": row["CX理由"],
                    "件数": _cnt,
                    "構成比": _ratio,
                })
        if top_rows:
            result[f"年代別CX理由TOP10（{area_label}）"] = pd.DataFrame(top_rows)

    return result


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


# ======================================================================
# 1週間後FC 資料ボード（Google Sheets 読み取り専用）
# ======================================================================
_SHIRYOU_SHEET_ID = "1E-bMWswznqU8GZBA-3cUy9FAYKO0oYWGsf4tk6w4ryY"


def fetch_fc_shiryou(sf: Salesforce) -> dict[str, pd.DataFrame]:
    """
    シート2（1週間後FC 基本手順）とシート3（不備対応手順）を読み取り、
    セクションごとに整形して返す。
    戻り値は {"__shiryou__": [section, ...]} の特殊形式。
    app.py 側でカスタム描画する。
    """
    from talk_script_store import _get_gspread_client

    try:
        client = _get_gspread_client()
        sp = client.open_by_key(_SHIRYOU_SHEET_ID)
    except Exception as e:
        return {"エラー": pd.DataFrame({"メッセージ": [f"シート取得失敗: {e}"]})}

    def _read_sheet(name: str) -> list[list[str]]:
        ws = sp.worksheet(name)
        return ws.get_all_values()

    try:
        raw2 = _read_sheet("シート2")
        raw3 = _read_sheet("シート3")
    except Exception as e:
        return {"エラー": pd.DataFrame({"メッセージ": [f"シート読み込み失敗: {e}"]})}

    sections = []

    # --- シート2: 1週間後FC 基本手順 ---
    sections.append(_parse_sheet2(raw2))
    # --- シート3: 不備対応手順 ---
    sections.append(_parse_sheet3(raw3))

    return {"__shiryou__": sections}


def _cell(row: list[str], idx: int) -> str:
    if idx < len(row):
        return (row[idx] or "").strip()
    return ""


def _collect(raw, rows, col) -> list[str]:
    """指定行範囲・列から空でないセルを収集。"""
    return [_cell(raw[i], col) for i in range(rows[0], min(rows[1], len(raw))) if _cell(raw[i], col)]


def _parse_sheet2(raw: list[list[str]]) -> dict:
    """シート2をフロー図向けに構造化。"""
    return {
        "title": "1週間後FC 基本手順",
        "scope": _cell(raw[2], 1) if len(raw) > 2 else "",
        "task": _cell(raw[4], 1) if len(raw) > 4 else "",
        "confirm": _collect(raw, (6, 14), 1),
        "after_call": [
            {"label": "架電　留守",         "icon": "phone_rusu",    "items": _collect(raw, (15, 30), 1)},
            {"label": "架電　留守（7日目）", "icon": "phone_rusu7",   "items": _collect(raw, (15, 30), 3)},
            {"label": "架電　完了",         "icon": "phone_kanryou", "items": _collect(raw, (15, 30), 5)},
        ],
        "callback": [
            {"label": "折り返し対応（再コール）", "items": _collect(raw, (30, 41), 1)},
            {"label": "折り返し対応（完了時）",   "items": _collect(raw, (30, 41), 4)},
        ],
    }


def _parse_sheet3(raw: list[list[str]]) -> dict:
    """シート3を不備カテゴリ別に構造化。"""
    categories = []

    # --- 番ポ不備 ---
    categories.append({
        "name": "番ポ不備", "color": "#E67E22",
        "desc": _cell(raw[4], 1) if len(raw) > 4 else "",
        "steps": _collect(raw, (6, 11), 1),
        "complete": _collect(raw, (17, 28), 1),
        "absent": _collect(raw, (17, 28), 6),
        "flow": _collect(raw, (30, 36), 1),
    })

    # --- 住所不備 ---
    categories.append({
        "name": "住所不備", "color": "#2980B9",
        "desc": _cell(raw[4], 10) if len(raw) > 4 else "",
        "steps": _collect(raw, (6, 11), 10),
        "complete": _collect(raw, (17, 28), 10),
        "absent": _collect(raw, (17, 28), 15),
        "flow": _collect(raw, (31, 36), 10),
    })

    # --- 事業変 ---
    categories.append({
        "name": "事業変", "color": "#8E44AD",
        "desc": _cell(raw[60], 1) if len(raw) > 60 else "",
        "steps": _collect(raw, (64, 67), 1),
        "notes": _collect(raw, (69, 73), 1),
        "complete": _collect(raw, (78, 93), 1),
        "absent": _collect(raw, (78, 93), 6),
        "flow": _collect(raw, (95, 101), 1),
    })

    # --- 事前解約 ---
    categories.append({
        "name": "事前解約", "color": "#C0392B",
        "desc": _cell(raw[60], 11) if len(raw) > 60 else "",
        "steps": _collect(raw, (64, 67), 11),
        "notes": _collect(raw, (69, 73), 11),
        "complete": _collect(raw, (78, 93), 11),
        "absent": _collect(raw, (78, 93), 15),
        "flow": [],
    })

    # --- 豆知識 ---
    knowledge = _collect(raw, (37, 54), 1)

    return {
        "title": "不備対応手順",
        "categories": categories,
        "knowledge": knowledge,
    }


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
        key="cs_shift_calendar",
        label="シフト表",
        description="CS促進全員の月間シフトをカレンダー形式で表示",
        fetch=lambda sf: pd.DataFrame(),
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
        key="cx_age_area",
        label="エリア別年代別CX内訳",
        description="エリア×年代別のCX件数＋CX理由TOP10（「その他」除外、構成比付き）",
        fetch=fetch_cx_age_area,
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
        key="1week_cx_check",
        label="１週間後CXチェック",
        description="過去3ヶ月で1週間後FC完了→キャンセルになった案件一覧（活動完了日で絞り込み可）",
        fetch=fetch_1week_cx_check,
        category="TOTAL",
    ),
    Metric(
        key="line_template",
        label="Lステ整形",
        description="電話番号→顧客の商流／取次商材を引き当て、自由入力テキストに名乗り・発信番号を差し込んだ定型文を生成",
        fetch=lambda sf: pd.DataFrame(),
        category="TOTAL",
    ),
    Metric(
        key="kari_keisan_gift_gai",
        label="仮計算",
        description="2026/1-4月エントリ: レコード所有企業が株式会社GIFT以外のソネット/NURO取次件数を月別集計",
        fetch=fetch_kari_keisan_gift_gai,
        category="TOTAL",
    ),
    Metric(
        key="timee_management",
        label="タイミー管理",
        description="タイミー就業予定表を5分ごとに自動同期。ワーカーごと固有6桁ID/メモ/タグ/直雇勧誘済/キャンセル数を管理",
        fetch=lambda sf: pd.DataFrame(),
        category="タイミー",
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
        key="next_month_shift",
        label="促進翌月シフト",
        description="翌月のシフト一覧（促進全体・1週間後FC・促進・タイミー部隊）",
        fetch=fetch_next_month_shift,
        category="責任者用",
    ),
    Metric(
        key="shuchi",
        label="周知",
        description="メンバーへの周知事項を掲示・各メンバーが確認チェック（リアルタイム共有）",
        fetch=lambda sf: {"dummy": pd.DataFrame()},
        category="責任者用",
    ),
    Metric(
        key="ikusei_kpi",
        label="育成KPI",
        description="育成KPI（準備中）",
        fetch=lambda sf: pd.DataFrame(),
        category="責任者用",
    ),
    Metric(
        key="skill_tree",
        label="スキルツリー",
        description="スキルツリー（準備中）",
        fetch=lambda sf: pd.DataFrame(),
        category="責任者用",
    ),
    Metric(
        key="call_history",
        label="通話履歴",
        description="本日のCS促進メンバーの架電履歴（留守以外）。リアルタイム取得",
        fetch=fetch_call_history,
        category="責任者用",
    ),
]


# --- ツール: メンバー別トークスクリプト（動的管理） ---
from tool_members_store import get_members, get_all_member_names, get_member_names, get_boards_as_tuples, is_excluded_member as _tool_excluded

# 全メンバー名（非アクティブ含む、インデックス安定用）
TALK_SCRIPT_MEMBERS_ALL: list[str] = get_all_member_names()
# アクティブメンバー名（サイドバー表示用）
TALK_SCRIPT_MEMBERS: list[str] = get_member_names()

# 各メンバーが持てるボード一覧（ストアから動的取得）
# (suffix, label) のタプルリスト
TALK_SCRIPT_BOARDS: list[tuple[str, str]] = get_boards_as_tuples()

def _build_talk_script_metrics() -> list[Metric]:
    """メンバー×割当済みボードから Metric リストを動的生成。"""
    result = []
    members = get_members()
    boards = get_boards_as_tuples()
    for _i, _m in enumerate(members):
        if not _m.get("active", True):
            continue
        if _tool_excluded(_m["name"]):
            continue
        for _suffix, _board_label in boards:
            if _suffix in _m.get("assignments", []):
                result.append(Metric(
                    key=f"talk_script_{_i:02d}_{_suffix}",
                    label=_board_label,
                    description=f"{_m['name']} の {_board_label}",
                    fetch=lambda sf: pd.DataFrame(),
                    category="ツール",
                ))
    return result

METRICS.extend(_build_talk_script_metrics())


def reload_talk_script_metrics():
    """メンバー/ボード変更後にMETRICSを再構築（マスタ画面から呼ばれる）。"""
    global TALK_SCRIPT_MEMBERS, TALK_SCRIPT_MEMBERS_ALL, TALK_SCRIPT_BOARDS
    from tool_members_store import clear_members_cache
    clear_members_cache()
    TALK_SCRIPT_MEMBERS_ALL = get_all_member_names()
    TALK_SCRIPT_MEMBERS = get_member_names()
    TALK_SCRIPT_BOARDS = get_boards_as_tuples()
    # 既存の talk_script_* を除去して再生成
    METRICS[:] = [m for m in METRICS if not m.key.startswith("talk_script_")]
    METRICS.extend(_build_talk_script_metrics())


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
    if idx >= len(TALK_SCRIPT_MEMBERS_ALL):
        return None
    suffix = parts[3]
    label = next((lbl for sfx, lbl in TALK_SCRIPT_BOARDS if sfx == suffix), suffix)
    return TALK_SCRIPT_MEMBERS_ALL[idx], label


def get_metric(key: str) -> Metric:
    for m in METRICS:
        if m.key == key:
            return m
    raise KeyError(key)
