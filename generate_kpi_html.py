# -*- coding: utf-8 -*-
"""適正コール数KPIを、誰が見ても分かる静的HTMLにして docs/files に出力する。

公開URL(jsDelivr): https://cdn.jsdelivr.net/gh/yoshidass0538-cell/sf-dashboard@main/docs/files/kpi-call-target.html
データはSF読み取り専用。実行日時点の直近30日でスナップショットを焼き込む。
"""
from __future__ import annotations
import html
import sys
from datetime import date
from dotenv import dotenv_values
from simple_salesforce import Salesforce
import kpi_call_target as kpi

ASOF = date.today().isoformat()  # 実行日（資料の作成日）
HIDE_IN_PERSON = {"栗田 優衣"}   # 個人一覧から外す人


def _sf():
    # .envから読むが os.environ は汚染しない（load_dotenvを使わない）。明示Salesforce()で接続
    z = dotenv_values(".env")
    return Salesforce(username=z["SF_USERNAME"], password=z["SF_PASSWORD"],
                      security_token=z["SF_TOKEN"], domain=z.get("SF_DOMAIN", "login"))


def _person_rows(ind):
    rows = []
    for m in ind["members"]:
        if m["name"] in HIDE_IN_PERSON:
            continue
        eff = sum(v[0] for v in m["per_type"].values())
        rus = sum(v[1] for v in m["per_type"].values())
        kan = sum(v[3] for v in m["per_type"].values())
        wd = m["workdays"] or 1
        rows.append({
            "name": m["name"],
            "workdays": m["workdays"],
            "per_day_calls": (eff + rus) / wd,
            "eff": eff, "rus": rus, "kan": kan,
            "eff_per_day": eff / wd,
            "time_per_day": m["per_day_min"],
            "rate": m["rate"],
        })
    rows.sort(key=lambda r: -r["per_day_calls"])
    return rows


def _bar(rate):
    pct = max(0, min(100, rate))
    if rate >= 45:
        col = "#2e7d32"; mark = "しっかり"
    elif rate >= 25:
        col = "#e6a700"; mark = "ふつう"
    else:
        col = "#c62828"; mark = "少なめ"
    return (
        f'<div class="bar"><div class="bar-fill" style="width:{pct:.0f}%;background:{col};"></div>'
        f'<span class="bar-txt">{rate:.0f}%・{mark}</span></div>'
    )


def build_html(typ, ind):
    e = html.escape
    # 種別テーブル
    trows = ""
    for r in typ["rows"]:
        trows += (
            "<tr>"
            f'<td class="l">{e(r["name"])}</td>'
            f'<td>{r["total"]:,}</td>'
            f'<td>{r["talk_min"]:.1f}分</td>'
            f'<td>{r["per_call_min"]:.1f}分</td>'
            f'<td class="hi">{r["per_hour"]:.0f}件</td>'
            f'<td class="hi">{r["per_day"]:.0f}件</td>'
            "</tr>"
        )
    # 個人テーブル
    person_rows = _person_rows(ind)
    person_count = len(person_rows)
    prows = ""
    for r in person_rows:
        prows += (
            "<tr>"
            f'<td class="l">{e(r["name"])}</td>'
            f'<td>{r["per_day_calls"]:.0f}件</td>'
            f'<td>{r["eff_per_day"]:.0f}件</td>'
            f'<td>{r["kan"]:,}件</td>'
            f'<td>{r["time_per_day"]:.0f}分</td>'
            f'<td>{_bar(r["rate"])}</td>'
            "</tr>"
        )

    return f"""<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>適正コール数のめやす（CS促進）</title>
<style>
 *{{box-sizing:border-box;}}
 body{{margin:0;background:#eef1f4;color:#1b1f24;
   font-family:"Hiragino Kaku Gothic ProN","Yu Gothic",Meiryo,sans-serif;
   line-height:1.7;-webkit-text-size-adjust:100%;}}
 .wrap{{max-width:920px;margin:0 auto;padding:20px 16px 60px;}}
 h1{{font-size:24px;margin:8px 0 2px;}}
 .sub{{color:#5a6470;font-size:13px;margin-bottom:20px;}}
 .card{{background:#fff;border-radius:12px;padding:18px 18px 20px;margin:16px 0;
   box-shadow:0 1px 4px rgba(0,0,0,.08);}}
 h2{{font-size:18px;margin:2px 0 4px;display:flex;align-items:center;gap:8px;}}
 h2 .n{{background:#1565c0;color:#fff;border-radius:8px;width:26px;height:26px;
   display:inline-flex;align-items:center;justify-content:center;font-size:15px;flex:0 0 auto;}}
 .lead{{color:#444;font-size:14px;margin:4px 0 12px;}}
 table{{border-collapse:collapse;width:100%;font-size:14px;}}
 th,td{{border:1px solid #dce1e7;padding:9px 8px;text-align:center;}}
 th{{background:#f1f4f8;color:#3a444f;font-weight:700;font-size:13px;}}
 td.l{{text-align:left;font-weight:600;}}
 td.hi{{background:#e8f5e9;font-weight:700;font-size:15px;}}
 .scroll{{overflow-x:auto;}}
 .bar{{position:relative;height:22px;background:#eceff2;border-radius:6px;min-width:120px;overflow:hidden;}}
 .bar-fill{{position:absolute;left:0;top:0;height:100%;border-radius:6px;}}
 .bar-txt{{position:relative;z-index:1;font-size:12px;font-weight:700;color:#10243a;
   line-height:22px;text-shadow:0 0 2px #fff,0 0 2px #fff;}}
 .legend{{font-size:13px;color:#444;margin-top:10px;}}
 .legend span{{display:inline-block;margin-right:14px;}}
 .dot{{display:inline-block;width:11px;height:11px;border-radius:50%;margin-right:4px;vertical-align:middle;}}
 .time-row{{display:flex;flex-wrap:wrap;gap:6px;margin:10px 0 2px;}}
 .chip{{background:#f1f4f8;border-radius:8px;padding:6px 10px;font-size:13px;}}
 .chip b{{color:#1565c0;}}
 .note{{font-size:12.5px;color:#5a6470;margin-top:10px;}}
 .foot{{text-align:center;color:#8a94a0;font-size:12px;margin-top:24px;}}
</style>
</head>
<body>
<div class="wrap">
  <h1>適正コール数のめやす（CS促進）</h1>
  <div class="sub">担当者 {person_count}名（共有アカウント除く）／ 直近30日の実績 ／ 作成日 {ASOF}</div>

  <div class="card">
    <h2><span class="n">1</span>1日に電話できる時間</h2>
    <div class="lead">朝10時から夜19時までのうち、昼休憩と小休憩を引くと、実際に電話に使える時間は
      <b>1日7時間（420分）</b>です。</div>
    <div class="time-row">
      <div class="chip">在席 <b>9時間</b></div>
      <div class="chip">− 昼休憩 1時間</div>
      <div class="chip">− 小休憩 10分×6</div>
      <div class="chip">＝ 電話できる時間 <b>420分</b></div>
    </div>
  </div>

  <div class="card">
    <h2><span class="n">2</span>電話の種類ごとの「1時間・1日にできる件数」</h2>
    <div class="lead">1件にかかる時間（実際の通話時間＋記録などの後処理）から、無理なくこなせる件数のめやすを出しています。
      <b>緑の数字がめやすの件数</b>です。</div>
    <div class="scroll">
    <table>
      <tr><th>電話の種類</th><th>直近30日<br>の件数</th><th>1回の<br>通話時間</th><th>1件に<br>かかる時間</th>
        <th>1時間の<br>めやす</th><th>1日(420分)<br>のめやす</th></tr>
      {trows}
    </table>
    </div>
    <div class="note">※「1件にかかる時間」＝つながった電話は「通話時間＋3分」、留守は「3分」で計算した平均。
      通話時間はZoomの実測値です。</div>
  </div>

  <div class="card">
    <h2><span class="n">3</span>一人ひとりの実績（直近30日・1日あたり）</h2>
    <div class="lead">いちばん右は、<b>1日420分のうち電話に使えた割合</b>です（受電や事務の時間は含みません）。</div>
    <div class="scroll">
    <table>
      <tr><th>担当者</th><th>1日の<br>電話件数</th><th>つながった<br>件数/日</th>
        <th>完了<br>(30日)</th><th>電話に使った<br>時間/日</th><th>420分のうち</th></tr>
      {prows}
    </table>
    </div>
    <div class="legend">
      <span><span class="dot" style="background:#2e7d32;"></span>45%以上＝しっかり</span>
      <span><span class="dot" style="background:#e6a700;"></span>25〜45%＝ふつう</span>
      <span><span class="dot" style="background:#c62828;"></span>25%未満＝少なめ</span>
    </div>
    <div class="note">割合が低い主な理由は、つながった件数（中身のある電話の本数）が少ないことです。
      通話が長いことが理由で低くなることはありません。受電・事務など電話以外の仕事はこの割合に含みません。</div>
  </div>

  <div class="foot">CS促進 / 適正コール数のめやす ・ {ASOF} 時点</div>
</div>
</body>
</html>
"""


def main():
    sf = _sf()
    typ = kpi.compute(sf)
    ind = kpi.compute_individual(sf, "ActivityDate = LAST_N_DAYS:30")
    out = build_html(typ, ind)
    path = "docs/files/kpi-call-target.html"
    with open(path, "w", encoding="utf-8") as f:
        f.write(out)
    print("WROTE", path, len(out), "bytes")


if __name__ == "__main__":
    sys.exit(main())
