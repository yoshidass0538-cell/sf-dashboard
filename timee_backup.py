"""タイミー キャンセル履歴のデイリーバックアップ。

目的:
  2026-05-21 にキャンセル履歴シートが上書きで消失した実害があったため、
  どんな未知バグが将来発生しても巻き戻せるよう、毎日 timee_worker_texts の
  完全コピーを別ワークシートに保存する。

挙動:
  - `timee_worker_texts` の全行を `timee_worker_texts_bak_YYYY-MM-DD` に保存
  - 同日付の既存バックアップは置換(冪等)
  - 保持期間 BACKUP_RETENTION_DAYS 日を超えるバックアップは自動削除

復元:
  python timee_backup.py restore --date 2026-05-20

実行:
  python timee_backup.py            # バックアップ
  python timee_backup.py backup     # 同上
  python timee_backup.py list       # 保存済みバックアップ一覧
  python timee_backup.py restore --date YYYY-MM-DD
                                    # 指定日のバックアップで現行を置換
"""

from __future__ import annotations

import argparse
import re
from datetime import date, datetime, timedelta, timezone

import gspread

import timee_master_store as store

JST = timezone(timedelta(hours=9))
BACKUP_PREFIX = "timee_worker_texts_bak_"
BACKUP_RETENTION_DAYS = 30
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _today_iso() -> str:
    return datetime.now(JST).date().isoformat()


def _spreadsheet():
    client = store._get_client()
    return client.open_by_key(store._get_sheet_id())


def _list_backup_worksheets(sh) -> list[tuple[str, gspread.Worksheet]]:
    out = []
    for ws in sh.worksheets():
        t = ws.title
        if not t.startswith(BACKUP_PREFIX):
            continue
        d = t[len(BACKUP_PREFIX):]
        if not DATE_RE.match(d):
            continue
        out.append((d, ws))
    out.sort(key=lambda x: x[0])
    return out


def backup() -> None:
    """timee_worker_texts を今日付のバックアップシートに丸ごと保存。"""
    sh = _spreadsheet()
    # 1. 元シート読出し (生rows = ヘッダー含む)
    src = sh.worksheet(store.WORKER_TEXT_WORKSHEET)
    values = src.get_all_values()
    if not values:
        values = [store.WORKER_TEXT_HEADERS]
    # 念のためヘッダー欠落時は補完
    if values[0][:len(store.WORKER_TEXT_HEADERS)] != store.WORKER_TEXT_HEADERS:
        values = [store.WORKER_TEXT_HEADERS] + values

    today = _today_iso()
    title = f"{BACKUP_PREFIX}{today}"

    # 2. 既存同日付シートは置換
    try:
        existing = sh.worksheet(title)
        sh.del_worksheet(existing)
    except gspread.exceptions.WorksheetNotFound:
        pass

    # 3. 作成して書込み
    rows_n = max(len(values), 2)
    cols_n = max(len(values[0]) if values else 1, len(store.WORKER_TEXT_HEADERS))
    ws = sh.add_worksheet(title=title, rows=rows_n, cols=cols_n)
    ws.update(values=values, range_name="A1", value_input_option="RAW")
    print(f"[backup] saved -> {title}  rows={len(values)}")

    # 4. 保持期間超えを削除
    cutoff = (datetime.now(JST).date() - timedelta(days=BACKUP_RETENTION_DAYS)).isoformat()
    deleted = 0
    for d, bws in _list_backup_worksheets(sh):
        if d < cutoff:
            sh.del_worksheet(bws)
            print(f"[backup] purged old: {bws.title}")
            deleted += 1
    print(f"[backup] rotation: deleted {deleted} old backup(s) older than {cutoff}")


def list_backups() -> None:
    sh = _spreadsheet()
    backups = _list_backup_worksheets(sh)
    print(f"# {len(backups)} backups:")
    for d, ws in backups:
        rc = ws.row_count
        print(f"  {d}  rows~{rc}  title={ws.title}")


def restore(target_date: str) -> None:
    """指定日のバックアップで timee_worker_texts を置換。"""
    if not DATE_RE.match(target_date):
        raise ValueError(f"date must be YYYY-MM-DD: {target_date}")
    sh = _spreadsheet()
    title = f"{BACKUP_PREFIX}{target_date}"
    try:
        bws = sh.worksheet(title)
    except gspread.exceptions.WorksheetNotFound:
        avail = [d for d, _ in _list_backup_worksheets(sh)]
        raise SystemExit(f"backup not found: {title}\navailable: {avail}")

    values = bws.get_all_values()
    if not values:
        raise SystemExit(f"backup is empty: {title}")
    # ヘッダー揃え
    if values[0][:len(store.WORKER_TEXT_HEADERS)] != store.WORKER_TEXT_HEADERS:
        values = [store.WORKER_TEXT_HEADERS] + values

    # 復元先(現行 worker_texts) に直接書込み
    cur = sh.worksheet(store.WORKER_TEXT_WORKSHEET)
    cur.clear()
    cur.update(values=values, range_name="A1", value_input_option="USER_ENTERED")
    print(f"[restore] {title} -> {store.WORKER_TEXT_WORKSHEET}  rows={len(values)}")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("cmd", nargs="?", default="backup",
                   choices=["backup", "list", "restore"])
    p.add_argument("--date", help="YYYY-MM-DD (restore対象)")
    args = p.parse_args()
    if args.cmd == "backup":
        backup()
    elif args.cmd == "list":
        list_backups()
    elif args.cmd == "restore":
        if not args.date:
            raise SystemExit("--date YYYY-MM-DD が必要")
        restore(args.date)


if __name__ == "__main__":
    main()
