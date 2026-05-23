"""シフト変更提案エンジン

制約:
- 原田・室谷・金澤 の3名中2名がなるべく毎日出勤
- 佐々木・堀田 のどちらかが必ず出勤
- 出勤人数のバラつきを抑える
- 各人の月間稼働日数を維持 (1日抜く=1日足す)
- 連勤悪化させない
"""
from __future__ import annotations
from collections import defaultdict
from typing import NamedTuple

THREE_TEAM = ("原田", "室谷", "金澤")
TWO_TEAM = ("佐々木", "堀田")


class Move(NamedTuple):
    person: str  # 氏名キー (姓のみ)
    frm: int
    to: int
    reason: str


def _short(name: str) -> str:
    return name.split("　")[0] if "　" in name else name


def _runs(days):
    if not days:
        return []
    ds = sorted(set(days))
    out, cur = [], [ds[0]]
    for d in ds[1:]:
        if d == cur[-1] + 1:
            cur.append(d)
        else:
            out.append(cur)
            cur = [d]
    out.append(cur)
    return out


def _max_run(days):
    rs = _runs(days)
    return max((len(r) for r in rs), default=0)


def _long_run_count(days, threshold=5):
    return sum(1 for r in _runs(days) if len(r) >= threshold)


def _has(names, key):
    return any(key in (n or "") for n in names)


def _violates_3cond(names):
    return sum(1 for k in THREE_TEAM if _has(names, k)) < 2


def _violates_2cond(names):
    return not any(k in (n or "") for n in names for k in TWO_TEAM)


def _person_days(by_day, last_day):
    pd = defaultdict(list)
    for d in range(1, last_day + 1):
        for n in by_day.get(d, []):
            pd[n].append(d)
    return {n: sorted(set(ds)) for n, ds in pd.items()}


def _find_full(by_day, key, last_day):
    for d in range(1, last_day + 1):
        for n in by_day.get(d, []):
            if key in (n or ""):
                return n
    return None


def _can_move(by_day, person_days, full_name, who_key, frm, to, last_day, forbidden_days=None):
    """連勤悪化しないか / 既出勤じゃないか / 個人NG日 チェック"""
    if frm == to or to < 1 or to > last_day or frm < 1 or frm > last_day:
        return False
    if full_name not in by_day.get(frm, []):
        return False
    if any(who_key in (n or "") for n in by_day.get(to, [])):
        return False
    # 個人NG日チェック
    if forbidden_days:
        ng = forbidden_days.get(who_key, set())
        if to in ng:
            return False
    old = person_days.get(full_name, [])
    new = [d for d in old if d != frm] + [to]
    if _max_run(new) > _max_run(old):
        return False
    if _long_run_count(new) > _long_run_count(old):
        return False
    # 新規発生する連勤の最大長が、消失する連勤の最大長を超えないこと
    # 例: [5連]が消えて[6連]が新発生 はNG
    old_runs_set = {tuple(r) for r in _runs(old)}
    new_runs_set = {tuple(r) for r in _runs(new)}
    added = new_runs_set - old_runs_set
    removed = old_runs_set - new_runs_set
    if added:
        added_max = max(len(r) for r in added)
        removed_max = max((len(r) for r in removed), default=0)
        if added_max > removed_max:
            return False
    # 制約: frm を抜くことで新規違反を起こさない
    new_frm_names = [n for n in by_day.get(frm, []) if n != full_name]
    if not _violates_3cond(by_day.get(frm, [])) and _violates_3cond(new_frm_names):
        return False
    if not _violates_2cond(by_day.get(frm, [])) and _violates_2cond(new_frm_names):
        return False
    return True


def _apply(by_day, person_days, full_name, frm, to):
    by_day[frm].remove(full_name)
    by_day.setdefault(to, []).append(full_name)
    person_days[full_name] = sorted([d for d in person_days[full_name] if d != frm] + [to])


def propose_moves(by_day: dict[int, list[str]], last_day: int,
                  blacklist: set[tuple[str, int, int]] | None = None,
                  confirmed: set[tuple[str, int, int]] | None = None,
                  forbidden_days: dict[str, set[int]] | None = None) -> list[Move]:
    """SF最新データから変更候補を計算。

    - blacklist: 不可とマークされた (person, frm, to) のセット
    - confirmed: 可とマークされ既に反映済とみなす (person, frm, to)
    - forbidden_days: 個人別NG日 {person_key: {day, day, ...}}
    """
    blacklist = blacklist or set()
    confirmed = confirmed or set()
    forbidden_days = forbidden_days or {}

    work = {d: list(by_day.get(d, [])) for d in range(1, last_day + 1)}
    pd = _person_days(work, last_day)
    moves: list[Move] = []

    def try_move(who_key, frm, to, reason):
        if (who_key, frm, to) in blacklist:
            return False
        full = _find_full(work, who_key, last_day)
        if not full:
            return False
        if not _can_move(work, pd, full, who_key, frm, to, last_day, forbidden_days):
            return False
        moves.append(Move(who_key, frm, to, reason))
        _apply(work, pd, full, frm, to)
        return True

    # 1. 3条件違反の解消
    for d in range(1, last_day + 1):
        names = work.get(d, [])
        if not names:
            continue
        present = [k for k in THREE_TEAM if _has(names, k)]
        if len(present) >= 2:
            continue
        for who_key in THREE_TEAM:
            if who_key in present:
                continue
            full = _find_full(work, who_key, last_day)
            if not full:
                continue
            for frm in sorted(pd[full], key=lambda x: -len(work.get(x, []))):
                if frm == d:
                    continue
                if try_move(who_key, frm, d, f"6/{d} 3名条件解消"):
                    present.append(who_key)
                    break
            if len(present) >= 2:
                break

    # 2. 2条件違反の解消
    for d in range(1, last_day + 1):
        names = work.get(d, [])
        if not names:
            continue
        if any(k in (n or "") for n in names for k in TWO_TEAM):
            continue
        for who_key in TWO_TEAM:
            full = _find_full(work, who_key, last_day)
            if not full:
                continue
            placed = False
            for frm in sorted(pd[full], key=lambda x: -len(work.get(x, []))):
                if frm == d:
                    continue
                if try_move(who_key, frm, d, f"6/{d} 2名条件解消"):
                    placed = True
                    break
            if placed:
                break

    # 3. 人数のバラつき調整 (過剰→不足)
    def cur_counts():
        return {d: len(set(work.get(d, []))) for d in range(1, last_day + 1)}

    move_count = defaultdict(int)  # 同一人物の提案上限制御
    PER_PERSON_LIMIT = 2
    for m in moves:  # 既に提案済(条件解消で)の人をカウント
        move_count[m.person] += 1

    for _ in range(50):
        cnt = cur_counts()
        avg = sum(cnt.values()) / last_day
        over = [d for d, c in cnt.items() if c >= avg + 1.0]
        under = [d for d, c in cnt.items() if c <= avg - 1.0]
        if not over or not under:
            break
        over.sort(key=lambda d: -cnt[d])
        under.sort(key=lambda d: cnt[d])
        moved = False
        for od in over:
            # 動かし回数の少ない人を優先
            members = sorted(list(work.get(od, [])), key=lambda nm: move_count[_short(nm)])
            for nm in members:
                who_short = _short(nm)
                if move_count[who_short] >= PER_PERSON_LIMIT:
                    continue
                for ud in under:
                    if cnt[ud] >= avg:
                        continue
                    test_from = [n for n in work[od] if n != nm]
                    if _short(nm) in THREE_TEAM and _violates_3cond(test_from) and not _violates_3cond(work[od]):
                        continue
                    if _short(nm) in TWO_TEAM and _violates_2cond(test_from) and not _violates_2cond(work[od]):
                        continue
                    reason = f"人数調整 6/{od}({cnt[od]}名) → 6/{ud}({cnt[ud]}名)"
                    if try_move(who_short, od, ud, reason):
                        cnt[od] -= 1
                        cnt[ud] += 1
                        move_count[who_short] += 1
                        moved = True
                        break
                if moved:
                    break
            if moved:
                break
        if not moved:
            break

    # ※連勤短縮のみの Move は提案しない (ユーザ方針: 人数調整に伴う連勤緩和のみ許容)

    # confirmed 済みの move は提案から除外
    return [m for m in moves if (m.person, m.frm, m.to) not in confirmed]


