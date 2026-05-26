"""開通前対応ボード用の集計ロジック（読み取り専用）。

定義:
  「開通前の対応」= 対応日(Field1_del__c)が開通日(Account.Field130__c)より過去、
    または開通日が空欄の活動で、かつ以下いずれかに該当するもの（件数ベース）。
      - 不備停滞解消型: 対応区分(Field3_del__c)='FC'  かつ 対応ステータス(Field2_del__c)='フォローコール(代コン)'
      - 問い合わせ対応型: 対応区分='架電' かつ 対応ステータス IN ('対応','キャンセル対応')
  1顧客で複数回あればその回数だけカウント。

集計軸:
  エントリ月(コホート) × 対応月 で、コホートのエントリ件数あたり開通前対応件数（発生率）を
  商材別(ソネット/NURO/AU光)に算出する。これにより
  「当月/先月/先々月/3ヶ月前のエントリ件数」から当月の開通前対応必要数を見積もれる。
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

JST = timezone(timedelta(hours=9))

PRODUCTS = ["ソネット", "NURO", "AU光"]
PRODUCT_LIKE = {
    "ソネット": "LIKE '%So-net%'",
    "NURO": "LIKE '%NURO%'",
    "AU光": "LIKE 'AU光%'",
}

# 対応の絞り込み（区分×ステータスの組み合わせ）
TAIOU_FILTER = (
    "((Field3_del__c='FC' AND Field2_del__c='フォローコール(代コン)') "
    "OR (Field3_del__c='架電' AND Field2_del__c IN ('対応','キャンセル対応')))"
)

# コール結果(Field4_del__c)がこの値＝不在。有効対話数の集計では除外する
EXCLUDE_RESULTS = {"留守"}

N_HANDLING = 4   # 対応月の表示数（当月含む直近4ヶ月）
MAX_OFFSET = 3   # エントリ月オフセット（当月=0 〜 3ヶ月前）


def _ym(y: int, m: int) -> str:
    return f"{y:04d}-{m:02d}"


def _add_months(y: int, m: int, delta: int) -> tuple[int, int]:
    idx = (y * 12 + (m - 1)) + delta
    return idx // 12, idx % 12 + 1


def _month_start_iso_z(y: int, m: int) -> str:
    """その月1日0:00 JST を UTC ISO(Z) で返す（Task日時フィルタ用）。"""
    dt = datetime(y, m, 1, tzinfo=JST).astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _to_jst_date(iso_dt: str):
    if not iso_dt:
        return None
    try:
        return datetime.fromisoformat(iso_dt.replace("Z", "+00:00")).astimezone(JST).date()
    except Exception:
        return None


def _to_date(s: str):
    if not s:
        return None
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").date()
    except Exception:
        return None


def compute(sf, now: datetime | None = None) -> dict:
    now = now or datetime.now(JST)
    cy, cm = now.year, now.month
    current_ym = _ym(cy, cm)

    # 対応月（古い→新しい）: 当月含む直近 N_HANDLING ヶ月
    handling = [_add_months(cy, cm, -(N_HANDLING - 1 - i)) for i in range(N_HANDLING)]
    handling_ym = [_ym(y, m) for (y, m) in handling]
    handling_set = set(handling_ym)

    # エントリ月: 対応月の最古から MAX_OFFSET ヶ月前まで
    h0y, h0m = handling[0]
    entry_min_y, entry_min_m = _add_months(h0y, h0m, -MAX_OFFSET)
    entry_min_iso = f"{entry_min_y:04d}-{entry_min_m:02d}-01"
    handling_min_z = _month_start_iso_z(h0y, h0m)

    data = {}
    for prod in PRODUCTS:
        like = PRODUCT_LIKE[prod]

        # 1. エントリ件数（エントリ月別、1クエリ）
        eq = (
            "SELECT CALENDAR_YEAR(Field156__c) y, CALENDAR_MONTH(Field156__c) m, COUNT(Id) c "
            "FROM Account "
            f"WHERE Field76__r.Name {like} AND Field156__c >= {entry_min_iso} "
            "GROUP BY CALENDAR_YEAR(Field156__c), CALENDAR_MONTH(Field156__c)"
        )
        entry_counts: dict[str, int] = {}
        for r in sf.query_all(eq)["records"]:
            if r["y"] is None or r["m"] is None:
                continue
            entry_counts[_ym(int(r["y"]), int(r["m"]))] = int(r["c"])

        # 2. 開通前対応のカウント（対応月×エントリ月）
        #    matrix     = 対応架電回数（留守込み）
        #    matrix_eff = 有効対話数（留守を除外）
        tq = (
            "SELECT AccountId, Field1_del__c, Field4_del__c, Account.Field130__c, Account.Field156__c "
            "FROM Task "
            f"WHERE {TAIOU_FILTER} AND Account.Field76__r.Name {like} "
            f"AND Field1_del__c >= {handling_min_z}"
        )
        matrix: dict[tuple[str, str], int] = {}       # 対応架電回数（留守込み）
        matrix_eff: dict[tuple[str, str], int] = {}   # 有効対話数（留守を除外）
        matrix_rusu: dict[tuple[str, str], int] = {}  # 無効対話数（留守のみ）
        for t in sf.query_all(tq)["records"]:
            hd = _to_jst_date(t.get("Field1_del__c"))
            if hd is None:
                continue
            hym = _ym(hd.year, hd.month)
            if hym not in handling_set:
                continue
            acc = t.get("Account") or {}
            ed = _to_date(acc.get("Field156__c"))
            if ed is None:
                continue
            kd = _to_date(acc.get("Field130__c"))
            # 開通前: 開通日が空 もしくは 対応日 < 開通日
            if kd is not None and hd >= kd:
                continue
            eym = _ym(ed.year, ed.month)
            matrix[(eym, hym)] = matrix.get((eym, hym), 0) + 1
            if (t.get("Field4_del__c") or "") in EXCLUDE_RESULTS:
                matrix_rusu[(eym, hym)] = matrix_rusu.get((eym, hym), 0) + 1
            else:
                matrix_eff[(eym, hym)] = matrix_eff.get((eym, hym), 0) + 1

        data[prod] = {
            "entry_counts": entry_counts, "matrix": matrix,
            "matrix_eff": matrix_eff, "matrix_rusu": matrix_rusu,
        }

    return {
        "products": PRODUCTS,
        "handling_ym": handling_ym,
        "current_ym": current_ym,
        "max_offset": MAX_OFFSET,
        "data": data,
        "asof": now.strftime("%Y/%m/%d %H:%M"),
    }


def offset_entry_ym(handling_ym: str, offset: int) -> str:
    y, m = int(handling_ym[:4]), int(handling_ym[5:7])
    oy, om = _add_months(y, m, -offset)
    return _ym(oy, om)
