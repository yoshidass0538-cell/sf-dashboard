"""
タイミー就業予定表ポーリング統合スクリプト（GitHub Actions用）

処理フロー:
  1. 当月Excelをダウンロード（必須）
  2. 翌月Excelをダウンロード（meta.last_next_month_fetch が今日でなければ）
  3. レコードをパース → ワーカーマスタを upsert（新規はID発行）
  4. 直前スナップショットと差分検知
       - 新規マッチング → Chatwork通知（1メッセージにまとめる）
       - キャンセル（未来日のみ） → ワーカー履歴に追記
  5. ワーカーマスタ・スナップショット・メタを保存

Chatwork通知ルーム: 435890729
通知タイトル:
  出勤回数 >= 1 → 【リピーターマッチング】
  出勤回数 == 0 → 【新規マッチング】

10:00 JSTの最初の同期では、前夜～朝のマッチングが
スナップショット差分として一括検知されるため、自然にまとめ通知される。
"""

from __future__ import annotations

import os
import sys
import traceback
from datetime import date, datetime, timezone, timedelta
from pathlib import Path

import requests

import timee_master_store as store
from timee_downloader import download_month_excel, parse_excel_records


JST = timezone(timedelta(hours=9))
CHATWORK_ROOM_ID = "435890729"
CHATWORK_API_URL = "https://api.chatwork.com/v2"


# ----------------------------------------------------------------------
# Chatwork
# ----------------------------------------------------------------------
def _chatwork_send(body: str) -> None:
    token = os.environ.get("CHATWORK_API_TOKEN", "")
    if not token:
        print("[WARN] CHATWORK_API_TOKEN 未設定のため通知スキップ")
        return
    headers = {
        "X-ChatWorkToken": token,
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    }
    resp = requests.post(
        f"{CHATWORK_API_URL}/rooms/{CHATWORK_ROOM_ID}/messages",
        headers=headers,
        data={"body": body, "self_unread": 1},
        timeout=15,
    )
    print(f"[Chatwork] status={resp.status_code} body={resp.text[:200]}")


def _build_match_block(rec: dict, worker: dict) -> str:
    """1件分のマッチング情報ブロック。"""
    cancel_count = len(worker.get("キャンセル履歴", []))
    title = "【リピーターマッチング】" if rec.get("出勤回数", 0) >= 1 else "【新規マッチング】"
    lines = [
        title,
        f"ID: {rec['id']}",
        f"{worker.get('氏名', '')}（{worker.get('カナ', '')}）{worker.get('性別', '')}{worker.get('年齢', '')}歳",
        f"就業日: {rec.get('就業日', '')}  {rec.get('開始時間', '')}-{rec.get('終了時間', '')}",
        f"出勤回数: {rec.get('出勤回数', 0)}回　{rec.get('グループ', '')}",
        f"キャンセル履歴: {cancel_count}回",
    ]
    return "\n".join(lines)


def _send_match_notifications(new_matches: list[dict], workers: dict) -> None:
    if not new_matches:
        return
    blocks = []
    # 出勤回数=0(新規) を先に並べる → リピーター
    sorted_matches = sorted(new_matches, key=lambda r: (r.get("出勤回数", 0), r.get("就業日", "")))
    for rec in sorted_matches:
        worker = workers.get(rec["id"], {})
        blocks.append(_build_match_block(rec, worker))
    body = "[info][title]タイミーマッチング検知[/title]" + "\n\n".join(blocks) + "[/info]"
    _chatwork_send(body)


# ----------------------------------------------------------------------
# 同期メイン
# ----------------------------------------------------------------------
def _next_month(d: date) -> tuple[int, int]:
    if d.month == 12:
        return d.year + 1, 1
    return d.year, d.month + 1


def _should_fetch_next_month(meta: dict, today_iso: str) -> bool:
    return meta.get("last_next_month_fetch") != today_iso


def run_sync() -> None:
    now_jst = datetime.now(JST)
    today = now_jst.date()
    today_iso = today.isoformat()
    print(f"[Timee Sync] start {now_jst.isoformat()}")

    Path("./tmp").mkdir(parents=True, exist_ok=True)

    # 1. ダウンロード
    cur_path = f"./tmp/timee_{today.year}_{today.month:02d}.xlsx"
    download_month_excel(today.year, today.month, cur_path)
    records = parse_excel_records(cur_path)
    print(f"[Timee Sync] current month records: {len(records)}")

    meta = store.load_meta()
    if _should_fetch_next_month(meta, today_iso):
        ny, nm = _next_month(today)
        next_path = f"./tmp/timee_{ny}_{nm:02d}.xlsx"
        try:
            download_month_excel(ny, nm, next_path)
            next_records = parse_excel_records(next_path)
            print(f"[Timee Sync] next month records: {len(next_records)}")
            records.extend(next_records)
            meta["last_next_month_fetch"] = today_iso
        except Exception as e:
            print(f"[WARN] 翌月分取得に失敗: {e}")

    # 2. ワーカーマスタを upsert
    workers = store.load_workers()
    new_worker_ids: list[str] = []
    snapshot_curr: list[dict] = []
    for rec in records:
        wid, is_new = store.upsert_worker(workers, rec, today_iso)
        if is_new:
            new_worker_ids.append(wid)
        snapshot_curr.append({
            "id": wid,
            "就業日": rec["就業日"],
            "出勤回数": rec.get("出勤回数", 0),
            "開始時間": rec.get("開始時間", ""),
            "終了時間": rec.get("終了時間", ""),
            "求人タイトル": rec.get("求人タイトル", ""),
            "グループ": rec.get("グループ", ""),
            "バッジ": rec.get("バッジ", ""),
        })

    # 3. 差分検知
    snapshot_prev = store.load_snapshot()
    new_matches, cancellations = store.diff_snapshots(snapshot_prev, snapshot_curr, today)
    print(f"[Timee Sync] new={len(new_matches)} cancel={len(cancellations)} new_workers={len(new_worker_ids)}")

    if cancellations:
        store.record_cancellations(workers, cancellations, today_iso)

    # 4. 保存（マスタ → スナップショット → メタ）
    store.save_workers(workers)
    store.save_snapshot(snapshot_curr)
    store.save_meta(meta)

    # 5. 通知
    _send_match_notifications(new_matches, workers)
    print("[Timee Sync] done")


if __name__ == "__main__":
    try:
        run_sync()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
