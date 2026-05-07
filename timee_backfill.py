"""
タイミー就業予定表の過去分一括取込スクリプト（手動実行用）

使い方:
  GitHub Actions の workflow_dispatch（"Timee Backfill"）から起動。
  入力 months に "2026-01,2026-02,2026-03,2026-04" のようにYYYY-MM列を渡す。

挙動:
  - 指定月をPlaywright経由で順番にDLし、Excelをパース
  - 新ワーカーはマスタにIDを発行して登録（初回登録日は最も古い就業日）
  - 既存ワーカーは触らない
  - データはアーカイブ専用ワークシート（timee_archive）に追記
    （※同期側のスナップショットには触らない＝5分毎の差分検知に影響なし）
  - 既に取り込み済みの (id, 就業日) ペアは重複追記しない
  - Chatwork通知は送らない（過去分なので）
"""

from __future__ import annotations

import argparse
import sys
import traceback
from datetime import date
from pathlib import Path

import timee_master_store as store
from timee_downloader import download_month_excel, parse_excel_records


def _parse_months(s: str) -> list[tuple[int, int]]:
    out = []
    for p in s.split(","):
        p = p.strip()
        if not p:
            continue
        y, m = p.split("-")
        out.append((int(y), int(m)))
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--months", required=True,
                        help="例: 2026-01,2026-02,2026-03,2026-04")
    args = parser.parse_args()

    months = _parse_months(args.months)
    today_iso = date.today().isoformat()
    Path("./tmp").mkdir(parents=True, exist_ok=True)

    workers = store.load_workers()
    total_new_workers = 0
    total_archive_added = 0

    for (y, m) in months:
        print(f"\n[Backfill] === {y}-{m:02d} ダウンロード開始 ===")
        path = f"./tmp/timee_{y}_{m:02d}_backfill.xlsx"
        download_month_excel(y, m, path)
        records = parse_excel_records(path, default_year=y, default_month=m)
        print(f"[Backfill] {y}-{m:02d} 取得: {len(records)} レコード")

        archive_entries = []
        for rec in records:
            wid, is_new = store.upsert_worker(workers, rec, today_iso)
            if is_new:
                total_new_workers += 1
                # 過去取込: 初回登録日を実際の就業日に設定
                workers[wid]["初回登録日"] = rec["就業日"]
            else:
                # 既存ワーカーでも、より古い就業日を見つけたら初回登録日を遡る
                cur = workers[wid].get("初回登録日", "")
                if rec["就業日"] and (not cur or rec["就業日"] < cur):
                    workers[wid]["初回登録日"] = rec["就業日"]

            archive_entries.append({
                "id": wid,
                "就業日": rec["就業日"],
                "出勤回数": rec.get("出勤回数", 0),
                "開始時間": rec.get("開始時間", ""),
                "終了時間": rec.get("終了時間", ""),
                "求人タイトル": rec.get("求人タイトル", ""),
                "グループ": rec.get("グループ", ""),
                "バッジ": rec.get("バッジ", ""),
            })

        added = store.append_archive(archive_entries)
        total_archive_added += added
        print(f"[Backfill] {y}-{m:02d} アーカイブ追記: {added} (重複除外あり)")

    # ワーカー更新を保存
    store.save_workers(workers)
    print(f"\n[Backfill] 完了: 新規ワーカー={total_new_workers}, アーカイブ追記={total_archive_added}")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
