"""
ユーザー認証情報を Google Sheets に永続化するストア。

- 保存先: ikusei用スプレッドシート内の `user_auth_data` ワークシートのA1セル
- 全ユーザー共有（st.cache_resource）
- 5秒スロットリング
- 平文保存（マスタ閲覧可能者にはパスワード見える前提）

データ構造:
{
  "users": [
    {
      "id": "s-yoshida",
      "password": "<パスワード>",
      "display_name": "吉田 颯",
      "active": true,
      "last_login": "",
      "created_at": "2026-05-20"
    },
    ...
  ]
}
"""

import json
import time
from datetime import datetime, timezone, timedelta

import streamlit as st
import gspread

from talk_template_store import (
    _get_writable_client,
    _IKUSEI_SHEET_ID_FALLBACK,
)

WORKSHEET_NAME = "user_auth_data"
CELL = "A1"

_JST = timezone(timedelta(hours=9))


def _today_jst() -> str:
    return datetime.now(_JST).strftime("%Y-%m-%d")


def _now_jst() -> str:
    return datetime.now(_JST).strftime("%Y-%m-%d %H:%M")


def _seed_password(user_id: str) -> str:
    """シード用パスワードを st.secrets から取得（コードに平文を置かない）。

    secrets.toml 例:
      [seed_passwords]
      s-yoshida = "xxxx"
    未設定ユーザーは空文字となり、verify_credentials でログイン不可として扱う。
    """
    try:
        return str(st.secrets["seed_passwords"][user_id])
    except Exception:
        return ""


# 初期登録ユーザー（初回デプロイ時のシード）。パスワードは st.secrets 管理。
_SEED_MEMBERS = [
    ("s-yoshida",   "吉田 颯"),
    ("k-muro",      "室谷 慧"),
    ("r-harada",    "原田 綾子"),
    ("s-zawa",      "金澤 駿平"),
    ("s-yoshimoto", "吉本 将吾"),
    ("k-horita",    "堀田 輝斗"),
    ("k-kakuta",    "角田 心華"),
    ("a-sasaki",    "佐々木 彩乃"),
    ("t-kasai",     "葛西 翼"),
    ("k-amagai",    "雨貝 一生"),
    ("r-kikuti",    "菊地 隆真"),
    ("y-kuri",      "栗田 優衣"),
    ("s-kan",       "勘七 瞬"),
]

_DEFAULT_USERS = [
    {"id": uid, "password": _seed_password(uid), "display_name": name,
     "active": True, "last_login": "", "created_at": "2026-05-20"}
    for uid, name in _SEED_MEMBERS
]


def _get_ws():
    client = _get_writable_client()
    try:
        sheet_id = st.secrets["ikusei"]["spreadsheet_id"]
    except Exception:
        sheet_id = _IKUSEI_SHEET_ID_FALLBACK
    sh = client.open_by_key(sheet_id)
    try:
        return sh.worksheet(WORKSHEET_NAME)
    except gspread.exceptions.WorksheetNotFound:
        return sh.add_worksheet(title=WORKSHEET_NAME, rows=2, cols=2)


@st.cache_resource
def _shared_cache() -> dict:
    """全ユーザー共有キャッシュ。

    読込失敗を「未初期化(None)」と誤認すると ensure_seeded 等が既存データを初期値で
    上書きする事故になるため、失敗時はリトライしてからでないと None にしない。
    """
    last_err = None
    for _ in range(3):
        try:
            ws = _get_ws()
            raw = ws.acell(CELL).value
            if raw:
                data = json.loads(raw)
                if isinstance(data, dict) and isinstance(data.get("users"), list):
                    return {"users": data["users"]}
            # 読めたが空 → 未初期化
            return {"users": None}
        except Exception as e:
            last_err = e
            time.sleep(0.4)
    # 3回とも失敗 = 読込不能。未初期化とは区別できないため None を返すが、
    # この状態を根拠に「書き込み(シード/保存)」してはならない（各関数側で直読みする）。
    return {"users": None}


def get_users() -> list[dict]:
    """全ユーザー（非アクティブ含む）。未保存ならデフォルトをそのまま返す（初回読込時のシードは保存処理で行う）。"""
    cached = _shared_cache().get("users")
    if cached is None:
        return [u.copy() for u in _DEFAULT_USERS]
    return cached


def ensure_seeded() -> None:
    """シートが本当に空のときだけ初期ユーザーを1度書き込む（冪等・fail-safe）。

    重要: キャッシュ(_shared_cache)は読込失敗時も None を返すため、それを根拠に
    シードすると既存ユーザーを初期13名で上書きする重大事故になる（過去に複数回発生）。
    必ず Sheets を直読みし、
      - 読めない → 何もしない（既存データ保護）
      - セルに何か入っている → 何もしない（上書き禁止）
      - セルが本当に空 → そのときだけ初期シード
    """
    try:
        ws = _get_ws()
        raw = ws.acell(CELL).value
    except Exception:
        return  # 読込不能時は絶対にシードしない
    if raw is not None and str(raw).strip() != "":
        return  # 既にデータあり → 触らない
    try:
        ws.update_acell(CELL, json.dumps({"users": _DEFAULT_USERS}, ensure_ascii=False))
        _shared_cache.clear()
    except Exception:
        pass


def get_active_users() -> list[dict]:
    return [u for u in get_users() if u.get("active", True)]


def find_user(user_id: str) -> dict | None:
    user_id = (user_id or "").strip()
    for u in get_users():
        if u.get("id") == user_id:
            return u
    return None


def verify_credentials(user_id: str, password: str) -> tuple[bool, str, dict | None]:
    """
    認証チェック。
    戻り値: (成功フラグ, メッセージ, ユーザー辞書 or None)

    キャッシュが古いと復元直後のユーザーがログインできないため、認証は必ず
    Sheetsの最新を直読みして判定する（読込失敗時のみキャッシュにフォールバック）。
    """
    user_id = (user_id or "").strip()
    try:
        users = _read_live_users()
    except Exception:
        users = get_users()
    user = next((u for u in users if u.get("id") == user_id), None)
    if user is None:
        return False, "IDまたはパスワードが違います", None
    stored = user.get("password") or ""
    # パスワード未設定ユーザー（シード未投入等）は空文字一致でのログインを許さない
    if not stored or stored != password:
        return False, "IDまたはパスワードが違います", None
    if not user.get("active", True):
        return False, "このアカウントは無効化されています。管理者に連絡してください。", None
    return True, "ログインしました", user


_last_save = {"t": 0.0}


_BACKUP_WS = "user_auth_backup"


def _save_users(users: list[dict], *, force: bool = False) -> tuple[bool, str]:
    now = time.time()
    if not force and now - _last_save["t"] < 5:
        return False, "保存スキップ（5秒以内の連続保存）"
    try:
        ws = _get_ws()
        # 現在のライブ内容を取得（ドロップガード＋バックアップ用）
        try:
            live_raw = ws.acell(CELL).value
            live_users = json.loads(live_raw).get("users", []) if live_raw else []
        except Exception:
            live_raw, live_users = None, []

        # 安全装置①: 既存より2名以上減る保存は脱落事故の疑いとして中止
        if live_users and (len(live_users) - len(users)) >= 2:
            return False, (
                f"保存中止: ユーザーが{len(live_users)}→{len(users)}名へ大幅減少しました"
                "（脱落事故防止のためブロック）。意図的な一括削除なら管理者へご連絡ください。"
            )

        # 安全装置②: 構成（ID集合）が変わる時は書き込み前にバックアップ(append-only)
        if live_raw:
            try:
                _live_ids = {u.get("id") for u in live_users}
                _new_ids = {u.get("id") for u in users}
                if _live_ids != _new_ids:
                    sh = ws.spreadsheet
                    try:
                        bws = sh.worksheet(_BACKUP_WS)
                    except Exception:
                        bws = sh.add_worksheet(title=_BACKUP_WS, rows=4000, cols=2)
                    bws.append_row([_now_jst(), live_raw], value_input_option="RAW")
            except Exception:
                pass

        ws.update_acell(CELL, json.dumps({"users": users}, ensure_ascii=False))
        cache = _shared_cache()
        cache["users"] = users
        _last_save["t"] = now
        return True, "保存しました"
    except Exception as e:
        return False, f"保存エラー: {e}"


def save_users(users: list[dict]) -> tuple[bool, str]:
    """ユーザーリスト全体を保存。"""
    return _save_users(users)


def _read_live_users() -> list[dict]:
    """Sheetsから最新のユーザーリストを直接読む（キャッシュ非経由）。

    古い画面（キャッシュ）のまま保存すると、他者が追加したユーザーが脱落する事故が
    起きるため、追加/削除/更新の直前は必ずこれで最新を取得してから差分を適用する。
    読込結果が空や失敗の場合は、データ消失防止のため例外を投げて保存を中止させる
    （[[feedback_load_fail_never_silent_empty]] の方針）。
    """
    ws = _get_ws()
    raw = ws.acell(CELL).value
    if not raw or not str(raw).strip():
        raise RuntimeError("最新ユーザーの読込結果が空でした")
    data = json.loads(raw)
    users = data.get("users")
    if not isinstance(users, list) or not users:
        raise RuntimeError("最新ユーザーが空/不正でした")
    return users


def add_user(user_id: str, password: str, display_name: str) -> tuple[bool, str]:
    user_id = (user_id or "").strip()
    password = (password or "").strip()
    display_name = (display_name or "").strip()
    if not user_id or not password or not display_name:
        return False, "ID・パスワード・表示名はすべて必須です"
    try:
        users = _read_live_users()
    except Exception as e:
        return False, f"最新ユーザーの読込に失敗したため保存を中止しました: {e}"
    if any(u.get("id") == user_id for u in users):
        return False, f"ID「{user_id}」は既に登録されています"
    users.append({
        "id": user_id,
        "password": password,
        "display_name": display_name,
        "active": True,
        "last_login": "",
        "created_at": _today_jst(),
    })
    return _save_users(users, force=True)


def update_password(user_id: str, new_password: str) -> tuple[bool, str]:
    new_password = (new_password or "").strip()
    if not new_password:
        return False, "新しいパスワードを入力してください"
    try:
        users = _read_live_users()
    except Exception as e:
        return False, f"最新ユーザーの読込に失敗したため保存を中止しました: {e}"
    for u in users:
        if u.get("id") == user_id:
            u["password"] = new_password
            return _save_users(users, force=True)
    return False, f"ID「{user_id}」が見つかりません"


def update_display_name(user_id: str, new_name: str) -> tuple[bool, str]:
    new_name = (new_name or "").strip()
    if not new_name:
        return False, "表示名を入力してください"
    try:
        users = _read_live_users()
    except Exception as e:
        return False, f"最新ユーザーの読込に失敗したため保存を中止しました: {e}"
    for u in users:
        if u.get("id") == user_id:
            u["display_name"] = new_name
            return _save_users(users, force=True)
    return False, f"ID「{user_id}」が見つかりません"


def set_active(user_id: str, active: bool) -> tuple[bool, str]:
    try:
        users = _read_live_users()
    except Exception as e:
        return False, f"最新ユーザーの読込に失敗したため保存を中止しました: {e}"
    for u in users:
        if u.get("id") == user_id:
            u["active"] = bool(active)
            return _save_users(users, force=True)
    return False, f"ID「{user_id}」が見つかりません"


def delete_user(user_id: str) -> tuple[bool, str]:
    try:
        users = _read_live_users()
    except Exception as e:
        return False, f"最新ユーザーの読込に失敗したため保存を中止しました: {e}"
    new_users = [u for u in users if u.get("id") != user_id]
    if len(new_users) == len(users):
        return False, f"ID「{user_id}」が見つかりません"
    return _save_users(new_users, force=True)


def record_login(user_id: str) -> None:
    """ログイン成功時刻を記録（保存失敗してもログインは通す）。

    重要: 古いキャッシュで全上書きすると他メンバーが脱落する事故になるため、
    必ずSheetsの最新を直読みしてから該当者のlast_loginだけ更新して保存する。
    最新が読めない場合は保存しない（履歴更新を諦める＝データ消失より安全側）。
    """
    try:
        users = _read_live_users()
    except Exception:
        return
    changed = False
    for u in users:
        if u.get("id") == user_id:
            u["last_login"] = _now_jst()
            changed = True
            break
    if changed:
        try:
            _save_users(users, force=True)
        except Exception:
            pass


def clear_users_cache() -> None:
    _shared_cache.clear()
