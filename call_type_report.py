# -*- coding: utf-8 -*-
"""架電種別トータルコール数 の集計＋公開HTML(スタンドアロン)生成。

Streamlit非依存・自己完結（metrics等の重いモジュールに依存しない）。
アプリ内表示(metricsが再エクスポート)とGitHub Actions(サーバー生成)の両方から使う。
依存: pandas のみ（fetchは渡された simple_salesforce の接続を使う）。
"""
from __future__ import annotations

from collections import defaultdict

import pandas as pd

# ── 集計定義 ─────────────────────────────────────────────
CALL_TYPE_ORDER = [
    "開通後対応", "開通前対応", "自社OP", "キャンセル対応",
    "1週間後FC", "工事取得FC", "新設FC(顧客架電)", "新設FC(コンサル窓口架電)",
    "開通後FC", "オーナー確認(新設FC)",
]
# 開通前/後対応のみ、コール結果に「処理のみ」「キャンセル依頼」を追加集計する
CALL_TYPE_TAIOU = {"開通後対応", "開通前対応"}
CALL_RESULT_BASE = ["完了", "留守", "再コール", "対応依頼"]
CALL_RESULT_TAIOU_EXTRA = ["処理のみ", "キャンセル依頼"]
CALL_TOTAL_PRODUCTS = ["全て", "NIFTY", "NURO", "SO-NET", "AU光"]
# シフト・集計から常に除外する担当者（正規化名）
EXCLUDED_OWNERS_NORM = {"高橋真友香", "大滝紀香"}

_CALL_PRODUCT_LIKE = {
    "NIFTY": "NIFTY光%", "NURO": "NURO光%", "SO-NET": "So-net光%", "AU光": "AU光%",
}
# 区分=FC のステータス（全角/半角括弧を正規化後）→ 架電種別
_CALL_FC_STATUS_MAP = {
    "フォローコール(1週間後FC)": "1週間後FC",
    "フォローコール(工事取得)": "工事取得FC",
    "フォローコール(代コン)": "新設FC(顧客架電)",
    "フォローコール(代コン窓口)": "新設FC(コンサル窓口架電)",
    "フォローコール(開通後①)": "開通後FC",
    "オーナー確認": "オーナー確認(新設FC)",
}
# 区分=架電 のステータス → 架電種別（対応は開通日有無で別途分割）
_CALL_KADEN_STATUS_MAP = {"自社OP": "自社OP", "キャンセル対応": "キャンセル対応"}


def _call_paren_np(s):
    return (s or "").replace("（", "(").replace("）", ")")


def _call_norm_result(r):
    r = r or ""
    if r in ("キャンセル受理", "キャンセル希望", "キャンセル依頼"):
        return "キャンセル依頼"
    return r


def fetch(sf, start_date, end_date, product="全て"):
    """架電種別トータルコール数を日別×担当者別に集計して返す(DataFrame)。

    列: 日付, 担当者, 架電種別, 完了, 留守, 再コール, 対応依頼, 処理のみ, キャンセル依頼, 合計
    """
    cols = ["日付", "担当者", "架電種別", "完了", "留守", "再コール",
            "対応依頼", "処理のみ", "キャンセル依頼", "合計"]

    users_rs = sf.query_all(
        "SELECT Id, Name FROM User WHERE Department = 'CS促進' AND IsActive = true"
    )["records"]
    cs_ids = {
        r["Id"] for r in users_rs
        if (r.get("Name") or "").replace(" ", "").replace("　", "") not in EXCLUDED_OWNERS_NORM
    }
    if not cs_ids:
        return pd.DataFrame(columns=cols)
    ids_lit = ",".join(f"'{u}'" for u in cs_ids)

    prod_filter = ""
    if product and product != "全て" and product in _CALL_PRODUCT_LIKE:
        prod_filter = f" AND Account.Field76__r.Name LIKE '{_CALL_PRODUCT_LIKE[product]}'"
    base_where = (
        f"ActivityDate >= {start_date} AND ActivityDate <= {end_date} "
        f"AND OwnerId IN ({ids_lit}){prod_filter}"
    )

    agg = defaultdict(lambda: defaultdict(int))

    def _add(date, owner, ctype, result, cnt):
        agg[(date, owner, ctype)][_call_norm_result(result)] += cnt

    for cond, ctype in ((" AND Account.Field130__c = null", "開通前対応"),
                        (" AND Account.Field130__c != null", "開通後対応")):
        for r in sf.query_all(
            "SELECT ActivityDate ad, Owner.Name oname, Field4_del__c res, COUNT(Id) c FROM Task "
            f"WHERE {base_where} AND Field3_del__c = '架電' AND Field2_del__c = '対応'{cond} "
            "GROUP BY ActivityDate, Owner.Name, Field4_del__c"
        )["records"]:
            _add(r.get("ad"), r.get("oname"), ctype, r.get("res"), int(r["c"]))

    for r in sf.query_all(
        "SELECT ActivityDate ad, Owner.Name oname, Field2_del__c st, Field4_del__c res, COUNT(Id) c FROM Task "
        f"WHERE {base_where} AND Field3_del__c = '架電' AND Field2_del__c IN ('自社OP','キャンセル対応') "
        "GROUP BY ActivityDate, Owner.Name, Field2_del__c, Field4_del__c"
    )["records"]:
        ctype = _CALL_KADEN_STATUS_MAP.get(r.get("st"))
        if ctype:
            _add(r.get("ad"), r.get("oname"), ctype, r.get("res"), int(r["c"]))

    for r in sf.query_all(
        "SELECT ActivityDate ad, Owner.Name oname, Field2_del__c st, Field4_del__c res, COUNT(Id) c FROM Task "
        f"WHERE {base_where} AND Field3_del__c = 'FC' "
        "GROUP BY ActivityDate, Owner.Name, Field2_del__c, Field4_del__c"
    )["records"]:
        ctype = _CALL_FC_STATUS_MAP.get(_call_paren_np(r.get("st")))
        if ctype:
            _add(r.get("ad"), r.get("oname"), ctype, r.get("res"), int(r["c"]))

    rows = []
    for (date, owner, ctype), rmap in agg.items():
        is_taiou = ctype in CALL_TYPE_TAIOU
        base_sum = sum(rmap.get(k, 0) for k in CALL_RESULT_BASE)
        extra_sum = sum(rmap.get(k, 0) for k in CALL_RESULT_TAIOU_EXTRA) if is_taiou else 0
        total = base_sum + extra_sum
        if total == 0:
            continue
        rows.append({
            "日付": date, "担当者": owner, "架電種別": ctype,
            "完了": rmap.get("完了", 0), "留守": rmap.get("留守", 0),
            "再コール": rmap.get("再コール", 0), "対応依頼": rmap.get("対応依頼", 0),
            "処理のみ": rmap.get("処理のみ", 0) if is_taiou else 0,
            "キャンセル依頼": rmap.get("キャンセル依頼", 0) if is_taiou else 0,
            "合計": total,
        })
    if not rows:
        return pd.DataFrame(columns=cols)
    df = pd.DataFrame(rows, columns=cols)
    df["架電種別"] = pd.Categorical(df["架電種別"], categories=CALL_TYPE_ORDER, ordered=True)
    df = df.sort_values(["日付", "担当者", "架電種別"]).reset_index(drop=True)
    df["架電種別"] = df["架電種別"].astype(str)
    return df


# 互換: 旧名でも呼べるように
fetch_call_type_totals = fetch


# ── HTML生成 ─────────────────────────────────────────────
_BASE = ["完了", "留守", "再コール", "対応依頼"]
_EXTRA = ["処理のみ", "キャンセル依頼"]
_KIND = {"完了": "g", "留守": "r"}

_THEAD = ("padding:4px 8px;border:1px solid #33414d;font-size:11px;color:#cfd8dc;"
          "background:#263340;white-space:nowrap;text-align:center;")
_TL = ("padding:3px 9px;border:1px solid #2b3640;font-size:12px;color:#e6edf3;"
       "text-align:left;white-space:nowrap;")
_TR = ("padding:3px 9px;border:1px solid #2b3640;font-size:12px;color:#e6edf3;"
       "text-align:right;white-space:nowrap;")


def _dlabel(d):
    return f"{int(d[5:7])}/{int(d[8:10])}"


def _pct(n, dn):
    return round(n / dn * 100) if dn else 0


def _rate_bg(kind, pct):
    if not kind:
        return ""
    a = 0.10 + 0.50 * min(pct, 100) / 100.0
    if kind == "g":
        return f"background:rgba(67,160,71,{a:.2f});"
    return f"background:rgba(229,57,53,{a:.2f});"


def _num_td(n, strong=False):
    fw = "font-weight:700;color:#ffffff;" if strong else ""
    return f'<td style="{_TR}{fw}">{n}</td>'


def _res_td(n, denom, kind=None):
    if denom and denom > 0:
        pct = round(n / denom * 100)
        return (f'<td style="{_TR}{_rate_bg(kind, pct)}">{n} '
                f'<span style="color:#aeb9c4;font-size:10px;">({pct}%)</span></td>')
    return f'<td style="{_TR}color:#6b7885;">0</td>'


def _label_td(text, indent=False, strong=False):
    pad = "padding-left:22px;" if indent else ""
    fw = "font-weight:700;" if strong else ""
    bg = "background:#22303a;" if strong else ""
    return f'<td style="{_TL}{pad}{fw}{bg}">{text}</td>'


def _prep(df):
    dcol = sorted(df["日付"].unique())
    idx = {}
    for r in df.to_dict("records"):
        idx[(r["担当者"], r["架電種別"], r["日付"])] = r
    people = sorted(df["担当者"].unique())
    agg = {}
    for (pp, tt, dd), rr in idx.items():
        a = agg.setdefault((tt, dd), {k: 0 for k in ("完了", "留守", "再コール", "対応依頼",
                                                     "処理のみ", "キャンセル依頼", "合計")})
        for k in a:
            a[k] += rr[k]
    return dcol, idx, people, agg


def _entity_rows(getter, dcol):
    tp = [t for t in CALL_TYPE_ORDER if any(getter(t, d) for d in dcol)]
    if not tp:
        return None
    grand = {d: {k: 0 for k in ("完了", "留守", "再コール", "対応依頼", "合計")} for d in dcol}
    for t in tp:
        for d in dcol:
            r = getter(t, d)
            if r:
                for k in ("完了", "留守", "再コール", "対応依頼"):
                    grand[d][k] += r[k]
                grand[d]["合計"] += r["合計"]
    gtot = {k: sum(grand[d][k] for d in dcol) for k in ("完了", "留守", "再コール", "対応依頼", "合計")}
    rows = [("総数", False, None, "num", [gtot["合計"]] + [grand[d]["合計"] for d in dcol])]
    for k in _BASE:
        rows.append(("合計" + k + "数", True, _KIND.get(k), "rate",
                     [(gtot[k], gtot["合計"])] + [(grand[d][k], grand[d]["合計"]) for d in dcol]))
    for t in tp:
        ttot = {d: (getter(t, d)["合計"] if getter(t, d) else 0) for d in dcol}
        ts = sum(ttot.values())
        rows.append((t + "　総数", False, None, "num", [ts] + [ttot[d] for d in dcol]))
        for k in _BASE + (_EXTRA if t in CALL_TYPE_TAIOU else []):
            ks = sum((getter(t, d)[k] if getter(t, d) else 0) for d in dcol)
            rows.append((k, True, _KIND.get(k), "rate",
                         [(ks, ts)] + [((getter(t, d)[k] if getter(t, d) else 0), ttot[d]) for d in dcol]))
    return rows


def _table_html(title, getter, dcol):
    rows = _entity_rows(getter, dcol)
    if not rows:
        return ""
    h = [f'<div style="font-size:15px;font-weight:800;color:#fff;margin:14px 0 4px;">{title}</div>',
         '<div style="overflow-x:auto;">',
         '<table style="border-collapse:collapse;background:#1e2730;">']
    h.append('<tr><th style="' + _THEAD + 'text-align:left;">架電種別 / 結果</th>'
             '<th style="' + _THEAD + '">合計</th>'
             + "".join('<th style="' + _THEAD + '">' + _dlabel(d) + '</th>' for d in dcol) + '</tr>')
    for label, indent, kind, ctype, cells in rows:
        strong = (ctype == "num")
        tds = _label_td(label, indent=indent, strong=strong)
        if ctype == "num":
            tds += "".join(_num_td(c, strong=True) for c in cells)
        else:
            tds += "".join(_res_td(c[0], c[1], kind) for c in cells)
        h.append('<tr>' + tds + '</tr>')
    h.append('</table></div>')
    return "".join(h)


def _full_body(dcol, idx, people, agg):
    parts = [_table_html("合計（全担当者）", lambda t, d: agg.get((t, d)), dcol)]
    for p in people:
        parts.append(_table_html(p, (lambda pp: (lambda t, d: idx.get((pp, t, d))))(p), dcol))
    return "".join(parts)


def _summary_body(idx, people, agg, month_lbl, product):
    overall = {k: 0 for k in ("完了", "留守", "再コール", "対応依頼", "合計")}
    per_type = {}
    for (t, d), r in agg.items():
        pt = per_type.setdefault(t, {k: 0 for k in ("完了", "留守", "再コール", "対応依頼", "合計")})
        for k in ("完了", "留守", "再コール", "対応依頼", "合計"):
            pt[k] += r[k]
            overall[k] += r[k]
    per_person = {}
    for (pp, t, d), r in idx.items():
        v = per_person.setdefault(pp, {"完了": 0, "合計": 0})
        v["完了"] += r["完了"]
        v["合計"] += r["合計"]
    # タイトル/メタは _standalone 側で出すため、本文は中身のみ（重複防止）
    h = ['<div class="cards">']
    for lbl, k in [("コール総数", "合計"), ("完了", "完了"), ("留守", "留守"),
                   ("再コール", "再コール"), ("対応依頼", "対応依頼")]:
        val = overall[k]
        sub = "" if k == "合計" else f'<span class="p">{_pct(val, overall["合計"])}%</span>'
        h.append(f'<div class="card"><div class="cl">{lbl}</div><div class="cv">{val:,}件 {sub}</div></div>')
    h.append('</div><h2>架電の種類ごと</h2><table class="s"><tr><th>種類</th><th>コール数</th>'
             '<th>完了率</th><th>留守率</th></tr>')
    for t in CALL_TYPE_ORDER:
        if t in per_type and per_type[t]["合計"] > 0:
            v = per_type[t]
            h.append(f'<tr><td class="l">{t}</td><td>{v["合計"]:,}</td>'
                     f'<td>{_pct(v["完了"], v["合計"])}%</td><td>{_pct(v["留守"], v["合計"])}%</td></tr>')
    h.append('</table><h2>担当者ごと</h2><table class="s"><tr><th>担当者</th><th>コール数</th><th>完了率</th></tr>')
    for nm, v in sorted(per_person.items(), key=lambda x: -x[1]["合計"]):
        h.append(f'<tr><td class="l">{nm}</td><td>{v["合計"]:,}</td><td>{_pct(v["完了"], v["合計"])}%</td></tr>')
    h.append('</table>')
    return "".join(h)


def _standalone(body, title, meta, expire_ymd, summary):
    if summary:
        style = ("body{background:#fff;color:#1a1f26;font-family:'Segoe UI',sans-serif;margin:0;"
                 "padding:22px;max-width:820px;}h1{font-size:22px;margin:0 0 2px;}h2{font-size:16px;margin:20px 0 6px;}"
                 ".meta{color:#667;font-size:13px;margin:0 0 14px;}"
                 ".cards{display:flex;flex-wrap:wrap;gap:10px;margin:8px 0 4px;}"
                 ".card{background:#f2f5f8;border-radius:10px;padding:10px 14px;min-width:120px;}"
                 ".cl{font-size:12px;color:#667;}.cv{font-size:18px;font-weight:700;}"
                 ".cv .p{font-size:13px;color:#2e7d32;font-weight:600;margin-left:4px;}"
                 "table.s{border-collapse:collapse;width:100%;margin:2px 0 6px;}"
                 "table.s th,table.s td{border:1px solid #dde3ea;padding:5px 10px;font-size:13px;text-align:right;}"
                 "table.s th{background:#eef2f6;}table.s td.l,table.s th:first-child{text-align:left;}")
    else:
        style = ("body{background:#151b22;color:#e6edf3;font-family:'Segoe UI',sans-serif;margin:0;padding:18px;}"
                 "h1{font-size:20px;margin:0 0 2px;}.meta{color:#9fb3c8;font-size:13px;margin:0 0 14px;}"
                 "table{border-collapse:collapse;}")
    return (
        "<!doctype html><html lang='ja'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{title}</title><style>{style}"
        "#ctx{display:none;padding:48px 16px;text-align:center;font-size:18px;color:#b26a00;}"
        "</style></head><body>"
        f"<div id='ctb'><h1>{title}</h1><div class='meta'>{meta}　／　公開期限 {expire_ymd}</div>{body}</div>"
        "<div id='ctx'>この資料は公開期限が切れています。</div>"
        "<script>(function(){try{var exp=new Date('" + expire_ymd + "T23:59:59+09:00');"
        "if(isNaN(exp.getTime())||new Date()>exp){throw 0;}}catch(e){"
        "document.getElementById('ctb').style.display='none';"
        "document.getElementById('ctx').style.display='block';}})();</script>"
        "</body></html>"
    )


def build(df, product, start_iso, end_iso, summary, expire_ymd, created_iso):
    """公開用スタンドアロンHTMLを返す。"""
    dcol, idx, people, agg = _prep(df)
    sy, sm = int(start_iso[:4]), int(start_iso[5:7])
    em, ed = int(end_iso[5:7]), int(end_iso[8:10])
    is_full_month = (start_iso[8:10] == "01")
    month_lbl = f"{sy}年{sm}月" if (is_full_month and (sm == em)) else f"{sy}年{sm}月（{em}/{ed}時点）"
    meta = (f"期間 {start_iso.replace('-', '/')}〜{end_iso.replace('-', '/')} ／ "
            f"対象 CS促進メンバー ／ 作成 {created_iso.replace('-', '/')}")
    if summary:
        title = f"コール集計 {month_lbl}（{product}）"
        body = _summary_body(idx, people, agg, month_lbl, product)
    else:
        title = f"架電種別トータルコール数（{product}）"
        body = _full_body(dcol, idx, people, agg)
    return _standalone(body, title, meta, expire_ymd, summary)
