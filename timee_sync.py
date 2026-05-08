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
from timee_job_calendar import fetch_month_postings
from timee_worker_detail import fetch_worker_details

# ワーカー詳細(平均Good率/直前キャンセル率/管理用メモ)の更新間隔と1回あたり上限
WORKER_DETAIL_TTL_HOURS = 6
WORKER_DETAIL_MAX_PER_RUN = 20


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


def _format_shift(rec: dict) -> str:
    """就業日を「5/8 10:00～19:00」形式に整形。"""
    ds = rec.get("就業日", "")
    try:
        d = datetime.strptime(ds, "%Y-%m-%d").date()
        date_str = f"{d.month}/{d.day}"
    except Exception:
        date_str = ds
    start = rec.get("開始時間", "")
    end = rec.get("終了時間", "")
    return f"{date_str} {start}～{end}"


def _build_match_block(records: list[dict], worker: dict) -> str:
    """同一ワーカーの複数レコードを1ブロックにまとめる。

    出力例:
        【リピーターマッチング】
        ID: 441603
        竹邉 雅美（タケベ マサミ）女51歳
        就業日:
        5/19 10:00～19:00
        5/21 10:00～19:00
        5/25 10:00～19:00
        リピート回数: 6回
        S工事取得経験者
        手かかからない人
        ...
        キャンセル履歴: 0回
    """
    rec0 = records[0]
    cancel_count = len(worker.get("キャンセル履歴", []))
    is_repeater = rec0.get("出勤回数", 0) >= 1
    title = "【リピーターマッチング】" if is_repeater else "【新規マッチング】"

    lines = [
        title,
        f"ID: {rec0['id']}",
        f"{worker.get('氏名', '')}（{worker.get('カナ', '')}）{worker.get('性別', '')}{worker.get('年齢', '')}歳",
    ]

    # 就業日（1件なら横並び、2件以上ならラベルだけにして次行から並べる）
    sorted_recs = sorted(records, key=lambda r: r.get("就業日", ""))
    if len(sorted_recs) == 1:
        lines.append(f"就業日: {_format_shift(sorted_recs[0])}")
    else:
        lines.append("就業日:")
        for r in sorted_recs:
            lines.append(_format_shift(r))

    # 回数+グループ（グループは1行ずつ改行）
    count_label = "リピート回数" if is_repeater else "出勤回数"
    lines.append(f"{count_label}: {rec0.get('出勤回数', 0)}回")
    groups_str = rec0.get("グループ", "")
    for g in (g.strip() for g in groups_str.split(",")):
        if g:
            lines.append(g)

    lines.append(f"キャンセル履歴: {cancel_count}回")
    return "\n".join(lines)


def _send_match_notifications(new_matches: list[dict], workers: dict) -> None:
    if not new_matches:
        return
    # 同一IDをまとめる
    by_id: dict[str, list[dict]] = {}
    for rec in new_matches:
        by_id.setdefault(rec["id"], []).append(rec)
    # 並び順: 新規(出勤回数=0)を先 → リピーター。同区分内はIDで安定ソート
    sorted_groups = sorted(
        by_id.items(),
        key=lambda kv: (1 if kv[1][0].get("出勤回数", 0) >= 1 else 0, kv[0]),
    )
    blocks = []
    for wid, recs in sorted_groups:
        worker = workers.get(wid, {})
        blocks.append(_build_match_block(recs, worker))
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
    records = parse_excel_records(cur_path, default_year=today.year, default_month=today.month)
    print(f"[Timee Sync] current month records: {len(records)}")

    meta = store.load_meta()
    if _should_fetch_next_month(meta, today_iso):
        ny, nm = _next_month(today)
        next_path = f"./tmp/timee_{ny}_{nm:02d}.xlsx"
        try:
            download_month_excel(ny, nm, next_path)
            next_records = parse_excel_records(next_path, default_year=ny, default_month=nm)
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

    # 4.4. ワーカー詳細(平均Good率/直前キャンセル率/管理用メモ)の間引き更新
    try:
        from datetime import timedelta as _td
        # 候補: current snapshot に出現するワーカー
        snapshot_wids = {r["id"] for r in snapshot_curr}
        candidates = []
        cutoff = now_jst - _td(hours=WORKER_DETAIL_TTL_HOURS)
        for wid in snapshot_wids:
            w = workers.get(wid, {})
            last = w.get("timee_detail_fetched_at")  # ISO形式 or None
            stale = True
            if last:
                try:
                    last_dt = datetime.fromisoformat(last)
                    stale = last_dt < cutoff
                except Exception:
                    stale = True
            if stale:
                candidates.append(wid)
        # 古いものから優先（None=未取得→最古扱い）
        candidates.sort(key=lambda wid: workers.get(wid, {}).get("timee_detail_fetched_at") or "")
        targets_wids = candidates[:WORKER_DETAIL_MAX_PER_RUN]
        # 各wid の今日以降最古の 就業日 を求める(求人パス用)
        wid_to_shift: dict[str, str] = {}
        for r in snapshot_curr:
            _wid = r.get("id")
            _ds = str(r.get("就業日") or "")
            if not _wid or _ds < today_iso:
                continue
            cur = wid_to_shift.get(_wid)
            if cur is None or _ds < cur:
                wid_to_shift[_wid] = _ds
        targets = [
            (workers[wid]["氏名"], workers[wid]["カナ"], wid_to_shift.get(wid))
            for wid in targets_wids
        ]
        print(f"[Timee Sync] worker_detail candidates={len(candidates)} fetching={len(targets)}")
        if targets:
            detail_map = fetch_worker_details(targets)
            now_iso = now_jst.isoformat(timespec="seconds")
            updated = 0
            no_match = 0
            key_to_wid = store.build_key_to_id(workers)
            for k, fields in detail_map.items():
                wid = key_to_wid.get(k)
                if not wid:
                    continue
                w = workers[wid]
                if fields.get("_status") == "no_match":
                    # Timeeのワーカー管理に出てこない(=未稼働)。fetched_atだけ更新して
                    # 再試行スパムを止める。値は空のまま
                    w["timee_detail_fetched_at"] = now_iso
                    w["timee_not_in_list"] = True
                    no_match += 1
                    continue
                w["good_rate"] = fields.get("good_rate", "")
                w["cancel_rate"] = fields.get("cancel_rate", "")
                w["timee_memo"] = fields.get("timee_memo", "")
                w["timee_detail_fetched_at"] = now_iso
                w["timee_not_in_list"] = False
                updated += 1
            print(f"[Timee Sync] worker_detail updated {updated}名 / no_match {no_match}名")
            if updated or no_match:
                store.save_workers(workers)
    except Exception as e:
        print(f"[WARN] ワーカー詳細取得に失敗: {e}")

    # 4.5. 求人一覧（カレンダー）スナップショット取得（当月＋翌月）
    try:
        all_postings = []
        for y, m in [(today.year, today.month), _next_month(today)]:
            try:
                month_postings = fetch_month_postings(y, m)
                print(f"[Timee Sync] postings {y}-{m:02d}: {len(month_postings)}件")
                all_postings.extend(month_postings)
            except Exception as e:
                print(f"[WARN] 求人一覧 {y}-{m:02d} 取得失敗: {e}")
        if all_postings:
            store.save_postings(all_postings)
            print(f"[Timee Sync] postings saved: total {len(all_postings)}件")
    except Exception as e:
        print(f"[WARN] 求人一覧の保存に失敗: {e}")

    # 5. 通知
    _send_match_notifications(new_matches, workers)
    print("[Timee Sync] done")


if __name__ == "__main__":
    try:
        run_sync()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
