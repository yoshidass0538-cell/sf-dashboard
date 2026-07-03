# -*- coding: utf-8 -*-
"""架電種別トータルコール数の公開HTMLを生成して docs/files に書き出す。

GitHub Actions(call_type_html.yml)から呼ばれる。SF認証は環境変数から。
入力(環境変数):
  CT_MODE    = 'full' | 'summary'
  CT_PRODUCT = 全て / NIFTY / NURO / SO-NET / AU光
  CT_START   = YYYY-MM-DD
  CT_END     = YYYY-MM-DD
出力:
  docs/files/call-type-total.html            (CT_MODE=full)
  docs/files/call-type-total-teishutsu.html  (CT_MODE=summary)
  同名の <name>-expire.txt (YYYYMMDD, 今日+7)
"""
import os
import sys
from datetime import date, timedelta

from simple_salesforce import Salesforce

import call_type_report


def _env(k, default=""):
    v = os.environ.get(k)
    if v:
        return v
    try:
        from dotenv import dotenv_values
        return dotenv_values(".env").get(k, default) or default
    except Exception:
        return default


def main():
    mode = (_env("CT_MODE") or "full").strip()
    product = (_env("CT_PRODUCT") or "全て").strip()
    start = (_env("CT_START") or "").strip()
    end = (_env("CT_END") or "").strip()
    summary = (mode == "summary")
    if not start or not end:
        today = date.today()
        start = today.replace(day=1).isoformat()
        end = today.isoformat()

    sf = Salesforce(
        username=_env("SF_USERNAME"), password=_env("SF_PASSWORD"),
        security_token=_env("SF_TOKEN"), domain=(_env("SF_DOMAIN") or "login"),
    )
    df = call_type_report.fetch(sf, start, end, product)
    if df.empty:
        print("no data; abort")
        sys.exit(0)

    exp = (date.today() + timedelta(days=7))
    html = call_type_report.build(
        df, product, start, end, summary, exp.strftime("%Y-%m-%d"), date.today().isoformat()
    )
    name = "call-type-total-teishutsu" if summary else "call-type-total"
    os.makedirs("docs/files", exist_ok=True)
    with open(f"docs/files/{name}.html", "w", encoding="utf-8") as f:
        f.write(html)
    with open(f"docs/files/{name}-expire.txt", "w", encoding="utf-8") as f:
        f.write(exp.strftime("%Y%m%d"))
    print(f"generated docs/files/{name}.html ({len(html)} bytes), expire {exp}")


if __name__ == "__main__":
    main()
