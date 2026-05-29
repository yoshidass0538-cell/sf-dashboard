"""
Salesforce 集計ダッシュボード（Streamlit）

ローカル実行:
    py -m streamlit run app.py

新しい集計を追加するには metrics.py に Metric を追記するだけ。
"""

import pandas as pd
try:
    pd.options.future.infer_string = False
except Exception:
    pass
import streamlit as st
from st_aggrid import AgGrid, GridOptionsBuilder, JsCode
from streamlit_sortables import sort_items

from sf_client import get_sf
from metrics import METRICS, get_metric, TALK_SCRIPT_MEMBERS, TALK_SCRIPT_BOARDS, parse_talk_script_key, reload_talk_script_metrics
from ikusei_store import get_store, save_store

st.set_page_config(page_title="SF 集計ダッシュボード", page_icon="📊", layout="wide")

# ブラウザ自動翻訳を無効化 & フォント設定
st.markdown(
    """
    <script>
    document.documentElement.setAttribute('translate', 'no');
    document.documentElement.setAttribute('lang', 'ja');
    document.documentElement.classList.add('notranslate');
    </script>
    <meta name="google" content="notranslate">
    """,
    unsafe_allow_html=True,
)
st.markdown(
    """
    <style>
    html, body, [class*="css"], .stMarkdown, .stDataFrame, th, td,
    .ag-theme-balham, .ag-cell, .ag-header-cell-text {
        font-family: 'メイリオ', Meiryo, 'Hiragino Sans', 'Yu Gothic', sans-serif !important;
    }
    /* サイドバー背景グラデーション: ライトモード */
    html.light-mode [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #e8eaf6 0%, #c5cae9 30%, #9fa8da 70%, #b39ddb 100%) !important;
        border-right: 2px solid rgba(0, 0, 0, 0.15) !important;
    }
    html.light-mode [data-testid="stSidebar"] *,
    html.light-mode [data-testid="stSidebar"] button {
        color: #1a1a2e !important;
    }
    /* サイドバー背景グラデーション: ダークモード */
    html.dark-mode [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #1a1a2e 0%, #16213e 30%, #0f3460 70%, #533483 100%) !important;
        border-right: 2px solid rgba(255, 255, 255, 0.2) !important;
    }
    html.dark-mode [data-testid="stSidebar"] *,
    html.dark-mode [data-testid="stSidebar"] button,
    html.dark-mode [data-testid="stSidebar"] h3,
    html.dark-mode [data-testid="stSidebar"] p,
    html.dark-mode [data-testid="stSidebar"] span,
    html.dark-mode [data-testid="stSidebar"] label,
    html.dark-mode [data-testid="stSidebar"] summary,
    html.dark-mode [data-testid="stSidebar"] summary p,
    html.dark-mode [data-testid="stSidebar"] summary svg {
        color: #ffffff !important;
        fill: #ffffff !important;
    }
    html.dark-mode [data-testid="stSidebar"] button {
        background: rgba(255, 255, 255, 0.12) !important;
        border: 1px solid rgba(255, 255, 255, 0.25) !important;
    }
    html.dark-mode [data-testid="stSidebar"] button:hover {
        background: rgba(255, 255, 255, 0.22) !important;
    }
    /* メインエリア背景: ライトモード */
    html.light-mode [data-testid="stAppViewContainer"] {
        background: linear-gradient(180deg, #e8eaf6 0%, #c5cae9 30%, #9fa8da 70%, #b39ddb 100%) !important;
    }
    html.light-mode [data-testid="stMain"],
    html.light-mode [data-testid="stMainBlockContainer"],
    html.light-mode [data-testid="stVerticalBlock"],
    html.light-mode .main .block-container,
    html.light-mode section[data-testid="stMain"] {
        background: transparent !important;
    }
    html.light-mode [data-testid="stHeader"] {
        background: rgba(255, 255, 255, 0.8) !important;
        backdrop-filter: blur(10px) !important;
    }
    /* メインエリア背景: ダークモード */
    html.dark-mode [data-testid="stAppViewContainer"] {
        background: linear-gradient(180deg, #1a1a2e 0%, #16213e 30%, #0f3460 70%, #533483 100%) !important;
    }
    html.dark-mode [data-testid="stMain"] {
        background: transparent !important;
    }
    /* +タブを右端に寄せる */
    [data-testid="stTabs"] [role="tablist"] {
        display: flex;
        width: 100%;
    }
    [data-testid="stTabs"] [role="tablist"] button:last-child {
        margin-left: auto;
        margin-right: 0;
        position: absolute;
        right: 0;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# ----------------------------------------------------------------------
# 入口ログインゲート（IDとパスワードで認証）
# ----------------------------------------------------------------------
from user_auth_store import (
    verify_credentials as _auth_verify,
    record_login as _auth_record_login,
    ensure_seeded as _auth_ensure_seeded,
)

if not st.session_state.get("logged_in_user"):
    _auth_ensure_seeded()
    # ロゴをbase64で読み込み（既にトップで読み込まれているがログイン時は別経路なので個別に）
    import base64 as _b64_login
    try:
        with open("gcs_logo.png", "rb") as _f:
            _login_logo_b64 = _b64_login.b64encode(_f.read()).decode()
    except Exception:
        _login_logo_b64 = ""

    st.markdown(
        """
        <style>
        /* サイドバー・ヘッダー・ツールバーを非表示 */
        [data-testid="stSidebar"], [data-testid="collapsedControl"],
        [data-testid="stHeader"], [data-testid="stToolbar"] { display: none !important; }
        [data-testid="stAppViewContainer"] { padding-top: 0 !important; }

        /* 全画面アニメーション背景 */
        [data-testid="stAppViewContainer"] {
            background:
                radial-gradient(1200px 600px at 10% 0%, rgba(179, 157, 219, 0.55), transparent 60%),
                radial-gradient(900px 500px at 90% 10%, rgba(83, 52, 131, 0.55), transparent 55%),
                radial-gradient(1000px 700px at 50% 100%, rgba(15, 52, 96, 0.65), transparent 60%),
                linear-gradient(135deg, #1a1a2e 0%, #16213e 35%, #0f3460 70%, #533483 100%) !important;
            background-size: 200% 200%, 200% 200%, 200% 200%, 100% 100% !important;
            animation: loginBgShift 18s ease-in-out infinite !important;
            min-height: 100vh !important;
        }
        @keyframes loginBgShift {
            0%, 100% { background-position: 0% 0%, 100% 0%, 50% 100%, 0 0; }
            50%      { background-position: 30% 30%, 70% 40%, 40% 70%, 0 0; }
        }

        /* 浮遊するグロー粒子 */
        [data-testid="stAppViewContainer"]::before,
        [data-testid="stAppViewContainer"]::after {
            content: "";
            position: fixed;
            border-radius: 50%;
            filter: blur(60px);
            opacity: 0.55;
            pointer-events: none;
            z-index: 0;
        }
        [data-testid="stAppViewContainer"]::before {
            width: 380px; height: 380px;
            background: radial-gradient(circle, #b39ddb 0%, transparent 70%);
            top: -80px; left: -80px;
            animation: floatA 14s ease-in-out infinite;
        }
        [data-testid="stAppViewContainer"]::after {
            width: 460px; height: 460px;
            background: radial-gradient(circle, #533483 0%, transparent 70%);
            bottom: -120px; right: -120px;
            animation: floatB 16s ease-in-out infinite;
        }
        @keyframes floatA { 0%,100%{transform:translate(0,0)} 50%{transform:translate(60px,40px)} }
        @keyframes floatB { 0%,100%{transform:translate(0,0)} 50%{transform:translate(-50px,-30px)} }

        /* 本体カード */
        .login-wrap {
            display: flex;
            justify-content: center;
            align-items: flex-start;
            padding-top: 4vh;
            padding-bottom: 0;
            margin-bottom: 0;
            position: relative;
            z-index: 1;
        }
        .login-card {
            width: 100%;
            max-width: 880px;
            padding: 32px 48px 14px;
            background: rgba(255, 255, 255, 0.08);
            backdrop-filter: blur(22px) saturate(180%);
            -webkit-backdrop-filter: blur(22px) saturate(180%);
            border: 1px solid rgba(255, 255, 255, 0.18);
            border-radius: 22px;
            box-shadow: 0 25px 60px rgba(0, 0, 0, 0.45),
                        0 0 0 1px rgba(255, 255, 255, 0.05) inset;
            animation: cardIn 0.7s cubic-bezier(0.2, 0.9, 0.3, 1.2) both;
            margin-bottom: 0;
        }
        @keyframes cardIn {
            from { opacity: 0; transform: translateY(24px) scale(0.96); }
            to   { opacity: 1; transform: translateY(0) scale(1); }
        }
        .login-logo {
            display: flex; align-items: center; justify-content: center;
            margin-bottom: 18px;
        }
        .login-logo img {
            width: 110px; height: auto;
            filter: drop-shadow(0 6px 14px rgba(0,0,0,0.4));
            animation: logoBounce 1.1s cubic-bezier(0.2, 0.9, 0.3, 1.4) both;
        }
        @keyframes logoBounce {
            0%   { opacity: 0; transform: scale(0.6) rotate(-8deg); }
            60%  { opacity: 1; transform: scale(1.08) rotate(3deg); }
            100% { opacity: 1; transform: scale(1) rotate(0); }
        }
        .login-title {
            text-align: center;
            font-size: 1.7rem;
            font-weight: 800;
            letter-spacing: 0.04em;
            background: linear-gradient(90deg, #fff 0%, #d1c4e9 50%, #b39ddb 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
            margin: 0 0 6px 0;
        }
        .login-subtitle {
            text-align: center;
            color: rgba(255, 255, 255, 0.72);
            font-size: 0.92rem;
            margin: 0;
            letter-spacing: 0.02em;
        }
        /* タイトルカード直後の Streamlit ブロック余白を詰める */
        .login-wrap + div [data-testid="stVerticalBlock"] > div:first-child > div:first-child { margin-top: 0 !important; }
        [data-testid="stIFrame"] { margin-top: 18px !important; }
        [data-testid="stMainBlockContainer"] {
            padding-top: 0 !important;
            padding-bottom: 0 !important;
            max-width: 100% !important;
        }
        [data-testid="stMain"] { padding: 0 !important; }

        /* 入力欄を白背景＋ガラス風に */
        [data-testid="stForm"] {
            background: transparent !important;
            border: none !important;
            padding: 0 !important;
            max-width: 480px !important;
            margin: 0 auto !important;
        }
        [data-testid="stForm"] label {
            color: #ffffff !important;
            font-size: 0.88rem !important;
            font-weight: 600 !important;
            letter-spacing: 0.03em;
        }
        [data-testid="stForm"] input {
            background: rgba(255, 255, 255, 0.92) !important;
            color: #1a1a2e !important;
            border: 1px solid rgba(255, 255, 255, 0.4) !important;
            border-radius: 10px !important;
            padding: 12px 14px !important;
            font-size: 1rem !important;
            transition: all 0.25s ease !important;
        }
        [data-testid="stForm"] input:focus {
            border-color: #b39ddb !important;
            box-shadow: 0 0 0 4px rgba(179, 157, 219, 0.25) !important;
            background: #ffffff !important;
        }

        /* ログインボタン */
        [data-testid="stForm"] button[kind="primary"] {
            background: linear-gradient(135deg, #7e57c2 0%, #5e35b1 60%, #4527a0 100%) !important;
            color: #fff !important;
            border: none !important;
            border-radius: 12px !important;
            padding: 12px !important;
            font-size: 1.05rem !important;
            font-weight: 700 !important;
            letter-spacing: 0.06em !important;
            box-shadow: 0 10px 25px rgba(81, 45, 168, 0.45) !important;
            transition: all 0.25s cubic-bezier(0.2, 0.9, 0.3, 1.2) !important;
            margin-top: 6px !important;
        }
        [data-testid="stForm"] button[kind="primary"]:hover {
            transform: translateY(-2px) !important;
            box-shadow: 0 14px 32px rgba(81, 45, 168, 0.6),
                        0 0 30px rgba(179, 157, 219, 0.35) !important;
            filter: brightness(1.1) !important;
        }
        [data-testid="stForm"] button[kind="primary"]:active {
            transform: translateY(0) !important;
        }

        /* エラーメッセージ */
        [data-testid="stAlert"] {
            background: rgba(220, 38, 38, 0.18) !important;
            border: 1px solid rgba(220, 38, 38, 0.45) !important;
            color: #ffe0e0 !important;
            border-radius: 10px !important;
            backdrop-filter: blur(10px) !important;
        }
        [data-testid="stAlert"] * { color: #ffe0e0 !important; }

        .login-foot {
            text-align: center;
            color: rgba(255,255,255,0.45);
            font-size: 0.75rem;
            margin-top: 22px;
            letter-spacing: 0.05em;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    _logo_html = (
        f'<div class="login-logo"><img src="data:image/png;base64,{_login_logo_b64}" alt="logo"></div>'
        if _login_logo_b64 else ""
    )
    st.markdown(
        '<div class="login-wrap"><div class="login-card">'
        f'{_logo_html}'
        '<div class="login-title">CS促進ダッシュボード</div>'
        '<div class="login-subtitle">IDとパスワードを入力してください</div>'
        '</div></div>',
        unsafe_allow_html=True,
    )

    # フル幅ラッパ（タイトルカード直下、画面幅いっぱい）
    _form_col = st.columns([1, 20, 1])[1]
    with _form_col:
        # --- 🎮 日替わりミニゲーム（タイトル直下、ログイン欄の上）---
        import streamlit.components.v1 as _login_components
        from login_games import pick_today_game as _pick_game
        _today_game = _pick_game()
        _login_components.html(
            _today_game["html"],
            height=_today_game["height"],
            scrolling=False,
        )

        with st.form("login_form", clear_on_submit=False):
            _login_id = st.text_input("ID", key="login_id_input", placeholder="例: s-yoshida")
            _login_pw = st.text_input("パスワード", type="password", key="login_pw_input", placeholder="••••••••")
            _submitted = st.form_submit_button("🔓 ログイン", type="primary", use_container_width=True)

        st.markdown(
            '<div class="login-foot">© CS促進 - 認証が必要です</div>',
            unsafe_allow_html=True,
        )
    if _submitted:
        _ok, _msg, _user = _auth_verify(_login_id, _login_pw)
        if _ok and _user is not None:
            st.session_state["logged_in_user"] = {
                "id": _user["id"],
                "display_name": _user.get("display_name", _user["id"]),
            }
            _auth_record_login(_user["id"])
            st.rerun()
        else:
            with _form_col:
                st.error(_msg)
    st.stop()


# ----------------------------------------------------------------------
# 接続 & データ取得（キャッシュ）
# ----------------------------------------------------------------------
@st.cache_resource
def _sf():
    return get_sf()


# ボードを開くたびに毎回取得（キャッシュなし）
_REALTIME_KEYS = {"today", "cs_shift", "list_volume", "shinsetsu_today", "shinsetsu_shift", "next_month_shift", "call_history"}
# 5分キャッシュ
_CACHE_5MIN_KEYS = {"1week_cx_check"}
# 10分キャッシュ（10分自動更新するボード用）
_CACHE_10MIN_KEYS = {"orikaeshi_kensu", "day_calls"}
# 2時間キャッシュ
_CACHE_2H_KEYS = {"total_calls", "fc_1week", "sokushin_monthly", "kari_keisan", "kari_keisan_gift_gai", "cx_age_area"}
# 毎日11:00更新（日次キャッシュ）
_CACHE_DAILY_KEYS = {"progress", "daikon_kaitsu"}


def _daily_cache_key() -> str:
    """11:00を境に切り替わるキャッシュキーを返す。"""
    from datetime import datetime, timezone, timedelta
    jst = timezone(timedelta(hours=9))
    now = datetime.now(jst)
    if now.hour < 11:
        return (now - timedelta(days=1)).strftime("%Y-%m-%d")
    return now.strftime("%Y-%m-%d")


@st.cache_data(ttl=300, show_spinner="取得中...")
def _load_5min(metric_key: str) -> pd.DataFrame:
    return get_metric(metric_key).fetch(_sf())


@st.cache_data(ttl=600, show_spinner="取得中...")
def _load_10min(metric_key: str) -> pd.DataFrame:
    return get_metric(metric_key).fetch(_sf())


@st.cache_data(ttl=7200, show_spinner="Salesforce から取得中...")
def _load_2h(metric_key: str) -> pd.DataFrame:
    return get_metric(metric_key).fetch(_sf())


@st.cache_data(ttl=7200, show_spinner="Salesforce から取得中...")
def _load_cx_age_area(start_date: str, end_date: str):
    from metrics import fetch_cx_age_area
    return fetch_cx_age_area(_sf(), start_date=start_date, end_date=end_date)


@st.cache_data(ttl=86400, show_spinner="Salesforce から取得中...")
def _load_daily(metric_key: str, cache_day: str, v: int = 19) -> pd.DataFrame:
    return get_metric(metric_key).fetch(_sf())


@st.cache_data(ttl=86400, show_spinner="開通前対応を集計中...")
def _load_kaitsu_mae_taiou(cache_day: str, v: int = 4):
    # v は集計仕様変更時にキャッシュを無効化するためのバージョン番号
    import kaitsu_mae_taiou as _kmt
    return _kmt.compute(_sf())


@st.cache_data(ttl=86400, show_spinner="工事取得FC資料を集計中...")
def _load_kouji_shutoku_fc(cache_day: str, v: int = 1):
    import kouji_shutoku_fc as _ksf
    return _ksf.compute(_sf())


@st.cache_data(ttl=86400, show_spinner="1次停滞理由を集計中...")
def _load_daikon_riyu_au_sonet(cache_day: str, v: int = 1):
    import daikon_riyu_au_sonet as _drs
    return _drs.compute(_sf())


@st.cache_data(ttl=86400, show_spinner="不備停滞切り捨て判定を集計中...")
def _load_fubitaitai_kirisute(cache_day: str, v: int = 2):
    import fubitaitai_kirisute as _fk
    return _fk.compute(_sf())


@st.cache_data(ttl=86400, show_spinner="不備停滞切り捨て判定(東)を集計中...")
def _load_fubitaitai_kirisute_higashi(cache_day: str, v: int = 2):
    import fubitaitai_kirisute as _fk
    return _fk.compute(_sf(), area="東")


@st.cache_data(ttl=86400, show_spinner="不備停滞切り捨て判定(西)を集計中...")
def _load_fubitaitai_kirisute_nishi(cache_day: str, v: int = 2):
    import fubitaitai_kirisute as _fk
    return _fk.compute(_sf(), area="西")


@st.cache_data(ttl=86400, show_spinner="不備停滞切り捨て判定(AUリスト)を集計中...")
def _load_fubitaitai_kirisute_au(cache_day: str, v: int = 2):
    import fubitaitai_kirisute as _fk
    return _fk.compute(_sf(), list_type="AU")


@st.cache_data(ttl=86400, show_spinner="不備停滞切り捨て判定(ドコモリスト)を集計中...")
def _load_fubitaitai_kirisute_docomo(cache_day: str, v: int = 2):
    import fubitaitai_kirisute as _fk
    return _fk.compute(_sf(), list_type="docomo")


@st.cache_data(ttl=86400, show_spinner="不備停滞切り捨て判定(SBリスト)を集計中...")
def _load_fubitaitai_kirisute_sb(cache_day: str, v: int = 2):
    import fubitaitai_kirisute as _fk
    return _fk.compute(_sf(), list_type="SB")


def _load(metric_key: str):
    if metric_key in _CACHE_5MIN_KEYS:
        return _load_5min(metric_key)
    if metric_key in _CACHE_10MIN_KEYS:
        return _load_10min(metric_key)
    if metric_key in _CACHE_2H_KEYS:
        return _load_2h(metric_key)
    if metric_key in _CACHE_DAILY_KEYS:
        return _load_daily(metric_key, _daily_cache_key())
    # リアルタイム: 毎回取得
    return get_metric(metric_key).fetch(_sf())


# ----------------------------------------------------------------------
# サイドバー: 指標選択
# ----------------------------------------------------------------------
import base64
with open("gcs_logo.png", "rb") as f:
    _icon_b64 = base64.b64encode(f.read()).decode()
st.sidebar.markdown(
    f'<div style="display:flex;align-items:center;gap:10px;margin-bottom:10px;">'
    f'<img src="data:image/png;base64,{_icon_b64}" width="130">'
    f'<span style="font-size:1.5rem;font-weight:bold;">CS促進</span>'
    f'</div>',
    unsafe_allow_html=True,
)

# カテゴリでグルーピング
# ツール配下の talk_script_* メトリクスは「サイドバーでネスト描画」するため、
# board_order の通常アイテムからは除外する
categories: dict[str, list] = {}
for m in METRICS:
    if m.category == "ツール" and m.key.startswith("talk_script_"):
        continue
    categories.setdefault(m.category, []).append(m)
categories.setdefault("ツール", [])  # 空でも存在を保証

label_to_key = {m.label: m.key for m in METRICS}

# セッションに並び順を保持（Google Sheetsから読み込み、無ければデフォルト）
from ui_order_store import build_initial_board_order, save_order as _save_board_order, clear_order_cache as _clear_order_cache
if "board_order" not in st.session_state:
    st.session_state["board_order"] = build_initial_board_order(METRICS)
else:
    # 再構築判定:
    #  - ツールカテゴリが空 or 存在しない（旧形式）
    #  - METRICS のラベルが追加 / 変更され、board_order に含まれていない
    _bo = st.session_state["board_order"]
    _tool_entry = next((c for c in _bo if c.get("header") == "ツール"), None)
    _bo_labels = {label for entry in _bo for label in entry.get("items", [])}
    _current_labels = {
        m.label for m in METRICS
        if not (m.category == "ツール" and m.key.startswith("talk_script_"))
    }
    _missing_labels = _current_labels - _bo_labels
    if (
        _tool_entry is None
        or not _tool_entry.get("items")
        or _missing_labels
    ):
        # Sheets側の保存値が古いケースに備え、共有キャッシュも一度クリア
        try:
            _clear_order_cache()
        except Exception:
            pass
        del st.session_state["board_order"]
        st.rerun()

# カテゴリ別配色
_CAT_COLORS = {
    "1週間後FC": {"bg": "#4A6FA5", "fg": "#ffffff"},
    "促進":      {"bg": "#2E8B57", "fg": "#ffffff"},
    "ツール":    {"bg": "#D4850A", "fg": "#ffffff"},
    "タイミー":  {"bg": "#FFC107", "fg": "#222222"},
    "SECRET":    {"bg": "#DC2626", "fg": "#ffffff"},
    "資料": {"bg": "#6B46C1", "fg": "#ffffff"},
}

# CS1〜CS7ログイン時は「ツール」カテゴリのみ表示（他カテゴリ・マスタ・SECRET・資料すべて非表示）
_lu_top = st.session_state.get("logged_in_user") or {}
_lu_id_top = (_lu_top.get("id") or "").lower()
_cs_only_view = _lu_id_top in {f"cs{n}" for n in range(1, 8)}

# CS only モードではツールカテゴリを初期展開
if _cs_only_view and not st.session_state.get("_cs_view_initialized"):
    st.session_state["cat_open_ツール"] = True
    st.session_state["_cs_view_initialized"] = True

# サイドバー: TOTAL はそのまま表示、他カテゴリはトグル式
# SECRET / 資料 は「マスタ」ボタンの下に表示するためここではスキップ
for container in st.session_state["board_order"]:
    cat = container["header"]
    if cat in ("SECRET", "資料"):
        continue
    if _cs_only_view and cat != "ツール":
        continue
    if cat == "TOTAL":
        st.sidebar.subheader(cat)
        for label in container["items"]:
            mkey = label_to_key.get(label)
            if mkey and st.sidebar.button(label, key=f"btn_{mkey}", use_container_width=True):
                st.session_state["selected"] = mkey
    else:
        colors = _CAT_COLORS.get(cat, {"bg": "#555", "fg": "#fff"})
        toggle_key = f"cat_open_{cat}"
        if toggle_key not in st.session_state:
            st.session_state[toggle_key] = False
        is_open = st.session_state[toggle_key]
        arrow = "▼" if is_open else "▶"
        css_id = f"cat-{cat}"
        with st.sidebar.container(key=css_id):
            if st.button(f"{arrow}  {cat}", key=f"toggle_{cat}", use_container_width=True):
                if cat == "責任者用" and not st.session_state.get("responsible_auth"):
                    st.session_state["selected"] = "_responsible_auth"
                    st.rerun()
                elif cat == "タイミー" and not st.session_state.get("timee_auth"):
                    st.session_state["selected"] = "_timee_auth"
                    st.rerun()
                elif cat == "SECRET" and not st.session_state.get("secret_auth"):
                    st.session_state["selected"] = "_secret_auth"
                    st.rerun()
                else:
                    st.session_state[toggle_key] = not is_open
                    st.rerun()
        if is_open:
            # ツールは「メンバー → ボード」の2階層ネスト描画
            # メンバー順は board_order の保存済みitemsを使用
            if cat == "ツール":
                from tool_members_store import get_member_assignments, get_all_member_names, is_excluded_member as _tool_excluded
                _all_names = get_all_member_names()
                # CS1〜CS7アカウントでログイン中はCS1〜CS7のみ表示
                _lu_for_tool = st.session_state.get("logged_in_user") or {}
                _lu_id_for_tool = (_lu_for_tool.get("id") or "").lower()
                _cs_only_mode = _lu_id_for_tool in {f"cs{n}" for n in range(1, 8)}
                for _member_name in container["items"]:
                    if _member_name not in _all_names:
                        continue
                    if _tool_excluded(_member_name):
                        continue
                    if _cs_only_mode and not _member_name.startswith("CS"):
                        continue
                    _mem_idx = _all_names.index(_member_name)
                    _mem_assignments = get_member_assignments(_member_name)
                    if not _mem_assignments:
                        continue  # トーク割当なし → 非表示
                    _mem_toggle_key = f"_member_open_{_mem_idx}"
                    if _mem_toggle_key not in st.session_state:
                        st.session_state[_mem_toggle_key] = False
                    _mem_open = st.session_state[_mem_toggle_key]
                    _mem_arrow = "▼" if _mem_open else "▶"
                    if st.sidebar.button(
                        f"　{_mem_arrow} {_member_name}",
                        key=f"toggle_member_{_mem_idx}",
                        use_container_width=True,
                    ):
                        st.session_state[_mem_toggle_key] = not _mem_open
                        st.rerun()
                    if _mem_open:
                        for _suffix, _board_label in TALK_SCRIPT_BOARDS:
                            if _suffix not in _mem_assignments:
                                continue  # 未割当のトークはスキップ
                            _bkey = f"talk_script_{_mem_idx:02d}_{_suffix}"
                            _icon = "📖" if _suffix == "shiryou" else "📋"
                            if st.sidebar.button(
                                f"　　{_icon} {_board_label}",
                                key=f"btn_{_bkey}",
                                use_container_width=True,
                            ):
                                st.session_state["selected"] = _bkey
            else:
                for label in container["items"]:
                    mkey = label_to_key.get(label)
                    if mkey and st.sidebar.button(label, key=f"btn_{mkey}", use_container_width=True):
                        st.session_state["selected"] = mkey
valid_keys = {m.key for m in METRICS} | {"_master", "_responsible_auth", "_timee_auth", "_secret_auth", "_presen_auth"}
_sel = st.session_state.get("selected")
# talk_script_* は動的生成のため、キャッシュ未更新でも有効とみなす
if _sel not in valid_keys and not (_sel and _sel.startswith("talk_script_")):
    st.session_state["selected"] = METRICS[0].key

# CS1〜CS7ログイン時は、ツール以外のボードを開いていたら本人のタイミー工事取得へ強制リダイレクト
if _cs_only_view:
    from tool_members_store import get_all_member_names as _get_all_for_cs
    _all_for_cs = _get_all_for_cs()
    _cs_display = (_lu_top.get("display_name") or "").strip()
    _cs_expected = None
    if _cs_display in _all_for_cs:
        _cs_idx = _all_for_cs.index(_cs_display)
        _cs_expected = f"talk_script_{_cs_idx:02d}_timee_kouji"
    _curr_sel = st.session_state.get("selected") or ""
    _is_own_board = bool(_cs_expected) and _curr_sel == _cs_expected
    if not _is_own_board:
        if _cs_expected:
            st.session_state["selected"] = _cs_expected
        # フォールバック: 表示名が不明な場合は METRICS[0] のまま（救済不可）

selected_key = st.session_state["selected"]

if st.sidebar.button("🔄 キャッシュ更新", width="stretch"):
    _load_5min.clear()
    _load_10min.clear()
    _load_2h.clear()
    _load_daily.clear()
    from orikaeshi_check_store import clear_check_cache
    from tool_members_store import clear_members_cache
    from talk_template_store import clear_template_cache
    from talk_script_store import clear_caches as _clear_ts_caches
    from user_auth_store import clear_users_cache as _clear_users_cache
    clear_check_cache()
    clear_members_cache()
    clear_template_cache()
    _clear_ts_caches()
    _clear_users_cache()
    reload_talk_script_metrics()
    # board_order の共有キャッシュもクリア（Sheets 側の最新を強制再読込）
    try:
        _clear_order_cache()
    except Exception:
        pass
    if "board_order" in st.session_state:
        del st.session_state["board_order"]
    st.rerun()

st.sidebar.caption("データは5分間キャッシュされます")

# カテゴリトグルボタンの配色をJSで適用
import streamlit.components.v1 as components
components.html("""
<script>
// 親ドキュメント側の自動翻訳を無効化（components.html内で確実に実行）
try {
    const pdoc = window.parent.document;
    pdoc.documentElement.setAttribute('translate', 'no');
    pdoc.documentElement.setAttribute('lang', 'ja');
    pdoc.documentElement.classList.add('notranslate');
    if (!pdoc.querySelector('meta[name="google"][content="notranslate"]')) {
        const m = pdoc.createElement('meta');
        m.name = 'google';
        m.content = 'notranslate';
        pdoc.head.appendChild(m);
    }
    // 描画後の動的要素にも notranslate を強制付与
    function forceNoTranslate() {
        pdoc.querySelectorAll('body, body *').forEach(el => {
            if (!el.classList.contains('notranslate')) {
                el.classList.add('notranslate');
                el.setAttribute('translate', 'no');
            }
        });
    }
    forceNoTranslate();
    new MutationObserver(forceNoTranslate).observe(pdoc.body, {childList: true, subtree: true});
} catch (e) {}

const colorMap = {
    '1週間後FC': {bg: '#4A6FA5', hover: '#3A5F95'},
    '促進':      {bg: '#2E8B57', hover: '#257A4A'},
    '責任者用':  {bg: '#8B5CF6', hover: '#7C3AED'},
    'ツール':    {bg: '#D4850A', hover: '#B8730A'},
    'タイミー':  {bg: '#E91E63', hover: '#C2185B'},
    'SECRET':    {bg: '#DC2626', hover: '#B91C1C'},
};
function applyCatStyle(btn, c, hovered) {
    // ダークモードCSSの !important に勝つため setProperty(..., 'important') で上書き
    btn.style.setProperty('background', hovered ? c.hover : c.bg, 'important');
    btn.style.setProperty('color', '#fff', 'important');
    btn.style.setProperty('font-weight', '700', 'important');
    btn.style.setProperty('font-size', '1.05rem', 'important');
    btn.style.setProperty('border', 'none', 'important');
    btn.style.setProperty('border-radius', '8px', 'important');
}
function styleCatButtons() {
    const sidebar = window.parent.document.querySelector('[data-testid="stSidebar"]');
    if (!sidebar) return;
    const buttons = sidebar.querySelectorAll('button');
    buttons.forEach(btn => {
        const text = btn.textContent.trim().replace(/^[▶▼]\\s*/, '');
        const c = colorMap[text];
        if (!c) return;
        applyCatStyle(btn, c, false);
        if (btn.dataset.catColored === '1') return;  // ハンドラ重複付与を防止
        btn.dataset.catColored = '1';
        btn.addEventListener('mouseenter', () => applyCatStyle(btn, c, true));
        btn.addEventListener('mouseleave', () => applyCatStyle(btn, c, false));
    });
}
styleCatButtons();
// 描画直後の取り逃しに備え、最初の数秒間はポーリングでも適用
let _styleTicks = 0;
const _styleInterval = setInterval(() => {
    styleCatButtons();
    if (++_styleTicks > 30) clearInterval(_styleInterval);  // 約3秒
}, 100);
const obs = new MutationObserver(styleCatButtons);
obs.observe(window.parent.document.body, {childList: true, subtree: true});

// Streamlitのテーマ検出 → html にクラス付与
// stHeaderの背景色はグラデーション適用外なので安定して検出できる
function detectTheme() {
    const doc = window.parent.document;
    const el = doc.querySelector('[data-testid="stHeader"]');
    if (!el) return;
    const bg = window.getComputedStyle(el).backgroundColor;
    const match = bg.match(/\d+/g);
    if (match) {
        const brightness = (parseInt(match[0]) + parseInt(match[1]) + parseInt(match[2])) / 3;
        if (brightness < 128) {
            doc.documentElement.classList.add('dark-mode');
            doc.documentElement.classList.remove('light-mode');
        } else {
            doc.documentElement.classList.add('light-mode');
            doc.documentElement.classList.remove('dark-mode');
        }
    }
}
detectTheme();
setInterval(detectTheme, 2000);
</script>
""", height=0)

if not _cs_only_view and st.sidebar.button("🔒 マスタ", key="btn_master", width="stretch"):
    st.session_state["selected"] = "_master"

# --- SECRET カテゴリ（マスタの直下、パスワード保護）---
_secret_container = next(
    (c for c in st.session_state["board_order"] if c.get("header") == "SECRET"),
    None,
)
if _secret_container and not _cs_only_view:
    _secret_toggle_key = "cat_open_SECRET"
    if _secret_toggle_key not in st.session_state:
        st.session_state[_secret_toggle_key] = False
    _secret_open = st.session_state[_secret_toggle_key]
    _secret_arrow = "▼" if _secret_open else "▶"
    with st.sidebar.container(key="cat-SECRET"):
        if st.button(f"{_secret_arrow}  SECRET", key="toggle_SECRET", use_container_width=True):
            if not st.session_state.get("secret_auth"):
                st.session_state["selected"] = "_secret_auth"
                st.rerun()
            else:
                st.session_state[_secret_toggle_key] = not _secret_open
                st.rerun()
    if _secret_open and st.session_state.get("secret_auth"):
        for label in _secret_container.get("items", []):
            mkey = label_to_key.get(label)
            if mkey and st.sidebar.button(label, key=f"btn_{mkey}", use_container_width=True):
                st.session_state["selected"] = mkey

# --- 資料カテゴリ（SECRETの直下、パスワード保護）---
_presen_container = next(
    (c for c in st.session_state["board_order"] if c.get("header") == "資料"),
    None,
)
if _presen_container and not _cs_only_view:
    _presen_toggle_key = "cat_open_資料"
    if _presen_toggle_key not in st.session_state:
        st.session_state[_presen_toggle_key] = False
    _presen_open = st.session_state[_presen_toggle_key]
    _presen_arrow = "▼" if _presen_open else "▶"
    with st.sidebar.container(key="cat-資料"):
        if st.button(f"{_presen_arrow}  資料", key="toggle_資料", use_container_width=True):
            if not st.session_state.get("presen_auth"):
                st.session_state["selected"] = "_presen_auth"
                st.rerun()
            else:
                st.session_state[_presen_toggle_key] = not _presen_open
                st.rerun()
    if _presen_open and st.session_state.get("presen_auth"):
        for label in _presen_container.get("items", []):
            mkey = label_to_key.get(label)
            if mkey and st.sidebar.button(label, key=f"btn_{mkey}", use_container_width=True):
                st.session_state["selected"] = mkey


# --- 👤 ログイン情報＋ログアウト（サイドバー最下部）---
st.sidebar.markdown("---")
_current_user = st.session_state.get("logged_in_user") or {}
_current_name = _current_user.get("display_name") or _current_user.get("id") or ""
if _current_name:
    st.sidebar.markdown(
        f'<div style="padding:6px 8px; font-size:0.9rem; color:#1a1a2e;">'
        f'👤 <b>{_current_name}</b></div>',
        unsafe_allow_html=True,
    )
if st.sidebar.button("🚪 ログアウト", key="btn_logout", use_container_width=True):
    for _k in list(st.session_state.keys()):
        del st.session_state[_k]
    st.rerun()


# ----------------------------------------------------------------------
# メイン
# ----------------------------------------------------------------------
if selected_key == "_responsible_auth":
    st.title("🔒 責任者用")
    pw = st.text_input("パスワードを入力してください", type="password", key="responsible_pw")
    if pw:
        if pw == "yoshida":
            st.session_state["responsible_auth"] = True
            st.session_state["cat_open_責任者用"] = True
            st.session_state["selected"] = METRICS[0].key
            st.rerun()
        else:
            st.error("パスワードが違います")
    st.stop()

if selected_key == "_timee_auth":
    st.title("🔒 タイミー")
    pw = st.text_input("パスワードを入力してください", type="password", key="timee_pw")
    if pw:
        if pw == "gift":
            st.session_state["timee_auth"] = True
            st.session_state["cat_open_タイミー"] = True
            st.session_state["selected"] = "timee_management"
            st.rerun()
        else:
            st.error("パスワードが違います")
    st.stop()

if selected_key == "_secret_auth":
    st.title("🔒 SECRET")
    pw = st.text_input("パスワードを入力してください", type="password", key="secret_pw")
    if pw:
        if pw == "pokipoki":
            st.session_state["secret_auth"] = True
            st.session_state["cat_open_SECRET"] = True
            # SECRET 1番上のボードを開く（無ければマスタへ）
            _secret_c = next(
                (c for c in st.session_state["board_order"] if c.get("header") == "SECRET"),
                None,
            )
            _first_label = (_secret_c.get("items") or [None])[0] if _secret_c else None
            _first_key = label_to_key.get(_first_label) if _first_label else None
            st.session_state["selected"] = _first_key or "_master"
            st.rerun()
        else:
            st.error("パスワードが違います")
    st.stop()

if selected_key == "_presen_auth":
    st.title("🔒 資料")
    pw = st.text_input("パスワードを入力してください", type="password", key="presen_pw")
    if pw:
        if pw == "pokipoki":
            st.session_state["presen_auth"] = True
            st.session_state["cat_open_資料"] = True
            # 資料 1番上のボードを開く
            _presen_c = next(
                (c for c in st.session_state["board_order"] if c.get("header") == "資料"),
                None,
            )
            _first_label = (_presen_c.get("items") or [None])[0] if _presen_c else None
            _first_key = label_to_key.get(_first_label) if _first_label else None
            st.session_state["selected"] = _first_key or "_master"
            st.rerun()
        else:
            st.error("パスワードが違います")
    st.stop()

if selected_key == "_master":
    st.title("⚙ マスタ")
    if not st.session_state.get("master_auth"):
        pw = st.text_input("パスワードを入力してください", type="password", key="master_pw")
        if pw:
            if pw == "yoshida":
                st.session_state["master_auth"] = True
                st.rerun()
            else:
                st.error("パスワードが違います")
        st.stop()
    # --- 📋 ボード並び順の変更（トグル方式：sort_itemsはexpander非対応） ---
    if "master_order_open" not in st.session_state:
        st.session_state["master_order_open"] = False
    _order_arrow = "▼" if st.session_state["master_order_open"] else "▶"
    if st.button(f"{_order_arrow}  📋 ボード並び順の変更", key="toggle_master_order", use_container_width=True):
        st.session_state["master_order_open"] = not st.session_state["master_order_open"]
        st.rerun()
    if st.session_state["master_order_open"]:
        st.caption("ドラッグ＆ドロップで並び替えてください。「💾 並び順を保存」で全ユーザーに反映されます。")
        _sig = "_".join(
            f"{c['header']}:{len(c.get('items', []))}"
            for c in st.session_state["board_order"]
        )
        new_order = sort_items(
            st.session_state["board_order"],
            multi_containers=True,
            direction="vertical",
            key=f"board_sort_{_sig}",
        )
        st.session_state["board_order"] = new_order
        if st.button("💾 並び順を保存", key="save_board_order", type="primary"):
            ok, msg = _save_board_order(new_order)
            st.session_state["selected"] = "_master"
            st.toast(msg, icon="✅" if ok else "⚠️")

    st.divider()

    # --- 👥 ユーザー管理（入口ログイン用ID/パスワード） ---
    with st.expander("👥 ユーザー管理（ログインID／パスワード）", expanded=False):
        from user_auth_store import (
            get_users as _ua_get_users,
            add_user as _ua_add_user,
            update_password as _ua_update_password,
            update_display_name as _ua_update_display_name,
            set_active as _ua_set_active,
            delete_user as _ua_delete_user,
            clear_users_cache as _ua_clear_cache,
        )

        st.caption(
            "ボードへのログインに使うID／パスワードを管理します。"
            "「有効」のチェックを外すと、そのユーザーはログイン不可になります（削除しなくても締め出せます）。"
            "変更後は **画面下部の「💾 変更を保存」ボタンを必ず押してください**（自動保存ではありません）。"
        )

        # --- 新規追加 ---
        st.markdown("##### ➕ 新規ユーザーを追加")
        _ua_c1, _ua_c2, _ua_c3, _ua_c4 = st.columns([2, 2, 3, 1])
        _new_uid = _ua_c1.text_input("ID", key="ua_new_id", placeholder="例: y-tanaka")
        _new_upw = _ua_c2.text_input("パスワード", key="ua_new_pw", placeholder="例: tanaka2026")
        _new_uname = _ua_c3.text_input("表示名", key="ua_new_name", placeholder="例: 田中 太郎")
        if _ua_c4.button("追加", key="ua_add_btn", use_container_width=True):
            ok, msg = _ua_add_user(_new_uid, _new_upw, _new_uname)
            st.toast(msg, icon="✅" if ok else "⚠️")
            if ok:
                st.session_state.pop("ua_new_id", None)
                st.session_state.pop("ua_new_pw", None)
                st.session_state.pop("ua_new_name", None)
                st.rerun()

        st.divider()

        # --- 一覧 ---
        st.markdown("##### 📋 登録済みユーザー")
        _users = _ua_get_users()
        if not _users:
            st.info("ユーザーが登録されていません。")
        else:
            _h1, _h2, _h3, _h4, _h5, _h6 = st.columns([2, 2, 3, 1, 2, 1])
            _h1.markdown("**ID**")
            _h2.markdown("**パスワード**")
            _h3.markdown("**表示名**")
            _h4.markdown("**有効**")
            _h5.markdown("**最終ログイン**")
            _h6.markdown("**削除**")

            for _ui, _u in enumerate(_users):
                _uid = _u.get("id", "")
                c1, c2, c3, c4, c5, c6 = st.columns([2, 2, 3, 1, 2, 1])
                with c1:
                    st.text_input(
                        "ID", value=_uid, key=f"ua_id_show_{_ui}",
                        disabled=True, label_visibility="collapsed",
                    )
                with c2:
                    st.text_input(
                        "パスワード", value=_u.get("password", ""),
                        key=f"ua_pw_{_ui}", label_visibility="collapsed",
                    )
                with c3:
                    st.text_input(
                        "表示名", value=_u.get("display_name", ""),
                        key=f"ua_name_{_ui}", label_visibility="collapsed",
                    )
                with c4:
                    st.checkbox(
                        "有効", value=_u.get("active", True),
                        key=f"ua_active_{_ui}", label_visibility="collapsed",
                    )
                with c5:
                    st.markdown(
                        f"<span style='font-size:0.85rem;color:#555;'>{_u.get('last_login') or '—'}</span>",
                        unsafe_allow_html=True,
                    )
                with c6:
                    if st.button("🗑", key=f"ua_del_{_ui}", help=f"{_u.get('display_name', _uid)} を削除"):
                        _me = (st.session_state.get("logged_in_user") or {}).get("id")
                        if _uid == _me:
                            st.toast("自分自身は削除できません", icon="⚠️")
                        else:
                            ok, msg = _ua_delete_user(_uid)
                            st.toast(msg, icon="✅" if ok else "⚠️")
                            if ok:
                                st.rerun()

            # --- 常時表示の保存ボタン ---
            st.markdown("")  # 余白
            _save_col_l, _save_col_c, _save_col_r = st.columns([1, 2, 1])
            if _save_col_c.button(
                "💾 変更を保存",
                key="ua_save_changes",
                type="primary",
                use_container_width=True,
            ):
                _any_fail = False
                _changed_count = 0
                for _ui, _u in enumerate(_users):
                    _uid = _u.get("id", "")
                    _pw_cur = st.session_state.get(f"ua_pw_{_ui}", _u.get("password", ""))
                    _name_cur = st.session_state.get(f"ua_name_{_ui}", _u.get("display_name", ""))
                    _active_cur = st.session_state.get(f"ua_active_{_ui}", _u.get("active", True))
                    if _pw_cur != _u.get("password", ""):
                        ok1, _ = _ua_update_password(_uid, _pw_cur)
                        if not ok1:
                            _any_fail = True
                        else:
                            _changed_count += 1
                    if _name_cur != _u.get("display_name", ""):
                        ok2, _ = _ua_update_display_name(_uid, _name_cur)
                        if not ok2:
                            _any_fail = True
                        else:
                            _changed_count += 1
                    if _active_cur != _u.get("active", True):
                        ok3, _ = _ua_set_active(_uid, _active_cur)
                        if not ok3:
                            _any_fail = True
                        else:
                            _changed_count += 1
                if _changed_count == 0 and not _any_fail:
                    st.toast("変更はありませんでした", icon="ℹ️")
                else:
                    st.toast(
                        f"{_changed_count}件の変更を保存しました" if not _any_fail else "一部保存に失敗しました",
                        icon="✅" if not _any_fail else "⚠️",
                    )
                st.rerun()
            _save_col_c.caption(
                "🔁 保存後はキャッシュが更新され、次回ログインから新しいパスワードが有効になります。"
            )

    st.divider()

    # --- 📝 トーク種類管理 ---
    with st.expander("📝 トーク種類管理", expanded=False):
        from tool_members_store import (
            get_members, save_members, clear_members_cache,
            get_boards, save_boards, next_board_suffix,
        )

        _tool_boards = get_boards()
        st.caption("トーク種類の追加・削除ができます。追加した種類はメンバー割当で選択可能になります。")

        # 追加フォーム
        _bc1, _bc2 = st.columns([4, 1])
        _new_board_label = _bc1.text_input("新しいトーク種類名", key="master_new_board", placeholder="例: 新設FCトーク")
        if _bc2.button("➕ 追加", key="master_add_board", use_container_width=True):
            _new_board_label = _new_board_label.strip()
            if not _new_board_label:
                st.warning("種類名を入力してください。")
            elif any(b["label"] == _new_board_label for b in _tool_boards):
                st.warning("同名のトーク種類が既に存在します。")
            else:
                _new_suffix = next_board_suffix()
                _tool_boards.append({"suffix": _new_suffix, "label": _new_board_label})
                ok, msg = save_boards(_tool_boards)
                reload_talk_script_metrics()
                st.toast(f"「{_new_board_label}」を追加しました（ID: {_new_suffix}）", icon="✅")
                st.rerun()

        # 一覧＋削除
        for _bi, _b in enumerate(_tool_boards):
            _bc_name, _bc_del = st.columns([5, 1])
            _bc_name.markdown(f"**{_b['label']}**　`{_b['suffix']}`")
            if len(_tool_boards) > 1:  # 最低1つは残す
                if _bc_del.button("✕", key=f"del_board_{_bi}", help=f"{_b['label']} を削除"):
                    _removed_suffix = _b["suffix"]
                    _tool_boards.pop(_bi)
                    # メンバーの割当からも除去
                    _members_for_cleanup = get_members()
                    for _m in _members_for_cleanup:
                        if _removed_suffix in _m.get("assignments", []):
                            _m["assignments"].remove(_removed_suffix)
                    from tool_members_store import save_all
                    ok, msg = save_all(_members_for_cleanup, _tool_boards)
                    reload_talk_script_metrics()
                    st.toast(f"「{_b['label']}」を削除しました", icon="✅")
                    st.rerun()

    st.divider()

    # --- 👥 ツールメンバー管理 ---
    with st.expander("👥 ツールメンバー管理", expanded=False):
        from tool_members_store import get_members, save_members, clear_members_cache

        _tool_members = get_members()
        _tool_boards_for_assign = get_boards()

        st.caption("メンバーの追加・削除、トーク割当の変更ができます。変更後は「💾 保存」を押してください。")

        # --- メンバー追加 ---
        _add_col1, _add_col2 = st.columns([4, 1])
        _new_name = _add_col1.text_input("新しいメンバー名", key="master_new_member", placeholder="例: 山田 太郎")
        if _add_col2.button("➕ 追加", key="master_add_member", use_container_width=True):
            _new_name = _new_name.strip()
            if not _new_name:
                st.warning("名前を入力してください。")
            elif any(m["name"] == _new_name and m.get("active", True) for m in _tool_members):
                st.warning("同名のメンバーが既に存在します。")
            else:
                _all_suffixes = [b["suffix"] for b in _tool_boards_for_assign]
                # 非アクティブで同名がいれば再有効化
                _reactivated = False
                for m in _tool_members:
                    if m["name"] == _new_name and not m.get("active", True):
                        m["active"] = True
                        m["assignments"] = _all_suffixes
                        _reactivated = True
                        break
                if not _reactivated:
                    _tool_members.append({
                        "name": _new_name,
                        "assignments": _all_suffixes,
                        "active": True,
                    })
                ok, msg = save_members(_tool_members)
                reload_talk_script_metrics()
                # board_orderにも新メンバーを追加
                for entry in st.session_state.get("board_order", []):
                    if entry.get("header") == "ツール":
                        if _new_name not in entry.get("items", []):
                            entry["items"].append(_new_name)
                            _save_board_order(st.session_state["board_order"])
                st.toast(f"「{_new_name}」を追加しました", icon="✅")
                st.rerun()

        # --- メンバー一覧＋トーク割当＋削除 ---
        _member_changed = False
        for _mi, _m in enumerate(_tool_members):
            if not _m.get("active", True):
                continue
            _n_boards = max(len(_tool_boards_for_assign), 1)
            _c_name, _c_talks, _c_del = st.columns([3, _n_boards * 2, 1])
            _c_name.markdown(f"**{_m['name']}**")

            # トーク割当チェックボックス（動的ボード対応）
            _current_assigns = _m.get("assignments", [])
            _new_assigns = []
            _talk_cols = _c_talks.columns(_n_boards)
            for _ti, _b in enumerate(_tool_boards_for_assign):
                _checked = _talk_cols[_ti].checkbox(
                    _b["label"], value=(_b["suffix"] in _current_assigns),
                    key=f"assign_{_mi}_{_b['suffix']}",
                )
                if _checked:
                    _new_assigns.append(_b["suffix"])
            if sorted(_new_assigns) != sorted(_current_assigns):
                _m["assignments"] = _new_assigns
                _member_changed = True

            # 削除ボタン
            if _c_del.button("✕", key=f"del_member_{_mi}", help=f"{_m['name']} を削除"):
                _m["active"] = False
                _m["assignments"] = []
                ok, msg = save_members(_tool_members)
                reload_talk_script_metrics()
                # board_orderからも除去
                for entry in st.session_state.get("board_order", []):
                    if entry.get("header") == "ツール":
                        items = entry.get("items", [])
                        if _m["name"] in items:
                            items.remove(_m["name"])
                            _save_board_order(st.session_state["board_order"])
                st.toast(f"「{_m['name']}」を削除しました", icon="✅")
                st.rerun()

        # 保存ボタン（トーク割当変更時）
        if st.button("💾 メンバー設定を保存", key="save_tool_members", type="primary"):
            ok, msg = save_members(_tool_members)
            if ok:
                reload_talk_script_metrics()
            st.toast(msg, icon="✅" if ok else "⚠️")

    st.divider()

    with st.expander("🏢 商流別名乗りマスタ", expanded=False):
        st.caption(
            "トーク本文の `{{名乗}}` プレースホルダーを、顧客の「取次商材情報」と「商流」から自動で置き換えます。"
            "新しい取次商材／商流が増えたらここに行を追加してください。"
        )
        from nanori_master_store import (
            get_rows as _nanori_get_rows,
            set_rows as _nanori_set_rows,
            save_master as _nanori_save,
            clear_cache as _nanori_clear_cache,
        )

        _nanori_state_key = "_nanori_rows"
        if _nanori_state_key not in st.session_state:
            st.session_state[_nanori_state_key] = [dict(r) for r in _nanori_get_rows()]

        _rows = st.session_state[_nanori_state_key]

        hc1, hc2, hc3, hc4, hc5 = st.columns([3, 2, 3, 2, 1])
        hc1.markdown("**取次商材情報**")
        hc2.markdown("**商流**")
        hc3.markdown("**名乗り（置換後の文言）**")
        hc4.markdown("**置換トリガー文字列**")
        hc5.markdown("**削除**")

        _nanori_to_delete = []
        for _ri, _row in enumerate(_rows):
            c1, c2, c3, c4, c5 = st.columns([3, 2, 3, 2, 1])
            with c1:
                _row["取次商材情報"] = st.text_input(
                    "商材", value=_row.get("取次商材情報", ""),
                    key=f"nanori_shozai_{_ri}",
                    label_visibility="collapsed",
                    placeholder="例: So-net光_004",
                )
            with c2:
                _row["商流"] = st.text_input(
                    "商流", value=_row.get("商流", ""),
                    key=f"nanori_shoryu_{_ri}",
                    label_visibility="collapsed",
                    placeholder="例: 株式会社WAF",
                )
            with c3:
                _row["名乗り"] = st.text_input(
                    "名乗り", value=_row.get("名乗り", ""),
                    key=f"nanori_nanori_{_ri}",
                    label_visibility="collapsed",
                    placeholder="例: 株式会社WAF",
                )
            with c4:
                _row["トリガー"] = st.text_input(
                    "トリガー", value=_row.get("トリガー", ""),
                    key=f"nanori_trigger_{_ri}",
                    label_visibility="collapsed",
                    placeholder="空欄なら {{名乗}}",
                )
            with c5:
                if st.button("🗑", key=f"nanori_del_{_ri}", help="この行を削除"):
                    _nanori_to_delete.append(_ri)

        if _nanori_to_delete:
            for _ri in sorted(_nanori_to_delete, reverse=True):
                _rows.pop(_ri)
            for _i in range(len(_rows) + len(_nanori_to_delete)):
                for _p in ("nanori_shozai_", "nanori_shoryu_", "nanori_nanori_", "nanori_trigger_"):
                    st.session_state.pop(f"{_p}{_i}", None)
            st.rerun()

        st.markdown("&nbsp;", unsafe_allow_html=True)
        bc1, bc2, bc3 = st.columns([1, 1, 1])
        if bc1.button("➕ 行を追加", key="nanori_add_row", use_container_width=True):
            _rows.append({"取次商材情報": "", "商流": "", "名乗り": "", "トリガー": ""})
            st.rerun()
        if bc2.button("💾 名乗りマスタを保存", key="nanori_save", type="primary", use_container_width=True):
            _nanori_set_rows(_rows)
            ok, msg = _nanori_save()
            st.toast(msg, icon="✅" if ok else "⚠️")
            if ok:
                st.session_state["selected"] = "_master"
                st.rerun()
        if bc3.button("⟳ 再読み込み", key="nanori_reload", use_container_width=True):
            _nanori_clear_cache()
            st.session_state.pop(_nanori_state_key, None)
            st.session_state["selected"] = "_master"
            st.rerun()

    st.divider()

    with st.expander("🔁 置換表", expanded=False):
        st.caption(
            "トーク本文中のトリガー文字列を置換後の文言に一律で差し替えます。"
            "条件なしで全トークに適用されます。"
        )
        from replace_master_store import (
            get_rows as _rep_get_rows,
            set_rows as _rep_set_rows,
            save_master as _rep_save,
            clear_cache as _rep_clear_cache,
        )

        _rep_state_key = "_replace_rows"
        if _rep_state_key not in st.session_state:
            st.session_state[_rep_state_key] = [dict(r) for r in _rep_get_rows()]
        _rep_rows = st.session_state[_rep_state_key]

        rhc1, rhc2, rhc3 = st.columns([3, 3, 1])
        rhc1.markdown("**置換トリガー文字列**")
        rhc2.markdown("**置換後の文言**")
        rhc3.markdown("**削除**")

        _rep_to_delete = []
        for _ri, _row in enumerate(_rep_rows):
            rc1, rc2, rc3 = st.columns([3, 3, 1])
            with rc1:
                _row["トリガー"] = st.text_input(
                    "トリガー", value=_row.get("トリガー", ""),
                    key=f"rep_trigger_{_ri}",
                    label_visibility="collapsed",
                    placeholder="置換前の文字列",
                )
            with rc2:
                _row["置換後"] = st.text_input(
                    "置換後", value=_row.get("置換後", ""),
                    key=f"rep_after_{_ri}",
                    label_visibility="collapsed",
                    placeholder="置換後の文言",
                )
            with rc3:
                if st.button("🗑", key=f"rep_del_{_ri}", help="この行を削除"):
                    _rep_to_delete.append(_ri)

        if _rep_to_delete:
            for _ri in sorted(_rep_to_delete, reverse=True):
                _rep_rows.pop(_ri)
            for _i in range(len(_rep_rows) + len(_rep_to_delete)):
                for _p in ("rep_trigger_", "rep_after_"):
                    st.session_state.pop(f"{_p}{_i}", None)
            st.rerun()

        st.markdown("&nbsp;", unsafe_allow_html=True)
        rbc1, rbc2, rbc3 = st.columns([1, 1, 1])
        if rbc1.button("➕ 行を追加", key="rep_add_row", use_container_width=True):
            _rep_rows.append({"トリガー": "", "置換後": ""})
            st.rerun()
        if rbc2.button("💾 置換表を保存", key="rep_save", type="primary", use_container_width=True):
            _rep_set_rows(_rep_rows)
            ok, msg = _rep_save()
            st.toast(msg, icon="✅" if ok else "⚠️")
            if ok:
                st.session_state["selected"] = "_master"
                st.rerun()
        if rbc3.button("⟳ 再読み込み", key="rep_reload", use_container_width=True):
            _rep_clear_cache()
            st.session_state.pop(_rep_state_key, None)
            st.session_state["selected"] = "_master"
            st.rerun()

    st.divider()

    with st.expander("📞 トークスクリプト編集", expanded=False):
        # 編集するトークスクリプトの種別を動的に生成
        _talk_script_options = ["（選択してください）"] + [b["label"] for b in get_boards()]
        _selected_script = st.selectbox(
            "編集するトークスクリプトを選択",
            _talk_script_options,
            key="master_talk_script_select",
        )

        if _selected_script == "（選択してください）":
            st.info("編集したいトークスクリプトを上のプルダウンから選択してください。")
            st.stop()

        st.caption(f"【{_selected_script}】セクションごとに本文を編集できます。「保存」を押すとGoogle Sheetsに即時保存され、全ユーザーに反映されます。")
        from talk_template_store import (
            get_templates,
            save_templates,
            reset_to_default,
            get_sections_by_kind,
            update_sections,
            get_section_rule,
            update_section_rule,
            SONET_FUBI_KEYS,
            SONET_CLOSING_KEYS,
            SONET_SOKUSHIN_KEYS,
            LINE_TEMPLATE_KEYS,
            clear_template_cache,
            SONET_SOKUSHIN_HIERARCHY,
            SOKUSHIN_DEFAULT_SECTIONS,
            get_sokushin_sections,
            update_sokushin_sections,
            get_sokushin_text,
            update_sokushin_text,
            get_sokushin_section_rule,
            update_sokushin_section_rule,
            get_sokushin_line_templates,
            update_sokushin_line_template,
        )
        from talk_script_store import get_lookup_columns
        _lookup_cols = get_lookup_columns()

        templates = get_templates()
        if _selected_script == "促進用トーク":
            st.markdown(
                '<div style="background:#2E8B57;color:#fff;padding:10px 16px;'
                'border-radius:8px;font-weight:700;margin:8px 0 12px 0;">'
                '🎯 促進用トーク テンプレート（代コン不備解消用）</div>',
                unsafe_allow_html=True,
            )
            st.caption(
                "商材 → カテゴリ → テンプレート を選択して編集してください。"
                "ダイコンステータスに応じて自動で切り替わります。"
            )

            _SK_OP_OPTIONS = {
                "not_empty": "入力済みの時だけ",
                "empty": "空の時だけ",
                "eq": "次の文字列と一致する",
                "ne": "次の文字列と一致しない",
                "contains": "次の文字列を含む",
                "not_contains": "次の文字列を含まない",
                "starts_with": "次の文字列から始まる",
                "lt": "＜（より小さい）",
                "gt": "＞（より大きい）",
                "le": "＝＜（以下）",
                "ge": "＝＞（以上）",
            }
            _SK_OP_KEYS = list(_SK_OP_OPTIONS.keys())
            _SK_OPS_NEED_VALUE = {"eq", "ne", "contains", "not_contains", "starts_with", "lt", "gt", "le", "ge"}

            def _render_sokushin_section_config(tmpl_key: str):
                """セクション構成・表示条件エディタ。
                セッション状態を使わず、キャッシュを真実の源として毎回フレッシュに扱う。
                各操作は即キャッシュ更新 + Sheet保存 + rerun。"""
                _sec_list = list(get_sokushin_sections(tmpl_key))

                def _clear_sec_widget_states(tk: str, max_idx: int):
                    """セクション関連の widget state を全て破棄（並び替え/削除後）"""
                    for _ki in range(max_idx):
                        for _prefix in (
                            f"sk_sec_name_{tk}_",
                            f"sk_sec_rule_mode_{tk}_",
                            f"sk_sec_rule_field_{tk}_",
                            f"sk_sec_rule_value_{tk}_",
                            f"sk_sec_rule_op_{tk}_",
                        ):
                            st.session_state.pop(f"{_prefix}{_ki}", None)

                def _persist_now(new_list):
                    """キャッシュ更新 + Sheetへ即座に保存（throttle無視）。"""
                    import time as _time_p
                    from talk_template_store import (
                        _shared_templates as _st_p,
                        _get_storage_worksheet as _ws_p,
                        _serialize as _ser_p,
                        TEMPLATE_CELL as _cell_p,
                        _last_save as _ls_p,
                    )
                    update_sokushin_sections(tmpl_key, new_list)
                    try:
                        _ws_p().update_acell(_cell_p, _ser_p(_st_p()))
                        _ls_p["t"] = _time_p.time()
                    except Exception:
                        pass  # 失敗してもキャッシュは更新済みなのでUIは継続

                _to_delete: list[int] = []
                _renamed: dict[int, str] = {}

                for si, sn in enumerate(_sec_list):
                    _rule_current = get_sokushin_section_rule(tmpl_key, sn)
                    _cur_field = _rule_current.get("field", "")
                    _cur_op = _rule_current.get("op", "")
                    _has_rule = bool(_cur_field and _cur_op)

                    if _has_rule:
                        _badge_bg, _badge_fg, _badge_text = "#FFF3CD", "#856404", "⚙ 条件付き表示"
                    else:
                        _badge_bg, _badge_fg, _badge_text = "#D4EDDA", "#155724", "✓ 常に表示"

                    st.markdown(
                        f'<div style="background:#fff;border:2px solid #2E8B57;border-radius:10px;'
                        f'padding:14px 16px;margin:12px 0 6px 0;box-shadow:0 1px 3px rgba(0,0,0,0.06);">'
                        f'<div style="display:flex;align-items:center;gap:10px;margin-bottom:8px;">'
                        f'<span style="background:#2E8B57;color:#fff;border-radius:50%;'
                        f'width:28px;height:28px;display:inline-flex;align-items:center;justify-content:center;'
                        f'font-weight:700;font-size:0.9rem;">{si+1}</span>'
                        f'<span style="font-weight:700;font-size:1.05rem;color:#333;">{sn}</span>'
                        f'<span style="background:{_badge_bg};color:{_badge_fg};padding:2px 10px;'
                        f'border-radius:12px;font-size:0.8rem;font-weight:600;margin-left:auto;">'
                        f'{_badge_text}</span>'
                        f'</div></div>',
                        unsafe_allow_html=True,
                    )

                    st.markdown(
                        '<div style="font-size:0.85rem;color:#666;margin:4px 0 2px 0;">セクション名</div>',
                        unsafe_allow_html=True,
                    )
                    cn1, cn2, cn3, cn4 = st.columns([8, 1, 1, 1])
                    with cn1:
                        new_name = st.text_input(
                            f"sk_sec_{si}", value=sn, key=f"sk_sec_name_{tmpl_key}_{si}",
                            label_visibility="collapsed",
                        )
                        if new_name != sn:
                            _renamed[si] = new_name
                    with cn2:
                        if si > 0 and st.button("⬆", key=f"sk_sec_up_{tmpl_key}_{si}", help="上に移動"):
                            _sec_list[si], _sec_list[si - 1] = _sec_list[si - 1], _sec_list[si]
                            _clear_sec_widget_states(tmpl_key, len(_sec_list) + 5)
                            _persist_now(_sec_list)
                            st.rerun()
                    with cn3:
                        if si < len(_sec_list) - 1 and st.button("⬇", key=f"sk_sec_down_{tmpl_key}_{si}", help="下に移動"):
                            _sec_list[si], _sec_list[si + 1] = _sec_list[si + 1], _sec_list[si]
                            _clear_sec_widget_states(tmpl_key, len(_sec_list) + 5)
                            _persist_now(_sec_list)
                            st.rerun()
                    with cn4:
                        if st.button("🗑", key=f"sk_sec_del_{tmpl_key}_{si}", help="削除"):
                            _to_delete.append(si)

                    st.markdown(
                        '<div style="font-size:0.85rem;color:#666;margin:10px 0 2px 0;">表示タイミング</div>',
                        unsafe_allow_html=True,
                    )
                    _mode_options = ["常に表示", "条件付き（顧客情報に応じて自動判定）"]
                    _current_mode = _mode_options[1] if _has_rule else _mode_options[0]
                    _new_mode = st.radio(
                        "表示モード",
                        options=_mode_options,
                        index=_mode_options.index(_current_mode),
                        key=f"sk_sec_rule_mode_{tmpl_key}_{si}",
                        label_visibility="collapsed",
                        horizontal=True,
                    )

                    if _new_mode == _mode_options[1]:
                        _field_options = [""] + _lookup_cols
                        _field_idx = _field_options.index(_cur_field) if _cur_field in _field_options else 0
                        _cur_value = _rule_current.get("value", "")

                        st.markdown(
                            '<div style="font-size:0.8rem;color:#666;margin:8px 0 2px 0;">① 顧客情報の項目</div>',
                            unsafe_allow_html=True,
                        )
                        _new_field = st.selectbox(
                            "判定項目",
                            options=_field_options,
                            format_func=lambda x: "（選択してください）" if x == "" else x,
                            index=_field_idx,
                            key=f"sk_sec_rule_field_{tmpl_key}_{si}",
                            label_visibility="collapsed",
                        )
                        st.markdown(
                            '<div style="font-size:0.8rem;color:#666;margin:8px 0 2px 0;">② 比較する値</div>',
                            unsafe_allow_html=True,
                        )
                        _new_value = st.text_input(
                            "比較値",
                            value=_cur_value,
                            key=f"sk_sec_rule_value_{tmpl_key}_{si}",
                            label_visibility="collapsed",
                            placeholder="例: あり / 2026-01-01 など",
                            disabled=(not _new_field),
                        )
                        st.markdown(
                            '<div style="font-size:0.8rem;color:#666;margin:8px 0 2px 0;">③ 条件</div>',
                            unsafe_allow_html=True,
                        )
                        _op_idx = _SK_OP_KEYS.index(_cur_op) if _cur_op in _SK_OP_KEYS else 0
                        _new_op = st.selectbox(
                            "条件",
                            options=_SK_OP_KEYS,
                            format_func=lambda x: _SK_OP_OPTIONS[x],
                            index=_op_idx,
                            key=f"sk_sec_rule_op_{tmpl_key}_{si}",
                            label_visibility="collapsed",
                            disabled=(not _new_field),
                        )

                        if not _new_field:
                            _new_rule = {}
                        elif _new_op in _SK_OPS_NEED_VALUE and not _new_value:
                            _new_rule = {}
                        elif _new_op in _SK_OPS_NEED_VALUE:
                            _new_rule = {"field": _new_field, "op": _new_op, "value": _new_value}
                        else:
                            _new_rule = {"field": _new_field, "op": _new_op}
                    else:
                        _new_rule = {}

                    st.markdown('<div style="margin-bottom:16px;"></div>', unsafe_allow_html=True)

                    if _new_rule != _rule_current:
                        update_sokushin_section_rule(tmpl_key, sn, _new_rule)

                # 名前変更を反映（Sheet永続化含む）
                if _renamed:
                    for si, newname in _renamed.items():
                        if not newname.strip():
                            continue
                        old = _sec_list[si]
                        _sec_list[si] = newname
                        # テキスト・ルールも引き継ぎ
                        old_text = get_sokushin_text(tmpl_key, old)
                        update_sokushin_text(tmpl_key, newname, old_text)
                        old_rule = get_sokushin_section_rule(tmpl_key, old)
                        if old_rule:
                            update_sokushin_section_rule(tmpl_key, newname, old_rule)
                            update_sokushin_section_rule(tmpl_key, old, {})
                    _persist_now(_sec_list)
                    # rerun で widget keys 再生成
                    _clear_sec_widget_states(tmpl_key, len(_sec_list) + 5)
                    st.rerun()

                if _to_delete:
                    for si in sorted(_to_delete, reverse=True):
                        if 0 <= si < len(_sec_list):
                            _sec_list.pop(si)
                    _clear_sec_widget_states(tmpl_key, len(_sec_list) + len(_to_delete) + 5)
                    _persist_now(_sec_list)
                    st.rerun()

                # セクション追加
                st.markdown("---")
                _add_col1, _add_col2 = st.columns([5, 1])
                _new_sec_name = _add_col1.text_input(
                    "新セクションを追加",
                    key=f"sk_sec_add_input_{tmpl_key}",
                    placeholder="セクション名を入力",
                    label_visibility="collapsed",
                )
                if _add_col2.button("＋追加", key=f"sk_sec_add_btn_{tmpl_key}", use_container_width=True):
                    nm = (_new_sec_name or "").strip()
                    if nm and nm not in _sec_list:
                        _sec_list.append(nm)
                        st.session_state.pop(f"sk_sec_add_input_{tmpl_key}", None)
                        _persist_now(_sec_list)
                        st.rerun()

            def _render_sokushin_text_editor(tmpl_key: str):
                """トーク編集エディタ（各セクションのtext_area）"""
                sections = get_sokushin_sections(tmpl_key)
                if not sections:
                    st.info("セクションが未定義です。「セクション構成・表示条件」タブで追加してください。")
                    return
                for sn in sections:
                    st.markdown(
                        f'<div style="background:#E8F5E9;border-left:4px solid #2E8B57;'
                        f'padding:6px 12px;margin:10px 0 4px 0;border-radius:4px;font-weight:600;color:#1B5E20;">'
                        f'{sn}</div>',
                        unsafe_allow_html=True,
                    )
                    current = get_sokushin_text(tmpl_key, sn)
                    new_val = st.text_area(
                        sn,
                        value=current,
                        height=200,
                        key=f"sk_text_{tmpl_key}_{sn}",
                        label_visibility="collapsed",
                    )
                    if new_val != current:
                        update_sokushin_text(tmpl_key, sn, new_val)

            def _render_sokushin_line_editor(tmpl_key: str):
                """LINEテンプレエディタ（動的ヘッダー: 追加/改名/削除可）"""
                from talk_template_store import (
                    get_sokushin_line_headers,
                    update_sokushin_line_headers,
                )
                headers = get_sokushin_line_headers(tmpl_key)
                _hdr_key = f"_sk_line_hdr_{tmpl_key}"
                st.session_state[_hdr_key] = list(headers)
                _hdr_list = st.session_state[_hdr_key]

                def _clear_line_widget_states(tk: str, max_idx: int):
                    for _ki in range(max_idx):
                        for _prefix in (
                            f"sk_line_hdr_name_{tk}_",
                            f"sk_line_text_{tk}_",
                        ):
                            st.session_state.pop(f"{_prefix}{_ki}", None)

                _line_renamed: dict[int, str] = {}
                _line_to_delete: list[int] = []

                line_map = get_sokushin_line_templates(tmpl_key)

                for li, lk in enumerate(_hdr_list):
                    st.markdown(
                        f'<div style="background:#FFF3E0;border-left:4px solid #E65100;'
                        f'padding:6px 12px;margin:10px 0 4px 0;border-radius:4px;font-weight:600;color:#BF360C;'
                        f'display:flex;align-items:center;gap:8px;">'
                        f'<span style="background:#E65100;color:#fff;border-radius:50%;width:24px;height:24px;'
                        f'display:inline-flex;align-items:center;justify-content:center;font-size:0.85rem;">💬</span>'
                        f'<span style="flex:1;">{lk}</span></div>',
                        unsafe_allow_html=True,
                    )
                    hc1, hc2, hc3, hc4 = st.columns([8, 1, 1, 1])
                    with hc1:
                        _new_hdr = st.text_input(
                            f"line_hdr_{li}",
                            value=lk,
                            key=f"sk_line_hdr_name_{tmpl_key}_{li}",
                            label_visibility="collapsed",
                            placeholder="ヘッダー名",
                        )
                        if _new_hdr != lk:
                            _line_renamed[li] = _new_hdr
                    with hc2:
                        if li > 0 and st.button("⬆", key=f"sk_line_up_{tmpl_key}_{li}", help="上に移動"):
                            _hdr_list[li], _hdr_list[li - 1] = _hdr_list[li - 1], _hdr_list[li]
                            _clear_line_widget_states(tmpl_key, len(_hdr_list) + 5)
                            update_sokushin_line_headers(tmpl_key, _hdr_list)
                            st.rerun()
                    with hc3:
                        if li < len(_hdr_list) - 1 and st.button("⬇", key=f"sk_line_down_{tmpl_key}_{li}", help="下に移動"):
                            _hdr_list[li], _hdr_list[li + 1] = _hdr_list[li + 1], _hdr_list[li]
                            _clear_line_widget_states(tmpl_key, len(_hdr_list) + 5)
                            update_sokushin_line_headers(tmpl_key, _hdr_list)
                            st.rerun()
                    with hc4:
                        if st.button("🗑", key=f"sk_line_del_{tmpl_key}_{li}", help="削除"):
                            _line_to_delete.append(li)

                    current = line_map.get(lk, "")
                    new_val = st.text_area(
                        lk,
                        value=current,
                        height=160,
                        key=f"sk_line_text_{tmpl_key}_{li}",
                        label_visibility="collapsed",
                    )
                    if new_val != current:
                        update_sokushin_line_template(tmpl_key, lk, new_val)

                for li, newname in _line_renamed.items():
                    if not newname.strip():
                        continue
                    old = _hdr_list[li]
                    _hdr_list[li] = newname
                    old_text = line_map.get(old, "")
                    update_sokushin_line_template(tmpl_key, newname, old_text)

                if _line_to_delete:
                    for li in sorted(_line_to_delete, reverse=True):
                        if 0 <= li < len(_hdr_list):
                            _hdr_list.pop(li)
                    _clear_line_widget_states(tmpl_key, len(_hdr_list) + len(_line_to_delete) + 5)
                    update_sokushin_line_headers(tmpl_key, _hdr_list)
                    st.rerun()

                st.markdown("---")
                _add_lc1, _add_lc2 = st.columns([5, 1])
                _new_hdr_name = _add_lc1.text_input(
                    "新しいLINEテンプレを追加",
                    key=f"sk_line_hdr_add_input_{tmpl_key}",
                    placeholder="ヘッダー名を入力（例: 不在LINE）",
                    label_visibility="collapsed",
                )
                if _add_lc2.button("＋追加", key=f"sk_line_hdr_add_btn_{tmpl_key}", use_container_width=True):
                    nm = (_new_hdr_name or "").strip()
                    if nm and nm not in _hdr_list:
                        _hdr_list.append(nm)
                        st.session_state.pop(f"sk_line_hdr_add_input_{tmpl_key}", None)
                        update_sokushin_line_headers(tmpl_key, _hdr_list)
                        st.rerun()

                update_sokushin_line_headers(tmpl_key, _hdr_list)

            # ===== 3段タブ（商材 → カテゴリ → テンプレ） =====
            _product_names = list(SONET_SOKUSHIN_HIERARCHY.keys())
            _product_tabs = st.tabs(_product_names)
            for _p_tab, _product in zip(_product_tabs, _product_names):
                with _p_tab:
                    _cat_names = list(SONET_SOKUSHIN_HIERARCHY[_product].keys())
                    _cat_tabs = st.tabs(_cat_names)
                    for _c_tab, _category in zip(_cat_tabs, _cat_names):
                        with _c_tab:
                            _tmpl_names = SONET_SOKUSHIN_HIERARCHY[_product][_category]
                            _tmpl_tabs = st.tabs([f"🎯 {t}" for t in _tmpl_names])
                            for _t_tab, _tmpl_key in zip(_tmpl_tabs, _tmpl_names):
                                with _t_tab:
                                    _inner = st.tabs([
                                        "📝 セクション構成・表示条件",
                                        "✏️ トーク編集",
                                        "💬 LINEテンプレ",
                                    ])
                                    with _inner[0]:
                                        _render_sokushin_section_config(_tmpl_key)
                                    with _inner[1]:
                                        _render_sokushin_text_editor(_tmpl_key)
                                    with _inner[2]:
                                        _render_sokushin_line_editor(_tmpl_key)

            st.divider()
            col_save_sk, col_reload_sk = st.columns([1, 1])
            if col_save_sk.button(
                "💾 促進用トーク を保存",
                key="talk_save_sokushin_only",
                type="primary",
                use_container_width=True,
            ):
                # 保存サイズを事前チェック（Google Sheets セル上限 50000 chars）
                import json as _json_sk
                _tpl_dump = _json_sk.dumps(get_templates(), ensure_ascii=False)
                _size_kb = len(_tpl_dump.encode("utf-8")) / 1024
                if len(_tpl_dump) > 48000:
                    st.error(
                        f"⚠ 保存データが大きすぎます（{_size_kb:.1f}KB、"
                        f"{len(_tpl_dump)}文字）。Google Sheets セル上限50000文字に近いため、"
                        f"保存できない可能性があります。テンプレの本文を短くしてください。"
                    )
                else:
                    ok, msg = save_templates()
                    st.toast(f"{msg} ({_size_kb:.1f}KB)", icon="✅" if ok else "⚠️")
                    if ok:
                        # キャッシュをクリアして次回アクセス時に Sheet から再読み込み
                        clear_template_cache()
                        st.session_state["selected"] = "_master"
                        st.rerun()
            if col_reload_sk.button(
                "⟳ 再読み込み",
                key="talk_reload_sokushin_only",
                use_container_width=True,
            ):
                clear_template_cache()
                st.session_state["selected"] = "_master"
                st.rerun()
            st.stop()

        _sections_by_kind = get_sections_by_kind()

        talk_kind_tabs = st.tabs(["So-net光", "NURO光"])
        _kind_meta = [
            ("Sonet", "So-net光", "#1976D2"),
            ("NURO", "NURO光", "#7B1FA2"),
        ]
        for tab, (kind, label, color) in zip(talk_kind_tabs, _kind_meta):
            with tab:
                kind_templates = templates.setdefault(kind, {})
                current_sections = list(_sections_by_kind.get(kind, []))

                # サブタブで機能を整理
                sub_tabs = st.tabs([
                    "📝 セクション構成・表示条件",
                    "✏️ テンプレート本文編集",
                    "💬 LINEテンプレ",
                ])

                # ===== サブタブ1: セクション構成・表示条件 =====
                with sub_tabs[0]:
                    st.caption("セクション名の変更・追加・削除・並び替え、表示/非表示条件の設定ができます。変更後は下の「💾 保存」を押してください。")

                    # 並び替え用session_stateキー
                    _sec_order_key = f"_sec_order_{kind}"
                    if _sec_order_key not in st.session_state:
                        st.session_state[_sec_order_key] = list(current_sections)
                    _sec_list = st.session_state[_sec_order_key]

                    # 各セクションの編集行
                    _to_delete = []
                    _renamed = {}
                    _OP_OPTIONS = {
                        "not_empty": "入力済みの時だけ",
                        "empty": "空の時だけ",
                        "eq": "次の文字列と一致する",
                        "ne": "次の文字列と一致しない",
                        "contains": "次の文字列を含む",
                        "not_contains": "次の文字列を含まない",
                        "starts_with": "次の文字列から始まる",
                        "lt": "＜（より小さい）",
                        "gt": "＞（より大きい）",
                        "le": "＝＜（以下）",
                        "ge": "＝＞（以上）",
                    }
                    _OP_KEYS = list(_OP_OPTIONS.keys())
                    # value入力が必要な演算子
                    _OPS_NEED_VALUE = {"eq", "ne", "contains", "not_contains", "starts_with", "lt", "gt", "le", "ge"}
                    for si, sn in enumerate(_sec_list):
                        _rule_current = get_section_rule(kind, sn)
                        _cur_field = _rule_current.get("field", "")
                        _cur_op = _rule_current.get("op", "")
                        _has_rule = bool(_cur_field and _cur_op)

                        # 表示状態バッジ
                        if _has_rule:
                            _badge_bg = "#FFF3CD"
                            _badge_fg = "#856404"
                            _badge_text = f"⚙ 条件付き表示"
                        else:
                            _badge_bg = "#D4EDDA"
                            _badge_fg = "#155724"
                            _badge_text = "✓ 常に表示"

                        # カード枠の開始
                        st.markdown(
                            f'<div style="background:#fff;border:2px solid #8B5CF6;border-radius:10px;'
                            f'padding:14px 16px;margin:12px 0 6px 0;box-shadow:0 1px 3px rgba(0,0,0,0.06);">'
                            f'<div style="display:flex;align-items:center;gap:10px;margin-bottom:8px;">'
                            f'<span style="background:#8B5CF6;color:#fff;border-radius:50%;'
                            f'width:28px;height:28px;display:inline-flex;align-items:center;justify-content:center;'
                            f'font-weight:700;font-size:0.9rem;">{si+1}</span>'
                            f'<span style="font-weight:700;font-size:1.05rem;color:#333;">{sn}</span>'
                            f'<span style="background:{_badge_bg};color:{_badge_fg};padding:2px 10px;'
                            f'border-radius:12px;font-size:0.8rem;font-weight:600;margin-left:auto;">'
                            f'{_badge_text}</span>'
                            f'</div></div>',
                            unsafe_allow_html=True,
                        )

                        # 1行目: セクション名の編集 + 操作ボタン
                        st.markdown(
                            '<div style="font-size:0.85rem;color:#666;margin:4px 0 2px 0;">セクション名</div>',
                            unsafe_allow_html=True,
                        )
                        cn1, cn2, cn3, cn4 = st.columns([8, 1, 1, 1])
                        with cn1:
                            new_name = st.text_input(
                                f"sec_{si}", value=sn, key=f"sec_name_{kind}_{si}",
                                label_visibility="collapsed",
                            )
                            if new_name != sn:
                                _renamed[si] = new_name
                        with cn2:
                            if si > 0 and st.button("⬆", key=f"sec_up_{kind}_{si}", help="上に移動"):
                                _sec_list[si], _sec_list[si - 1] = _sec_list[si - 1], _sec_list[si]
                                # 並び替え後はtext_input session_stateをクリア
                                # （インデックスキーに古い名前が残ってrename誤検知を防ぐ）
                                for _i in range(len(_sec_list)):
                                    st.session_state.pop(f"sec_name_{kind}_{_i}", None)
                                st.rerun()
                        with cn3:
                            if si < len(_sec_list) - 1 and st.button("⬇", key=f"sec_down_{kind}_{si}", help="下に移動"):
                                _sec_list[si], _sec_list[si + 1] = _sec_list[si + 1], _sec_list[si]
                                for _i in range(len(_sec_list)):
                                    st.session_state.pop(f"sec_name_{kind}_{_i}", None)
                                st.rerun()
                        with cn4:
                            if st.button("🗑", key=f"sec_del_{kind}_{si}", help="削除"):
                                _to_delete.append(si)

                        # 2行目: 表示タイミング（ラジオで選択）
                        st.markdown(
                            '<div style="font-size:0.85rem;color:#666;margin:10px 0 2px 0;">表示タイミング</div>',
                            unsafe_allow_html=True,
                        )
                        _mode_options = ["常に表示", "条件付き（顧客情報に応じて自動判定）"]
                        _current_mode = _mode_options[1] if _has_rule else _mode_options[0]
                        _new_mode = st.radio(
                            "表示モード",
                            options=_mode_options,
                            index=_mode_options.index(_current_mode),
                            key=f"sec_rule_mode_{kind}_{si}",
                            label_visibility="collapsed",
                            horizontal=True,
                        )

                        # 条件付きを選んだ場合のみ、フィールド+値+条件の詳細が出現
                        if _new_mode == _mode_options[1]:
                            st.markdown(
                                '<div style="background:#F3E8FF;border-radius:6px;padding:10px 12px;margin-top:6px;">'
                                '<div style="font-size:0.88rem;color:#5B2C6F;margin-bottom:6px;">'
                                '顧客情報の下記項目が条件を満たす時のみ、このセクションを表示します。</div>'
                                '</div>',
                                unsafe_allow_html=True,
                            )
                            _field_options = [""] + _lookup_cols
                            _field_idx = _field_options.index(_cur_field) if _cur_field in _field_options else 0
                            _cur_value = _rule_current.get("value", "")

                            # 1段目: 顧客情報の項目
                            st.markdown(
                                '<div style="font-size:0.8rem;color:#666;margin:8px 0 2px 0;">① 顧客情報の項目</div>',
                                unsafe_allow_html=True,
                            )
                            _new_field = st.selectbox(
                                "判定項目",
                                options=_field_options,
                                format_func=lambda x: "（選択してください）" if x == "" else x,
                                index=_field_idx,
                                key=f"sec_rule_field_{kind}_{si}",
                                label_visibility="collapsed",
                            )

                            # 2段目: 文字列入力（比較する値）
                            st.markdown(
                                '<div style="font-size:0.8rem;color:#666;margin:8px 0 2px 0;">② 比較する値（文字列入力）</div>',
                                unsafe_allow_html=True,
                            )
                            _new_value = st.text_input(
                                "比較値",
                                value=_cur_value,
                                key=f"sec_rule_value_{kind}_{si}",
                                label_visibility="collapsed",
                                placeholder="例: あり / 2026-01-01 / ソネット など（空/入力済みチェックの時は未使用）",
                                disabled=(not _new_field),
                            )

                            # 3段目: 条件
                            st.markdown(
                                '<div style="font-size:0.8rem;color:#666;margin:8px 0 2px 0;">③ 条件</div>',
                                unsafe_allow_html=True,
                            )
                            _op_idx = _OP_KEYS.index(_cur_op) if _cur_op in _OP_KEYS else 0
                            _new_op = st.selectbox(
                                "条件",
                                options=_OP_KEYS,
                                format_func=lambda x: _OP_OPTIONS[x],
                                index=_op_idx,
                                key=f"sec_rule_op_{kind}_{si}",
                                label_visibility="collapsed",
                                disabled=(not _new_field),
                            )

                            # プレビュー文 & ルール確定
                            if not _new_field:
                                st.markdown(
                                    '<div style="background:#FEE2E2;border-left:3px solid #DC2626;'
                                    'padding:6px 10px;margin-top:8px;border-radius:4px;font-size:0.85rem;color:#7F1D1D;">'
                                    '⚠ 「顧客情報の項目」を選択してください</div>',
                                    unsafe_allow_html=True,
                                )
                                _new_rule = {}
                            elif _new_op in _OPS_NEED_VALUE and not _new_value:
                                st.markdown(
                                    '<div style="background:#FEE2E2;border-left:3px solid #DC2626;'
                                    'padding:6px 10px;margin-top:8px;border-radius:4px;font-size:0.85rem;color:#7F1D1D;">'
                                    '⚠ 「比較する値」を入力してください</div>',
                                    unsafe_allow_html=True,
                                )
                                _new_rule = {}
                            else:
                                if _new_op in _OPS_NEED_VALUE:
                                    _preview = f"💡 {_new_field} が「{_new_value}」{_OP_OPTIONS[_new_op]} 時のみ表示"
                                    _new_rule = {"field": _new_field, "op": _new_op, "value": _new_value}
                                else:
                                    _preview = f"💡 {_new_field} が {_OP_OPTIONS[_new_op]} 表示されます"
                                    _new_rule = {"field": _new_field, "op": _new_op}
                                st.markdown(
                                    f'<div style="background:#FFFBEA;border-left:3px solid #F59E0B;'
                                    f'padding:6px 10px;margin-top:8px;border-radius:4px;font-size:0.85rem;color:#78350F;">'
                                    f'{_preview}</div>',
                                    unsafe_allow_html=True,
                                )
                        else:
                            _new_rule = {}

                        st.markdown('<div style="margin-bottom:16px;"></div>', unsafe_allow_html=True)

                        # ルール変更を反映
                        if _new_rule != _rule_current:
                            update_section_rule(kind, sn, _new_rule)

                    # 名前変更を反映
                    for si, new_name in _renamed.items():
                        old_name = _sec_list[si]
                        _sec_list[si] = new_name
                        # テンプレート本文も引き継ぎ
                        if old_name in kind_templates and old_name != new_name:
                            kind_templates[new_name] = kind_templates.pop(old_name)
                        # 表示ルールも引き継ぎ
                        _old_rule = get_section_rule(kind, old_name)
                        if _old_rule and old_name != new_name:
                            update_section_rule(kind, old_name, {})
                            update_section_rule(kind, new_name, _old_rule)

                    # 削除を反映
                    if _to_delete:
                        for di in sorted(_to_delete, reverse=True):
                            _sec_list.pop(di)
                        # 削除後はインデックスがずれるためtext_input session_stateをクリア
                        for _i in range(len(_sec_list) + len(_to_delete)):
                            st.session_state.pop(f"sec_name_{kind}_{_i}", None)
                        st.rerun()

                    # 新規追加
                    ac1, ac2 = st.columns([4, 1])
                    with ac1:
                        _new_sec = st.text_input("新しいセクション名", key=f"sec_new_{kind}", placeholder="例: ヒアリング")
                    with ac2:
                        st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
                        if st.button("＋ 追加", key=f"sec_add_{kind}", use_container_width=True):
                            if _new_sec and _new_sec not in _sec_list:
                                _sec_list.append(_new_sec)
                                # 新規追加後もtext_input session_stateをクリア（念のため）
                                for _i in range(len(_sec_list)):
                                    st.session_state.pop(f"sec_name_{kind}_{_i}", None)
                                st.rerun()

                # ===== サブタブ2: テンプレート本文編集 =====
                with sub_tabs[1]:
                    st.caption("各セクションの本文を編集できます。「💾 保存」で全ユーザーに反映されます。")
                    for sec_name in _sections_by_kind.get(kind, []):
                        # 不備解消(Sonet)は9種テンプレに展開
                        if sec_name == "不備解消" and kind == "Sonet":
                            fubi_templates = templates.setdefault("Sonet_fubi", {})
                            st.markdown(
                                f'<div style="background:{color};color:#fff;padding:8px 14px;'
                                f'border-radius:6px;font-weight:700;margin:18px 0 8px 0;">'
                                f'【不備解消】テンプレート（ダイコンステータス別 9種）</div>',
                                unsafe_allow_html=True,
                            )
                            st.caption("ダイコンステータスから自動選択されます。「工事日調整希望」は「工事取得」に変換されます。")
                            for fkey in SONET_FUBI_KEYS:
                                with st.expander(f"📋 {fkey}", expanded=False):
                                    current = fubi_templates.get(fkey, "")
                                    new_val = st.text_area(
                                        fkey,
                                        value=current,
                                        height=300,
                                        key=f"talk_edit_fubi_{fkey}",
                                        label_visibility="collapsed",
                                    )
                                    if new_val != current:
                                        fubi_templates[fkey] = new_val
                            continue

                        # 締め(Sonet)は2種テンプレに展開
                        if sec_name == "締め" and kind == "Sonet":
                            closing_templates = templates.setdefault("Sonet_closing", {})
                            st.markdown(
                                f'<div style="background:{color};color:#fff;padding:8px 14px;'
                                f'border-radius:6px;font-weight:700;margin:18px 0 8px 0;">'
                                f'【締め】テンプレート（利用回線あり/不明 2種）</div>',
                                unsafe_allow_html=True,
                            )
                            st.caption("お客様の利用回線が「あり」「不明 or 空欄」のどちらかで自動選択されます。")
                            for ckey in SONET_CLOSING_KEYS:
                                with st.expander(f"📋 {ckey}", expanded=False):
                                    current = closing_templates.get(ckey, "")
                                    new_val = st.text_area(
                                        ckey,
                                        value=current,
                                        height=240,
                                        key=f"talk_edit_closing_{ckey}",
                                        label_visibility="collapsed",
                                    )
                                    if new_val != current:
                                        closing_templates[ckey] = new_val
                            continue

                        with st.expander(f"【{sec_name}】", expanded=False):
                            current = kind_templates.get(sec_name, "")
                            new_val = st.text_area(
                                sec_name,
                                value=current,
                                height=240,
                                key=f"talk_edit_{kind}_{sec_name}",
                                label_visibility="collapsed",
                            )
                            if new_val != current:
                                kind_templates[sec_name] = new_val

                # ===== サブタブ3: LINEテンプレ =====
                with sub_tabs[2]:
                    st.caption("完了LINE・留守LINE・留守完了LINEの3種を編集できます。")
                    line_store_key = "Sonet_line" if kind == "Sonet" else "NURO_line"
                    line_store = templates.setdefault(line_store_key, {})
                    st.markdown(
                        f'<div style="background:#06C755;color:#fff;padding:8px 14px;'
                        f'border-radius:6px;font-weight:700;margin:18px 0 8px 0;">'
                        f'💬 LINEテンプレ（3種）</div>',
                        unsafe_allow_html=True,
                    )
                    for lkey in LINE_TEMPLATE_KEYS:
                        with st.expander(f"💬 {lkey}", expanded=False):
                            current = line_store.get(lkey, "")
                            new_val = st.text_area(
                                lkey,
                                value=current,
                                height=240,
                                key=f"talk_edit_line_{kind}_{lkey}",
                                label_visibility="collapsed",
                            )
                            if new_val != current:
                                line_store[lkey] = new_val

                # ===== 共通の保存/再読み込み（タブ外） =====
                st.divider()
                col_save, col_reload = st.columns([1, 1])
                if col_save.button(f"💾 {label} を保存", key=f"talk_save_{kind}", use_container_width=True, type="primary"):
                    # セクション構成の変更（並び替え・追加・削除）もここで確定
                    update_sections(kind, list(_sec_list))
                    st.session_state[_sec_order_key] = list(_sec_list)
                    ok, msg = save_templates()
                    st.toast(msg, icon="✅" if ok else "⚠️")
                    if ok:
                        st.session_state["selected"] = "_master"
                        st.rerun()
                if col_reload.button(f"⟳ 再読み込み", key=f"talk_reload_{kind}", use_container_width=True):
                    clear_template_cache()
                    st.session_state["selected"] = "_master"
                    st.rerun()
    st.stop()

metric = get_metric(selected_key)
# talk_script_NN_xxx の場合はメンバー名 / ボード名 を見出しに反映
_parsed_title = parse_talk_script_key(selected_key)
if _parsed_title:
    _title = f"{_parsed_title[0]} ／ {_parsed_title[1]}"
else:
    _title = metric.label
st.markdown(f'<h1 translate="no">{_title}</h1>', unsafe_allow_html=True)

# 資料ボード（ツール内）: talk_script_NN_shiryou 形式
if selected_key.startswith("talk_script_") and selected_key.endswith("_shiryou"):
    from metrics import fetch_fc_shiryou

    @st.cache_data(ttl=86400, show_spinner="資料を取得中...")
    def _load_shiryou(_cache_day: str):
        return fetch_fc_shiryou(_sf())

    from datetime import datetime, timezone, timedelta as _td
    _jst = timezone(_td(hours=9))
    _now = datetime.now(_jst)
    _shiryou_cache_key = (_now - _td(days=1)).strftime("%Y-%m-%d") if _now.hour < 11 else _now.strftime("%Y-%m-%d")

    fetched = _load_shiryou(_shiryou_cache_key)
    shiryou_data = fetched.get("__shiryou__") if isinstance(fetched, dict) else None
    if not shiryou_data:
        st.warning("資料データの取得に失敗しました。")
        if isinstance(fetched, dict):
            for k, v in fetched.items():
                st.subheader(k)
                st.dataframe(v)
        st.stop()

    sheet2, sheet3 = shiryou_data[0], shiryou_data[1]

    def _esc(t):
        return (t or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    st.markdown("""
    <style>
    .sr-font, .sr-font * { font-family: 'メイリオ', Meiryo, 'Hiragino Sans', sans-serif !important; }
    .sr-title { background: linear-gradient(90deg, #D4850A, #e8a83e); color: #fff; padding: 12px 20px;
        font-weight: bold; font-size: 1.15rem; border-radius: 8px; margin: 24px 0 16px 0; }
    .sr-info { background: #fff8ed; border-left: 4px solid #D4850A; border-radius: 0 8px 8px 0;
        padding: 12px 16px; margin: 8px 0; color: #3a2a0a; white-space: pre-wrap; line-height: 1.7; font-size: 0.88rem; }
    .sr-flow { display: flex; flex-direction: column; align-items: center; gap: 0; margin: 16px 0; }
    .sr-step { background: #fff; border: 2px solid #D4850A; border-radius: 10px; padding: 10px 20px;
        min-width: 280px; max-width: 90%; text-align: center; font-weight: bold; font-size: 0.92rem;
        color: #2a1a00; position: relative; white-space: pre-wrap; line-height: 1.6; }
    .sr-step-num { display: inline-block; background: #D4850A; color: #fff; width: 26px; height: 26px;
        border-radius: 50%; text-align: center; line-height: 26px; font-size: 0.82rem; margin-right: 8px; font-weight: bold; }
    .sr-arrow { color: #D4850A; font-size: 1.4rem; line-height: 1; margin: 2px 0; }
    .sr-branch { display: flex; gap: 12px; margin: 16px 0; flex-wrap: wrap; justify-content: center; }
    .sr-branch-card { flex: 1; min-width: 220px; max-width: 360px; border-radius: 10px; overflow: hidden;
        box-shadow: 0 2px 8px rgba(0,0,0,0.10); }
    .sr-branch-hdr { padding: 8px 14px; font-weight: bold; font-size: 0.9rem; text-align: center; }
    .sr-branch-body { padding: 10px 14px; background: #fff; font-size: 0.82rem; line-height: 1.65;
        white-space: pre-wrap; color: #2a1a0a; }
    .sr-compare { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin: 12px 0; }
    @media (max-width: 768px) { .sr-compare { grid-template-columns: 1fr; } }
    .sr-cmp-card { border-radius: 10px; overflow: hidden; box-shadow: 0 2px 6px rgba(0,0,0,0.08); }
    .sr-cmp-hdr { padding: 8px 14px; font-weight: bold; font-size: 0.9rem; text-align: center; color: #fff; }
    .sr-cmp-hdr-ok { background: linear-gradient(90deg, #27ae60, #2ecc71); }
    .sr-cmp-hdr-ng { background: linear-gradient(90deg, #e67e22, #f39c12); }
    .sr-cmp-body { padding: 10px 14px; background: #fff; font-size: 0.82rem; line-height: 1.65;
        white-space: pre-wrap; color: #2a1a0a; }
    .sr-warn { background: #fef3e2; border: 1px solid #f0c36d; border-radius: 8px; padding: 10px 14px;
        margin: 8px 0; font-size: 0.85rem; color: #7a5a00; line-height: 1.6; white-space: pre-wrap; }
    .sr-warn::before { content: "\\26A0\\FE0F "; }
    .sr-knowledge { background: #eef6ff; border: 1px solid #a3c4e8; border-radius: 8px; padding: 12px 16px;
        margin: 8px 0; font-size: 0.85rem; color: #1a3a5a; line-height: 1.7; white-space: pre-wrap; }
    .sr-cat-hdr { padding: 10px 16px; border-radius: 8px; color: #fff; font-weight: bold;
        font-size: 1rem; margin: 12px 0 8px 0; }
    </style>
    """, unsafe_allow_html=True)

    # シート2: 基本手順
    st.markdown(f'<div class="sr-title sr-font">{_esc(sheet2["title"])}</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="sr-info sr-font"><b>対応範囲:</b> {_esc(sheet2["scope"])}</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="sr-info sr-font"><b>やること:</b> {_esc(sheet2["task"])}</div>', unsafe_allow_html=True)

    st.markdown('<div class="sr-title sr-font" style="font-size:1rem;">確認 → 架電 フロー</div>', unsafe_allow_html=True)
    flow_html = '<div class="sr-flow sr-font">'
    for i, step in enumerate(sheet2["confirm"]):
        flow_html += f'<div class="sr-step"><span class="sr-step-num">{i+1}</span>{_esc(step)}</div>'
        if i < len(sheet2["confirm"]) - 1:
            flow_html += '<div class="sr-arrow">▼</div>'
    flow_html += '</div>'
    st.markdown(flow_html, unsafe_allow_html=True)

    st.markdown('<div class="sr-title sr-font" style="font-size:1rem;">架電後の後処理</div>', unsafe_allow_html=True)
    st.markdown('<div style="text-align:center;font-size:1.3rem;color:#D4850A;margin:4px 0;">▼ 架電結果により分岐 ▼</div>', unsafe_allow_html=True)
    colors = [("#e67e22", "#fef5ed"), ("#d35400", "#fef0e5"), ("#27ae60", "#eafaf1")]
    branch_html = '<div class="sr-branch sr-font">'
    for idx, ac in enumerate(sheet2["after_call"]):
        c_main, c_bg = colors[idx]
        items_html = "\n".join(_esc(it) for it in ac["items"])
        branch_html += (
            f'<div class="sr-branch-card" style="border: 2px solid {c_main};">'
            f'<div class="sr-branch-hdr" style="background:{c_main};color:#fff;">{_esc(ac["label"])}</div>'
            f'<div class="sr-branch-body" style="background:{c_bg};">{items_html}</div>'
            f'</div>'
        )
    branch_html += '</div>'
    st.markdown(branch_html, unsafe_allow_html=True)

    st.markdown('<div class="sr-title sr-font" style="font-size:1rem;">折り返し対応</div>', unsafe_allow_html=True)
    compare_html = '<div class="sr-compare sr-font">'
    for i, cb in enumerate(sheet2["callback"]):
        hdr_cls = "sr-cmp-hdr-ng" if i == 0 else "sr-cmp-hdr-ok"
        items_html = "\n".join(_esc(it) for it in cb["items"])
        compare_html += (
            f'<div class="sr-cmp-card">'
            f'<div class="sr-cmp-hdr {hdr_cls}">{_esc(cb["label"])}</div>'
            f'<div class="sr-cmp-body">{items_html}</div>'
            f'</div>'
        )
    compare_html += '</div>'
    st.markdown(compare_html, unsafe_allow_html=True)

    # シート3: 不備対応手順
    st.markdown(f'<div class="sr-title sr-font">{_esc(sheet3["title"])}</div>', unsafe_allow_html=True)
    tabs = st.tabs([cat["name"] for cat in sheet3["categories"]] + ["豆知識"])
    for tab, cat in zip(tabs[:-1], sheet3["categories"]):
        with tab:
            c = cat["color"]
            st.markdown(
                f'<div class="sr-cat-hdr sr-font" style="background:{c};">{_esc(cat["name"])}</div>'
                f'<div class="sr-info sr-font">{_esc(cat["desc"])}</div>',
                unsafe_allow_html=True,
            )
            if cat.get("steps"):
                st.markdown(f'<div class="sr-cat-hdr sr-font" style="background:{c};font-size:0.92rem;">対応手順</div>', unsafe_allow_html=True)
                fl = '<div class="sr-flow sr-font">'
                for si, s in enumerate(cat["steps"]):
                    fl += f'<div class="sr-step" style="border-color:{c};text-align:left;max-width:100%;"><span class="sr-step-num" style="background:{c};">{si+1}</span>{_esc(s)}</div>'
                    if si < len(cat["steps"]) - 1:
                        fl += f'<div class="sr-arrow" style="color:{c};">▼</div>'
                fl += '</div>'
                st.markdown(fl, unsafe_allow_html=True)
            if cat.get("notes"):
                st.markdown(f'<div class="sr-warn sr-font">{chr(10).join(_esc(n) for n in cat["notes"])}</div>', unsafe_allow_html=True)
            if cat.get("complete") or cat.get("absent"):
                st.markdown(f'<div class="sr-cat-hdr sr-font" style="background:{c};font-size:0.92rem;">架電結果</div>', unsafe_allow_html=True)
                cmp = '<div class="sr-compare sr-font">'
                cmp += (
                    f'<div class="sr-cmp-card"><div class="sr-cmp-hdr sr-cmp-hdr-ok">完了</div>'
                    f'<div class="sr-cmp-body">{chr(10).join(_esc(x) for x in cat.get("complete", []))}</div></div>'
                    f'<div class="sr-cmp-card"><div class="sr-cmp-hdr sr-cmp-hdr-ng">留守</div>'
                    f'<div class="sr-cmp-body">{chr(10).join(_esc(x) for x in cat.get("absent", []))}</div></div>'
                )
                cmp += '</div>'
                st.markdown(cmp, unsafe_allow_html=True)
            if cat.get("flow"):
                st.markdown(f'<div class="sr-cat-hdr sr-font" style="background:{c};font-size:0.92rem;">全体の流れ</div>', unsafe_allow_html=True)
                fl2 = '<div class="sr-flow sr-font">'
                for fi, fs in enumerate(cat["flow"]):
                    fl2 += f'<div class="sr-step" style="border-color:{c};"><span class="sr-step-num" style="background:{c};">{fi+1}</span>{_esc(fs)}</div>'
                    if fi < len(cat["flow"]) - 1:
                        fl2 += f'<div class="sr-arrow" style="color:{c};">▼</div>'
                fl2 += '</div>'
                st.markdown(fl2, unsafe_allow_html=True)
    with tabs[-1]:
        knowledge = sheet3.get("knowledge", [])
        if knowledge:
            st.markdown(f'<div class="sr-knowledge sr-font">{chr(10).join(_esc(k) for k in knowledge)}</div>', unsafe_allow_html=True)
    st.stop()

# トークスクリプト（テスト）: 電話番号で顧客情報引き当て
# selected_key が "talk_script_NN" 形式（メンバー別の独立ボード）
if selected_key.startswith("talk_script_"):
    from talk_script_store import (
        lookup_customer,
        load_talk_script,
        detect_kind,
        normalize_phone,
        clear_caches,
    )

    # メンバー別ユニーク接尾辞 → session_state を独立化
    _board_id = selected_key  # 例: talk_script_00_fc1week
    _parsed = parse_talk_script_key(selected_key)
    _member_name = _parsed[0] if _parsed else ""
    _board_label = _parsed[1] if _parsed else metric.label

    # ボードsuffixからlookup先ワークシートを解決（1週間後FC / 代コン不備 など）
    _key_parts = selected_key.split("_", 3)
    _board_suffix = _key_parts[3] if len(_key_parts) >= 4 else ""
    from talk_script_store import resolve_lookup_sheet
    _lookup_sheet = resolve_lookup_sheet(_board_suffix)

    st.caption(f"電話番号を貼り付けると顧客情報を引き当て、商材に応じたトークスクリプトを表示します。（{_member_name} 専用ボード）")

    col_in, col_btn = st.columns([4, 1])
    with col_in:
        phone_input = st.text_input(
            "電話番号",
            placeholder="例: 080-4200-2238 / 08042002238",
            key=f"talk_phone_{_board_id}",
            label_visibility="collapsed",
        )
    with col_btn:
        if st.button("🔄 データ更新", key=f"talk_refresh_{_board_id}", use_container_width=True):
            clear_caches()
            st.rerun()

    phone_clean = normalize_phone(phone_input)

    if not phone_clean:
        st.info("電話番号を入力してください。")
        st.stop()

    info = lookup_customer(phone_clean, _lookup_sheet)
    _lookup_source = _lookup_sheet
    # タイミー工事取得トーク: 1週間後FC該当案件で見つからなければ So-net光案件 タブにフォールバック
    if info is None and _board_suffix == "timee_kouji":
        from talk_script_store import SONET_KAITSU_LOOKUP_SHEET
        info = lookup_customer(phone_clean, SONET_KAITSU_LOOKUP_SHEET)
        if info is not None:
            _lookup_source = SONET_KAITSU_LOOKUP_SHEET
    if info is None:
        st.warning(f"電話番号 `{phone_clean}` に該当する顧客情報が見つかりません。")
        st.stop()
    # フォールバック発火時は明示する
    if _board_suffix == "timee_kouji" and _lookup_source != _lookup_sheet:
        st.info(f"📋 1週間後FC該当案件に見つからなかったため『{_lookup_source}』タブから取得しました。")

    # --- 商流変更アラート（直前に表示した商流と違えば警告） ---
    _current_shoryu = (info.get("商流（引用）") or "").strip()
    _prev_shoryu = st.session_state.get("_last_shoryu", "")
    if _current_shoryu and _prev_shoryu and _current_shoryu != _prev_shoryu:
        st.markdown(
            f'<div style="background:linear-gradient(90deg,#FF6B6B,#FF8E53);'
            f'color:#fff;padding:14px 20px;border-radius:10px;margin:10px 0 14px 0;'
            f'box-shadow:0 3px 10px rgba(255,107,107,0.4);font-weight:700;font-size:1.05rem;'
            f'border:2px solid #fff;">'
            f'📞 商流が変わったのでZOOM Phoneの発信番号の変更をお願いします。'
            f'<div style="font-size:0.85rem;font-weight:500;margin-top:4px;opacity:0.95;">'
            f'前回: {_prev_shoryu} → 今回: {_current_shoryu}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
        st.toast(
            f"⚠ 商流変更：{_prev_shoryu} → {_current_shoryu} ／ ZOOM Phone発信番号の変更をお願いします",
            icon="📞",
        )
    if _current_shoryu:
        st.session_state["_last_shoryu"] = _current_shoryu

    # --- 顧客情報カード ---
    def _v(key: str) -> str:
        v = info.get(key, "")
        return str(v) if v not in (None, "") else "—"

    # 利用回線別 事業変番号連絡先（既存回線の解約窓口）
    _KAISEN_RENRAKUSAKI = {
        "ソフトバンク光": ("0800-111-2009", "10:00〜19:00（※日曜・祝日・年末年始を除く）"),
        "OCN光":          ("0120-506-506", "10:00〜19:00（※日曜・祝日・年末年始を除く）"),
        "ニフティ光":      ("03-6625-3265", "10:00〜17:00"),
        "BIGLOBE光":      ("0120-86-0962（固定電話のみ）／03-6385-0962（固定以外）", "9:00〜18:00（年中無休）"),
        "T-COM光":        ("0120-805-633", "平日10:00〜20:00／土日祝10:00〜18:00"),
        "楽天光":          ("0120-987-300", "9:00〜18:00"),
        "ドコモ光":        ("ドコモの携帯電話から：151（無料）／一般電話などから：0120-800-000（通話料無料）", "9:00〜18:00"),
    }

    def _build_renrakusaki_html(riyou_kaisen: str, *, standalone: bool = False) -> str:
        """利用回線に応じた事業変番号連絡先HTML。該当なしなら空文字列。
        standalone=True で独立カードとして、False で他カード内に埋め込む装飾。
        """
        r = (riyou_kaisen or "").strip()
        if not r:
            return ""
        if "nifty" in r.lower() or "ニフティ" in r:
            key = "ニフティ光"
        else:
            key = r
        v = _KAISEN_RENRAKUSAKI.get(key)
        if not v:
            return ""
        phone, hours = v
        inner = (
            f'<div style="font-weight:700;color:#D35400;font-size:0.95rem;margin-bottom:4px;">'
            f'📞 事業変番号連絡先（{key}）</div>'
            f'<div style="font-size:0.9rem;color:#222;line-height:1.65;">'
            f'📱 電話番号：{phone}<br>'
            f'🕐 受付時間：{hours}'
            f'</div>'
        )
        if standalone:
            return (
                f'<div style="background:#FFF3E0;border-left:6px solid #E67E22;'
                f'border-radius:8px;padding:14px 20px;margin:8px 0 16px 0;'
                f'box-shadow:0 2px 8px rgba(0,0,0,0.08);">{inner}</div>'
            )
        return (
            f'<div style="margin-top:12px;padding:10px 14px;background:#FFF3E0;'
            f'border-left:4px solid #E67E22;border-radius:6px;">{inner}</div>'
        )

    def _render_url_links_expander() -> None:
        """LINEテンプレの下に表示するURLリンク集（商材に応じて一部切替）。"""
        _url_links = [
            ("📄 PDF", "https://docs.google.com/spreadsheets/d/13vrMrnaJaIbnr2rP1lyVsNvms9_NbsIB4JB97LOCRzs/edit?gid=1416336661#gid=1416336661"),
            ("📊 CXシート", "https://docs.google.com/spreadsheets/d/1sIc_FJ0mXwgbHNAyw9OOhjCLRDmZZi1c5rW_Oe89Gqg/edit?gid=1315622606#gid=1315622606"),
            ("💰 料金表", "https://docs.google.com/spreadsheets/d/1WVKdr46AqugyYgLrqjhBCCorxP7vyw10UDgxN7x2f68/edit?gid=1718294555#gid=1718294555"),
            ("🔧 工事加算額", "https://flets-w.com/price/addition/"),
        ]
        # 商材別リンク（kindは呼び出し時点で確定している前提）
        if kind == "Sonet":
            _url_links.append((
                "⚡ ファストリンク",
                "https://secap.so-net.ne.jp/fast-link/agts/AGTS0000.xhtml",
            ))
        elif kind == "NURO":
            _url_links.append((
                "🚶 WALK",
                "https://nuro.jp/authmanager/menuManage/",
            ))
        with st.expander("🔗 URLリンク", expanded=False):
            _items = "".join(
                f'<a href="{url}" target="_blank" rel="noopener noreferrer" '
                f'style="display:inline-block;padding:8px 14px;background:#E3F2FD;'
                f'border:1px solid #90CAF9;border-radius:6px;color:#1976D2;'
                f'font-weight:600;text-decoration:none;font-size:0.95rem;">{label}</a>'
                for label, url in _url_links
            )
            st.markdown(
                f'<div style="display:flex;flex-wrap:wrap;gap:10px;margin:4px 0;">{_items}</div>',
                unsafe_allow_html=True,
            )

    shozai = _v("取次商材情報")
    kind = detect_kind(shozai)
    kind_label = "NURO光" if kind == "NURO" else "So-net光"
    kind_color = "#7B1FA2" if kind == "NURO" else "#1976D2"

    kessai_raw = info.get("決済登録日（引用）", "")
    kessai_status = "✅ 登録済み" if kessai_raw not in (None, "") else "❌ 未登録"

    # 年齢: 小数点以下切捨て
    _age_raw = info.get("年齢", "")
    try:
        _age_display = str(int(float(_age_raw))) if _age_raw not in (None, "") else "—"
    except (ValueError, TypeError):
        _age_display = str(_age_raw) if _age_raw not in (None, "") else "—"

    # 前確OKコメントから案内料金 / CB案内を抽出（Account ID単位で5分キャッシュ）
    _account_id = (info.get("取引先 ID") or "").strip()
    _zk = {"description": "", "activity_date": "", "found": False}
    _ryokin_display = "—"
    _cb_display = "—"
    if _account_id:
        try:
            from zenkaku_store import get_zenkaku_ok_comment
            _zk = get_zenkaku_ok_comment(_sf(), _account_id)
        except Exception:
            pass
        if _zk["found"]:
            import re as _re
            _desc_raw = _zk["description"]
            _m_r = _re.search(r"案内料金[：:]\s*([0-9,]+\s*円)", _desc_raw)
            if _m_r:
                _ryokin_display = _m_r.group(1).replace(" ", "")
            _m_cb = _re.search(r"CB案内[：:]\s*([^\r\n]+)", _desc_raw)
            if _m_cb:
                _cb_display = _m_cb.group(1).strip()

    st.markdown(
        f"""
        <div style="
            background: rgba(255,255,255,0.85);
            border-left: 6px solid {kind_color};
            border-radius: 8px;
            padding: 16px 20px;
            margin: 12px 0 20px 0;
            box-shadow: 0 2px 8px rgba(0,0,0,0.08);
        ">
        <div style="font-size:1.1rem;font-weight:700;color:{kind_color};margin-bottom:8px;">
            {kind_label}　|　{_v("申込者氏名")}（{_v("申込者氏名（フリガナ）")}）
        </div>
        <table style="width:100%;border-collapse:collapse;font-size:0.95rem;color:#222;">
            <tr>
                <td style="padding:4px 8px;width:25%;color:#666;">エントリ日</td>
                <td style="padding:4px 8px;font-weight:600;">{_v("案件進捗管理: エントリ日")}</td>
                <td style="padding:4px 8px;width:25%;color:#666;">工事予定日</td>
                <td style="padding:4px 8px;font-weight:600;">{_v("工事予定日（引用）")}</td>
            </tr>
            <tr>
                <td style="padding:4px 8px;color:#666;">開通日</td>
                <td style="padding:4px 8px;font-weight:600;">{_v("開通日（引用）")}</td>
                <td style="padding:4px 8px;color:#666;">ST大区分</td>
                <td style="padding:4px 8px;font-weight:600;">{_v("status大区分（引用）")}</td>
            </tr>
            <tr>
                <td style="padding:4px 8px;color:#666;">利用回線</td>
                <td style="padding:4px 8px;font-weight:600;">{_v("利用回線")}</td>
                <td style="padding:4px 8px;color:#666;">LINE登録(突合)</td>
                <td style="padding:4px 8px;font-weight:600;">{_v("【Lｽﾃｯﾌﾟ】突合完了日（引用）")}</td>
            </tr>
            <tr>
                <td style="padding:4px 8px;color:#666;">決済登録</td>
                <td style="padding:4px 8px;font-weight:600;">{kessai_status}</td>
                <td style="padding:4px 8px;color:#666;">取次商材</td>
                <td style="padding:4px 8px;font-weight:600;">{shozai}</td>
            </tr>
            <tr>
                <td style="padding:4px 8px;color:#666;">年齢</td>
                <td style="padding:4px 8px;font-weight:600;">{_age_display}</td>
                <td style="padding:4px 8px;color:#666;">利用携帯＆台数</td>
                <td style="padding:4px 8px;font-weight:600;">{_v("利用携帯＆利用台数")}</td>
            </tr>
            <tr>
                <td style="padding:4px 8px;color:#666;">商流</td>
                <td style="padding:4px 8px;font-weight:600;">{_v("商流（引用）")}</td>
                <td style="padding:4px 8px;color:#666;">エリア</td>
                <td style="padding:4px 8px;font-weight:600;">{_v("エリア（東西）")}</td>
            </tr>
            <tr>
                <td style="padding:4px 8px;color:#666;">郵便番号</td>
                <td style="padding:4px 8px;font-weight:600;">{_v("郵便番号(設置先)")}</td>
                <td style="padding:4px 8px;color:#666;">ダイコンST</td>
                <td style="padding:4px 8px;font-weight:600;">{_v("ダイコンステータス")}</td>
            </tr>
            <tr>
                <td style="padding:4px 8px;color:#666;">住所</td>
                <td colspan="3" style="padding:4px 8px;font-weight:600;">{_v("住所結合")}</td>
            </tr>
            <tr>
                <td style="padding:4px 8px;color:#666;">案内料金</td>
                <td style="padding:4px 8px;font-weight:600;">{_ryokin_display}</td>
                <td style="padding:4px 8px;color:#666;">CB案内</td>
                <td style="padding:4px 8px;font-weight:600;">{_cb_display}</td>
            </tr>
        </table>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # タイミー工事取得トーク: 顧客カードのエントリ日で本文タブを切替（前確OK/LINE/URL/本文テンプレは全部スキップ）
    if _board_suffix == "timee_kouji":
        import html as _html_tk
        from datetime import date as _date_tk, datetime as _dt_tk
        from talk_script_store import load_timee_kouji_script, TIMEE_KOUJI_TABS
        from nanori_master_store import apply_nanori_substitution as _apply_nanori_tk
        from replace_master_store import apply_replace_substitution as _apply_replace_tk

        # エントリ日のパース（YYYY/MM/DD or YYYY-MM-DD or YYYY/M/D 等）
        _entry_raw = (info.get("案件進捗管理: エントリ日") or "").strip()
        _entry_date = None
        for _fmt in ("%Y/%m/%d", "%Y-%m-%d", "%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
            try:
                _entry_date = _dt_tk.strptime(_entry_raw, _fmt).date()
                break
            except (ValueError, TypeError):
                continue

        if _entry_date is None:
            st.warning(f"エントリ日のパースに失敗しました（値: `{_entry_raw}`）。ET+7-10 タブで表示します。")
            _elapsed_days = 0
            _tab_label = TIMEE_KOUJI_TABS["et7_10"]
            _tab_key = "et7_10"
        else:
            _today_tk = _date_tk.today()
            _elapsed_days = (_today_tk - _entry_date).days
            if _elapsed_days <= 10:
                _tab_label = TIMEE_KOUJI_TABS["et7_10"]
                _tab_key = "et7_10"
            else:
                _tab_label = TIMEE_KOUJI_TABS["et11"]
                _tab_key = "et11"

        # エントリ日経過バッジ
        _badge_color = "#1976D2" if _tab_key == "et7_10" else "#C62828"
        st.markdown(
            f'<div style="background:{_badge_color};color:#fff;display:inline-block;'
            f'padding:6px 14px;border-radius:6px;font-weight:700;margin:8px 0 4px 0;">'
            f'📅 エントリ日経過 {_elapsed_days}日 → 「{_tab_label}」を使用</div>',
            unsafe_allow_html=True,
        )

        st.subheader(f"📞 タイミー工事取得トーク　|　{_tab_label}")

        try:
            _sections_tk = load_timee_kouji_script(_tab_label)
        except Exception as _e_tk:
            st.error(f"トークスクリプトの読み込みに失敗しました: {_e_tk}")
            st.stop()

        if not _sections_tk:
            st.info(f"「{_tab_label}」タブに本文が見つかりませんでした。")
            st.stop()

        # 決済登録済みなら【決済未登録】セクションは非表示
        _kessai_done = bool((info.get("決済登録日（引用）") or "").strip())

        for _sec in _sections_tk:
            _sec_name = _sec["section"]
            _body = _sec["body"]
            if _kessai_done and "決済未登録" in _sec_name:
                continue
            if not _body:
                # 見出しのみの行も表示する
                st.markdown(
                    f'<div style="background:#E3F2FD;border-left:4px solid #1976D2;'
                    f'padding:6px 12px;margin:12px 0 4px 0;border-radius:4px;'
                    f'font-weight:600;color:#0D47A1;">{_sec_name}</div>',
                    unsafe_allow_html=True,
                )
                continue
            _body = _apply_nanori_tk(_body, info)
            _body = _apply_replace_tk(_body)
            _safe_tk = _html_tk.escape(_body).replace("\n", "<br>").replace(" ", "&nbsp;")
            st.markdown(
                f'<div style="background:#E3F2FD;border-left:4px solid #1976D2;'
                f'padding:6px 12px;margin:12px 0 4px 0;border-radius:4px;'
                f'font-weight:600;color:#0D47A1;">{_sec_name}</div>'
                f'<div style="background:rgba(255,255,255,0.85);border-left:6px solid #1976D2;'
                f'border-radius:6px;padding:14px 20px;font-size:0.95rem;line-height:1.7;color:#1a1a1a;'
                f'box-shadow:0 1px 4px rgba(0,0,0,0.06);white-space:pre-wrap;'
                f"font-family:'Meiryo','メイリオ','Yu Gothic',sans-serif;font-weight:700;"
                f'">{_safe_tk}</div>',
                unsafe_allow_html=True,
            )

        st.stop()

    # 1週間後FCトーク: 顧客カード直下に 事業変番号連絡先 を表示
    if _board_suffix == "fc1week":
        _renrakusaki_fc_html = _build_renrakusaki_html(info.get("利用回線") or "", standalone=True)
        if _renrakusaki_fc_html:
            st.markdown(_renrakusaki_fc_html, unsafe_allow_html=True)

    # 促進用トーク（代コン不備）：ダイコンステータス別の補足カードを表示
    if _board_suffix == "sokushin":
        from talk_template_store import select_sokushin_key as _select_sokushin_key_card
        _daikon_for_card = (info.get("ダイコンステータス") or "").strip()
        _sokushin_key_for_card = _select_sokushin_key_card(_daikon_for_card)
        _supplement_fields: list[tuple[str, str]] = []
        if _sokushin_key_for_card == "工事取得3者間":
            _supplement_fields = [
                ("工事予定日", "工事予定日（引用）"),
                ("工事Ⅰ状況", "工事Ⅰ状況（引用）"),
                ("申込時工事取得状況", "申込時工事取得状況"),
                ("初回取次(API取得工事日)", "初回取次(API取得工事日)"),
                ("工事取得FC回数", "工事取得FC回数"),
                ("API取次対象", "API取次対象"),
                ("代理店コンサル希望", "代理店コンサル希望"),
            ]
        elif _sokushin_key_for_card == "番ポ不備FC":
            _supplement_fields = [
                ("固定申込", "固定申込"),
                ("固定電話1", "固定電話1（引用）"),
                ("おでん案内フラグ", "おでん案内フラグ"),
                ("開通後ホーム電話案内", "開通後ホーム電話案内"),
            ]
        # チェックボックス表示するboolean列
        _checkbox_cols = {"おでん案内フラグ"}

        def _render_supp_value(col: str) -> str:
            if col in _checkbox_cols:
                raw = info.get(col)
                if isinstance(raw, bool):
                    checked = raw
                else:
                    checked = str(raw).strip().lower() in ("true", "1", "yes")
                mark = "☑" if checked else "☐"
                color = "#2E8B57" if checked else "#888"
                return f'<span style="font-size:1.15rem;color:{color};">{mark}</span>'
            return _v(col)

        if _supplement_fields:
            _supp_rows = "".join(
                f'<tr><td style="padding:4px 8px;width:32%;color:#666;">{lbl}</td>'
                f'<td style="padding:4px 8px;font-weight:600;">{_render_supp_value(col)}</td></tr>'
                for lbl, col in _supplement_fields
            )

            _renrakusaki_html = _build_renrakusaki_html(info.get("利用回線") or "", standalone=False)

            st.markdown(
                f'<div style="background:rgba(255,255,255,0.85);border-left:6px solid #2E8B57;'
                f'border-radius:8px;padding:14px 20px;margin:8px 0 16px 0;'
                f'box-shadow:0 2px 8px rgba(0,0,0,0.08);">'
                f'<div style="font-size:1.0rem;font-weight:700;color:#2E8B57;margin-bottom:6px;">'
                f'🎯 促進用 補足情報（{_sokushin_key_for_card}）</div>'
                f'<table style="width:100%;border-collapse:collapse;font-size:0.92rem;color:#222;">'
                f'{_supp_rows}</table>'
                f'{_renrakusaki_html}'
                f'</div>',
                unsafe_allow_html=True,
            )


    # --- 前確OKコメント全文（折りたたみ） ---
    if _zk["found"]:
        with st.expander(f"📋 前確OKコメント全文（{_zk['activity_date']}）", expanded=False):
            st.code(_zk["description"], language=None)

    # 促進用トーク（代コン不備）：ダイコンステータスに応じて5種テンプレから選択表示
    if _board_suffix == "sokushin":
        import html as _html_sk
        from talk_template_store import (
            select_sokushin_key,
            get_sokushin_sections,
            get_sokushin_text,
            get_sokushin_section_rule,
            evaluate_section_rule as _eval_rule_sk,
            get_sokushin_line_templates,
            get_sokushin_line_headers as _get_sk_line_headers,
        )
        from nanori_master_store import apply_nanori_substitution as _apply_nanori_sk
        from replace_master_store import apply_replace_substitution as _apply_replace_sk

        _daikon_val = (info.get("ダイコンステータス") or "").strip()
        _sokushin_key = select_sokushin_key(_daikon_val)

        if not _sokushin_key:
            st.markdown(
                f'<div style="background:#F5F5F5;border-left:6px solid #9E9E9E;'
                f'border-radius:8px;padding:14px 20px;margin:8px 0 16px 0;'
                f'box-shadow:0 2px 8px rgba(0,0,0,0.08);">'
                f'<div style="font-size:1.0rem;font-weight:700;color:#555;">'
                f'📭 現在トークなし</div>'
                f'<div style="font-size:0.88rem;color:#777;margin-top:4px;">'
                f'ダイコンステータス「{_daikon_val or "(空)"}」は促進用トークの対応外です。'
                f'</div></div>',
                unsafe_allow_html=True,
            )
            st.stop()

        # LINEテンプレ（折りたたみ）— 前確OKコメント全文の直下に配置
        _line_map_sk = get_sokushin_line_templates(_sokushin_key)
        _line_headers_sk = _get_sk_line_headers(_sokushin_key)
        if any(_line_map_sk.values()) and _line_headers_sk:
            with st.expander("💬 LINEテンプレ", expanded=False):
                _line_tabs = st.tabs(_line_headers_sk)
                for _tab, _lk in zip(_line_tabs, _line_headers_sk):
                    with _tab:
                        _body_line = _line_map_sk.get(_lk, "")
                        if not _body_line:
                            st.caption("（未入力）")
                            continue
                        _body_line = _apply_nanori_sk(_body_line, info)
                        _body_line = _apply_replace_sk(_body_line)
                        _safe_line = _html_sk.escape(_body_line).replace("\n", "<br>").replace(" ", "&nbsp;")
                        st.markdown(
                            f'<div style="background:#FFF8E1;border-left:4px solid #E65100;'
                            f'border-radius:6px;padding:12px 18px;font-size:0.92rem;line-height:1.65;'
                            f'color:#1a1a1a;white-space:pre-wrap;">{_safe_line}</div>',
                            unsafe_allow_html=True,
                        )

        # URLリンク（折りたたみ）— LINEテンプレの下
        _render_url_links_expander()

        st.subheader(f"🎯 促進用トーク　|　{_sokushin_key}")
        st.caption(f"ダイコンステータス: **{_daikon_val}** → テンプレ: **{_sokushin_key}**")

        _sections_sk = get_sokushin_sections(_sokushin_key)
        if not _sections_sk:
            st.info(f"「{_sokushin_key}」のセクションが未定義です。マスタ画面で構成を設定してください。")
            st.stop()

        # 現回線SB / 現回線AU系 セクションの表示判定（利用回線→利用携帯の優先順）
        _SB_SECTION_NAME = "現回線SB\u3000おうちの電話"
        _AU_SECTION_NAME = "現回線AU系\u3000ホームプラス電話"
        _AU_KAISEN = {"BIGLOBE光", "T-COM光", "auひかり", "ソネット光", "ニフティ光"}
        _SB_KAISEN = {"ソフトバンク光"}
        _SB_MOBILE_KW = ["softbank", "ソフトバンク", "y!mobile", "ワイモバイル"]
        _AU_MOBILE_KW = ["kddi", "uq", "povo", "au"]
        _riyou_kaisen_raw = (info.get("利用回線") or "").strip()
        _riyou_mobile_lower = (info.get("利用携帯＆利用台数") or "").strip().lower()
        _show_sb = False
        _show_au = False
        if _riyou_kaisen_raw in _AU_KAISEN:
            _show_au = True
        elif _riyou_kaisen_raw in _SB_KAISEN:
            _show_sb = True
        else:
            if any(kw in _riyou_mobile_lower for kw in _SB_MOBILE_KW):
                _show_sb = True
            elif any(kw in _riyou_mobile_lower for kw in _AU_MOBILE_KW):
                _show_au = True

        _rendered_any = False
        for _sec_name in _sections_sk:
            # 現回線SB/AU系は専用ロジック、それ以外は通常のルール評価
            if _sec_name == _SB_SECTION_NAME:
                if not _show_sb:
                    continue
            elif _sec_name == _AU_SECTION_NAME:
                if not _show_au:
                    continue
            else:
                _rule = get_sokushin_section_rule(_sokushin_key, _sec_name)
                if not _eval_rule_sk(_rule, info):
                    continue
            _body = get_sokushin_text(_sokushin_key, _sec_name)
            if not _body:
                continue
            _body = _apply_nanori_sk(_body, info)
            _body = _apply_replace_sk(_body)
            # ○○光 を顧客の利用回線で自動置換
            _riyou_kaisen_sk = (info.get("利用回線") or "").strip()
            if _riyou_kaisen_sk and "○○光" in _body:
                _body = _body.replace("○○光", _riyou_kaisen_sk)
            _safe = _html_sk.escape(_body).replace("\n", "<br>").replace(" ", "&nbsp;")
            st.markdown(
                f'<div style="background:#E8F5E9;border-left:4px solid #2E8B57;'
                f'padding:6px 12px;margin:12px 0 4px 0;border-radius:4px;'
                f'font-weight:600;color:#1B5E20;">【{_sec_name}】</div>'
                f'<div style="background:rgba(255,255,255,0.85);border-left:6px solid #2E8B57;'
                f'border-radius:6px;padding:14px 20px;font-size:0.95rem;line-height:1.7;color:#1a1a1a;'
                f'box-shadow:0 1px 4px rgba(0,0,0,0.06);white-space:pre-wrap;'
                f"font-family:'Meiryo','メイリオ','Yu Gothic',sans-serif;font-weight:700;"
                f'">{_safe}</div>',
                unsafe_allow_html=True,
            )
            _rendered_any = True

        if not _rendered_any:
            st.info(
                f"「{_sokushin_key}」の表示対象セクションがありません。"
                "マスタ画面でセクション本文・表示条件を確認してください。"
            )

        st.stop()

    # --- LINEテンプレ（折りたたみ） ---
    import html as _html
    from talk_template_store import get_templates as _get_tpl_for_line, LINE_TEMPLATE_KEYS
    _all_templates_for_line = _get_tpl_for_line()
    _line_store_key = "Sonet_line" if kind == "Sonet" else "NURO_line"
    line_templates = _all_templates_for_line.get(_line_store_key, {})
    if any(line_templates.values()):
        with st.expander("💬 LINEテンプレ", expanded=False):
            line_tabs = st.tabs(LINE_TEMPLATE_KEYS)
            from replace_master_store import apply_replace_substitution as _apply_replace_line
            from nanori_master_store import apply_nanori_substitution as _apply_nanori_line
            for tab, lkey in zip(line_tabs, LINE_TEMPLATE_KEYS):
                with tab:
                    body = line_templates.get(lkey, "")
                    if not body:
                        st.info("（テンプレなし）")
                        continue
                    # 名乗り＋置換表を適用（トーク本文と同じ扱い）
                    body = _apply_nanori_line(body, info)
                    body = _apply_replace_line(body)
                    safe = _html.escape(body).replace("\n", "<br>").replace(" ", "&nbsp;")
                    st.markdown(
                        f'<div style="background:rgba(255,255,255,0.9);border-left:4px solid #06C755;'
                        f'border-radius:6px;padding:14px 20px;font-size:0.92rem;line-height:1.7;'
                        f'color:#1a1a1a;box-shadow:0 1px 4px rgba(0,0,0,0.06);white-space:pre-wrap;">'
                        f'{safe}</div>',
                        unsafe_allow_html=True,
                    )

    # URLリンク（折りたたみ）— LINEテンプレの下
    _render_url_links_expander()


    # --- トークスクリプト本文（セクション別テンプレ + 動的処理） ---
    from talk_template_store import (
        get_templates,
        get_sections,
        get_section_rule,
        evaluate_section_rule,
        select_fubi_key,
        apply_dynamic_processing,
    )

    st.subheader(f"📞 トークスクリプト（{kind_label}）")
    templates = get_templates()
    sections = get_sections(kind)
    kind_templates = templates.get(kind, {})

    # Sonetの場合、不備解消セクションは9種テンプレから動的選択
    fubi_key_selected = None
    closing_key_selected = None
    if kind == "Sonet":
        fubi_key_selected = select_fubi_key(
            info.get("ダイコンステータス", ""),
            info.get("工事予定日（引用）", ""),
        )
        # 締め: 利用回線の有無で2種から選択
        _kaisen_val = (info.get("利用回線") or "").strip()
        closing_key_selected = "利用回線あり" if (_kaisen_val and _kaisen_val != "不明") else "利用回線不明"

    def _render_section_body(body: str) -> str:
        """セクション本文を行単位でHTML化（見出し/注釈をスタイリング）。"""
        if not body:
            return '<div style="color:#999;font-style:italic;">（空のセクション）</div>'
        out = []
        for raw in body.split("\n"):
            text = raw.rstrip()
            if not text.strip():
                out.append('<div style="height:8px;"></div>')
                continue
            safe = _html.escape(text).replace(" ", "&nbsp;")
            stripped = text.strip()
            if stripped.startswith("■") or stripped.startswith("★") or stripped.startswith("・"):
                out.append(
                    f'<div style="font-weight:700;color:{kind_color};margin:6px 0 2px 0;">{safe}</div>'
                )
            elif stripped.startswith("※") or stripped.startswith("→"):
                out.append(
                    f'<div style="color:#888;font-size:0.85rem;margin-left:8px;">{safe}</div>'
                )
            else:
                out.append(f'<div>{safe}</div>')
        return "".join(out)

    for sec_name in sections:
        # マスタで設定した引用情報ベースの表示ルールを評価
        _rule = get_section_rule(kind, sec_name)
        if not evaluate_section_rule(_rule, info):
            continue

        # 不備解消セクションは動的に9種から選択（Sonetのみ）
        if sec_name == "不備解消" and kind == "Sonet":
            fubi_templates = templates.get("Sonet_fubi", {})
            body = fubi_templates.get(fubi_key_selected, "")
            section_label = f"【不備解消】　🎯 {fubi_key_selected}"
        # 締めセクションは利用回線の有無で2種から選択（Sonetのみ）
        elif sec_name == "締め" and kind == "Sonet":
            closing_templates = templates.get("Sonet_closing", {})
            body = closing_templates.get(closing_key_selected, "")
            section_label = f"【締め】　🎯 {closing_key_selected}"
        else:
            body = kind_templates.get(sec_name, "")
            section_label = f"【{sec_name}】"

        # Sonet の動的処理を適用
        if kind == "Sonet":
            body = apply_dynamic_processing(body, info)

        # 商流別名乗りの差し込み（{{名乗}} → 取次商材情報＋商流で解決）
        from nanori_master_store import apply_nanori_substitution as _apply_nanori
        body = _apply_nanori(body, info)

        # 汎用置換表の適用（条件なし一律置換）
        from replace_master_store import apply_replace_substitution as _apply_replace
        body = _apply_replace(body)

        st.markdown(
            f'<div style="background:{kind_color};color:#fff;padding:8px 14px;'
            f'border-radius:6px;font-weight:700;margin:18px 0 6px 0;font-size:1.05rem;">'
            f'{section_label}</div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            f'<div style="background:rgba(255,255,255,0.85);border-radius:6px;'
            f'padding:14px 20px;font-size:0.95rem;line-height:1.7;color:#1a1a1a;'
            f'box-shadow:0 1px 4px rgba(0,0,0,0.06);'
            f"font-family:'Meiryo','メイリオ','Yu Gothic',sans-serif;font-weight:700;"
            f'">{_render_section_body(body)}</div>',
            unsafe_allow_html=True,
        )

    st.stop()

# 育成KPI: カテゴリ→メンバータブ表示
if selected_key == "ikusei_kpi":
    store = get_store()

    # セッション用に共有ストアからコピー（sort_itemsはセッション経由で操作）
    if "ikusei_order" not in st.session_state:
        st.session_state["ikusei_order"] = store["order"]

    # メンバーをドラッグ&ドロップで配置
    if "ikusei_edit" not in st.session_state:
        st.session_state["ikusei_edit"] = False
    if st.button("メンバー配置を変更" if not st.session_state["ikusei_edit"] else "配置を閉じる"):
        st.session_state["ikusei_edit"] = not st.session_state["ikusei_edit"]
        st.rerun()
    if st.session_state["ikusei_edit"]:
        new_order = sort_items(
            st.session_state["ikusei_order"],
            multi_containers=True,
            direction="vertical",
        )
        st.session_state["ikusei_order"] = new_order
        store["order"] = new_order

        with st.expander("担当者を削除"):
            for group in store["order"]:
                for member in group["items"]:
                    col1, col2 = st.columns([4, 1])
                    col1.write(f"{group['header']} ▸ {member}")
                    m_key = member.replace(" ", "").replace("\u3000", "")
                    if col2.button("✕", key=f"del_{m_key}"):
                        group["items"].remove(member)
                        st.session_state["ikusei_order"] = store["order"]
                        save_store()
                        st.rerun()

        with st.expander("フェーズ・メモを削除"):
            for group in store["order"]:
                for member in group["items"]:
                    m_key = member.replace(" ", "").replace("\u3000", "")
                    if m_key not in store["tabs"]:
                        continue
                    tabs_info = store["tabs"][m_key]
                    if not tabs_info:
                        continue
                    st.markdown(f"**{member}**")
                    for tab_info in tabs_info:
                        t_label = "フェーズ" if tab_info["type"] == "phase" else "メモ"
                        col1, col2 = st.columns([4, 1])
                        col1.write(f"　{tab_info['name']}（{t_label}）")
                        t_key = tab_info["name"].replace(" ", "")
                        if col2.button("✕", key=f"deltab_{m_key}_{t_key}"):
                            tabs_info.remove(tab_info)
                            save_store()
                            st.rerun()

    # カテゴリ→メンバータブ
    groups = store["order"]
    cat_names = [g["header"] for g in groups] + ["+"]
    all_cat_tabs = st.tabs(cat_names)

    with all_cat_tabs[-1]:
        new_cat = st.text_input("新しいカテゴリ名", key="new_ikusei_cat", placeholder="例: CS入電")
        if st.button("カテゴリを追加", key="add_ikusei_cat") and new_cat:
            existing = [g["header"] for g in store["order"]]
            if new_cat not in existing:
                store["order"].append({"header": new_cat, "items": []})
                st.session_state["ikusei_order"] = store["order"]
                save_store()
                st.rerun()
            else:
                st.warning("同じ名前のカテゴリが既にあります")

    from ikusei_store import is_excluded_member as _ikusei_excluded

    for cat_tab, group in zip(all_cat_tabs[:-1], groups):
        with cat_tab:
            visible_items = [m for m in group["items"] if not _ikusei_excluded(m)]
            member_labels = visible_items + ["+"] if visible_items else ["+"]
            all_member_tabs = st.tabs(member_labels)

            with all_member_tabs[-1]:
                new_member = st.text_input("新しい担当者名", key=f"new_member_{group['header']}", placeholder="例: 山田 太郎")
                if st.button("担当者を追加", key=f"add_member_{group['header']}") and new_member:
                    if new_member not in group["items"]:
                        group["items"].append(new_member)
                        st.session_state["ikusei_order"] = store["order"]
                        save_store()
                        st.rerun()
                    else:
                        st.warning("同じ名前の担当者が既にいます")

            for m_tab, member in zip(all_member_tabs[:-1], visible_items):
                    with m_tab:
                        import numpy as np
                        from datetime import datetime, timezone, timedelta

                        member_key = member.replace(" ", "").replace("\u3000", "")

                        # 共有ストアからタブ情報取得/初期化
                        if member_key not in store["tabs"]:
                            store["tabs"][member_key] = [
                                {"name": "フェーズ1", "type": "phase"},
                                {"name": "フェーズ2", "type": "phase"},
                                {"name": "フェーズ3", "type": "phase"},
                            ]

                        tabs_info = store["tabs"][member_key]
                        tab_labels = [t["name"] for t in tabs_info] + ["+"]
                        all_tabs = st.tabs(tab_labels)

                        with all_tabs[-1]:
                            tab_type = st.selectbox("タブの種類", ["フェーズ", "メモ"], key=f"tab_type_{member_key}")
                            new_name = st.text_input("タブ名", key=f"new_tab_{member_key}",
                                placeholder="フェーズ4" if tab_type == "フェーズ" else "メモ1")
                            if st.button("追加", key=f"add_tab_{member_key}") and new_name:
                                existing_names = [t["name"] for t in tabs_info]
                                if new_name not in existing_names:
                                    new_type = "phase" if tab_type == "フェーズ" else "memo"
                                    tabs_info.append({"name": new_name, "type": new_type})
                                    save_store()
                                    st.rerun()
                                else:
                                    st.warning("同じ名前のタブが既にあります")

                        _save_col, _reload_col = st.columns([1, 1])
                        if _save_col.button("💾 保存", key=f"save_{member_key}", use_container_width=True, type="primary"):
                            ok, msg = save_store()
                            st.toast(msg, icon="✅" if ok else "⚠️")
                            if ok:
                                st.rerun()
                        if _reload_col.button("🔄 最新を取得（他PCの編集を反映）", key=f"reload_{member_key}", use_container_width=True):
                            from ikusei_store import reload_store_from_sheet
                            ok, msg = reload_store_from_sheet()
                            st.toast(msg, icon="✅" if ok else "⚠️")
                            if ok:
                                st.rerun()

                        for p_tab, tab_info in zip(all_tabs[:-1], tabs_info):
                            with p_tab:
                                tab_name_key = tab_info["name"].replace(" ", "")
                                tab_type = tab_info["type"]

                                if tab_type == "memo":
                                    memo_key = f"ikusei_memo_{member_key}_{tab_name_key}"
                                    if memo_key not in store["memo"]:
                                        store["memo"][memo_key] = ""
                                    val = st.text_area(
                                        "メモ", value=store["memo"][memo_key],
                                        height=400, key=f"memo_editor_{member_key}_{tab_name_key}",
                                        placeholder="自由にメモを入力...",
                                    )
                                    store["memo"][memo_key] = val
                                else:
                                    # フェーズタブ（AgGrid）
                                    data_key = f"ikusei_data_{member_key}_{tab_name_key}"
                                    if data_key not in store["phase_data"]:
                                        store["phase_data"][data_key] = pd.DataFrame({
                                            "項目": [""] * 20,
                                            "取得したいスキル": [""] * 20,
                                            "進捗": [False] * 20,
                                            "完了日": [""] * 20,
                                            "メモ": [""] * 20,
                                        })

                                    df_ag = store["phase_data"][data_key].copy()
                                    for c in ["項目", "取得したいスキル", "完了日", "メモ"]:
                                        df_ag[c] = df_ag[c].fillna("").astype(str)
                                    df_ag["進捗"] = df_ag["進捗"].astype(bool)

                                    popup_editor = JsCode("""
                                        class PopupTextEditor {
                                            init(params) {
                                                this.params = params;
                                                this.wrapper = document.createElement('div');
                                                this.wrapper.style.cssText = 'background:#fff;border:2px solid #8B5CF6;border-radius:8px;padding:12px;box-shadow:0 4px 20px rgba(0,0,0,0.15);';
                                                this.textarea = document.createElement('textarea');
                                                this.textarea.value = params.value || '';
                                                this.textarea.style.cssText = 'width:350px;height:150px;font-size:14px;font-family:Meiryo,sans-serif;border:1px solid #ddd;border-radius:4px;padding:8px;resize:both;';
                                                this.textarea.addEventListener('keydown', (e) => {
                                                    if (e.key === 'Enter' && !e.shiftKey) { e.stopPropagation(); }
                                                    if (e.key === 'Escape') { params.stopEditing(); }
                                                });
                                                this.btn = document.createElement('button');
                                                this.btn.textContent = '確定';
                                                this.btn.style.cssText = 'display:block;margin-top:8px;padding:6px 20px;background:#8B5CF6;color:#fff;border:none;border-radius:4px;cursor:pointer;font-size:13px;float:right;';
                                                this.btn.addEventListener('click', () => params.stopEditing());
                                                this.wrapper.appendChild(this.textarea);
                                                this.wrapper.appendChild(this.btn);
                                            }
                                            getGui() { return this.wrapper; }
                                            getValue() { return this.textarea.value; }
                                            afterGuiAttached() { this.textarea.focus(); }
                                            isPopup() { return true; }
                                        }
                                    """)

                                    gb = GridOptionsBuilder.from_dataframe(df_ag)
                                    gb.configure_default_column(
                                        editable=True, resizable=True, sortable=False, filter=False,
                                        cellStyle={"textAlign": "center"},
                                    )
                                    _popup_col_style = {"textAlign": "left", "whiteSpace": "pre-wrap", "lineHeight": "1.5",
                                                        "paddingTop": "8px", "paddingBottom": "8px"}
                                    gb.configure_column("項目", editable=True,
                                        cellEditor=popup_editor, cellEditorPopup=True,
                                        wrapText=True, autoHeight=True, flex=2, minWidth=200,
                                        cellStyle=_popup_col_style,
                                    )
                                    gb.configure_column("取得したいスキル", flex=2, minWidth=150,
                                        cellEditor=popup_editor, cellEditorPopup=True,
                                        wrapText=True, autoHeight=True, cellStyle=_popup_col_style,
                                    )
                                    gb.configure_column("進捗", width=60, editable=True,
                                        cellRenderer=JsCode("""
                                            class CheckboxRenderer {
                                                init(params) {
                                                    this.params = params;
                                                    this.eGui = document.createElement('input');
                                                    this.eGui.type = 'checkbox';
                                                    this.eGui.checked = params.value === true;
                                                    this.eGui.style.cursor = 'pointer';
                                                    this.eGui.addEventListener('change', (e) => {
                                                        params.node.setDataValue(params.colDef.field, e.target.checked);
                                                    });
                                                }
                                                getGui() { return this.eGui; }
                                                refresh(params) { this.eGui.checked = params.value === true; return true; }
                                            }
                                        """),
                                    )
                                    gb.configure_column("完了日", width=90, editable=False)
                                    gb.configure_column("メモ", flex=2, minWidth=150,
                                        cellEditor=popup_editor, cellEditorPopup=True,
                                        wrapText=True, autoHeight=True, cellStyle=_popup_col_style,
                                    )

                                    jst = timezone(timedelta(hours=9))
                                    now = datetime.now(jst)
                                    today_js = f"{now.month}/{now.day}"
                                    gb.configure_grid_options(
                                        onCellValueChanged=JsCode(f"""
                                            function(e) {{
                                                if (e.colDef.field === '進捗') {{
                                                    if (e.newValue === true) {{
                                                        e.node.setDataValue('完了日', '{today_js}');
                                                    }} else {{
                                                        e.node.setDataValue('完了日', '');
                                                    }}
                                                }}
                                            }}
                                        """),
                                    )

                                    ag_result = AgGrid(
                                        df_ag,
                                        gridOptions=gb.build(),
                                        height=max(300, 42 + 36 * len(df_ag)),
                                        theme="balham",
                                        allow_unsafe_jscode=True,
                                        custom_css={
                                            ".ag-header-cell": {"background-color": "#8B5CF6", "color": "#fff", "font-weight": "bold", "text-align": "center", "border-right": "1px solid #d0c4f0"},
                                            ".ag-header-cell-label": {"justify-content": "center"},
                                            ".ag-cell": {"border-right": "1px solid #e0dce8"},
                                            ".ag-row-odd": {"background-color": "#ffffff"},
                                            ".ag-row-even": {"background-color": "#f5f3ff"},
                                        },
                                        key=f"ikusei_ag_{member_key}_{tab_name_key}",
                                        update_mode="VALUE_CHANGED",
                                    )
                                    if ag_result and ag_result.data is not None:
                                        store["phase_data"][data_key] = ag_result.data
    st.stop()

# エリア別年代別CX内訳: エントリ日の期間プルダウンで絞り込み（年/月/日セレクタで完全日本語化）
if selected_key == "cx_age_area":
    from datetime import date, timedelta
    import calendar as _cal

    _today = date.today()
    _default_start = _today - timedelta(days=180)
    _year_options = list(range(_today.year - 5, _today.year + 1))

    def _japanese_date_picker(label_prefix: str, default: date, key_prefix: str) -> date:
        """年/月/日の3セレクタで日付入力（完全日本語）。"""
        _y_key = f"{key_prefix}_y"
        _m_key = f"{key_prefix}_m"
        _d_key = f"{key_prefix}_d"
        _y_default = st.session_state.get(_y_key, default.year)
        _m_default = st.session_state.get(_m_key, default.month)
        _d_default = st.session_state.get(_d_key, default.day)
        st.markdown(f"<div style='font-size:0.85rem;color:#666;margin-bottom:2px;'>{label_prefix}</div>", unsafe_allow_html=True)
        cy, cm, cd = st.columns([2, 2, 2])
        with cy:
            y = st.selectbox(
                "年", options=_year_options,
                index=_year_options.index(_y_default) if _y_default in _year_options else len(_year_options) - 1,
                key=_y_key, format_func=lambda v: f"{v}年",
                label_visibility="collapsed",
            )
        with cm:
            m = st.selectbox(
                "月", options=list(range(1, 13)),
                index=_m_default - 1,
                key=_m_key, format_func=lambda v: f"{v}月",
                label_visibility="collapsed",
            )
        with cd:
            _last_day = _cal.monthrange(y, m)[1]
            _d_clamped = min(_d_default, _last_day)
            d = st.selectbox(
                "日", options=list(range(1, _last_day + 1)),
                index=_d_clamped - 1,
                key=_d_key, format_func=lambda v: f"{v}日",
                label_visibility="collapsed",
            )
        return date(y, m, d)

    _col_s, _col_t, _col_e = st.columns([6, 1, 6])
    with _col_s:
        _start = _japanese_date_picker("開始日（エントリ日）", _default_start, "cx_age_start")
    with _col_t:
        st.markdown("<div style='text-align:center;padding-top:32px;font-weight:600;'>〜</div>", unsafe_allow_html=True)
    with _col_e:
        _end = _japanese_date_picker("終了日（エントリ日）", _today, "cx_age_end")

    if _start > _end:
        st.error("開始日が終了日より後になっています。")
        st.stop()
    try:
        fetched = _load_cx_age_area(_start.strftime("%Y-%m-%d"), _end.strftime("%Y-%m-%d"))
    except Exception as e:
        st.error(f"取得に失敗しました: {e}")
        st.stop()
elif selected_key == "call_history":
    # 後の call_history 専用ブロックで期間指定fetchするため、ここではスキップ
    fetched = None
elif selected_key == "1week_cx_check":
    # 後の 1week_cx_check 専用ブロックで表示するため、ここではスキップ
    fetched = None
elif selected_key == "shuchi":
    # 周知ボード（リアルタイム）— 後の専用ブロックで表示
    fetched = None
elif selected_key == "line_template":
    # LINEテンプレ — 後の専用ブロックで表示
    fetched = None
elif selected_key == "timee_management":
    # タイミー管理 — 後の専用ブロックで表示
    fetched = None
elif selected_key == "cs_shift_calendar":
    # シフト表(CS促進全員、月カレンダー) — 後の専用ブロックで表示
    fetched = None
elif selected_key == "kaitsu_mae_taiou":
    # 開通前対応 — 後の専用ブロックで表示
    fetched = None
elif selected_key == "kouji_shutoku_fc":
    # 工事取得FC資料 — 後の専用ブロックで表示
    fetched = None
elif selected_key == "daikon_riyu_au_sonet":
    # ソネット光AU・UQ 1次停滞理由 — 後の専用ブロックで表示
    fetched = None
elif selected_key in ("fubitaitai_kirisute_area", "fubitaitai_kirisute_list"):
    # 不備停滞 切り捨て判定資料 (エリア別/リスト別) — 後の専用ブロックで表示
    fetched = None
elif selected_key == "skill_tree":
    # スキルツリー — 後の専用ブロックで表示
    fetched = None
else:
    try:
        fetched = _load(selected_key)
    except Exception as e:
        st.error(f"取得に失敗しました: {e}")
        st.stop()

# 通話履歴: 期間指定 + フィルター + 電話番号検索
if selected_key == "call_history":
    import re as _re_ch
    from datetime import date as _date_ch

    # 期間・更新・電話番号検索を1行に配置
    _today_ch = _date_ch.today()
    _c_start, _c_end, _c_reload, _c_search = st.columns([2, 2, 1, 4])
    _start_d = _c_start.date_input(
        "開始日", value=_today_ch, key="call_history_start", format="YYYY/MM/DD",
    )
    _end_d = _c_end.date_input(
        "終了日", value=_today_ch, key="call_history_end", format="YYYY/MM/DD",
    )
    _c_reload.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
    if _c_reload.button("🔄 更新", key="call_history_reload", use_container_width=True):
        st.rerun()
    _c_search.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
    phone_q = _c_search.text_input(
        "📞 電話番号で検索",
        key="call_history_phone_search",
        placeholder="例: 080-1234-5678 / 08012345678 / 1234",
        label_visibility="collapsed",
    )

    if _start_d > _end_d:
        st.error("開始日が終了日より後になっています。")
        st.stop()

    # 期間指定でフェッチ
    from metrics import fetch_call_history
    try:
        with st.spinner("取得中..."):
            df_ch = fetch_call_history(
                _sf(),
                start_date=_start_d.strftime("%Y-%m-%d"),
                end_date=_end_d.strftime("%Y-%m-%d"),
            )
    except Exception as e:
        st.error(f"取得に失敗しました: {e}")
        st.stop()
    if phone_q and not df_ch.empty:
        q_digits = _re_ch.sub(r"[^0-9]", "", phone_q)
        if q_digits:
            _phone_digits = df_ch["電話番号"].astype(str).str.replace(r"[^0-9]", "", regex=True)
            df_ch = df_ch[_phone_digits.str.contains(q_digits, na=False)]

    # --- 列値選択フィルター（multiselect） ---
    _filter_cols = [
        "対応日", "担当者", "対応区分", "対応ステータス", "コール結果",
        "依頼種別 変更前", "依頼種別 変更後",
    ]
    with st.expander("🔎 フィルター（列の値から選択 / 複数選択可 / 空欄は絞り込まない）", expanded=False):
        _fc = st.columns(len(_filter_cols))
        for _i, _col in enumerate(_filter_cols):
            if _col not in df_ch.columns:
                continue
            _opts = sorted(v for v in df_ch[_col].dropna().unique().tolist() if str(v) != "")
            _sel = _fc[_i].multiselect(_col, _opts, key=f"ch_filt_{_col}")
            if _sel:
                df_ch = df_ch[df_ch[_col].isin(_sel)]

    st.caption(f"表示件数: {len(df_ch)}件")

    if df_ch.empty:
        st.info("該当データはありません。")
    else:
        df_disp = df_ch.fillna("").astype(str)
        gb = GridOptionsBuilder.from_dataframe(df_disp)
        gb.configure_default_column(
            sortable=True, resizable=True, editable=False,
            type=["textColumn"],
            cellDataType="text",
            cellStyle={"textAlign": "left", "whiteSpace": "pre-wrap", "lineHeight": "1.4"},
        )
        _col_widths = {
            "対応日": 110, "対応日時": 80, "担当者": 110, "電話番号": 130,
            "対応区分": 90, "対応ステータス": 170, "コール結果": 100,
            "通話時間": 90, "依頼種別 変更前": 160, "依頼種別 変更後": 160,
        }
        for col, w in _col_widths.items():
            if col in df_disp.columns:
                gb.configure_column(col, width=w, suppressSizeToFit=True)
        gb.configure_column("コメント", flex=3, minWidth=300, wrapText=True, autoHeight=True,
                            cellStyle={"textAlign": "left", "whiteSpace": "pre-wrap", "lineHeight": "1.5"})
        # セル内テキストを範囲選択してコピーできるように（編集は不可のまま）
        gb.configure_grid_options(enableCellTextSelection=True, ensureDomOrder=True)

        AgGrid(
            df_disp,
            gridOptions=gb.build(),
            height=1200,
            theme="balham",
            allow_unsafe_jscode=True,
            custom_css={
                ".ag-header-cell": {"background-color": "#8B5CF6", "color": "#fff",
                                     "font-weight": "bold", "text-align": "center"},
                ".ag-header-cell-label": {"justify-content": "center"},
                ".ag-row-odd": {"background-color": "#ffffff"},
                ".ag-row-even": {"background-color": "#f3effe"},
            },
            key="aggrid_call_history",
        )
        st.download_button(
            "CSV ダウンロード",
            df_ch.to_csv(index=False).encode("utf-8-sig"),
            file_name="call_history.csv",
            mime="text/csv",
            key="dl_call_history",
        )
    st.stop()

# １週間後CXチェック: 活動完了日プルダウンで絞り込み
if selected_key == "line_template":
    from talk_script_store import (
        lookup_customer, normalize_phone, clear_caches,
        LOOKUP_SHEET, DAICON_LOOKUP_SHEET,
    )
    from nanori_master_store import apply_nanori_substitution

    st.caption("電話番号を入れて顧客の商流／取次商材を引き当て、本文を入力すると定型文末尾と合わせてコピーできるテンプレが生成されます。")

    col_in, col_btn = st.columns([4, 1])
    with col_in:
        phone_input = st.text_input(
            "電話番号",
            placeholder="例: 080-4200-2238 / 08042002238",
            key="line_template_phone",
            label_visibility="collapsed",
        )
    with col_btn:
        if st.button("🔄 データ更新", key="line_template_refresh", use_container_width=True):
            clear_caches()
            st.rerun()

    info = None
    phone_clean = normalize_phone(phone_input)
    if phone_clean:
        # 1週間後FC・代コン不備・全量(プリティーダービー用) を順に検索
        for _sheet in (LOOKUP_SHEET, DAICON_LOOKUP_SHEET, "SO新設プリティーダービー用"):
            try:
                _hit = lookup_customer(phone_clean, _sheet)
            except Exception:
                _hit = None
            if _hit is not None:
                info = _hit
                break
        if info is None:
            st.warning(f"電話番号 `{phone_clean}` に該当する顧客情報が見つかりません。")

    # --- 顧客情報カード（商流／取次商材のみ） ---
    if info:
        _shoryu = (info.get("商流（引用）") or "").strip() or "—"
        _shozai = (info.get("取次商材情報") or "").strip() or "—"
        cc1, cc2 = st.columns(2)
        with cc1:
            st.markdown(f"**商流**：{_shoryu}")
        with cc2:
            st.markdown(f"**取次商材**：{_shozai}")
        st.divider()

    body_text = st.text_area(
        "本文（自由入力）",
        key="line_template_body",
        height=200,
        placeholder="ここにLINE本文を入力してください。",
    )

    # 取次商材ごとに先頭行のフォーマットを切替
    #   NURO含む → "NURO 代理店：{{名乗}}"
    #   AU含む  → "{{名乗}}"（プレフィックス無し、名乗りのみ）
    #   その他  → "So-net 代理店：{{名乗}}"
    def _first_line(shozai: str) -> str:
        s = (shozai or "").upper()
        if "NURO" in s:
            return "NURO 代理店：{{名乗}}"
        if "AU" in s:
            return "{{名乗}}"
        return "So-net 代理店：{{名乗}}"

    _line1 = _first_line((info.get("取次商材情報") if info else "") or "")
    FOOTER_TEMPLATE = (
        "ご質問ご不明点がございましたら下記連絡先、もしくはこちらのLINEにてご返信お願いいたします。\n"
        f"{_line1}\n"
        "電話番号：{{発信番号}}\n"
        "営業時間：10:00～19:00　\n"
        "年末年始を除き年中無休"
    )

    if info:
        footer = apply_nanori_substitution(FOOTER_TEMPLATE, info)
    else:
        footer = FOOTER_TEMPLATE  # 顧客未取得時は置換しない（プレースホルダーのまま）

    combined = (body_text or "") + ("\n\n" if body_text else "") + footer

    # --- 確認注意バナー（高視認: 赤⇔黄パルス＋黒縁・拡大） ---
    st.markdown(
        """
        <style>
        @keyframes lt_warn_pulse {
            0%   { background:#FF1744; box-shadow:0 0 0 0 rgba(255,23,68,0.85), 0 4px 14px rgba(0,0,0,0.35); }
            50%  { background:#FFD600; box-shadow:0 0 0 12px rgba(255,23,68,0.0), 0 4px 14px rgba(0,0,0,0.35); color:#B71C1C; }
            100% { background:#FF1744; box-shadow:0 0 0 0 rgba(255,23,68,0.85), 0 4px 14px rgba(0,0,0,0.35); }
        }
        @keyframes lt_warn_shake {
            0%,100% { transform: translateX(0); }
            20% { transform: translateX(-2px); }
            40% { transform: translateX(2px); }
            60% { transform: translateX(-1px); }
            80% { transform: translateX(1px); }
        }
        .lt-warn-banner {
            color:#fff;
            padding:18px 22px;
            border-radius:12px;
            margin:14px 0 16px 0;
            font-weight:900;
            font-size:1.35rem;
            text-align:center;
            letter-spacing:1px;
            border:4px solid #000;
            text-shadow:1px 1px 0 #000, -1px -1px 0 #000, 1px -1px 0 #000, -1px 1px 0 #000;
            animation: lt_warn_pulse 1.2s ease-in-out infinite, lt_warn_shake 0.6s ease-in-out 3;
        }
        .lt-warn-icon {
            font-size:1.6rem;
            margin:0 6px;
            vertical-align:middle;
        }
        </style>
        <div class="lt-warn-banner">
            <span class="lt-warn-icon">⚠️</span>
            必ず会社名と電話番号あっているか確認お願いします！
            <span class="lt-warn-icon">⚠️</span>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # --- 整形済みテキスト＋独自コピーボタン ---
    # st.code はStreamlitのキーボードショートカット (c=Clear caches) と干渉するため、
    # 独自の textarea + clipboard.writeText に差し替える
    import streamlit.components.v1 as _components
    import html as _html
    _escaped = _html.escape(combined)
    _components.html(
        f"""
        <div style="font-family:'メイリオ',Meiryo,sans-serif;">
          <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:6px;">
            <div style="font-weight:700;font-size:0.95rem;">📋 整形済みテキスト</div>
            <button id="lt_copy_btn" onclick="
              const ta = document.getElementById('lt_textarea');
              navigator.clipboard.writeText(ta.value).then(() => {{
                const b = document.getElementById('lt_copy_btn');
                const orig = b.innerText;
                b.innerText = '✅ コピーしました';
                b.style.background = '#27AE60';
                setTimeout(() => {{ b.innerText = orig; b.style.background = '#4A6FA5'; }}, 1500);
              }});
            " style="background:#4A6FA5;color:#fff;border:none;border-radius:6px;
              padding:6px 14px;font-weight:700;font-size:0.9rem;cursor:pointer;">
              📋 コピー
            </button>
          </div>
          <textarea id="lt_textarea" readonly
            style="width:100%;height:220px;padding:10px 12px;font-family:inherit;
              font-size:0.95rem;line-height:1.55;border:1px solid rgba(49,51,63,0.2);
              border-radius:8px;background:#F0F2F6;color:#262730;
              resize:vertical;box-sizing:border-box;"
          >{_escaped}</textarea>
        </div>
        """,
        height=290,
    )

    st.stop()

if selected_key == "1week_cx_check":
    try:
        df_cx = _load_5min("1week_cx_check")
    except Exception as e:
        st.error(f"取得に失敗しました: {e}")
        st.stop()

    if df_cx is None or df_cx.empty:
        st.info("該当データはありません。")
        st.stop()

    _dates = sorted(
        {d for d in df_cx["1週間後FC完了履歴日"].dropna().tolist() if d},
        reverse=True,
    )
    _opts = ["全て"] + list(_dates)
    _sel = st.selectbox(
        "活動完了日で絞り込み",
        options=_opts,
        key="1week_cx_date_sel",
    )

    df_view = df_cx if _sel == "全て" else df_cx[df_cx["1週間後FC完了履歴日"] == _sel]
    st.caption(f"表示件数: {len(df_view)}件")

    if df_view.empty:
        st.info("該当データはありません。")
    else:
        df_disp = df_view.fillna("").astype(str)
        gb = GridOptionsBuilder.from_dataframe(df_disp)
        gb.configure_default_column(
            sortable=True, resizable=True, editable=False,
            type=["textColumn"], cellDataType="text",
            cellStyle={"textAlign": "left", "whiteSpace": "pre-wrap", "lineHeight": "1.4"},
        )
        _widths = {
            "担当者": 110,
            "1週間後FC完了履歴日": 140,
            "キャンセル日": 110,
            "キャンセル理由（大）": 140,
            "キャンセル理由（中）": 140,
            "キャンセル理由（小）": 140,
        }
        for col, w in _widths.items():
            if col in df_disp.columns:
                gb.configure_column(col, width=w, suppressSizeToFit=True)
        gb.configure_column(
            "申込受付番号",
            minWidth=200, wrapText=True, autoHeight=True,
            cellStyle={"textAlign": "left", "whiteSpace": "pre-wrap", "lineHeight": "1.4"},
        )
        gb.configure_column(
            "キャンセル対応コメント",
            flex=3, minWidth=300, wrapText=True, autoHeight=True,
            cellStyle={"textAlign": "left", "whiteSpace": "pre-wrap", "lineHeight": "1.5"},
        )
        gb.configure_grid_options(enableCellTextSelection=True, ensureDomOrder=True)

        AgGrid(
            df_disp,
            gridOptions=gb.build(),
            height=1200,
            theme="balham",
            allow_unsafe_jscode=True,
            custom_css={
                ".ag-header-cell": {
                    "background-color": "#4A6FA5", "color": "#fff",
                    "font-weight": "bold", "text-align": "center",
                },
                ".ag-header-cell-label": {"justify-content": "center"},
                ".ag-row-odd": {"background-color": "#ffffff"},
                ".ag-row-even": {"background-color": "#f0f4fa"},
            },
            key="aggrid_1week_cx_check",
        )
        st.download_button(
            "CSV ダウンロード",
            df_view.to_csv(index=False).encode("utf-8-sig"),
            file_name="1week_cx_check.csv",
            mime="text/csv",
            key="dl_1week_cx_check",
        )
    st.stop()

# DAYコール数: 帯グラフ表示
if selected_key == "day_calls":
    import plotly.express as px

    # 10分ごとに自動更新（キャッシュ更新ボタンを押さなくてもデータが新しくなる）
    try:
        from streamlit_autorefresh import st_autorefresh as _dc_autorefresh
        _dc_autorefresh(interval=600000, key="day_calls_autorefresh")
    except ImportError:
        pass

    def _render_bar_chart(title: str, df_src):
        st.subheader(title)
        if df_src is None or not isinstance(df_src, pd.DataFrame) or df_src.empty or "担当者" not in df_src.columns:
            st.info("該当データはありません。")
            return
        df_c = df_src.copy()
        totals = df_c.groupby("担当者")["コール数"].sum().sort_values(ascending=False)
        order = totals.index.tolist()
        # 最多コール数の担当者に👑マーク（0件時はスキップ、同値は全員付与）
        if not totals.empty and totals.iloc[0] > 0:
            _top_val = totals.iloc[0]
            _top_names = totals[totals == _top_val].index.tolist()
            _rename = {n: f"👑 {n}" for n in _top_names}
            df_c["担当者"] = df_c["担当者"].replace(_rename)
            order = [_rename.get(n, n) for n in order]
        df_c["ラベル"] = df_c["対応ステータス"] + " " + df_c["コール数"].astype(str)
        fig = px.bar(
            df_c, y="担当者", x="コール数", color="対応ステータス",
            orientation="h", text="ラベル", category_orders={"担当者": order},
        )
        fig.update_traces(
            textposition="inside", textfont_size=12,
            textfont_color="white", insidetextanchor="middle",
        )
        fig.update_layout(
            font=dict(family="メイリオ, Meiryo, sans-serif", size=14),
            xaxis_title="コール数", yaxis_title="",
            legend_title_text="対応ステータス",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
            height=max(300, 60 * len(order)),
            margin=dict(l=10, r=10, t=40, b=10),
            bargap=0.25,
        )
        # 👑を大きく表示（y軸ラベルをHTMLスパンで拡大）
        _tick_text = [
            n.replace("👑 ", '<span style="font-size:56px;">👑</span>&nbsp;', 1) if n.startswith("👑 ") else n
            for n in order
        ]
        fig.update_yaxes(tickmode="array", tickvals=order, ticktext=_tick_text)
        st.plotly_chart(fig, use_container_width=True)
        # 内訳テーブル（折りたたみ）
        with st.expander("内訳"):
            summary = df_c.pivot_table(
                index="担当者", columns="対応ステータス", values="コール数",
                aggfunc="sum", fill_value=0, margins=True, margins_name="合計",
            ).reset_index()
            summary = summary.rename(columns={"担当者": ""})
            st.dataframe(summary, use_container_width=True, hide_index=True)

    for chart_title, chart_df in fetched.items():
        _render_bar_chart(chart_title, chart_df)
        st.divider()
    st.stop()

# 周知ボード: マルチユーザー・リアルタイム編集
if selected_key == "shuchi":
    from datetime import date as _sh_date, datetime as _sh_datetime
    from shuchi_store import (
        load_rows_safe as _sh_load_rows,
        add_row as _sh_add_row,
        delete_row as _sh_delete_row,
        update_row as _sh_update_row,
        toggle_confirmation as _sh_toggle_conf,
    )

    # 確認対象メンバーは固定3名
    _SH_CONFIRM_MEMBERS = ["室谷 慧", "原田 綾子", "佐々木 彩乃"]

    def _sh_all_confirmed(row: dict) -> bool:
        return all(
            bool(row.get("confirmations", {}).get(m, {}).get("checked"))
            for m in _SH_CONFIRM_MEMBERS
        )

    _sh_rows = _sh_load_rows()

    # 編集中の行がない時のみ自動リロード（5秒）
    _sh_editing = any(
        st.session_state.get(f"sh_edit_mode_{r['id']}", False) for r in _sh_rows
    ) or st.session_state.get("sh_add_mode", False)
    if not _sh_editing:
        try:
            from streamlit_autorefresh import st_autorefresh as _sh_autorefresh
            _sh_autorefresh(interval=5000, key="sh_autorefresh")
        except ImportError:
            st.warning("streamlit-autorefresh が未インストール（手動リロードしてください）")

    st.subheader("📢 周知ボード")
    st.caption(
        "確認者: 室谷 / 原田 / 佐々木（3名全員がチェックすると下部の「過去の周知」へ移動）。"
        "マルチユーザー対応・編集/追加中以外は 5秒毎に自動更新。"
    )

    # 並び順: 周知日 昇順（新しいものが下）
    _sh_rows.sort(key=lambda r: (r.get("shuchi_date", ""), r.get("id", "")))
    _sh_active = [r for r in _sh_rows if not _sh_all_confirmed(r)]
    _sh_archived = [r for r in _sh_rows if _sh_all_confirmed(r)]

    # === 周知追加 ===
    if st.session_state.get("sh_add_mode", False):
        with st.container(border=True):
            st.markdown("**➕ 周知を追加**")
            _add_c1, _add_c2 = st.columns([1, 3])
            with _add_c1:
                _new_date = st.date_input(
                    "周知日",
                    value=_sh_date.today(),
                    key="sh_add_new_date",
                )
            with _add_c2:
                _new_content = st.text_area(
                    "周知内容",
                    value=st.session_state.get("sh_add_new_content_val", ""),
                    key="sh_add_new_content",
                    height=120,
                )
            _btn_c1, _btn_c2, _ = st.columns([1, 1, 4])
            if _btn_c1.button("追加", type="primary", key="sh_add_submit"):
                ok, msg = _sh_add_row(_new_date.isoformat(), _new_content)
                if ok:
                    st.session_state["sh_add_mode"] = False
                    st.session_state.pop("sh_add_new_content_val", None)
                    st.session_state.pop("sh_add_new_date", None)
                    st.session_state.pop("sh_add_new_content", None)
                    st.rerun()
                else:
                    st.error(msg)
            if _btn_c2.button("キャンセル", key="sh_add_cancel"):
                st.session_state["sh_add_mode"] = False
                st.session_state.pop("sh_add_new_date", None)
                st.session_state.pop("sh_add_new_content", None)
                st.rerun()
    else:
        if st.button("➕ 周知を追加", type="primary", key="sh_add_open"):
            st.session_state["sh_add_mode"] = True
            st.rerun()

    st.divider()

    def _sh_render_confirm_grid(row: dict, key_prefix: str, interactive: bool = True):
        """確認チェックボックス群を描画（3列固定）。"""
        _mcols = st.columns(len(_SH_CONFIRM_MEMBERS))
        for _j, _m in enumerate(_SH_CONFIRM_MEMBERS):
            with _mcols[_j]:
                _conf = row["confirmations"].get(_m, {})
                _checked = bool(_conf.get("checked"))
                _confd = _conf.get("confirmed_at", "")
                _new_chk = st.checkbox(
                    _m,
                    value=_checked,
                    key=f"{key_prefix}_{row['id']}_{_m}",
                    disabled=not interactive,
                )
                if _checked and _confd:
                    st.caption(f"✓ 確認日: {_confd}")
                elif _checked:
                    st.caption("✓ 確認済み")
                else:
                    st.caption("—")
                if interactive and _new_chk != _checked:
                    _sh_toggle_conf(row["id"], _m, _new_chk)
                    st.rerun()

    # === アクティブな周知 ===
    if not _sh_active:
        st.info("未完了の周知はありません。" + (f"（過去の周知 {len(_sh_archived)}件 は下部から閲覧できます）" if _sh_archived else ""))
    for _r in _sh_active:
        _rid = _r["id"]
        _edit_mode = st.session_state.get(f"sh_edit_mode_{_rid}", False)

        with st.container(border=True):
            if _edit_mode:
                try:
                    _cur_d = _sh_datetime.strptime(_r["shuchi_date"], "%Y-%m-%d").date()
                except (ValueError, TypeError):
                    _cur_d = _sh_date.today()
                _ec1, _ec2 = st.columns([1, 3])
                _new_d = _ec1.date_input(
                    "周知日", value=_cur_d, key=f"sh_edit_date_{_rid}"
                )
                _new_c = _ec2.text_area(
                    "周知内容", value=_r["content"],
                    key=f"sh_edit_content_{_rid}", height=120,
                )
                _ebc1, _ebc2, _ = st.columns([1, 1, 4])
                if _ebc1.button("保存", type="primary", key=f"sh_edit_save_{_rid}"):
                    _sh_update_row(_rid, shuchi_date=_new_d.isoformat(), content=_new_c)
                    st.session_state.pop(f"sh_edit_mode_{_rid}", None)
                    st.session_state.pop(f"sh_edit_date_{_rid}", None)
                    st.session_state.pop(f"sh_edit_content_{_rid}", None)
                    st.rerun()
                if _ebc2.button("キャンセル", key=f"sh_edit_cancel_{_rid}"):
                    st.session_state.pop(f"sh_edit_mode_{_rid}", None)
                    st.session_state.pop(f"sh_edit_date_{_rid}", None)
                    st.session_state.pop(f"sh_edit_content_{_rid}", None)
                    st.rerun()
            else:
                _hc1, _hc2, _hc3, _hc4 = st.columns([2, 6, 1, 1])
                _hc1.markdown(f"**📅 {_r['shuchi_date'] or '(日付未設定)'}**")
                _body = (_r["content"] or "_(内容未入力)_").replace("\n", "  \n")
                _hc2.markdown(_body)
                if _hc3.button("✏️", key=f"sh_edit_btn_{_rid}", help="編集"):
                    st.session_state[f"sh_edit_mode_{_rid}"] = True
                    st.rerun()
                _del_confirm_key = f"sh_del_confirm_{_rid}"
                if _hc4.button("🗑", key=f"sh_del_btn_{_rid}", help="削除（もう一度押すと確定）"):
                    if st.session_state.get(_del_confirm_key):
                        _sh_delete_row(_rid)
                        st.session_state.pop(_del_confirm_key, None)
                        st.rerun()
                    else:
                        st.session_state[_del_confirm_key] = True
                        st.rerun()
                if st.session_state.get(_del_confirm_key):
                    st.warning("削除するには🗑をもう一度押してください")

            st.caption("確認状況")
            _sh_render_confirm_grid(_r, key_prefix="sh_chk", interactive=True)

    # === 過去の周知（全員確認済）プルダウン ===
    if _sh_archived:
        st.divider()
        with st.expander(f"📦 過去の周知（確認完了 {len(_sh_archived)}件）", expanded=False):
            _ar_sorted = sorted(
                _sh_archived,
                key=lambda r: (r.get("shuchi_date", ""), r.get("id", "")),
                reverse=True,
            )
            _ar_labels = [
                f"{r['shuchi_date']} | {(r['content'][:40] + '…') if len(r['content']) > 40 else r['content']}"
                for r in _ar_sorted
            ]
            _sel = st.selectbox(
                "周知を選択",
                options=range(len(_ar_sorted)),
                format_func=lambda i: _ar_labels[i],
                key="sh_archived_select",
            )
            _ar = _ar_sorted[_sel] if 0 <= _sel < len(_ar_sorted) else None
            if _ar is not None:
                with st.container(border=True):
                    st.markdown(f"**📅 {_ar['shuchi_date']}**")
                    st.markdown((_ar["content"] or "_(内容未入力)_").replace("\n", "  \n"))
                    st.caption("確認状況（チェックを外すと「未完了」へ戻ります）")
                    _sh_render_confirm_grid(_ar, key_prefix="sh_ar_chk", interactive=True)
                    if st.button("🗑 この周知を削除", key=f"sh_ar_del_{_ar['id']}"):
                        _sh_delete_row(_ar["id"])
                        st.session_state.pop("sh_archived_select", None)
                        st.rerun()
    st.stop()

# 折返し件数: 件数テーブル＋セルごとチェックボックス
if selected_key == "orikaeshi_kensu":
    from orikaeshi_check_store import get_checks, save_checks, append_log

    # 操作ログ用: 現在のログインユーザーと時刻
    _lu = st.session_state.get("logged_in_user") or {}
    _current_user = _lu.get("display_name") or _lu.get("id") or "不明"
    log_entries: list[dict] = []

    # 10分ごとに自動更新（キャッシュ更新ボタンを押さなくてもデータが新しくなる）
    # 自動更新起因の再描画では、ユーザーが触っていないのにグリッドの古い状態が
    # 差分検知され「勝手にチェック＆そのセッションのユーザー名でログ記録」される。
    # autorefreshのカウンタ増加でタイマー起因の再描画を判定し、変更検知をスキップする。
    _is_autorefresh_run = False
    try:
        from streamlit_autorefresh import st_autorefresh as _ok_autorefresh
        _ar_count = _ok_autorefresh(interval=600000, key="orikaeshi_autorefresh")
        _prev_ar = st.session_state.get("_orikaeshi_ar_prev")
        if _prev_ar is not None and _ar_count != _prev_ar:
            _is_autorefresh_run = True
        st.session_state["_orikaeshi_ar_prev"] = _ar_count
    except ImportError:
        pass

    checks = get_checks()
    changed = False

    # ユーザー直前の操作を session_state に保持し、autorefresh で再描画されても
    # 反映前のクリックを引き継げるようにする（key -> 意図する bool）
    _intent_key = "orikaeshi_user_intent"
    if _intent_key not in st.session_state:
        st.session_state[_intent_key] = {}
    user_intent: dict = st.session_state[_intent_key]

    # user_intent と checks の差分処理
    #  - 一致: 既に保存済みなので user_intent から掃除（メモリ肥大防止）
    #  - 不一致: 前回のsaveがautorefresh等で取りこぼされた可能性 → checksに再同期して
    #            末尾の save_checks() で再保存させる
    for _ik in list(user_intent.keys()):
        _iv = user_intent[_ik]
        _sv = checks.get(_ik, False)
        if _iv == _sv:
            del user_intent[_ik]
        else:
            if _iv:
                checks[_ik] = True
            else:
                checks.pop(_ik, None)
            changed = True

    # TOTAL配色
    t = {
        "th_bg": "#D4850A", "th_border": "#B8730A", "th_color": "#ffffff",
        "even_bg": "#fdf5e9", "odd_bg": "#ffffff", "hover_bg": "#f5e4c8",
        "td_color": "#2a1f0a", "td_border": "#e0d0b5",
    }

    for i, (date_str, df) in enumerate(fetched.items()):
        if date_str == "エラー":
            st.error(df.iloc[0, 0] if not df.empty else "エラー")
            continue
        st.subheader(date_str)
        if df is None or df.empty:
            st.info("データなし")
            continue

        time_cols = [c for c in df.columns if c != "種別"]

        # --- 現在時刻の列を特定 (今日の表のみ) ---
        from datetime import datetime as _dt_now, timezone as _tz_now, timedelta as _td_now
        _jst_now = _tz_now(_td_now(hours=9))
        _now_jst = _dt_now.now(_jst_now)
        _is_today_tbl = False
        try:
            _is_today_tbl = (_dt_now.strptime(date_str, "%Y/%m/%d").date() == _now_jst.date())
        except ValueError:
            pass
        _highlight_idx = None
        if _is_today_tbl:
            for _ci, _col in enumerate(df.columns):
                _col_s = str(_col)
                if ":" in _col_s:
                    try:
                        if int(_col_s.split(":")[0]) == _now_jst.hour:
                            _highlight_idx = _ci + 1  # CSS nth-child は 1-based
                            break
                    except ValueError:
                        pass

        # --- 件数テーブル (HTML) ---
        # 列幅: 種別=200px固定, 合計=80px, 時間列=均等割 → 下のAgGridと揃える
        _SHUBETSU_W = 200  # px
        _GOKEI_W = 80      # px
        css_cls = f"table-orikaeshi-{i}"
        html = df.to_html(index=False, escape=False)
        _hl_css = ""
        if _highlight_idx:
            _hl_css = (
                f".{css_cls} th:nth-child({_highlight_idx}) {{ background:#c0392b!important; color:#fff!important; box-shadow:inset 0 -3px 0 #ffd86b; }}"
                f".{css_cls} td:nth-child({_highlight_idx}) {{ background:#ffe9b0!important; color:#7a1c10!important; font-weight:900!important; box-shadow:inset 2px 0 0 #c0392b, inset -2px 0 0 #c0392b; }}"
            )
        st.markdown(
            f"""
            <style>
            .{css_cls} {{ width:100%; border-collapse:collapse; font-size:1.9rem; table-layout:fixed; }}
            .{css_cls} th:nth-child(1), .{css_cls} td:nth-child(1) {{ width:{_SHUBETSU_W}px; font-size:1.1rem!important; }}
            .{css_cls} th:nth-child(2), .{css_cls} td:nth-child(2) {{ width:{_GOKEI_W}px; }}
            .{css_cls} th {{ text-align:center!important; vertical-align:middle!important; padding:28px 12px; background:{t['th_bg']}; color:{t['th_color']}; font-weight:700; border:1px solid {t['th_border']}; position:sticky; top:0; font-size:1.5rem; }}
            .{css_cls} td {{ text-align:center!important; vertical-align:middle!important; padding:26px 12px; color:{t['td_color']}; border:1px solid {t['td_border']}; font-weight:900; font-size:2.1rem; }}
            .{css_cls} tr:nth-child(even) {{ background:{t['even_bg']}; }}
            .{css_cls} tr:nth-child(odd) {{ background:{t['odd_bg']}; }}
            .{css_cls} tr:hover {{ background:{t['hover_bg']}; }}
            {_hl_css}
            @media screen and (max-width:768px) {{
                .{css_cls} {{ font-size:1.5rem; min-width:600px; }}
                .{css_cls} th {{ padding:14px 6px; white-space:nowrap; font-size:1.15rem; }}
                .{css_cls} td {{ padding:16px 6px; white-space:nowrap; font-size:1.6rem; }}
            }}
            </style>
            """,
            unsafe_allow_html=True,
        )
        table_html = html.replace("<table", f'<table class="{css_cls}"', 1)
        st.markdown(f'<div class="responsive-table-wrapper">{table_html}</div>', unsafe_allow_html=True)

        # --- チェックボックス (AgGrid: ALL列強調) ---
        check_time_cols = [c for c in time_cols if c != "合計"]

        check_rows = []
        for _, row in df.iterrows():
            cat = row["種別"]
            time_vals = {}
            for tc in check_time_cols:
                key = f"{date_str}|{cat}|{tc}"
                # user_intent優先（クリック直後の保存途中状態を保護）
                time_vals[tc] = user_intent.get(key, checks.get(key, False))
            all_val = all(time_vals.values()) if time_vals else False
            r = {"種別": cat, "ALL": all_val}
            r.update(time_vals)
            check_rows.append(r)
        check_df = pd.DataFrame(check_rows)

        # チェックボックスレンダラー
        _cb_renderer = JsCode("""
        class CbR{
            init(p){
                this.p=p;
                this.g=document.createElement('input');
                this.g.type='checkbox';
                this.g.checked=p.value===true;
                this.g.style.cursor='pointer';
                this.g.style.width='36px';
                this.g.style.height='36px';
                this.h=e=>{p.node.setDataValue(p.column.colId,e.target.checked);};
                this.g.addEventListener('click',this.h);
            }
            getGui(){return this.g;}
            refresh(p){this.g.checked=p.value===true;return true;}
            destroy(){this.g.removeEventListener('click',this.h);}
        }
        """)

        # 上の表とハイライト列を揃える (HTMLの_highlight_idxに対応する時間ラベル)
        _hl_col_name = None
        if _highlight_idx and 1 <= (_highlight_idx - 1) < len(df.columns):
            _hl_col_name = df.columns[_highlight_idx - 1]

        # ALL切替時に全時間帯を連動
        import json as _json
        _tc_json = _json.dumps(check_time_cols, ensure_ascii=False)
        _all_toggle = JsCode(
            "function(p){"
            "  if(p.column.colId==='ALL'){"
            f"    var tc={_tc_json};"
            "    tc.forEach(function(c){p.node.setDataValue(c,p.newValue);});"
            "  }"
            "}"
        )

        gb = GridOptionsBuilder.from_dataframe(check_df)
        gb.configure_default_column(
            resizable=False, sortable=False, filter=False,
            editable=True,
            cellRenderer=_cb_renderer,
        )
        gb.configure_column("種別",
            cellRenderer=None, editable=False, pinned="left",
            width=200, minWidth=200, maxWidth=200, suppressSizeToFit=True,
            cellStyle={"fontWeight": "bold", "textAlign": "left", "fontSize": "1.25rem",
                       "display": "flex", "alignItems": "center"})
        gb.configure_column("ALL",
            editable=True, width=80, minWidth=80, maxWidth=80, suppressSizeToFit=True,
            headerClass="orikaeshi-all-hdr",
            cellStyle={"backgroundColor": "rgba(212,133,10,0.25)",
                       "display": "flex", "alignItems": "center",
                       "justifyContent": "center"})
        for tc in check_time_cols:
            _is_hl = (tc == _hl_col_name)
            _cstyle = {"display": "flex", "alignItems": "center", "justifyContent": "center"}
            if _is_hl:
                _cstyle["backgroundColor"] = "#ffe9b0"
                _cstyle["boxShadow"] = "inset 2px 0 0 #c0392b, inset -2px 0 0 #c0392b"
            gb.configure_column(tc, editable=True, width=100, minWidth=50,
                headerClass=("orikaeshi-hl-hdr" if _is_hl else None),
                cellStyle=_cstyle)
        # サイドバー開閉/ウィンドウリサイズで列幅を再計算（種別はsuppressSizeToFit=Trueで140px固定）
        _resize_fit = JsCode("function(p){ p.api.sizeColumnsToFit(); }")
        gb.configure_grid_options(
            onCellValueChanged=_all_toggle,
            onGridSizeChanged=_resize_fit,
            onFirstDataRendered=_resize_fit,
            rowHeight=88,
            headerHeight=84,
        )

        _ag_css = {
            ".ag-header-cell": {
                "background-color": "#555",
                "color": "#fff",
                "font-weight": "bold",
                "text-align": "center",
                "font-size": "1.5rem",
            },
            ".ag-header-cell-label": {"justify-content": "center"},
            ".orikaeshi-all-hdr": {
                "background-color": "#D4850A !important",
                "color": "#fff !important",
                "font-weight": "900 !important",
                "font-size": "1.5rem !important",
            },
            ".orikaeshi-hl-hdr": {
                "background-color": "#c0392b !important",
                "color": "#fff !important",
                "font-weight": "900 !important",
                "font-size": "1.5rem !important",
            },
            ".ag-row-odd": {"background-color": "#ffffff"},
            ".ag-row-even": {"background-color": "#fdf5e9"},
        }

        ag_result = AgGrid(
            check_df,
            gridOptions=gb.build(),
            height=max(200, 90 + 88 * len(check_df)),
            theme="balham",
            allow_unsafe_jscode=True,
            custom_css=_ag_css,
            fit_columns_on_grid_load=True,
            update_mode="VALUE_CHANGED",
            reload_data=True,  # 自動更新時に古いグリッド状態が残り勝手に再チェックされるのを防ぐ
            key=f"orikaeshi_chk_{i}",
        )

        # 変更検知 → 共有ストアに反映
        # 自動更新起因の再描画では、グリッドの古い状態を誤って「操作」と扱わない
        if not _is_autorefresh_run and ag_result and ag_result.data is not None:
            for _, row in ag_result.data.iterrows():
                cat = row["種別"]
                for tc in check_time_cols:
                    key = f"{date_str}|{cat}|{tc}"
                    # AgGridは値を文字列 "false" で返すことがあり bool("false")==True
                    # となるため、文字列も明示的に判定する（チェック解除が保存されない不具合対策）
                    _rawv = row[tc]
                    if isinstance(_rawv, str):
                        val = _rawv.strip().lower() in ("true", "1", "yes")
                    else:
                        val = bool(_rawv)
                    # 入力時に流した値（user_intent優先のcheck_df基準）と比較
                    expected = user_intent.get(key, checks.get(key, False))
                    if val != expected:
                        # ユーザーが今このセルを操作した
                        user_intent[key] = val
                        if val:
                            checks[key] = True
                        else:
                            checks.pop(key, None)
                        changed = True
                        log_entries.append({
                            "at": _now_jst.strftime("%Y/%m/%d %H:%M:%S"),
                            "action": "チェック" if val else "解除",
                            "by": _current_user,
                            "key": key,
                        })

        st.download_button(
            "CSV ダウンロード",
            df.to_csv(index=False).encode("utf-8-sig"),
            file_name=f"orikaeshi_{date_str.replace('/', '-')}.csv",
            mime="text/csv",
            key=f"dl_orikaeshi_{i}",
        )
        st.divider()

    if changed:
        ok, msg = save_checks(checks)
        if not ok:
            st.error(f"⚠️ チェック状態の保存に失敗しました: {msg}")
        if log_entries:
            _lok, _lmsg = append_log(log_entries)
            if not _lok:
                st.warning(f"操作ログの記録に失敗: {_lmsg}")

    st.stop()

# 折返しチェック操作ログ（SECRETカテゴリ・非表示タブ）
if selected_key == "orikaeshi_check_log":
    from orikaeshi_check_store import get_log

    st.title("📋 折返しチェック操作ログ")
    st.caption("折返し件数ボードのチェック/解除を「誰が・いつ・どのセル」操作したかの履歴（新しい順・追記専用）")

    _log = get_log(limit=1000)
    if not _log:
        st.info("操作ログはまだありません。")
    else:
        _log_df = pd.DataFrame(_log)
        # key（日付|種別|時間帯）を読みやすい列に分解
        _parts = _log_df["key"].str.split("|", n=2, expand=True)
        _log_df["対象日"] = _parts[0]
        _log_df["種別"] = _parts[1] if _parts.shape[1] > 1 else ""
        _log_df["時間帯"] = _parts[2] if _parts.shape[1] > 2 else ""
        _disp = _log_df[["at", "action", "by", "対象日", "種別", "時間帯"]].rename(
            columns={"at": "日時", "action": "操作", "by": "ユーザー"}
        )
        st.dataframe(_disp, use_container_width=True, hide_index=True)
        st.download_button(
            "CSV ダウンロード",
            _disp.to_csv(index=False).encode("utf-8-sig"),
            file_name="orikaeshi_check_log.csv",
            mime="text/csv",
            key="dl_orikaeshi_log",
        )

    st.stop()

# 開通前対応ボード（商材別・エントリ月×対応月の発生率＋月次見込み）
if selected_key == "kaitsu_mae_taiou":
    import kaitsu_mae_taiou as _kmt

    st.title("開通前対応")
    st.caption(
        "「開通前の対応」= 対応日が開通日より過去 もしくは 開通日が空欄 で、"
        "（区分=FC × ステータス=フォローコール(代コン)）または"
        "（区分=架電 × ステータス=対応/キャンセル対応）の活動（対応架電回数ベース＝コール結果=留守も含む・1顧客複数回もカウント）。"
        " エントリ月×対応月で『エントリ件数あたりの開通前対応件数（発生率）』を商材別に集計します。"
    )

    _kc1, _kc2 = st.columns([1, 5])
    if _kc1.button("🔄 再集計", key="kmt_reload"):
        _load_kaitsu_mae_taiou.clear()
        st.rerun()

    res = _load_kaitsu_mae_taiou(_daily_cache_key())
    st.caption(
        f"集計時点: {res['asof']}　対応月 {res['handling_ym'][0]}〜{res['handling_ym'][-1]}"
        f"（{res['current_ym']} は進行中）"
    )

    _OFF_LABELS = ["当月", "1ヶ月前", "2ヶ月前", "3ヶ月前"]
    _max_off = res["max_offset"]
    _handling = res["handling_ym"]
    _current = res["current_ym"]
    _completed = [h for h in _handling if h != _current]  # 係数は完了した対応月のみで平均

    _ny, _nm = _kmt._add_months(int(_current[:4]), int(_current[5:7]), 1)
    _next_ym = _kmt._ym(_ny, _nm)

    def _calc_coeff(ec, mat):
        c = []
        for o in range(_max_off + 1):
            vals = []
            for h in _completed:
                eym = _kmt.offset_entry_ym(h, o)
                e = ec.get(eym, 0)
                if e:
                    vals.append(mat.get((eym, h), 0) / e)
            c.append(sum(vals) / len(vals) if vals else 0.0)
        return c

    def _pct(x, base):
        return f"{x / base * 100:.1f}%" if base else "-"

    def _kmt_table(df):
        # 値を中央寄せしたHTMLテーブルで表示
        _html = df.to_html(index=False, escape=False).replace("<table", '<table class="kmt-tbl"', 1)
        st.markdown(
            "<style>"
            ".kmt-tbl{width:100%;border-collapse:collapse;font-size:0.95rem;"
            "background:#fff;border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.18);}"
            ".kmt-tbl th,.kmt-tbl td{text-align:center!important;padding:6px 10px;border:1px solid #e0e0e0;color:#222!important;}"
            ".kmt-tbl th{background:rgba(212,133,10,0.18);color:#5a3a00!important;font-weight:700;}"
            ".kmt-tbl tr:nth-child(even) td{background:#faf9f5;}"
            "</style>"
            f'<div style="overflow-x:auto">{_html}</div>',
            unsafe_allow_html=True,
        )

    def _forecast(ec, ca, ce, cr, ck, target_ym):
        parts = []
        t_all = t_eff = t_rusu = t_kan = 0.0
        for o in range(_max_off + 1):
            eym = _kmt.offset_entry_ym(target_ym, o)
            e = ec.get(eym, 0)
            pa, pe, pr, pk = e * ca[o], e * ce[o], e * cr[o], e * ck[o]
            t_all += pa; t_eff += pe; t_rusu += pr; t_kan += pk
            parts.append({
                "エントリ月": eym, "区分": _OFF_LABELS[o],
                "エントリ件数": e, "係数": f"{ca[o] * 100:.1f}%",
                "対応架電回数": round(pa),
                "有効対話数": round(pe), "有効対話率": _pct(pe, pa),
                "無効対話数": round(pr), "無効対話率": _pct(pr, pa),
                "完了対話数": round(pk), "対応完了率": _pct(pk, pa),
            })
        return pd.DataFrame(parts), t_all, t_eff, t_rusu, t_kan

    # 全商材の係数・見込みを先に計算
    #   架電回数=留守込み / 有効対話=留守抜き / 無効対話=留守のみ / 完了対話=コール結果完了のみ
    _calc = {}
    for prod in res["products"]:
        d = res["data"][prod]
        ec = d["entry_counts"]
        coeff_all = _calc_coeff(ec, d["matrix"])
        coeff_eff = _calc_coeff(ec, d.get("matrix_eff", {}))
        coeff_rusu = _calc_coeff(ec, d.get("matrix_rusu", {}))
        coeff_kan = _calc_coeff(ec, d.get("matrix_kanryo", {}))
        _, tn_all, tn_eff, tn_rusu, tn_kan = _forecast(ec, coeff_all, coeff_eff, coeff_rusu, coeff_kan, _current)
        _, tx_all, tx_eff, tx_rusu, tx_kan = _forecast(ec, coeff_all, coeff_eff, coeff_rusu, coeff_kan, _next_ym)
        _calc[prod] = {
            "coeff_all": coeff_all, "coeff_eff": coeff_eff,
            "coeff_rusu": coeff_rusu, "coeff_kan": coeff_kan,
            "tn_all": tn_all, "tn_eff": tn_eff, "tn_rusu": tn_rusu, "tn_kan": tn_kan,
            "tx_all": tx_all, "tx_eff": tx_eff, "tx_rusu": tx_rusu, "tx_kan": tx_kan,
        }

    # --- サマリー表（最上部・商材別 今月/来月の見込み）---
    _summary_order = [p for p in ["ソネット", "AU光", "NURO"] if p in _calc] + \
                     [p for p in res["products"] if p not in ("ソネット", "AU光", "NURO")]

    def _sum_cols(prefix, a, e, r, k):
        return {
            f"{prefix} 対応架電回数": round(a),
            f"{prefix} 有効対話数": round(e), f"{prefix} 有効対話率": _pct(e, a),
            f"{prefix} 無効対話数": round(r), f"{prefix} 無効対話率": _pct(r, a),
            f"{prefix} 完了対話数": round(k), f"{prefix} 対応完了率": _pct(k, a),
        }

    _sum_rows = []
    for p in _summary_order:
        c = _calc[p]
        row = {"商材": p}
        row.update(_sum_cols(_current, c["tn_all"], c["tn_eff"], c["tn_rusu"], c["tn_kan"]))
        row.update(_sum_cols(_next_ym, c["tx_all"], c["tx_eff"], c["tx_rusu"], c["tx_kan"]))
        _sum_rows.append(row)
    _tot = {k: sum(_calc[p][k] for p in _summary_order)
            for k in ("tn_all", "tn_eff", "tn_rusu", "tn_kan", "tx_all", "tx_eff", "tx_rusu", "tx_kan")}
    _trow = {"商材": "合計"}
    _trow.update(_sum_cols(_current, _tot["tn_all"], _tot["tn_eff"], _tot["tn_rusu"], _tot["tn_kan"]))
    _trow.update(_sum_cols(_next_ym, _tot["tx_all"], _tot["tx_eff"], _tot["tx_rusu"], _tot["tx_kan"]))
    _sum_rows.append(_trow)

    st.markdown("### 📊 今月・来月の開通前対応 発生見込み（商材別）")
    _kmt_table(pd.DataFrame(_sum_rows))
    st.caption(
        "※対応架電回数＝留守込み／有効対話数＝留守を除いた数／無効対話数＝留守のみ／完了対話数＝コール結果=完了のみ。"
        "各率は（その数 ÷ 対応架電回数）。"
        f"今月（{_current}）は当月エントリ進行中のため過小、来月（{_next_ym}）は当月エントリ未発生分を含みません。"
    )
    st.divider()

    # --- 商材別 明細 ---
    for prod in res["products"]:
        d = res["data"][prod]
        ec = d["entry_counts"]
        mat = d["matrix"]
        c = _calc[prod]
        st.subheader(prod)

        # 発生率マトリクス（行=対応月／列=エントリ月オフセット・対応架電回数ベース）
        rows = []
        for h in _handling:
            label = f"{h}（進行中）" if h == _current else h
            row = {"対応月＼エントリ月": label}
            for o in range(_max_off + 1):
                eym = _kmt.offset_entry_ym(h, o)
                cnt = mat.get((eym, h), 0)
                e = ec.get(eym, 0)
                rate = (cnt / e * 100) if e else 0.0
                row[_OFF_LABELS[o]] = f"{rate:.1f}% ({cnt}/{e})"
            rows.append(row)
        _kmt_table(pd.DataFrame(rows))

        # 発生率係数（完了対応月の平均・対応架電回数ベース）
        st.markdown(
            f"**発生率係数（{'／'.join(_completed)} の平均・対応架電回数）**　"
            + "　".join(f"{_OFF_LABELS[o]}={c['coeff_all'][o] * 100:.1f}%" for o in range(_max_off + 1))
        )

        # 月次見込み（係数 × エントリ件数）
        _fc_now, _tn_all, _tn_eff, _tn_rusu, _tn_kan = _forecast(
            ec, c["coeff_all"], c["coeff_eff"], c["coeff_rusu"], c["coeff_kan"], _current)
        _fc_next, _tx_all, _tx_eff, _tx_rusu, _tx_kan = _forecast(
            ec, c["coeff_all"], c["coeff_eff"], c["coeff_rusu"], c["coeff_kan"], _next_ym)
        st.markdown(
            f"**{_current}（当月進行中）** 対応架電回数 約{round(_tn_all)} ／ 有効対話 約{round(_tn_eff)} "
            f"／ 無効対話 約{round(_tn_rusu)} ／ 完了対話 約{round(_tn_kan)}"
        )
        _kmt_table(_fc_now)
        st.markdown(
            f"**{_next_ym}** 対応架電回数 約{round(_tx_all)} ／ 有効対話 約{round(_tx_eff)} "
            f"／ 無効対話 約{round(_tx_rusu)} ／ 完了対話 約{round(_tx_kan)}"
        )
        _kmt_table(_fc_next)

        st.divider()

    st.stop()

# 工事取得FC資料（ソネット光・架電回数別の開通率と適正回数）
if selected_key == "kouji_shutoku_fc":
    import kouji_shutoku_fc as _ksf

    st.title("工事取得FC資料")
    st.caption(
        "ソネット光・直近180日の工事取得FC架電回数(Account.Field194__c)と開通率の関係から、"
        "適正な架電回数の目安を可視化する資料。"
    )

    # 印刷用CSS — Streamlit UI を隠してA4縦に最適化
    st.markdown("""
<style>
@media print {
  /* Streamlit本体のUIを非表示 */
  section[data-testid="stSidebar"],
  header[data-testid="stHeader"],
  div[data-testid="stToolbar"],
  div[data-testid="stDecoration"],
  footer,
  .ksf-no-print { display: none !important; }

  /* メインを全幅に */
  .main .block-container,
  section.main > div,
  div[data-testid="stAppViewContainer"] > section,
  div.block-container { max-width: 100% !important; padding: 6mm 8mm !important; }

  /* 背景色・影も印刷 */
  *, *::before, *::after {
    -webkit-print-color-adjust: exact !important;
    print-color-adjust: exact !important;
  }

  /* テーブル: 影は不要・字を少し詰める */
  .ksf-tbl { box-shadow: none !important; font-size: 9pt !important;
             page-break-inside: avoid; }
  .ksf-tbl th, .ksf-tbl td { padding: 3px 6px !important; }

  /* 章間の改ページ */
  .ksf-page-break { page-break-before: always; }

  /* KPIカードのボックスシャドウを軽く */
  div[style*="box-shadow"] { box-shadow: none !important; border: 1px solid #ccc !important; }

  /* 見出しの色は残す */
  h1, h2, h3 { color: #222 !important; }

  /* リンクの下線色 */
  a { color: #222 !important; text-decoration: none !important; }

  @page { size: A4 portrait; margin: 8mm; }
}
</style>
""", unsafe_allow_html=True)

    _kfc1, _kfc2, _kfc3 = st.columns([1, 1, 4])
    with _kfc1:
        st.markdown('<div class="ksf-no-print">', unsafe_allow_html=True)
        if st.button("🔄 再集計", key="ksf_reload"):
            _load_kouji_shutoku_fc.clear()
            st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)
    with _kfc2:
        # ブラウザの印刷ダイアログを開くボタン（iframeから親windowに対して実行）
        import streamlit.components.v1 as _components
        _components.html(
            """
            <div class="ksf-no-print">
              <button onclick="window.parent.print()"
                style="background:#5a3a00;color:#fff;border:none;padding:8px 18px;
                       border-radius:6px;cursor:pointer;font-weight:700;font-size:0.95rem;
                       box-shadow:0 2px 6px rgba(0,0,0,0.2);">
                🖨️ PDFに保存
              </button>
            </div>
            """,
            height=46,
        )

    res = _load_kouji_shutoku_fc(_daily_cache_key())
    st.caption(f"集計時点: {res['asof']}　集計期間: 直近{res['lookback_days']}日")
    st.markdown(
        '<div class="ksf-no-print" style="background:#fef3e0;border-left:4px solid #d4860a;'
        'padding:6px 12px;border-radius:4px;font-size:0.85rem;color:#5a3a00;margin:6px 0;">'
        '💡 「🖨️ PDFに保存」を押し、印刷ダイアログの<b>送り先で「PDFに保存」を選択</b>、'
        '<b>用紙=A4縦・余白=なし(または小)・背景のグラフィック=ON</b>にすると綺麗に出力されます。'
        '</div>',
        unsafe_allow_html=True,
    )

    # 共通テーブル描画
    def _ksf_table(df):
        _html = df.to_html(index=False, escape=False).replace("<table", '<table class="ksf-tbl"', 1)
        st.markdown(
            "<style>"
            ".ksf-tbl{width:100%;border-collapse:collapse;font-size:0.95rem;"
            "background:#fff;border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.18);margin-bottom:8px;}"
            ".ksf-tbl th,.ksf-tbl td{text-align:center!important;padding:6px 10px;border:1px solid #e0e0e0;color:#222!important;}"
            ".ksf-tbl th{background:rgba(212,133,10,0.18);color:#5a3a00!important;font-weight:700;}"
            ".ksf-tbl tr:nth-child(even) td{background:#faf9f5;}"
            ".ksf-tbl .row-best td{background:#fff3cd!important;font-weight:700;}"
            "</style>"
            f'<div style="overflow-x:auto">{_html}</div>',
            unsafe_allow_html=True,
        )

    def _kpi_card(label, value, sub=""):
        return (
            f"<div style='background:#fff;border-radius:10px;padding:14px 18px;"
            f"box-shadow:0 2px 8px rgba(0,0,0,0.15);text-align:center;'>"
            f"<div style='font-size:0.85rem;color:#555;'>{label}</div>"
            f"<div style='font-size:2.0rem;font-weight:800;color:#5a3a00;line-height:1.2;'>{value}</div>"
            f"<div style='font-size:0.78rem;color:#777;'>{sub}</div>"
            f"</div>"
        )

    # =============================================
    # 第1章: KPI 概要
    # =============================================
    st.markdown("## 📊 KPI 概要")
    k = res["kpi"]
    cols = st.columns(4)
    cols[0].markdown(_kpi_card(
        "直近180日 開通件数", f"{k['kaitsu_total']:,}",
        "ソネット光・開通済み"), unsafe_allow_html=True)
    cols[1].markdown(_kpi_card(
        "工事取得FC なしで開通", f"{k['fc_zero_rate']:.1f}%",
        f"{k['fc_zero_count']:,}件 / 自動進行群"), unsafe_allow_html=True)
    cols[2].markdown(_kpi_card(
        "平均架電回数（FC実施群）", f"{k['avg_pos']:.2f}回",
        f"中央値 {k['median_pos']:.0f}回 / N={k['kaitsu_total']-k['fc_zero_count']:,}"), unsafe_allow_html=True)
    cols[3].markdown(_kpi_card(
        "適正打ち切り目安", "5回",
        "限界効用1桁台に転落するライン"), unsafe_allow_html=True)
    st.divider()

    # =============================================
    # 第2章: 枠組み・定義
    # =============================================
    st.markdown("## 🧩 第1章 枠組み・定義")
    defn = [
        {"用語": "工事取得FC", "定義": "Task.Field2_del__c='フォローコール（工事取得）'。工事日が取れていない案件へ工事日確定を促す架電"},
        {"用語": "工事取得FC回数", "定義": "Account.Field194__c。1案件あたりの工事取得FC実施回数（SF側で集計済み）"},
        {"用語": "開通", "定義": "Account.Field130__c（工事完了日）にデータあり"},
        {"用語": "キャンセル(CX)", "定義": "Account.Field119__c（キャンセル日）にデータあり"},
        {"用語": "母集団（結果確定群）", "定義": f"直近{res['lookback_days']}日エントリ(Field156__c)のソネット光で開通orCX確定済"},
        {"用語": "FC実施群", "定義": "工事取得FC回数 > 0 の案件（=工事取得FCを1回以上行った案件）"},
        {"用語": "N回到達群", "定義": "工事取得FC回数 >= N の案件（N-1回までで結着しなかった案件）"},
        {"用語": "限界効用", "定義": "N回到達群のうち、ちょうどN回で開通した案件の割合（=N回目の架電を打つ価値）"},
    ]
    _ksf_table(pd.DataFrame(defn))
    st.divider()

    # =============================================
    # 第3章: 結果確定群サマリ
    # =============================================
    st.markdown("## 📞 第2章 結果確定群の全体像")
    st.markdown(
        f"<div style='font-size:1.05rem;'>母集団 <b>{res['outcome_total']:,}件</b>　"
        f"内訳: 開通 <b style='color:#1e7e34;'>{res['outcome_open']:,}件</b>　"
        f"／ CX <b style='color:#b94a48;'>{res['outcome_cx']:,}件</b>　"
        f"（全体開通率 <b>{res['outcome_open']/res['outcome_total']*100:.1f}%</b>）</div>",
        unsafe_allow_html=True
    )
    st.caption("以降の章は、この母集団を工事取得FC回数別にスライスして見ていきます。")
    st.divider()

    # =============================================
    # 第4章: 回数別バケット開通率（事後集計）
    # =============================================
    st.markdown('<div class="ksf-page-break"></div>', unsafe_allow_html=True)
    st.markdown("## 📈 第3章 工事取得FC回数別 開通率")
    st.caption(
        "工事取得FC回数で案件を分類し、その群の開通率を比較。0回群＝自動進行で開通する案件群（74%）と、"
        "FC実施群（1回以上）の振る舞いの差を見る。"
    )
    bucket_order = ["0回", "1〜2回", "3〜4回", "5〜6回", "7〜9回", "10回以上"]
    agg_rows = []
    for b in bucket_order:
        if b not in res["agg"]:
            continue
        v = res["agg"][b]
        t = v["開通"] + v["CX"]
        agg_rows.append({
            "工事取得FC回数": b,
            "開通": v["開通"], "CX": v["CX"], "計": t,
            "開通率": f"{v['開通']/t*100:.1f}%" if t else "-",
        })
    _ksf_table(pd.DataFrame(agg_rows))
    st.caption(
        "💡 **読み方**: 0回群と1〜2回群が最も開通率が高く、3〜4回も同水準。5〜6回でわずかに減少、"
        "**7〜9回で42%まで低下、10回以上では26%まで急落**。深追いするほどCX率が高まる構造。"
    )
    st.divider()

    # =============================================
    # 第5章: N回目の限界効用
    # =============================================
    st.markdown('<div class="ksf-page-break"></div>', unsafe_allow_html=True)
    st.markdown("## 🎯 第4章 N回目の限界効用（適正回数の核心）")
    st.caption(
        "「N回到達群のうち、ちょうどN回で開通した案件の割合」= N回目の架電を打って意味があったかを示す指標。"
        "母数からは0回案件（自動進行群）を除外している。"
    )
    marg_rows = []
    for m in res["marginal"]:
        # 評価ラベル
        if m["rate"] >= 13:
            ev = "🟢 強い"
        elif m["rate"] >= 10:
            ev = "🟡 有効"
        elif m["rate"] >= 7:
            ev = "🟠 境界"
        elif m["rate"] >= 4:
            ev = "🔴 弱い"
        else:
            ev = "⚫ ほぼ無効"
        marg_rows.append({
            "N回目": f"{m['N']}回目",
            "N回到達群": f"{m['reach']:,}",
            "ちょうどN回で開通": f"{m['exact_open']:,}",
            "限界効用": f"{m['rate']:.1f}%",
            "評価": ev,
        })
    _ksf_table(pd.DataFrame(marg_rows))
    st.caption(
        "💡 **読み方**: 1〜4回目までは限界効用10%以上で十分機能。**5回目で8%台に落ち、6回目以降は1桁前半に急落**。"
        "つまり「5回」が効率的な打ち切りラインの目安。"
    )
    st.divider()

    # =============================================
    # 第6章: 累積開通率（FC実施群を1とした場合の回収度合い）
    # =============================================
    st.markdown('<div class="ksf-page-break"></div>', unsafe_allow_html=True)
    st.markdown("## 📉 第5章 累積開通率（何回まで打てば何%回収できるか）")
    st.caption(
        f"工事取得FCを1回以上実施した{res['pos_total']:,}件を母数として、N回までに開通した累計件数の割合。"
    )
    cum_rows = []
    final_rate = res["cumulative"][-1]["rate"] if res["cumulative"] else 0
    for c in res["cumulative"]:
        if c["N"] > 15:
            continue
        pct_of_final = (c["rate"] / final_rate * 100) if final_rate else 0
        cum_rows.append({
            "N回まで": f"{c['N']}回",
            "累計開通件数": f"{c['cum_open']:,}",
            "累計開通率": f"{c['rate']:.1f}%",
            "最終比": f"{pct_of_final:.0f}%",
        })
    _ksf_table(pd.DataFrame(cum_rows))
    st.caption(
        "💡 **読み方**: 「最終比」= 最終的に開通する全件数のうち、N回までで何%を回収できるか。"
        "**5回までで開通見込みの約8割を回収**でき、それ以降の上乗せは限定的。"
    )
    st.divider()

    # =============================================
    # 第7章: 開通案件の架電回数分布
    # =============================================
    st.markdown("## 📊 第6章 開通案件の工事取得FC回数 分布")
    st.caption(
        f"直近{res['lookback_days']}日に開通したソネット光のうち、工事取得FC回数>0の{res['kaitsu_total']-res['kaitsu_zero']:,}件の分布。"
        "5回までで大半（約8割）が決着している。"
    )
    dist = res["dist_pos"]
    total_pos = sum(dist.values())
    cum = 0
    dist_rows = []
    for n in sorted(dist.keys()):
        if n > 20:
            continue  # 20回以上は別行でまとめ
        cum += dist[n]
        dist_rows.append({
            "回数": f"{n}回",
            "件数": f"{dist[n]:,}",
            "構成比": f"{dist[n]/total_pos*100:.1f}%",
            "累積構成比": f"{cum/total_pos*100:.1f}%",
        })
    over20_cnt = sum(v for n, v in dist.items() if n > 20)
    if over20_cnt:
        cum += over20_cnt
        dist_rows.append({
            "回数": "21回以上",
            "件数": f"{over20_cnt:,}",
            "構成比": f"{over20_cnt/total_pos*100:.1f}%",
            "累積構成比": f"{cum/total_pos*100:.1f}%",
        })
    _ksf_table(pd.DataFrame(dist_rows))
    st.caption(
        f"💡 **読み方**: 1回で開通{dist.get(1,0)}件（{dist.get(1,0)/total_pos*100:.1f}%）が最頻。"
        f"最大{max(dist.keys()) if dist else 0}回まで散在しているが、6回以上は構成比の少ないテール。"
        f" 平均{res['avg_pos']:.2f}回は外れ値に引かれた値で、**中央値2回・75%点{res['p75_pos']:.0f}回・90%点{res['p90_pos']:.0f}回**が実態に近い。"
    )
    st.divider()

    # =============================================
    # 第8章: 結論・提言
    # =============================================
    st.markdown('<div class="ksf-page-break"></div>', unsafe_allow_html=True)
    st.markdown("## 🏁 第7章 結論・提言")
    st.markdown("""
<div style='background:#fff;border-radius:10px;padding:16px 22px;box-shadow:0 2px 8px rgba(0,0,0,0.15);line-height:1.8;'>

**① 適正架電回数 = 5回**
- 1〜4回目は限界効用10%以上で機能
- 5回目で8%台に低下、累積回収率は約80%に到達
- 6回目以降は限界効用1桁前半に急落

**② 6回以上は「Go/No-Go判断」必須**
- 6〜9回群の開通率は40%台、10回以上では26%まで低下
- 「とりあえずもう1回」が深追いCXを生んでいる構造

**③ 0回案件74%は「FC不要層」**
- 工事取得FCを1度も打たずに開通する案件が母集団の3/4を占める
- FCリソースは「FCしないと進まない案件」へ集中投下すべき

**④ 運用ルール案**
- **打ち切り: 5回到達時点でSV判断を挟む**
- **6回目はGo/No-Go明示**（ダイコンステータス/最新コール結果で判断）
- **10回以上は原則打ち切り** → 別アプローチ（窓口連絡・上長介入等）に切り替え

</div>
""", unsafe_allow_html=True)

    st.stop()

# ソネット光AU・UQ 1次停滞理由
if selected_key == "daikon_riyu_au_sonet":
    import daikon_riyu_au_sonet as _drs

    st.title("ソネット光 × AU/UQ 1次停滞理由")
    st.caption(
        "利用携帯にAUまたはUQを含むソネット光案件の1次ダイコン理由別の発生数・開通数・開通率・発生率を、"
        "エリア(東/西/合算)×期間(直近半年合算＋エントリ月別)で可視化する資料。"
    )

    # 印刷用CSS (工事取得FCと同じ仕様)
    st.markdown("""
<style>
@media print {
  section[data-testid="stSidebar"],
  header[data-testid="stHeader"],
  div[data-testid="stToolbar"],
  div[data-testid="stDecoration"],
  footer,
  .drs-no-print { display: none !important; }

  .main .block-container,
  section.main > div,
  div[data-testid="stAppViewContainer"] > section,
  div.block-container { max-width: 100% !important; padding: 6mm 8mm !important; }

  *, *::before, *::after {
    -webkit-print-color-adjust: exact !important;
    print-color-adjust: exact !important;
  }

  .drs-tbl { box-shadow: none !important; font-size: 8.5pt !important;
             page-break-inside: avoid; }
  .drs-tbl th, .drs-tbl td { padding: 3px 6px !important; }
  .drs-page-break { page-break-before: always; }

  div[style*="box-shadow"] { box-shadow: none !important; border: 1px solid #ccc !important; }
  h1, h2, h3 { color: #222 !important; }
  @page { size: A4 portrait; margin: 8mm; }
}
</style>
""", unsafe_allow_html=True)

    _drc1, _drc2, _drc3 = st.columns([1, 1, 4])
    with _drc1:
        st.markdown('<div class="drs-no-print">', unsafe_allow_html=True)
        if st.button("🔄 再集計", key="drs_reload"):
            _load_daikon_riyu_au_sonet.clear()
            st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)
    with _drc2:
        import streamlit.components.v1 as _components
        _components.html(
            """
            <div class="drs-no-print">
              <button onclick="window.parent.print()"
                style="background:#5a3a00;color:#fff;border:none;padding:8px 18px;
                       border-radius:6px;cursor:pointer;font-weight:700;font-size:0.95rem;
                       box-shadow:0 2px 6px rgba(0,0,0,0.2);">
                🖨️ PDFに保存
              </button>
            </div>
            """,
            height=46,
        )

    res = _load_daikon_riyu_au_sonet(_daily_cache_key())
    st.caption(f"集計時点: {res['asof']}　集計期間: 直近{res['lookback_days']}日エントリ")

    def _drs_table(df, *, highlight_top: int = 0):
        _html = df.to_html(index=False, escape=False).replace("<table", '<table class="drs-tbl"', 1)
        st.markdown(
            "<style>"
            ".drs-tbl{width:100%;border-collapse:collapse;font-size:0.93rem;"
            "background:#fff;border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.18);margin-bottom:8px;}"
            ".drs-tbl th,.drs-tbl td{text-align:center!important;padding:6px 10px;border:1px solid #e0e0e0;color:#222!important;}"
            ".drs-tbl th{background:rgba(107,70,193,0.18);color:#3b2275!important;font-weight:700;}"
            ".drs-tbl td:first-child{text-align:left!important;font-weight:600;}"
            ".drs-tbl tr:nth-child(even) td{background:#faf9fd;}"
            "</style>"
            f'<div style="overflow-x:auto">{_html}</div>',
            unsafe_allow_html=True,
        )

    def _fmt_pct(num, den):
        return f"{num/den*100:.1f}%" if den else "-"

    # 共通: 1テーブル生成（行=理由、列=件数/開通/開通率/発生率）
    def _build_reason_table(area, ym):
        cell = res["table"].get(f"{area}|{ym}", {})
        total = res["totals"].get(f"{area}|{ym}", 0)
        rows = []
        # 理由順は合算全期間の件数順だが、当該 area×ym で件数0の理由はスキップ
        for r in res["reasons_order"]:
            v = cell.get(r)
            if not v or v["count"] == 0:
                continue
            rows.append({
                "1次停滞理由": r,
                "件数": v["count"],
                "開通": v["open"],
                "開通率": _fmt_pct(v["open"], v["count"]),
                "発生率": _fmt_pct(v["count"], total),
            })
        # 合計行
        rows.append({
            "1次停滞理由": "<b>合計</b>",
            "件数": f"<b>{total}</b>",
            "開通": f"<b>{sum(v['open'] for v in cell.values())}</b>",
            "開通率": f"<b>{_fmt_pct(sum(v['open'] for v in cell.values()), total)}</b>",
            "発生率": "<b>100.0%</b>",
        })
        return pd.DataFrame(rows), total

    # =============================================
    # KPI 概要
    # =============================================
    st.markdown("## 📊 KPI 概要")
    total_all = res["totals"].get("合算|全期間", 0)
    total_higashi = res["totals"].get("東|全期間", 0)
    total_nishi = res["totals"].get("西|全期間", 0)
    cell_all = res["table"].get("合算|全期間", {})
    open_all = sum(v["open"] for v in cell_all.values())
    top_reason = res["reasons_order"][0] if res["reasons_order"] else "(なし)"
    top_v = cell_all.get(top_reason, {"count": 0, "open": 0})

    def _kpi(label, value, sub=""):
        return (
            f"<div style='background:#fff;border-radius:10px;padding:14px 18px;"
            f"box-shadow:0 2px 8px rgba(0,0,0,0.15);text-align:center;'>"
            f"<div style='font-size:0.85rem;color:#555;'>{label}</div>"
            f"<div style='font-size:1.7rem;font-weight:800;color:#3b2275;line-height:1.2;'>{value}</div>"
            f"<div style='font-size:0.78rem;color:#777;'>{sub}</div>"
            f"</div>"
        )

    cols = st.columns(4)
    cols[0].markdown(_kpi(
        "母集団件数（半年合算）", f"{total_all:,}",
        f"東 {total_higashi:,} ／ 西 {total_nishi:,}"), unsafe_allow_html=True)
    cols[1].markdown(_kpi(
        "うち開通済", f"{open_all:,}",
        "Field130__c(工事完了日) あり"), unsafe_allow_html=True)
    cols[2].markdown(_kpi(
        "全体開通率", _fmt_pct(open_all, total_all),
        "1次停滞経験あり群の開通到達率"), unsafe_allow_html=True)
    cols[3].markdown(_kpi(
        "最頻 1次理由", top_reason,
        f"{top_v['count']}件 / 開通率 {_fmt_pct(top_v['open'], top_v['count'])}"), unsafe_allow_html=True)
    st.divider()

    # =============================================
    # 第1章 定義
    # =============================================
    st.markdown("## 🧩 第1章 母集団・用語定義")
    defn = [
        {"項目": "取次商材", "条件": "Field76__r.Name LIKE '%So-net%'（ソネット光）"},
        {"項目": "利用携帯", "条件": "Field373__c に 'AU' または 'UQ' を含む（大小文字無視）"},
        {"項目": "エリア", "条件": "Field43__c が '東' または '西'（その他値は除外）"},
        {"項目": "1次停滞理由", "条件": "Field242__c（1次ダイコン理由）に値あり。空欄=ストレート進行は除外"},
        {"項目": "エントリ期間", "条件": f"Field156__c が直近{res['lookback_days']}日（=半年）"},
        {"項目": "開通", "条件": "Field130__c（工事完了日）にデータあり"},
        {"項目": "件数", "条件": "母集団に該当する案件数"},
        {"項目": "開通数", "条件": "件数のうち、開通(Field130__c)に到達した数"},
        {"項目": "開通率", "条件": "開通数 ÷ 件数（その理由になった案件のうち開通したか）"},
        {"項目": "発生率", "条件": "件数 ÷ 当該範囲の合計件数（理由ごとの構成比）"},
    ]
    _drs_table(pd.DataFrame(defn))
    st.divider()

    # =============================================
    # 第2章 直近半年合算（東/西/合算）
    # =============================================
    st.markdown('<div class="drs-page-break"></div>', unsafe_allow_html=True)
    st.markdown(f"## 📈 第2章 直近{res['lookback_days']}日（半年）合算")
    st.caption("合算 → 東 → 西 の順で、1次停滞理由ごとに件数・開通・開通率・発生率を提示。")

    for area in ["合算", "東", "西"]:
        st.markdown(f"### {area}")
        df, tot = _build_reason_table(area, "全期間")
        if tot == 0:
            st.info(f"{area} の該当データはありません。")
            continue
        _drs_table(df)
    st.divider()

    # =============================================
    # 第3章 エントリ月別（合算）
    # =============================================
    st.markdown('<div class="drs-page-break"></div>', unsafe_allow_html=True)
    st.markdown("## 📅 第3章 エントリ月別 推移（合算）")
    st.caption(
        "エントリ月（直近6ヶ月）ごとの1次停滞理由ごとの件数と発生率。"
        "件数が時期で偏っている理由は当該キャンペーン/工事日付け運用の影響を疑う。"
    )

    # 行=理由、列=各月の件数(発生率%)
    months = res["months"]
    rows = []
    for r in res["reasons_order"]:
        row = {"1次停滞理由": r}
        any_data = False
        for m in months:
            cell = res["table"].get(f"合算|{m}", {}).get(r)
            tot = res["totals"].get(f"合算|{m}", 0)
            if cell and cell["count"] > 0:
                any_data = True
                row[m] = f"{cell['count']} ({cell['count']/tot*100:.0f}%)" if tot else f"{cell['count']}"
            else:
                row[m] = "-"
        if any_data:
            rows.append(row)
    # 合計行
    tot_row = {"1次停滞理由": "<b>合計件数</b>"}
    for m in months:
        tot_row[m] = f"<b>{res['totals'].get(f'合算|{m}', 0)}</b>"
    rows.append(tot_row)
    _drs_table(pd.DataFrame(rows))
    st.caption("※セルは「件数 (発生率%)」。発生率は当該月の母集団に対する構成比。")
    st.divider()

    # =============================================
    # 第4章 エントリ月別×エリア（東 / 西）
    # =============================================
    st.markdown('<div class="drs-page-break"></div>', unsafe_allow_html=True)
    st.markdown("## 🗺️ 第4章 エントリ月別 × エリア別")
    st.caption("東日本と西日本で1次停滞理由の傾向に差があるかを月別で比較。")

    for area in ["東", "西"]:
        st.markdown(f"### {area}")
        rows = []
        for r in res["reasons_order"]:
            row = {"1次停滞理由": r}
            any_data = False
            for m in months:
                cell = res["table"].get(f"{area}|{m}", {}).get(r)
                tot = res["totals"].get(f"{area}|{m}", 0)
                if cell and cell["count"] > 0:
                    any_data = True
                    row[m] = f"{cell['count']} ({cell['count']/tot*100:.0f}%)" if tot else f"{cell['count']}"
                else:
                    row[m] = "-"
            if any_data:
                rows.append(row)
        tot_row = {"1次停滞理由": "<b>合計件数</b>"}
        for m in months:
            tot_row[m] = f"<b>{res['totals'].get(f'{area}|{m}', 0)}</b>"
        rows.append(tot_row)
        _drs_table(pd.DataFrame(rows))
    st.divider()

    # =============================================
    # 第5章 開通率比較
    # =============================================
    st.markdown('<div class="drs-page-break"></div>', unsafe_allow_html=True)
    st.markdown("## 🎯 第5章 1次停滞理由別 開通率 比較")
    st.caption("半年合算ベースで、合算/東/西の開通率を理由ごとに横並びで比較。深追い不要 vs 介入価値ありの判別に。")

    rows = []
    for r in res["reasons_order"]:
        row = {"1次停滞理由": r}
        for area in ["合算", "東", "西"]:
            cell = res["table"].get(f"{area}|全期間", {}).get(r)
            if cell and cell["count"] > 0:
                row[f"{area} 件数"] = cell["count"]
                row[f"{area} 開通率"] = _fmt_pct(cell["open"], cell["count"])
            else:
                row[f"{area} 件数"] = "-"
                row[f"{area} 開通率"] = "-"
        rows.append(row)
    _drs_table(pd.DataFrame(rows))
    st.caption("💡 開通率が高い理由＝介入価値大、低い理由＝諦め筋（経過観察 or 別フロー）。")

    st.stop()

# 不備停滞 切り捨て判定資料（エリア別 / リスト別 の2ボード・タブ切替）
if selected_key in ("fubitaitai_kirisute_area", "fubitaitai_kirisute_list"):
    import fubitaitai_kirisute as _fk

    # 共通: 印刷用CSS（一度だけ）
    st.markdown("""
<style>
@media print {
  section[data-testid="stSidebar"],
  header[data-testid="stHeader"],
  div[data-testid="stToolbar"],
  div[data-testid="stDecoration"],
  footer,
  .fk-no-print { display: none !important; }
  .main .block-container,
  section.main > div,
  div[data-testid="stAppViewContainer"] > section,
  div.block-container { max-width: 100% !important; padding: 6mm 8mm !important; }
  *, *::before, *::after {
    -webkit-print-color-adjust: exact !important;
    print-color-adjust: exact !important;
  }
  .fk-tbl { box-shadow: none !important; font-size: 8.5pt !important;
            page-break-inside: avoid; }
  .fk-tbl th, .fk-tbl td { padding: 3px 6px !important; }
  .fk-page-break { page-break-before: always; }
  div[style*="box-shadow"] { box-shadow: none !important; border: 1px solid #ccc !important; }
  h1, h2, h3 { color: #222 !important; }
  @page { size: A4 portrait; margin: 8mm; }
}
.fk-tbl{width:100%;border-collapse:collapse;font-size:0.93rem;
background:#fff;border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.18);margin-bottom:8px;}
.fk-tbl th,.fk-tbl td{text-align:center!important;padding:6px 10px;border:1px solid #e0e0e0;color:#222!important;}
.fk-tbl th{background:rgba(107,70,193,0.18);color:#3b2275!important;font-weight:700;}
.fk-tbl td:first-child{text-align:left!important;font-weight:600;}
.fk-tbl tr:nth-child(even) td{background:#faf9fd;}
.fk-tbl tr.row-kiri td{background:#fde8e8!important;}
.fk-tbl tr.row-good td{background:#e8f5e9!important;}
</style>
""", unsafe_allow_html=True)

    def _fk_table(df):
        _html = df.to_html(index=False, escape=False).replace("<table", '<table class="fk-tbl"', 1)
        st.markdown(f'<div style="overflow-x:auto">{_html}</div>', unsafe_allow_html=True)

    def _fk_kpi(label, value, sub=""):
        return (
            f"<div style='background:#fff;border-radius:10px;padding:14px 18px;"
            f"box-shadow:0 2px 8px rgba(0,0,0,0.15);text-align:center;'>"
            f"<div style='font-size:0.85rem;color:#555;'>{label}</div>"
            f"<div style='font-size:1.7rem;font-weight:800;color:#3b2275;line-height:1.2;'>{value}</div>"
            f"<div style='font-size:0.78rem;color:#777;'>{sub}</div>"
            f"</div>"
        )

    def _fk_badge(rate):
        c = _fk.classify(rate)
        color = {"切り捨て推奨": "#b94a48", "グレーゾーン": "#d4860a", "介入価値大": "#1e7e34"}.get(c, "#666")
        return f"<span style='color:{color};font-weight:700;'>{c}</span>"

    def _render_kirisute(res, area_label, key_prefix):
        """1タブ分の描画（KPI〜結論）。key_prefixはウィジェットキー衝突回避用。"""
        # ヘッダー: 再集計ボタン
        _c1, _c2, _c3 = st.columns([1, 1, 4])
        with _c1:
            st.markdown('<div class="fk-no-print">', unsafe_allow_html=True)
            if st.button("🔄 再集計", key=f"fk_reload_{key_prefix}"):
                # 各タブ専用ローダーをここで都度clearするのは難しい
                # → ボード全体の再集計は上部のボタンで担うため、ここはタブ単位で行う
                st.cache_data.clear()
                st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)
        st.caption(
            f"集計時点: {res['asof']}　対象: {area_label}　"
            f"集計期間: 直近180日 / 直近365日（直近{res.get('exclude_recent_days', 90)}日除外、"
            f"カットオフ {res.get('cutoff_iso', '')} 以前のエントリ）"
        )

        p180 = res["by_period"][180]
        p365 = res["by_period"][365]

        # KPI 概要
        st.markdown("### 📊 KPI 概要")
        cols = st.columns(4)
        cols[0].markdown(_fk_kpi(
            "母集団 直近180日", f"{p180['total']:,}",
            f"開通{p180['total_open']:,}件 ({p180['total_open']/p180['total']*100:.1f}%)"
            if p180['total'] else ""
        ), unsafe_allow_html=True)
        cols[1].markdown(_fk_kpi(
            "母集団 直近365日", f"{p365['total']:,}",
            f"開通{p365['total_open']:,}件 ({p365['total_open']/p365['total']*100:.1f}%)"
            if p365['total'] else ""
        ), unsafe_allow_html=True)
        n_kiri_180 = sum(1 for r in p180['rows'] if r['open_rate'] < 20)
        n_kiri_365 = sum(1 for r in p365['rows'] if r['open_rate'] < 20)
        cols[2].markdown(_fk_kpi(
            "切り捨て候補 (180日)", f"{n_kiri_180}理由", "開通率<20%の理由数"
        ), unsafe_allow_html=True)
        cols[3].markdown(_fk_kpi(
            "切り捨て候補 (365日)", f"{n_kiri_365}理由", "開通率<20%の理由数"
        ), unsafe_allow_html=True)
        st.divider()

        # 第1章 母集団・指標定義
        st.markdown("### 🧩 第1章 母集団・指標定義")
        defn = [
            {"項目": "取次商材", "条件": "Field76__r.Name LIKE '%So-net%'（ソネット光）"},
            {"項目": "エントリ期間", "条件": f"Field156__c が直近180日 / 直近365日かつ {res.get('cutoff_iso', '')} 以前（直近3ヶ月除外＝結果未確定の案件を弾く）"},
            {"項目": "対象", "条件": f"{area_label}"},
            {"項目": "経験ベース", "条件": "1次〜10次のダイコン理由(Field242〜246/341〜345)のいずれかに該当理由を含む案件"},
            {"項目": "経験数 N", "条件": "その理由を1度でも経験した案件数（同一案件は1件としてカウント）"},
            {"項目": "発生率", "条件": "N ÷ その期間の母集団全件数（理由ごとの構成比）"},
            {"項目": "開通数", "条件": "Nのうち、開通(Field130__c)に到達した数"},
            {"項目": "開通率", "条件": "開通数 ÷ N"},
            {"項目": "平均架電", "条件": "開通済み案件が受けた代コン系FC（代コン/代コン窓口/工事取得）の平均回数（0回除外）"},
            {"項目": "⚠️ CX率を使わない理由", "条件": "ダイコン理由はCX完了後にも追記される運用のため、CX率は因果分析に使えない"},
            {"項目": "判定基準", "条件": "切り捨て推奨=開通率<20% ／ グレー=20-35% ／ 介入価値大=35%以上"},
            {"項目": "サンプル基準", "条件": "経験数N≧30 の理由のみ集計対象"},
        ]
        _fk_table(pd.DataFrame(defn))
        st.divider()

        # 第2章 両期間並列比較
        st.markdown('<div class="fk-page-break"></div>', unsafe_allow_html=True)
        st.markdown("### 📊 第2章 両期間 並列比較（メイン表）")
        rows_main = []
        for reason in res["reasons_order"]:
            v180 = next((r for r in p180["rows"] if r["reason"] == reason), None)
            v365 = next((r for r in p365["rows"] if r["reason"] == reason), None)
            row = {"不備停滞理由": reason}
            if v180:
                row["180日 経験数"] = v180["n"]
                row["180日 発生率"] = f"{v180['occur_rate']:.1f}%"
                row["180日 開通率"] = f"{v180['open_rate']:.1f}%"
                row["180日 平均架電"] = f"{v180['fc_avg_pos']:.1f}回"
            else:
                row["180日 経験数"] = "-"; row["180日 発生率"] = "-"; row["180日 開通率"] = "-"; row["180日 平均架電"] = "-"
            if v365:
                row["365日 経験数"] = v365["n"]
                row["365日 発生率"] = f"{v365['occur_rate']:.1f}%"
                row["365日 開通率"] = f"{v365['open_rate']:.1f}%"
                row["365日 平均架電"] = f"{v365['fc_avg_pos']:.1f}回"
                row["判定 (365日)"] = _fk_badge(v365["open_rate"])
            else:
                row["365日 経験数"] = "-"; row["365日 発生率"] = "-"; row["365日 開通率"] = "-"; row["365日 平均架電"] = "-"; row["判定 (365日)"] = "-"
            rows_main.append(row)
        _fk_table(pd.DataFrame(rows_main))
        st.divider()

        # 第3〜5章: 切り捨て / グレー / 介入価値大
        def _bucket_table(rows, sort_by_n=False):
            if sort_by_n:
                rows = sorted(rows, key=lambda x: -x["n"])
            else:
                rows = sorted(rows, key=lambda x: x["open_rate"])
            return pd.DataFrame([
                {
                    "不備停滞理由": r["reason"],
                    "経験数": r["n"],
                    "発生率": f"{r['occur_rate']:.1f}%",
                    "開通数": r["open"],
                    "開通率": f"{r['open_rate']:.1f}%",
                    "平均架電": f"{r['fc_avg_pos']:.1f}回",
                }
                for r in rows
            ])

        st.markdown('<div class="fk-page-break"></div>', unsafe_allow_html=True)
        st.markdown("### 🔴 第3章 切り捨て推奨（開通率<20%）")
        for days, p in [(180, p180), (365, p365)]:
            st.markdown(f"**直近{days}日**")
            kiri = [r for r in p["rows"] if r["open_rate"] < 20]
            if not kiri:
                st.info("該当なし")
            else:
                _fk_table(_bucket_table(kiri))
        st.divider()

        st.markdown('<div class="fk-page-break"></div>', unsafe_allow_html=True)
        st.markdown("### 🟡 第4章 グレーゾーン（開通率 20-35%）")
        for days, p in [(180, p180), (365, p365)]:
            st.markdown(f"**直近{days}日**")
            gray = [r for r in p["rows"] if 20 <= r["open_rate"] < 35]
            if not gray:
                st.info("該当なし")
            else:
                _fk_table(_bucket_table(gray, sort_by_n=True))
        st.divider()

        st.markdown('<div class="fk-page-break"></div>', unsafe_allow_html=True)
        st.markdown("### 🟢 第5章 介入価値大（開通率 35%以上）")
        for days, p in [(180, p180), (365, p365)]:
            st.markdown(f"**直近{days}日**")
            good = sorted([r for r in p["rows"] if r["open_rate"] >= 35], key=lambda x: -x["open_rate"])
            if not good:
                st.info("該当なし")
            else:
                _fk_table(_bucket_table(good))
        st.divider()

        # 第6章 結論
        st.markdown('<div class="fk-page-break"></div>', unsafe_allow_html=True)
        st.markdown("### 🏁 第6章 結論・運用提案")
        kiri_names = [r["reason"] for r in p365["rows"] if r["open_rate"] < 20]
        good_names = [r["reason"] for r in p365["rows"] if r["open_rate"] >= 35]
        gray_top_365 = sorted(
            [r for r in p365["rows"] if 20 <= r["open_rate"] < 35],
            key=lambda x: -x["n"],
        )[:3]
        st.markdown(f"""
<div style='background:#fff;border-radius:10px;padding:16px 22px;box-shadow:0 2px 8px rgba(0,0,0,0.15);line-height:1.8;'>

**① 切り捨て対象（直近365日基準・開通率<20%・対象={area_label}）**
- {' / '.join(kiri_names) if kiri_names else '該当なし'}

**② 集中投下先（直近365日基準・開通率≥35%）**
- {' / '.join(good_names) if good_names else '該当なし'}

**③ ボリュームゾーンへの中量投下（件数最大のグレー上位）**
{''.join([f'- **{r["reason"]}** ({r['n']:,}件 / 開通率{r['open_rate']:.1f}% / 平均{r['fc_avg_pos']:.1f}回)' + chr(10) for r in gray_top_365])}

</div>
""", unsafe_allow_html=True)

    # ボード分岐: エリア別 / リスト別
    if selected_key == "fubitaitai_kirisute_area":
        st.title("不備停滞 切り捨て判定資料（エリア別）")
        st.caption(
            "ソネット光の不備停滞理由別・経験ベース集計を「全件 / 東日本 / 西日本」のタブで切り替えて表示します。"
            " 直近3ヶ月のエントリは除外。"
        )
        tab_configs = [
            ("全件（東+西）", _load_fubitaitai_kirisute, "all"),
            ("東日本",        _load_fubitaitai_kirisute_higashi, "higashi"),
            ("西日本",        _load_fubitaitai_kirisute_nishi,   "nishi"),
        ]
    else:  # fubitaitai_kirisute_list
        st.title("不備停滞 切り捨て判定資料（リスト別）")
        st.caption(
            "ソネット光の不備停滞理由別・経験ベース集計をリスト別タブ（AUリスト / ドコモリスト / SBリスト）で表示します。"
            " 利用携帯Ⅰ/Ⅱ(Field12__c/Field13__c)のpicklistでリスト判定。直近3ヶ月のエントリは除外。"
        )
        tab_configs = [
            ("AUリスト（KDDI/UQ）",            _load_fubitaitai_kirisute_au,     "au"),
            ("ドコモリスト",                   _load_fubitaitai_kirisute_docomo, "docomo"),
            ("SBリスト（Softbank/Y!mobile）",  _load_fubitaitai_kirisute_sb,     "sb"),
        ]

    # 共通: PDF保存ボタン（現在表示中のタブが対象）
    _pdf_c1, _pdf_c2 = st.columns([1, 5])
    with _pdf_c1:
        import streamlit.components.v1 as _components
        _components.html(
            """
            <div class="fk-no-print">
              <button onclick="window.parent.print()"
                style="background:#5a3a00;color:#fff;border:none;padding:8px 18px;
                       border-radius:6px;cursor:pointer;font-weight:700;font-size:0.95rem;
                       box-shadow:0 2px 6px rgba(0,0,0,0.2);">
                🖨️ PDFに保存
              </button>
            </div>
            """,
            height=46,
        )
    st.caption("💡 PDF保存は『現在開いているタブ』が対象。タブを切り替えてから保存ボタンを押してください。")

    tab_labels = [c[0] for c in tab_configs]
    tabs = st.tabs(tab_labels)
    for tab, (label, loader, prefix) in zip(tabs, tab_configs):
        with tab:
            _res = loader(_daily_cache_key())
            _render_kirisute(_res, label, prefix)

    st.stop()

# スキルツリーボード(SVG手描き / Sheetsから動的読込)
if selected_key == "skill_tree":
    from skill_tree_store import (
        get_skill_tree, save_skill_tree, clear_skill_tree_cache, next_branch_id,
    )

    # 上方向(子→親)伝搬: 子全部チェックなら親自動チェック(再帰)
    def _skt_propagate(branch_data):
        _nodes_b = branch_data.get("nodes", []) or []
        _children_of = {}
        for _n in _nodes_b:
            _p = _n.get("parent")
            if _p is not None:
                _children_of.setdefault(_p, []).append(_n["id"])
        _by_id = {_n["id"]: _n for _n in _nodes_b}
        _changed = True
        while _changed:
            _changed = False
            for _n in _nodes_b:
                _chs = _children_of.get(_n["id"], [])
                if not _chs:
                    continue
                _new_v = all(_by_id[_c].get("checked", False) for _c in _chs)
                if bool(_n.get("checked", False)) != _new_v:
                    _n["checked"] = _new_v
                    _changed = True

    # 下方向(親→子孫)伝搬: 親をチェック/解除するとすべての子孫に同じ値を適用
    def _skt_propagate_down(branch_data, root_id, value):
        _nodes_b = branch_data.get("nodes", []) or []
        _children_of = {}
        for _n in _nodes_b:
            _p = _n.get("parent")
            if _p is not None:
                _children_of.setdefault(_p, []).append(_n["id"])
        _by_id = {_n["id"]: _n for _n in _nodes_b}
        _stack = list(_children_of.get(root_id, []))
        while _stack:
            _cur = _stack.pop()
            _node_cur = _by_id.get(_cur)
            if _node_cur is None:
                continue
            _node_cur["checked"] = value
            _stack.extend(_children_of.get(_cur, []))

    # チェックボックス変更時の自動保存コールバック(双方向伝搬付き)
    def _skt_on_check_change(_bid, _nid, _wkey):
        _new_val = bool(st.session_state.get(_wkey, False))
        try:
            _data_x = get_skill_tree()
            for _b in _data_x.get("branches", []):
                if int(_b.get("id", 0)) == _bid:
                    # 対象ノードを更新
                    _has_children = False
                    for _n in _b.get("nodes", []):
                        if int(_n.get("id", 0)) == _nid:
                            _n["checked"] = _new_val
                    # 子孫の存在判定
                    _has_children = any(
                        _n.get("parent") == _nid for _n in _b.get("nodes", [])
                    )
                    # 親をトグルしたら子孫も同じ値に
                    if _has_children:
                        _skt_propagate_down(_b, _nid, _new_val)
                    # 子→親 自動チェック
                    _skt_propagate(_b)
                    # session_state のチェックboxウィジェットも同期
                    for _n in _b.get("nodes", []):
                        _wkey2 = f"skt_inline_b{_bid}_n{_n['id']}"
                        st.session_state[_wkey2] = bool(_n.get("checked", False))
                    break
            save_skill_tree(_data_x)
        except Exception as _e:
            st.toast(f"保存失敗: {_e}", icon="⚠️")

    # ノード操作コールバック(編集UI)
    def _skt_cb_add_child(_bid, _parent_nid):
        _skt0 = st.session_state.get("skt_edit")
        if not _skt0:
            return
        for _b in _skt0.get("branches", []):
            if _b.get("id") == _bid:
                _ns = _b.setdefault("nodes", [])
                _max = max([n["id"] for n in _ns] + [0])
                _ns.append({
                    "id": _max + 1,
                    "label": "新規ノード",
                    "parent": _parent_nid,
                    "checked": False,
                })
                return

    def _skt_cb_del_node(_bid, _nid):
        """ノード削除: 配下の子孫もすべて再帰的に削除する。"""
        _skt0 = st.session_state.get("skt_edit")
        if not _skt0:
            return
        for _b in _skt0.get("branches", []):
            if _b.get("id") == _bid:
                _ns = _b.get("nodes", []) or []
                # 子孫を辿って削除対象IDを収集
                _children_of: dict = {}
                for _n in _ns:
                    _p = _n.get("parent")
                    if _p is not None:
                        _children_of.setdefault(_p, []).append(_n["id"])
                _to_remove = set()
                _stack = [_nid]
                while _stack:
                    _cur = _stack.pop()
                    if _cur in _to_remove:
                        continue
                    _to_remove.add(_cur)
                    _stack.extend(_children_of.get(_cur, []))
                _b["nodes"] = [_n for _n in _ns if _n.get("id") not in _to_remove]
                return

    def _skt_cb_move_node(_bid, _nid, _dir):
        """兄弟間でサブツリーごと位置入れ替え。"""
        _skt0 = st.session_state.get("skt_edit")
        if not _skt0:
            return
        for _b in _skt0.get("branches", []):
            if _b.get("id") != _bid:
                continue
            _ns = _b.get("nodes", []) or []
            # 対象ノード
            _t_idx = None
            _t_parent = None
            for _i, _n in enumerate(_ns):
                if _n.get("id") == _nid:
                    _t_idx = _i
                    _t_parent = _n.get("parent")
                    break
            if _t_idx is None:
                return
            # 同一親の兄弟インデックス
            _sib_idxs = [_i for _i, _n in enumerate(_ns) if _n.get("parent") == _t_parent]
            try:
                _pos = _sib_idxs.index(_t_idx)
            except ValueError:
                return
            _other_idx = None
            if _dir == "up" and _pos > 0:
                _other_idx = _sib_idxs[_pos - 1]
            elif _dir == "down" and _pos < len(_sib_idxs) - 1:
                _other_idx = _sib_idxs[_pos + 1]
            if _other_idx is None:
                return
            # サブツリー(子孫)IDを収集
            def _subtree_ids(_start_id):
                _ids = {_start_id}
                _stack = [_start_id]
                while _stack:
                    _cur = _stack.pop()
                    for _n in _ns:
                        if _n.get("parent") == _cur and _n["id"] not in _ids:
                            _ids.add(_n["id"])
                            _stack.append(_n["id"])
                return _ids
            _t_id = _ns[_t_idx]["id"]
            _o_id = _ns[_other_idx]["id"]
            _t_set = _subtree_ids(_t_id)
            _o_set = _subtree_ids(_o_id)
            # 各サブツリーをリスト順に抽出
            _t_block = [_n for _n in _ns if _n["id"] in _t_set]
            _o_block = [_n for _n in _ns if _n["id"] in _o_set]
            _remaining = [_n for _n in _ns if _n["id"] not in _t_set and _n["id"] not in _o_set]
            # 挿入位置: 元の最初のサブツリー先頭の手前にあった「remaining」要素数
            _first_pos = min(_t_idx, _other_idx)
            _insert_pos = sum(
                1 for _i, _n in enumerate(_ns)
                if _i < _first_pos and _n["id"] not in _t_set and _n["id"] not in _o_set
            )
            # 並び順決定
            if _dir == "up":
                _new_block = _t_block + _o_block
            else:
                _new_block = _o_block + _t_block
            _new_list = _remaining[:_insert_pos] + _new_block + _remaining[_insert_pos:]
            _ns.clear()
            _ns.extend(_new_list)
            return

    # ----- 編集UI(画面上で直接編集) -----
    with st.expander("✏ 編集する", expanded=False):
        st.caption(
            "起点ラベル・分岐の名前/色/ステージを編集できます。"
            "「💾 保存」を押すと全ユーザーに反映されます。"
        )

        if "skt_edit" not in st.session_state:
            try:
                st.session_state["skt_edit"] = get_skill_tree()
            except Exception as _e:
                st.error(f"読み込みに失敗: {_e}")
                st.session_state["skt_edit"] = None

        if st.session_state.get("skt_edit") is not None:
            _skt = st.session_state["skt_edit"]

            _starts_list = _skt.get("start_labels") or ["新人入社"]
            _starts_text = "\n".join(_starts_list)
            _new_starts = st.text_area(
                "起点ラベル（1行=1ノード、上から下へ縦に並ぶ）",
                value=_starts_text,
                key="skt_in_starts",
                height=110,
            )
            _skt["start_labels"] = [s.strip() for s in _new_starts.split("\n") if s.strip()] or ["新人入社"]

            st.markdown("**分岐**")

            _del_idx = None
            _move_op = None

            for _idx, _branch in enumerate(_skt.get("branches", [])):
                _bid = _branch.get("id", _idx)
                with st.container(border=True):
                    _c1, _c2, _c3, _c4, _c5 = st.columns([4, 1.4, 0.6, 0.6, 0.6])
                    _branch["label"] = _c1.text_input(
                        "分岐名", value=_branch.get("label", ""),
                        key=f"skt_in_b{_bid}_label",
                    )
                    _branch["color"] = _c2.color_picker(
                        "色", value=_branch.get("color", "#888888"),
                        key=f"skt_in_b{_bid}_color",
                    )
                    if _idx > 0:
                        if _c3.button("⬆", key=f"skt_b{_bid}_up", help="上へ"):
                            _move_op = (_idx, "up")
                    if _idx < len(_skt["branches"]) - 1:
                        if _c4.button("⬇", key=f"skt_b{_bid}_down", help="下へ"):
                            _move_op = (_idx, "down")
                    if _c5.button("🗑", key=f"skt_b{_bid}_del", help="削除"):
                        _del_idx = _idx

                    # ノード(ツリー構造) ----
                    _nodes = _branch.setdefault("nodes", [])
                    if _nodes:
                        _node_ids = [n["id"] for n in _nodes]
                        _label_by_id = {n["id"]: n.get("label", "") for n in _nodes}

                        # 親→兄弟ID列(リスト順) を作成して、兄弟内位置を判定
                        _parent_to_sibs = {}
                        for _nx in _nodes:
                            _parent_to_sibs.setdefault(_nx.get("parent"), []).append(_nx["id"])

                        # DFS順序＆深さ計算(表示用)
                        _kids_of = {}
                        for _nx in _nodes:
                            _p_x = _nx.get("parent")
                            _kids_of.setdefault(_p_x, []).append(_nx["id"])
                        _node_by_id = {_nx["id"]: _nx for _nx in _nodes}
                        _ordered = []  # [(node, depth), ...]
                        def _dfs_order(_pid, _depth):
                            for _cid in _kids_of.get(_pid, []):
                                if _cid in _node_by_id:
                                    _ordered.append((_node_by_id[_cid], _depth))
                                    _dfs_order(_cid, _depth + 1)
                        _dfs_order(None, 0)
                        # 万一フラット内に到達できないノードがあれば末尾に追加
                        _seen_ids = {n["id"] for (n, _) in _ordered}
                        for _nx in _nodes:
                            if _nx["id"] not in _seen_ids:
                                _ordered.append((_nx, 0))

                        _branch_color_e = (_branch.get("color") or "#888888").strip() or "#888888"

                        for _ni, (_node, _depth) in enumerate(_ordered):
                            _nid = _node["id"]
                            _ncl, _nc1, _nc2, _ncu, _ncd, _nc3, _nc4 = st.columns(
                                [0.7, 3, 2.2, 0.6, 0.6, 1.2, 1]
                            )
                            # 深さインジケーター(色付きツリーマーク)
                            if _depth == 0:
                                _prefix_html = (
                                    f"<span style='color:{_branch_color_e};"
                                    f"font-weight:800;font-size:18px;'>●</span>"
                                )
                            else:
                                _opacity = max(0.35, 1 - _depth * 0.15)
                                _prefix_html = (
                                    f"<span style='color:{_branch_color_e};"
                                    f"opacity:{_opacity};font-weight:600;'>"
                                    f"{'　' * _depth}└─</span>"
                                )
                            _ncl.markdown(
                                f"<div style='padding-top:6px;font-size:14px;"
                                f"white-space:nowrap;'>{_prefix_html}</div>",
                                unsafe_allow_html=True,
                            )
                            _node["label"] = _nc1.text_input(
                                f"ノード {_ni + 1}",
                                value=_node.get("label", ""),
                                key=f"skt_in_b{_bid}_n{_nid}_label",
                                label_visibility="collapsed",
                                placeholder="ノード名",
                            )
                            # 親選択(自分・自分の子孫を除外、循環防止)
                            _desc_set = set()
                            _stack_d = [_nid]
                            while _stack_d:
                                _cur_d = _stack_d.pop()
                                for _n_d in _nodes:
                                    if _n_d.get("parent") == _cur_d and _n_d["id"] not in _desc_set:
                                        _desc_set.add(_n_d["id"])
                                        _stack_d.append(_n_d["id"])
                            _opt_ids = [None] + [
                                _n["id"] for _n in _nodes
                                if _n["id"] != _nid and _n["id"] not in _desc_set
                            ]
                            _opt_labels = ["（ルート）"] + [
                                f"└ {_label_by_id.get(_oid, '')} #{_oid}"
                                for _oid in _opt_ids[1:]
                            ]
                            _cur_parent = _node.get("parent")
                            try:
                                _idx_p = _opt_ids.index(_cur_parent)
                            except ValueError:
                                _idx_p = 0
                            _new_p_idx = _nc2.selectbox(
                                f"親 (ノード{_ni + 1})",
                                options=list(range(len(_opt_ids))),
                                index=_idx_p,
                                format_func=lambda i, ol=_opt_labels: ol[i],
                                key=f"skt_in_b{_bid}_n{_nid}_parent",
                                label_visibility="collapsed",
                            )
                            _node["parent"] = _opt_ids[_new_p_idx]
                            # 同一親の兄弟内での位置を判定
                            _sib_ids = _parent_to_sibs.get(_node.get("parent"), [])
                            try:
                                _sib_pos = _sib_ids.index(_nid)
                            except ValueError:
                                _sib_pos = 0
                            _has_prev_sib = _sib_pos > 0
                            _has_next_sib = _sib_pos < len(_sib_ids) - 1
                            if _has_prev_sib:
                                _ncu.button(
                                    "⬆",
                                    key=f"skt_b{_bid}_n{_nid}_up",
                                    help="兄弟内で上へ(サブツリーごと)",
                                    use_container_width=True,
                                    on_click=_skt_cb_move_node,
                                    args=(_bid, _nid, "up"),
                                )
                            if _has_next_sib:
                                _ncd.button(
                                    "⬇",
                                    key=f"skt_b{_bid}_n{_nid}_down",
                                    help="兄弟内で下へ(サブツリーごと)",
                                    use_container_width=True,
                                    on_click=_skt_cb_move_node,
                                    args=(_bid, _nid, "down"),
                                )
                            _nc3.button(
                                "➕ 子",
                                key=f"skt_b{_bid}_n{_nid}_addchild",
                                help="このノードの子を追加",
                                use_container_width=True,
                                on_click=_skt_cb_add_child,
                                args=(_bid, _nid),
                            )
                            _nc4.button(
                                "🗑",
                                key=f"skt_b{_bid}_n{_nid}_del",
                                help="削除",
                                use_container_width=True,
                                on_click=_skt_cb_del_node,
                                args=(_bid, _nid),
                            )

                    # ノード追加(ルート/子の選択可)
                    _add_c1, _add_c2, _add_c3 = st.columns([4, 1, 1])
                    _new_node_label = _add_c1.text_input(
                        "新規ノード名",
                        key=f"skt_in_b{_bid}_new_node_label",
                        placeholder="新規ノード名",
                        label_visibility="collapsed",
                    )
                    _add_root = _add_c2.button(
                        "🌱 ルート", key=f"skt_b{_bid}_n_add_root",
                        use_container_width=True, help="分岐ヘッダ直下のルートノードを追加",
                    )
                    _add_child = _add_c3.button(
                        "➕ 子ノード", key=f"skt_b{_bid}_n_add_child",
                        use_container_width=True, help="最後のノードの子として追加(後で親変更可)",
                    )
                    if _add_root or _add_child:
                        _lab = (_new_node_label or "").strip() or "新規ノード"
                        _max_nid = max([n["id"] for n in _nodes] + [0])
                        if _add_root or not _nodes:
                            _new_parent = None
                        else:
                            _new_parent = _nodes[-1]["id"]
                        _nodes.append({
                            "id": _max_nid + 1,
                            "label": _lab,
                            "parent": _new_parent,
                        })
                        _k_new = f"skt_in_b{_bid}_new_node_label"
                        if _k_new in st.session_state:
                            del st.session_state[_k_new]
                        st.rerun()

            if _move_op is not None:
                _i, _dir = _move_op
                if _dir == "up" and _i > 0:
                    _skt["branches"][_i - 1], _skt["branches"][_i] = (
                        _skt["branches"][_i], _skt["branches"][_i - 1]
                    )
                elif _dir == "down" and _i < len(_skt["branches"]) - 1:
                    _skt["branches"][_i], _skt["branches"][_i + 1] = (
                        _skt["branches"][_i + 1], _skt["branches"][_i]
                    )
                st.rerun()

            if _del_idx is not None:
                _skt["branches"].pop(_del_idx)
                st.rerun()

            if st.button("➕ 分岐を追加", key="skt_add_branch"):
                _skt["branches"].append({
                    "id": next_branch_id(_skt["branches"]),
                    "label": "新規分岐",
                    "color": "#888888",
                    "stages": ["ステージ1"],
                })
                st.rerun()

            st.markdown("---")
            _sc1, _sc2 = st.columns([1, 1])
            if _sc1.button("💾 保存", key="skt_save", type="primary",
                           use_container_width=True):
                try:
                    # 構造保存時に最新の習得チェック状態を保持(クリック保存と競合させない)
                    _latest_checks = get_skill_tree()
                    _check_map = {
                        (int(_b.get("id", 0)), int(_n.get("id", 0))): bool(_n.get("checked", False))
                        for _b in _latest_checks.get("branches", [])
                        for _n in _b.get("nodes", [])
                    }
                    for _b in _skt.get("branches", []):
                        _bid_s = int(_b.get("id", 0))
                        for _n in _b.get("nodes", []):
                            _kc = (_bid_s, int(_n.get("id", 0)))
                            if _kc in _check_map:
                                _n["checked"] = _check_map[_kc]
                    ok, msg = save_skill_tree(_skt)
                    st.toast(msg, icon="✅" if ok else "⚠️")
                    for _k in list(st.session_state.keys()):
                        if _k.startswith("skt_in_") or _k == "skt_edit":
                            del st.session_state[_k]
                    st.rerun()
                except Exception as _e:
                    st.error(f"保存に失敗: {_e}")

            if _sc2.button("🔄 リセット(Sheetsから再読込)", key="skt_reset",
                           use_container_width=True):
                clear_skill_tree_cache()
                for _k in list(st.session_state.keys()):
                    if _k.startswith("skt_in_") or _k == "skt_edit":
                        del st.session_state[_k]
                st.rerun()

    # ----- 表示(Sheetsの確定版を読込) -----
    try:
        _skt_data = get_skill_tree()
    except Exception as _e:
        st.error(f"スキルツリーデータの読み込みに失敗: {_e}")
        st.stop()

    _start_labels = [
        s.strip() for s in (_skt_data.get("start_labels") or []) if s and s.strip()
    ] or ["新人入社"]

    def _skt_clean_branch(_b):
        _bid = _b.get("id")
        _lab = (_b.get("label") or "").strip()
        _col = (_b.get("color") or "#888888").strip() or "#888888"
        _ns_raw = _b.get("nodes") or []
        _id_set = {n.get("id") for n in _ns_raw}
        # parent が存在しない id を指していたら None に正規化
        _ns = []
        for _n in _ns_raw:
            if not (_n.get("label") or "").strip():
                continue
            _p = _n.get("parent")
            if _p is not None and _p not in _id_set:
                _p = None
            _ns.append({
                "id": _n["id"],
                "label": _n["label"].strip(),
                "parent": _p,
                "checked": bool(_n.get("checked", False)),
                "memo": (_n.get("memo") or "").strip(),
            })
        return _bid, _lab, _col, _ns

    _branches_src = [_skt_clean_branch(b) for b in _skt_data.get("branches", [])]
    _branches_src = [(bid, l, c, n) for (bid, l, c, n) in _branches_src if l and n]
    if not _branches_src:
        st.info("スキルツリーが未定義です。「✏ 編集する」から分岐とノードを作成してください。")
        st.stop()

    # 習得率(チェックされたノード / 全ノード)
    _total_nodes = sum(len(_n) for (_bid, _l, _c, _n) in _branches_src)
    _checked_nodes = sum(
        1 for (_bid, _l, _c, _n) in _branches_src for _nd in _n if _nd.get("checked")
    )
    _pct = (_checked_nodes / _total_nodes * 100) if _total_nodes else 0.0
    st.markdown(
        f"<div style='font-size:18px;font-weight:700;margin:6px 0;'>"
        f"🎯 習得率 <span style='color:#16a34a;'>{_pct:.1f}%</span> "
        f"<span style='font-size:13px;color:#666;font-weight:500;'>"
        f"({_checked_nodes} / {_total_nodes})</span></div>",
        unsafe_allow_html=True,
    )
    st.progress(_checked_nodes / _total_nodes if _total_nodes else 0.0)

    _PILL_W = 180
    _PILL_H = 44
    _NODE_X_UNIT = 200  # ノード水平方向の最小スロット幅
    _NODE_Y_GAP = 78    # ノード縦方向 top-to-top
    _BRANCH_X_PAD = 60  # 分岐(ツリー)同士の左右パディング
    _START_Y = 20
    _START_GAP = 60     # 起点ピル top-to-top
    _LEFT_PAD = 60
    _BANNER_TOP_RESERVE = 220  # 上端ノードのホバーバナー描画スペース
    _n_starts = len(_start_labels)
    _last_start_top = _START_Y + (_n_starts - 1) * _START_GAP
    _last_start_bottom = _last_start_top + _PILL_H
    _HEADER_Y = _last_start_bottom + 50

    # 各分岐のツリー配置を計算 (循環耐性あり)
    def _layout_tree(_nodes, _x_offset):
        """各分岐内のノード位置(ツリー)。返り値: positions, max_depth, width, roots."""
        _by_id = {n["id"]: n for n in _nodes}
        _children = {}
        _roots = []
        for _n in _nodes:
            _p = _n.get("parent")
            if _p is None or _p not in _by_id:
                _roots.append(_n["id"])
            else:
                _children.setdefault(_p, []).append(_n["id"])
        _positions = {}
        _max_d = [0]
        _cursor = [_x_offset]
        _visited = set()

        def _place(nid, depth):
            if nid in _visited:
                return  # 循環ガード
            _visited.add(nid)
            _max_d[0] = max(_max_d[0], depth)
            ch = _children.get(nid, [])
            if not ch:
                _x = _cursor[0]
                _cursor[0] += _NODE_X_UNIT
                _positions[nid] = (_x, depth)
                return
            for c in ch:
                _place(c, depth + 1)
            _placed_xs = [_positions[c][0] for c in ch if c in _positions]
            if _placed_xs:
                _positions[nid] = ((_placed_xs[0] + _placed_xs[-1]) / 2, depth)
            else:
                _x = _cursor[0]
                _cursor[0] += _NODE_X_UNIT
                _positions[nid] = (_x, depth)

        for _r in _roots:
            _place(_r, 0)
        # 配置されなかったノード(循環の一部など)は仮のルートとして配置
        for _n in _nodes:
            if _n["id"] not in _positions:
                _x = _cursor[0]
                _cursor[0] += _NODE_X_UNIT
                _positions[_n["id"]] = (_x, 0)
                if _n["id"] not in _roots:
                    _roots.append(_n["id"])
        _width = _cursor[0] - _x_offset
        if _width <= 0:
            _width = _NODE_X_UNIT
        return _positions, _max_d[0], _width, _roots

    _branch_layouts = []
    _x_cursor = _LEFT_PAD
    for _bid, _label, _color, _nodes in _branches_src:
        _pos, _max_d, _w, _roots = _layout_tree(_nodes, _x_cursor)
        _branch_layouts.append({
            "id": _bid,
            "label": _label, "color": _color, "nodes": _nodes,
            "positions": _pos, "max_depth": _max_d,
            "width": _w, "roots": _roots,
            "x_start": _x_cursor,
            "x_end": _x_cursor + _w,
        })
        _x_cursor += _w + _BRANCH_X_PAD

    _SVG_W = max(_x_cursor + _LEFT_PAD - _BRANCH_X_PAD, 600)
    _max_depth_all = max((bl["max_depth"] for bl in _branch_layouts), default=0)
    # 分岐ヘッダ行 = depth 0 の上、その下にdepth 0..max_depth_all のノードが並ぶ
    _SVG_H = _HEADER_Y + (_max_depth_all + 1) * _NODE_Y_GAP + _PILL_H + 24

    import html as _skt_html
    _SVG_VIEW_Y = -_BANNER_TOP_RESERVE
    _SVG_VIEW_H = _SVG_H + _BANNER_TOP_RESERVE
    _parts = [
        '<div style="overflow-x:auto;overflow-y:visible;padding-bottom:8px;">',
        f'<svg viewBox="0 {_SVG_VIEW_Y} {_SVG_W} {_SVG_VIEW_H}" '
        f'xmlns="http://www.w3.org/2000/svg" '
        f'width="{_SVG_W}" height="{_SVG_VIEW_H}" '
        f'style="display:block;font-size:13px;overflow:visible;">'
    ]
    _parts.append(
        '<style>'
        '.skt-node .skt-banner { opacity: 0; pointer-events: none; '
        'transition: opacity 0.12s ease-in-out; } '
        '.skt-node:hover .skt-banner { opacity: 1; }'
        '</style>'
    )
    _parts.append('<defs>')
    _parts.append(
        '<filter id="sk_shadow" x="-50%" y="-50%" width="200%" height="200%">'
        '<feDropShadow dx="0" dy="2" stdDeviation="3" flood-opacity="0.35"/></filter>'
    )
    for _gi, _bl in enumerate(_branch_layouts):
        _parts.append(
            f'<linearGradient id="sk_g_{_gi}" x1="0" y1="0" x2="0" y2="1">'
            f'<stop offset="0" stop-color="{_bl["color"]}"/>'
            f'<stop offset="1" stop-color="{_bl["color"]}" stop-opacity="0.78"/>'
            f'</linearGradient>'
        )
    _parts.append(
        '<linearGradient id="sk_g_start" x1="0" y1="0" x2="0" y2="1">'
        '<stop offset="0" stop-color="#5a5a5a"/>'
        '<stop offset="1" stop-color="#2d2d2d"/></linearGradient>'
    )
    _parts.append('</defs>')

    _mid_x = _SVG_W / 2
    _fan_y = (_last_start_bottom + _HEADER_Y) / 2

    # 起点ピル間の縦接続線
    for _si in range(_n_starts - 1):
        _y_top = _START_Y + _si * _START_GAP + _PILL_H
        _y_bot = _START_Y + (_si + 1) * _START_GAP
        _parts.append(
            f'<line x1="{_mid_x}" y1="{_y_top}" x2="{_mid_x}" y2="{_y_bot}" '
            f'stroke="#888" stroke-width="2.5" stroke-linecap="round"/>'
        )

    # 最下段の起点 → 各分岐ヘッダー への接続線
    _branch_header_xs = [
        (_bl["x_start"] + _bl["x_end"]) / 2 for _bl in _branch_layouts
    ]
    _parts.append(
        f'<line x1="{_mid_x}" y1="{_last_start_bottom}" x2="{_mid_x}" y2="{_fan_y}" '
        f'stroke="#888" stroke-width="2.5" stroke-linecap="round"/>'
    )
    if len(_branch_header_xs) >= 2:
        _parts.append(
            f'<line x1="{_branch_header_xs[0]}" y1="{_fan_y}" '
            f'x2="{_branch_header_xs[-1]}" y2="{_fan_y}" '
            f'stroke="#888" stroke-width="2.5" stroke-linecap="round"/>'
        )
    for _hx in _branch_header_xs:
        _parts.append(
            f'<line x1="{_hx}" y1="{_fan_y}" x2="{_hx}" y2="{_HEADER_Y}" '
            f'stroke="#888" stroke-width="2.5" stroke-linecap="round"/>'
        )

    # 起点ピル(上から下へ複数段)
    for _si, _sl in enumerate(_start_labels):
        _y = _START_Y + _si * _START_GAP
        _parts.append(
            f'<rect x="{_mid_x - _PILL_W / 2}" y="{_y}" width="{_PILL_W}" height="{_PILL_H}" '
            f'rx="22" ry="22" fill="url(#sk_g_start)" stroke="#777" stroke-width="1" '
            f'filter="url(#sk_shadow)"/>'
        )
        _parts.append(
            f'<text x="{_mid_x}" y="{_y + _PILL_H / 2 + 5}" text-anchor="middle" '
            f'fill="#fff" font-weight="700" font-size="14" font-family="Meiryo, sans-serif">'
            f'{_skt_html.escape(_sl)}</text>'
        )

    # 各分岐: ヘッダ + ノードツリー
    for _bi, _bl in enumerate(_branch_layouts):
        _label = _bl["label"]
        _color = _bl["color"]
        _hx = _branch_header_xs[_bi]
        # ヘッダーピル
        _parts.append(
            f'<rect x="{_hx - _PILL_W / 2}" y="{_HEADER_Y}" width="{_PILL_W}" height="{_PILL_H}" '
            f'rx="22" ry="22" fill="url(#sk_g_{_bi})" stroke="none" '
            f'filter="url(#sk_shadow)"/>'
        )
        _parts.append(
            f'<text x="{_hx}" y="{_HEADER_Y + _PILL_H / 2 + 5}" text-anchor="middle" '
            f'fill="#fff" font-weight="800" font-size="15" font-family="Meiryo, sans-serif" '
            f'letter-spacing="0.06em">{_skt_html.escape(_label)}</text>'
        )
        # ノードのy座標 = HEADER_Y + (depth+1) * NODE_Y_GAP
        _depth_to_y = lambda d: _HEADER_Y + (d + 1) * _NODE_Y_GAP

        # ヘッダから各ルートノードへの接続線
        _node_by_id = {n["id"]: n for n in _bl["nodes"]}
        _root_ids = _bl["roots"]
        _hdr_bottom = _HEADER_Y + _PILL_H
        if _root_ids:
            _root_xs = [_bl["positions"][rid][0] for rid in _root_ids]
            # ヘッダー直下の中央の y = depth0_top - 18
            _connector_y = _depth_to_y(0) - 18
            _parts.append(
                f'<line x1="{_hx}" y1="{_hdr_bottom}" x2="{_hx}" y2="{_connector_y}" '
                f'stroke="{_color}" stroke-width="3" stroke-linecap="round" opacity="0.85"/>'
            )
            if len(_root_xs) >= 2:
                _parts.append(
                    f'<line x1="{min(_root_xs)}" y1="{_connector_y}" '
                    f'x2="{max(_root_xs)}" y2="{_connector_y}" '
                    f'stroke="{_color}" stroke-width="3" stroke-linecap="round" opacity="0.85"/>'
                )
            for _rx in _root_xs:
                _parts.append(
                    f'<line x1="{_rx}" y1="{_connector_y}" x2="{_rx}" y2="{_depth_to_y(0)}" '
                    f'stroke="{_color}" stroke-width="3" stroke-linecap="round" opacity="0.85"/>'
                )

        # 親→子 接続線(各ノードからその子へ)
        for _n in _bl["nodes"]:
            _nid = _n["id"]
            _x_n, _d_n = _bl["positions"][_nid]
            _y_n = _depth_to_y(_d_n)
            # 子を探す
            _child_ids = [c["id"] for c in _bl["nodes"] if c.get("parent") == _nid]
            if not _child_ids:
                continue
            _child_xs = [_bl["positions"][cid][0] for cid in _child_ids]
            _bottom_n = _y_n + _PILL_H
            _connector_y = _depth_to_y(_d_n + 1) - 18
            _parts.append(
                f'<line x1="{_x_n}" y1="{_bottom_n}" x2="{_x_n}" y2="{_connector_y}" '
                f'stroke="{_color}" stroke-width="3" stroke-linecap="round" opacity="0.85"/>'
            )
            if len(_child_xs) >= 2:
                _parts.append(
                    f'<line x1="{min(_child_xs)}" y1="{_connector_y}" '
                    f'x2="{max(_child_xs)}" y2="{_connector_y}" '
                    f'stroke="{_color}" stroke-width="3" stroke-linecap="round" opacity="0.85"/>'
                )
            for _cx in _child_xs:
                _parts.append(
                    f'<line x1="{_cx}" y1="{_connector_y}" x2="{_cx}" y2="{_depth_to_y(_d_n + 1)}" '
                    f'stroke="{_color}" stroke-width="3" stroke-linecap="round" opacity="0.85"/>'
                )

        # 各ノードのピル + チェックボックス
        for _n in _bl["nodes"]:
            _nid = _n["id"]
            _x_n, _d_n = _bl["positions"][_nid]
            _y_n = _depth_to_y(_d_n)
            # ノードグループ(<title>=ブラウザ標準ツールチップ＋hover時カスタムバナー)
            _memo_n = (_n.get("memo") or "").strip()
            _memo_first = _memo_n.splitlines()[0] if _memo_n else ""
            _tip_text = _n.get("label", "")
            if _memo_first:
                _tip_text += " — " + _memo_first[:80]
                if len(_memo_n) > len(_memo_first) or len(_memo_first) > 80:
                    _tip_text += "…"
            _parts.append('<g class="skt-node">')
            _parts.append(f'<title>{_skt_html.escape(_tip_text)}</title>')
            _parts.append(
                f'<rect x="{_x_n - _PILL_W / 2}" y="{_y_n}" width="{_PILL_W}" height="{_PILL_H}" '
                f'rx="22" ry="22" fill="url(#sk_g_{_bi})" stroke="none" '
                f'filter="url(#sk_shadow)"/>'
            )
            # チェックボックス(ピル左端、視覚的表示のみ。トグルは下部のチェックUIで)
            _box_size = 16
            _box_x = _x_n - _PILL_W / 2 + 10
            _box_y = _y_n + (_PILL_H - _box_size) / 2
            if _n.get("checked"):
                _parts.append(
                    f'<rect x="{_box_x}" y="{_box_y}" width="{_box_size}" height="{_box_size}" '
                    f'rx="3" ry="3" fill="#ffffff" stroke="#ffffff" stroke-width="1.5"/>'
                )
                _parts.append(
                    f'<path d="M {_box_x + 3} {_box_y + 8} L {_box_x + 7} {_box_y + 12} '
                    f'L {_box_x + 13} {_box_y + 4}" stroke="#16a34a" stroke-width="2.5" '
                    f'fill="none" stroke-linecap="round" stroke-linejoin="round"/>'
                )
            else:
                _parts.append(
                    f'<rect x="{_box_x}" y="{_box_y}" width="{_box_size}" height="{_box_size}" '
                    f'rx="3" ry="3" fill="rgba(255,255,255,0.18)" stroke="#ffffff" '
                    f'stroke-width="1.5"/>'
                )
            # メモあり目印(鉛筆) — チェックボックス右隣に黄色いバッジ
            if _memo_n:
                _badge_cx = _box_x + _box_size + 12
                _badge_cy = _y_n + _PILL_H / 2
                _badge_r = 10
                _parts.append(
                    f'<circle cx="{_badge_cx}" cy="{_badge_cy}" r="{_badge_r}" '
                    f'fill="#fde047" stroke="#ffffff" stroke-width="2"/>'
                )
                _parts.append(
                    f'<text x="{_badge_cx}" y="{_badge_cy + 5}" text-anchor="middle" '
                    f'fill="#1f2937" font-size="14" font-family="Meiryo, sans-serif" '
                    f'font-weight="700">✏</text>'
                )
                _label_extra_shift = 22
            else:
                _label_extra_shift = 0
            # ラベル(チェックボックス＋鉛筆分だけ右にシフト)
            _parts.append(
                f'<text x="{_x_n + _box_size / 2 + 4 + _label_extra_shift}" y="{_y_n + _PILL_H / 2 + 5}" text-anchor="middle" '
                f'fill="#fff" font-weight="600" font-size="13" font-family="Meiryo, sans-serif">'
                f'{_skt_html.escape(_n.get("label", ""))}</text>'
            )
            # ホバー時のカスタムバナー(メモがあれば表示・foreignObjectでHTMLによる自動改行)
            if _memo_n:
                # 大きめサイズ + 内容に応じて高さ可変
                _bw = 380
                _chars = len(_memo_n)
                _explicit_breaks = _memo_n.count('\n')
                _est_lines = max(_explicit_breaks + 1, (_chars + 24) // 25)
                _est_lines = max(2, min(_est_lines, 10))
                _bh = _est_lines * 26 + 24
                _bx = _x_n - _bw / 2
                _by = _y_n - _bh - 12
                _parts.append('<g class="skt-banner">')
                _parts.append(
                    f'<foreignObject x="{_bx}" y="{_by}" width="{_bw}" height="{_bh}">'
                    f'<div xmlns="http://www.w3.org/1999/xhtml" '
                    f'style="background:#1f2937;color:#fff;'
                    f'padding:12px 16px;border-radius:8px;'
                    f'font-size:14px;line-height:1.6;'
                    f'font-family:Meiryo,sans-serif;'
                    f'word-break:break-word;overflow-wrap:anywhere;'
                    f'white-space:pre-wrap;'
                    f'border:1px solid rgba(255,255,255,0.55);'
                    f'box-shadow:0 4px 12px rgba(0,0,0,0.45);'
                    f'box-sizing:border-box;height:100%;overflow:hidden;'
                    f'">{_skt_html.escape(_memo_n)}</div>'
                    f'</foreignObject>'
                )
                _parts.append('</g>')
            _parts.append('</g>')

    _parts.append('</svg>')
    _parts.append('</div>')
    st.markdown("".join(_parts), unsafe_allow_html=True)

    # ----- ノード詳細パネル (selectbox + メモ編集・保存) -----
    with st.expander("🔍 ノードの詳細・メモを編集", expanded=False):
        _all_node_options = []
        for _bid_d, _lab_d, _col_d, _ns_d in _branches_src:
            for _nd in _ns_d:
                _all_node_options.append((_bid_d, _nd["id"], _lab_d, _col_d, _nd))
        if _all_node_options:
            _sel_idx = st.selectbox(
                "ノードを選択",
                options=list(range(len(_all_node_options))),
                format_func=lambda i: f"[{_all_node_options[i][2]}] {_all_node_options[i][4].get('label', '')}",
                key="skt_detail_select",
            )
            _sel = _all_node_options[_sel_idx]
            _sel_bid, _sel_nid, _sel_blabel, _sel_color, _sel_node = _sel
            _sel_state = "✅ 習得済み" if _sel_node.get("checked") else "⬜ 未習得"
            _sel_memo = (_sel_node.get("memo") or "")
            # 選択ノードが変わったら memo widget の session_state を保存済みの値で
            # 強制リフレッシュ(タブ切替後の表示ズレ防止)
            _last_sel_k = "skt_detail_last_sel"
            _current_sel = (_sel_bid, _sel_nid)
            _memo_widget_key = f"skt_dmemo_b{_sel_bid}_n{_sel_nid}"
            if st.session_state.get(_last_sel_k) != _current_sel:
                st.session_state[_last_sel_k] = _current_sel
                st.session_state[_memo_widget_key] = _sel_memo
            elif _memo_widget_key not in st.session_state:
                st.session_state[_memo_widget_key] = _sel_memo
            st.markdown(
                f"<div style='border-left:6px solid {_sel_color};padding:8px 12px;"
                f"margin-top:6px;background:rgba(0,0,0,0.02);border-radius:4px;'>"
                f"<div style='font-size:13px;color:#666;'>{_skt_html.escape(_sel_blabel)}</div>"
                f"<div style='font-size:18px;font-weight:700;margin:2px 0;'>"
                f"{_skt_html.escape(_sel_node.get('label', ''))}</div>"
                f"<div style='font-size:13px;color:#444;'>{_sel_state}</div>"
                f"</div>",
                unsafe_allow_html=True,
            )
            st.text_area(
                "📝 メモ",
                key=_memo_widget_key,
                height=120,
                placeholder="このノードのメモ（自由記入）",
            )
            _save_memo_clicked = st.button(
                "💾 メモを保存", key=f"skt_dmemo_save_{_sel_bid}_{_sel_nid}",
                type="primary",
            )
            if _save_memo_clicked:
                try:
                    _new_memo_val = st.session_state.get(_memo_widget_key, "")
                    _data_m = get_skill_tree()
                    for _b_m in _data_m.get("branches", []):
                        if int(_b_m.get("id", 0)) == _sel_bid:
                            for _n_m in _b_m.get("nodes", []):
                                if int(_n_m.get("id", 0)) == _sel_nid:
                                    _n_m["memo"] = _new_memo_val
                                    break
                            break
                    save_skill_tree(_data_m)
                    st.toast("メモを保存しました", icon="✅")
                    st.rerun()
                except Exception as _e:
                    st.error(f"保存失敗: {_e}")

    # ----- 習得チェック (折りたたみ・タブ＋親別エキスパンダ・自動保存) -----
    with st.expander("✅ 習得チェック", expanded=False):
        st.caption("チェックすると即時保存。子ノード全部チェックで親が自動チェック、上の図と習得率も更新されます。")
        _tab_labels = [_l for (_bid, _l, _c, _n) in _branches_src]
        if _tab_labels:
            _tabs = st.tabs(_tab_labels)
            for (_bid_chk, _label_chk, _color_chk, _nodes_chk), _tab in zip(_branches_src, _tabs):
                with _tab:
                    # 子マップ構築
                    _children_map = {}
                    for _n in _nodes_chk:
                        _p = _n.get("parent")
                        if _p is not None:
                            _children_map.setdefault(_p, []).append(_n)
                    _roots_chk = [_n for _n in _nodes_chk if _n.get("parent") is None]

                    def _render_chk_tree(_node, _depth=0):
                        _wkey = f"skt_inline_b{_bid_chk}_n{_node['id']}"
                        if _wkey not in st.session_state:
                            st.session_state[_wkey] = bool(_node.get("checked", False))
                        _chs = _children_map.get(_node["id"], [])
                        if _chs:
                            _mark = "✅ " if st.session_state.get(_wkey) else ""
                            with st.expander(f"{_mark}{_node.get('label', '')}", expanded=True):
                                st.checkbox(
                                    f"{_node.get('label', '')}（親）",
                                    key=_wkey,
                                    on_change=_skt_on_check_change,
                                    args=(_bid_chk, _node["id"], _wkey),
                                )
                                for _ch in _chs:
                                    _render_chk_tree(_ch, _depth + 1)
                        else:
                            st.checkbox(
                                _node.get("label", ""),
                                key=_wkey,
                                on_change=_skt_on_check_change,
                                args=(_bid_chk, _node["id"], _wkey),
                            )

                    for _root in _roots_chk:
                        _render_chk_tree(_root)
    st.stop()


# シフト表ボード（CS促進全員 / 月カレンダー）
if selected_key == "cs_shift_calendar":
    import calendar as _cs_cal
    import html as _cs_html
    from datetime import date as _cs_date
    from metrics import fetch_cs_shift_for_month

    _today_cs = _cs_date.today()
    _default_cs_m = _today_cs.strftime("%Y-%m")
    _cs_cur = st.session_state.get("cs_shift_cal_month", _default_cs_m)
    try:
        _cs_y, _cs_m = map(int, _cs_cur.split("-"))
    except Exception:
        _cs_y, _cs_m = _today_cs.year, _today_cs.month
        _cs_cur = f"{_cs_y:04d}-{_cs_m:02d}"

    # 月ナビ
    _cs_n1, _cs_n2, _cs_n3 = st.columns([1, 4, 1])
    if _cs_n1.button("⬅ 前月", key="cs_shift_prev", use_container_width=True):
        _ny, _nm = (_cs_y, _cs_m - 1) if _cs_m > 1 else (_cs_y - 1, 12)
        st.session_state["cs_shift_cal_month"] = f"{_ny:04d}-{_nm:02d}"
        st.rerun()
    _cs_n2.markdown(
        f"<div style='text-align:center;font-size:18px;font-weight:700;padding:8px 0;'>{_cs_y}年{_cs_m}月</div>",
        unsafe_allow_html=True,
    )
    if _cs_n3.button("翌月 ➡", key="cs_shift_next", use_container_width=True):
        _ny, _nm = (_cs_y, _cs_m + 1) if _cs_m < 12 else (_cs_y + 1, 1)
        st.session_state["cs_shift_cal_month"] = f"{_ny:04d}-{_nm:02d}"
        st.rerun()

    @st.cache_data(ttl=300, show_spinner="シフト取得中...")
    def _cs_shift_load(year: int, month: int):
        return fetch_cs_shift_for_month(_sf(), year, month)

    try:
        _by_day = _cs_shift_load(_cs_y, _cs_m)
    except Exception as e:
        st.error(f"取得に失敗しました: {e}")
        st.stop()

    def _render_shift_calendar(by_day: dict, ns: str, highlight_changes: dict | None = None):
        """カレンダー1枚をレンダリング。highlight_changes={day:set(name_key)} で移動先セル内の該当者を強調。"""
        _wd_labels = ["月", "火", "水", "木", "金", "土", "日"]
        _hcols = st.columns(7)
        for _i, _wd in enumerate(_wd_labels):
            _wd_color = "#4a90e2" if _i == 5 else ("#e74c3c" if _i == 6 else "#444")
            _hcols[_i].markdown(
                f"<div style='text-align:center;font-weight:700;color:{_wd_color};"
                f"padding:6px 0;border-bottom:2px solid #ddd;'>{_wd}</div>",
                unsafe_allow_html=True,
            )

        _cs_cal.setfirstweekday(_cs_cal.MONDAY)
        _weeks = _cs_cal.monthcalendar(_cs_y, _cs_m)
        for _week in _weeks:
            _cols = st.columns(7)
            for _i, _day in enumerate(_week):
                with _cols[_i]:
                    if _day == 0:
                        st.markdown("<div style='min-height:90px;'></div>", unsafe_allow_html=True)
                        continue
                    _d_obj = _cs_date(_cs_y, _cs_m, _day)
                    _is_past = _d_obj < _today_cs
                    _is_today = (_d_obj == _today_cs)
                    _is_sat = _i == 5
                    _is_sun = _i == 6

                    if _is_today:
                        _bg, _fg, _bd = "#fff3cd", "#664d03", "2px solid #f0c000"
                    elif _is_past:
                        _bg, _fg, _bd = "#f5f5f5", "#aaa", "1px solid #e0e0e0"
                    elif _is_sat:
                        _bg, _fg, _bd = "#e7f0fb", "#2c5fa0", "1px solid #c5d8ee"
                    elif _is_sun:
                        _bg, _fg, _bd = "#fde8ec", "#a5364c", "1px solid #f0c5cf"
                    else:
                        _bg, _fg, _bd = "#ffffff", "#222", "1px solid #d8dee5"

                    _list = by_day.get(_day, [])
                    _changed_keys = (highlight_changes or {}).get(_day, set())
                    if _list:
                        _txt_color = "#bbb" if _is_past else "#333"
                        _time_color = "#aaa" if _is_past else "#888"
                        _highlight_surnames = ("佐々木", "室谷", "原田", "堀田", "金澤")
                        _red_surnames = ("佐々木", "堀田")
                        def _is_hi(nm: str) -> bool:
                            return any(s in (nm or "") for s in _highlight_surnames)
                        def _is_red(nm: str) -> bool:
                            return any(s in (nm or "") for s in _red_surnames)
                        def _is_changed(nm: str) -> bool:
                            return any(k in (nm or "") for k in _changed_keys)
                        _lines = []
                        for _name, _s, _e in sorted(
                            _list,
                            key=lambda t: (0 if _is_hi(t[0]) else 1, t[1], t[0]),
                        ):
                            _t = f"{_s}-{_e}" if _s and _e else (_s or _e)
                            if _is_red(_name):
                                _mark = "🔴🟡 "
                            elif _is_hi(_name):
                                _mark = "🟡 "
                            else:
                                _mark = ""
                            _row_style = f"font-size:11px;color:{_txt_color};line-height:1.4;text-align:left;"
                            if _is_changed(_name):
                                _row_style += "background:#fff3b0;border-radius:3px;padding:0 2px;"
                            _lines.append(
                                f"<div style='{_row_style}'>"
                                f"{_mark}{_cs_html.escape(_name)} <span style='color:{_time_color};'>{_t}</span></div>"
                            )
                        _names_html = "".join(_lines)
                        _bomb = "💣 " if len(_list) <= 6 else ""
                        _cnt_html = (
                            f"<div style='font-size:13px;font-weight:700;margin-top:2px;"
                            f"color:{'#888' if _is_past else '#1565c0'};'>"
                            f"{_bomb}{len(_list)}<span style='font-size:10px;'>名</span></div>"
                        )
                    else:
                        _names_html = ""
                        _cnt_html = "<div style='font-size:11px;color:#ccc;margin-top:6px;'>—</div>"

                    st.markdown(
                        f"<div style='background:{_bg};color:{_fg};border:{_bd};"
                        f"border-radius:8px;padding:6px 6px;min-height:120px;text-align:center;"
                        f"margin-bottom:4px;overflow-wrap:break-word;'>"
                        f"<div style='font-size:14px;font-weight:700;'>{_day}</div>"
                        f"{_cnt_html}"
                        f"<div style='margin-top:4px;'>{_names_html}</div>"
                        f"</div>",
                        unsafe_allow_html=True,
                    )

    # ── 変更希望シフト（毎月自動表示）──
    from shift_proposer import propose_moves as _propose_shift
    from shift_forbidden_store import (
        get_forbidden as _shift_get_forbidden,
        save_forbidden as _shift_save_forbidden,
        clear_forbidden_cache as _shift_clear_forbidden_cache,
        get_staff_order as _shift_get_staff_order,
        save_staff_order as _shift_save_staff_order,
        merge_staff_order as _shift_merge_staff_order,
    )

    import calendar as _cs_cal2
    _cs_last_day = _cs_cal2.monthrange(_cs_y, _cs_m)[1]

    # 各日の氏名リスト (時刻付きタプル → 氏名のみ)
    _by_day_names = {d: [n for (n, _s, _e) in _by_day.get(d, [])] for d in range(1, _cs_last_day + 1)}

    # blacklist / confirmed の session_state キー (月別に分ける)
    _bl_key = f"shift_blacklist_{_cs_y}_{_cs_m}"
    _cf_key = f"shift_confirmed_{_cs_y}_{_cs_m}"
    if _bl_key not in st.session_state:
        st.session_state[_bl_key] = set()
    if _cf_key not in st.session_state:
        st.session_state[_cf_key] = {}  # {(person, frm, to): "YYYY-MM-DD HH:MM"}
    elif isinstance(st.session_state[_cf_key], set):
        # 旧形式(set)を辞書に変換
        st.session_state[_cf_key] = {k: "" for k in st.session_state[_cf_key]}

    # 変更不可日: Google Sheets からロード（全ユーザー共有）
    try:
        _forbidden = _shift_get_forbidden(_cs_y, _cs_m)
    except Exception as _e:
        st.error(f"変更不可日データの読込に失敗しました: {_e}")
        st.stop()

    # 2026-06 既知NG日のシード（保存済データが無い場合のみ・一回限り）
    if not _forbidden and _cs_y == 2026 and _cs_m == 6:
        try:
            _shift_save_forbidden(_cs_y, _cs_m, {
                "原田": {19, 23, 25},
                "佐々木": {15, 24, 30},
                "堀田": {11},
                "室谷": {1, 19},
                "雨貝": {1, 7},
                "葛西": {1},
                "角田": {1, 14, 15},
            })
            _shift_clear_forbidden_cache()
            _forbidden = _shift_get_forbidden(_cs_y, _cs_m)
        except Exception:
            pass

    _blacklist = st.session_state[_bl_key]
    _confirmed = st.session_state[_cf_key]

    _all_moves = _propose_shift(_by_day_names, _cs_last_day,
                                blacklist=_blacklist, confirmed=_confirmed,
                                forbidden_days=_forbidden)

    # 提案後のシフト state を作るためのヘルパー
    def _apply_moves_local(src: dict, moves: list) -> tuple[dict, dict]:
        res = {d: list(v) for d, v in src.items()}
        changed = {}
        for mv in moves:
            who, frm, to = mv.person, mv.frm, mv.to
            pool = res.get(frm, [])
            hit = next((t for t in pool if who in (t[0] or "")), None)
            if not hit:
                continue
            res[frm].remove(hit)
            res.setdefault(to, []).append(hit)
            changed.setdefault(to, set()).add(who)
            changed.setdefault(frm, set())
        return res, changed

    _proposed_by_day, _changed_days = _apply_moves_local(_by_day, _all_moves)

    # タブ: 通常はシフト表のみ表示。 変更希望シフトはタブ2クリックで表示
    _tab_main, _tab_prop = st.tabs([
        f"📅 シフト表",
        f"📝 変更希望シフト（自動提案 {len(_all_moves)}件）",
    ])

    with _tab_main:
        _render_shift_calendar(_by_day, ns="cur")
        st.caption(
            f"📆 {_cs_y}年{_cs_m}月　CS促進全員シフト　|　🟨 本日　🩶 経過済　🟦 土曜　🟥 日曜"
        )

    with _tab_prop:
        if not _all_moves:
            st.info("制約を満たす自動提案は現時点でありません（既に最適化済みか、不可リストで全候補が除外されています）。")
        else:
            st.caption(
                f"📋 {len(_all_moves)}件の候補。「不可」にチェックすると除外して再計算、"
                "「可能」はSF反映済 or 反映予定として下部の履歴に保存されます。"
            )
            _hh = st.columns([3, 1.2, 1.2, 3])
            _hh[0].markdown("**移動**")
            _hh[1].markdown("**可能**")
            _hh[2].markdown("**不可**")
            _hh[3].markdown("**理由**")
            for _i, _mv in enumerate(_all_moves):
                _row_cols = st.columns([3, 1.2, 1.2, 3])
                _row_cols[0].markdown(f"{_mv.person}　{_cs_m}/{_mv.frm} → {_cs_m}/{_mv.to}")
                _key_tup = (_mv.person, _mv.frm, _mv.to)
                _ck_ok = _row_cols[1].checkbox(
                    "可", key=f"mv_ok_{_cs_y}_{_cs_m}_{_i}_{_mv.person}_{_mv.frm}_{_mv.to}",
                    value=False,
                )
                _ck_ng = _row_cols[2].checkbox(
                    "不可", key=f"mv_ng_{_cs_y}_{_cs_m}_{_i}_{_mv.person}_{_mv.frm}_{_mv.to}",
                    value=False,
                )
                _row_cols[3].markdown(
                    f"<span style='color:#888;font-size:12px;'>{_mv.reason}</span>",
                    unsafe_allow_html=True,
                )
                if _ck_ok and _key_tup not in _confirmed:
                    from datetime import datetime as _dt
                    _confirmed[_key_tup] = _dt.now().strftime("%Y-%m-%d %H:%M")
                    st.session_state[_cf_key] = _confirmed
                    st.rerun()
                if _ck_ng and _key_tup not in _blacklist:
                    _blacklist.add(_key_tup)
                    st.session_state[_bl_key] = _blacklist
                    st.rerun()

            _bl_size = len(_blacklist)
            if _bl_size > 0:
                if st.button(f"🔄 不可リスト ({_bl_size}件) をリセット", key=f"bl_reset_{_cs_y}_{_cs_m}"):
                    st.session_state[_bl_key] = set()
                    st.rerun()

        _render_shift_calendar(_proposed_by_day, ns=f"prop_{_cs_y}_{_cs_m}",
                               highlight_changes=_changed_days)
        st.caption(
            "📝 変更希望シフト　|　黄色背景＝移動で追加された人　"
            "💣 6名以下　|　🟨 本日　🩶 経過済　🟦 土曜　🟥 日曜"
        )

        # ── 🚫 変更不可日（チェック＝この日への移動を禁止） ──
        st.markdown("---")
        st.markdown(
            "<div style='font-size:15px;font-weight:700;padding:8px 0 4px;'>"
            "🚫 変更不可日"
            "</div>",
            unsafe_allow_html=True,
        )
        st.caption(
            "各スタッフの「動かせない日」をチェックすると、その日への移動提案を除外します。"
            "変更は即時保存・全ユーザーで共有されます。"
        )

        # その月のシフトに登場するスタッフ全員を抽出（初期は出現順）
        _fb_seen_set: set[str] = set()
        _fb_current_staff: list[str] = []
        for _d in range(1, _cs_last_day + 1):
            for _nm, _, _ in _by_day.get(_d, []):
                if _nm and _nm not in _fb_seen_set:
                    _fb_seen_set.add(_nm)
                    _fb_current_staff.append(_nm)

        # 保存済み順序とマージ（保存順優先・新顔は末尾）
        try:
            _fb_saved_order = _shift_get_staff_order()
        except Exception:
            _fb_saved_order = []
        _fb_all_names = _shift_merge_staff_order(_fb_saved_order, _fb_current_staff)

        def _fb_last_key(full: str) -> str:
            """姓キーを抽出: 室谷 慧 → 室谷 / 佐々木 彩乃 → 佐々木"""
            return (full or "").split(" ")[0].split("　")[0].strip()

        if not _fb_all_names:
            st.info("当月のシフトデータが空のため、変更不可日テーブルを表示できません。")
        else:
            st.caption(
                "💡 行先頭の ⋮⋮ ハンドルをドラッグするとスタッフの並び替えができます。"
            )
            import pandas as _fb_pd
            _fb_wd_lbl = ["月", "火", "水", "木", "金", "土", "日"]
            # DataFrame の列名は ASCII で一意 (d1, d2, ...) にし、
            # AgGrid 側で headerName="日\n曜" を別途指定（同一日の列名衝突を回避＋多行表示）
            _fb_day_cols = [f"d{_d}" for _d in range(1, _cs_last_day + 1)]
            _fb_header_labels = {
                _fb_day_cols[_d - 1]:
                    f"{_d}\n{_fb_wd_lbl[_cs_date(_cs_y, _cs_m, _d).weekday()]}"
                for _d in range(1, _cs_last_day + 1)
            }

            _fb_rows = []
            for _full in _fb_all_names:
                _key = _fb_last_key(_full)
                _ng = _forbidden.get(_key, set())
                _row = {"スタッフ": _full}
                for _d in range(1, _cs_last_day + 1):
                    _row[_fb_day_cols[_d - 1]] = bool(_d in _ng)
                _fb_rows.append(_row)
            _df_fb = _fb_pd.DataFrame(_fb_rows)

            # チェックボックスレンダラー
            _fb_cb_renderer = JsCode("""
            class FbCb{
                init(p){
                    this.p=p;
                    this.g=document.createElement('input');
                    this.g.type='checkbox';
                    this.g.checked=p.value===true;
                    this.g.style.cursor='pointer';
                    this.g.style.width='18px';
                    this.g.style.height='18px';
                    this.h=e=>{p.node.setDataValue(p.column.colId,e.target.checked);};
                    this.g.addEventListener('click',this.h);
                }
                getGui(){return this.g;}
                refresh(p){this.g.checked=p.value===true;return true;}
                destroy(){this.g.removeEventListener('click',this.h);}
            }
            """)

            _fb_gb = GridOptionsBuilder.from_dataframe(_df_fb)
            _fb_gb.configure_default_column(
                resizable=False, sortable=False, filter=False,
                editable=True, cellRenderer=_fb_cb_renderer,
                cellStyle={"display": "flex", "alignItems": "center", "justifyContent": "center"},
            )
            _fb_gb.configure_column(
                "スタッフ",
                rowDrag=True, pinned="left", editable=False, cellRenderer=None,
                width=160, minWidth=140, suppressSizeToFit=True,
                cellStyle={"display": "flex", "alignItems": "center",
                           "justifyContent": "flex-start", "fontWeight": "bold"},
            )
            # 土日ヘッダーに色を付ける
            for _d in range(1, _cs_last_day + 1):
                _col = _fb_day_cols[_d - 1]
                _wd_idx = _cs_date(_cs_y, _cs_m, _d).weekday()
                _hdr_cls = None
                if _wd_idx == 5:
                    _hdr_cls = "fb-hdr-sat"
                elif _wd_idx == 6:
                    _hdr_cls = "fb-hdr-sun"
                _fb_gb.configure_column(
                    _col,
                    headerName=_fb_header_labels[_col],
                    width=60, minWidth=60, suppressSizeToFit=True,
                    headerClass=_hdr_cls,
                    wrapHeaderText=True,
                    autoHeaderHeight=True,
                )
            _fb_gb.configure_grid_options(
                rowDragManaged=True,
                animateRows=True,
                rowHeight=36,
                headerHeight=60,
                suppressMovableColumns=True,
            )

            _fb_css = {
                ".ag-header-cell": {
                    "background-color": "#555", "color": "#fff",
                    "font-weight": "bold", "text-align": "center",
                    "padding": "2px 0 !important",
                },
                ".ag-header-cell-label": {
                    "justify-content": "center",
                    "white-space": "pre-wrap !important",
                    "text-align": "center",
                    "line-height": "1.15",
                    "font-size": "13px",
                },
                ".ag-header-cell-text": {
                    "white-space": "pre-wrap !important",
                    "text-align": "center",
                    "overflow": "visible !important",
                    "text-overflow": "clip !important",
                },
                ".fb-hdr-sat": {
                    "background-color": "#4A6FA5 !important",
                    "color": "#fff !important",
                },
                ".fb-hdr-sun": {
                    "background-color": "#C0392B !important",
                    "color": "#fff !important",
                },
                ".ag-row-odd": {"background-color": "#ffffff"},
                ".ag-row-even": {"background-color": "#f7f9fc"},
                ".ag-row-dragging": {"background-color": "#fff3b0 !important"},
            }

            _fb_grid_key = f"shift_fb_aggrid_{_cs_y}_{_cs_m}"
            _fb_grid = AgGrid(
                _df_fb,
                gridOptions=_fb_gb.build(),
                height=max(160, 60 + 36 * len(_df_fb)),
                theme="balham",
                allow_unsafe_jscode=True,
                custom_css=_fb_css,
                update_mode="MODEL_CHANGED",
                key=_fb_grid_key,
            )

            def _fb_df_to_dict(_df) -> dict[str, set[int]]:
                _out: dict[str, set[int]] = {}
                for _, _r in _df.iterrows():
                    _k = _fb_last_key(str(_r["スタッフ"]))
                    if not _k:
                        continue
                    for _d in range(1, _cs_last_day + 1):
                        if bool(_r[_fb_day_cols[_d - 1]]):
                            _out.setdefault(_k, set()).add(_d)
                return _out

            if _fb_grid and _fb_grid.data is not None:
                _fb_after = _fb_grid.data
                # 並び順の差分
                _new_order = [str(n) for n in _fb_after["スタッフ"].tolist()]
                _order_changed = (_new_order != _fb_all_names)
                # チェック状態の差分
                _fb_new = _fb_df_to_dict(_fb_after)
                _fb_old = {k: set(v) for k, v in _forbidden.items() if v}
                _state_changed = (_fb_new != _fb_old)

                if _order_changed:
                    try:
                        _shift_save_staff_order(_new_order)
                    except Exception as _ord_e:
                        st.error(f"並び順の保存に失敗しました: {_ord_e}")
                        _order_changed = False
                if _state_changed:
                    try:
                        _shift_save_forbidden(_cs_y, _cs_m, _fb_new)
                    except Exception as _save_e:
                        st.error(f"変更不可日の保存に失敗しました: {_save_e}")
                        _state_changed = False

                if _order_changed or _state_changed:
                    if _fb_grid_key in st.session_state:
                        del st.session_state[_fb_grid_key]
                    st.toast("保存しました", icon="✅")
                    st.rerun()

        # ── 「可」 にした履歴 (反映予定/反映済の記録) ──
        if _confirmed:
            st.markdown("---")
            st.markdown(
                "<div style='font-size:15px;font-weight:700;padding:8px 0 4px;'>"
                f"✅ 「可」 にした移動の記録 ({len(_confirmed)}件)"
                "</div>",
                unsafe_allow_html=True,
            )
            _rows_html = "".join(
                f"<tr>"
                f"<td style='padding:3px 10px;border-bottom:1px solid #eee;'>{i+1}</td>"
                f"<td style='padding:3px 10px;border-bottom:1px solid #eee;'>{p}</td>"
                f"<td style='padding:3px 10px;border-bottom:1px solid #eee;'>{_cs_m}/{f} → {_cs_m}/{t}</td>"
                f"<td style='padding:3px 10px;border-bottom:1px solid #eee;color:#888;font-size:11px;'>{ts}</td>"
                f"</tr>"
                for i, ((p, f, t), ts) in enumerate(sorted(_confirmed.items(), key=lambda kv: kv[1]))
            )
            st.markdown(
                "<table style='font-size:13px;border-collapse:collapse;width:100%;max-width:600px;'>"
                "<thead><tr style='background:#f0f0f0;'>"
                "<th style='padding:5px 10px;text-align:left;'>#</th>"
                "<th style='padding:5px 10px;text-align:left;'>対象</th>"
                "<th style='padding:5px 10px;text-align:left;'>移動</th>"
                "<th style='padding:5px 10px;text-align:left;'>チェック日時</th>"
                "</tr></thead>"
                f"<tbody>{_rows_html}</tbody></table>",
                unsafe_allow_html=True,
            )
            if st.button(f"🗑 履歴をクリア", key=f"cf_clear_{_cs_y}_{_cs_m}"):
                st.session_state[_cf_key] = {}
                st.rerun()

    st.stop()


# タイミー管理ボード
if selected_key == "timee_management":
    import timee_master_store as _tms
    from datetime import date as _tm_date

    @st.cache_data(ttl=300)
    def _tm_load():
        workers = _tms.load_workers()
        snapshot = _tms.load_snapshot()
        try:
            archive = _tms.load_archive()
        except Exception:
            archive = []
        try:
            postings = _tms.load_postings()
        except Exception:
            postings = []
        # snapshot側を優先（同じ(id,就業日)が両方にあればsnapshot採用）
        seen = {(r.get("id"), r.get("就業日")) for r in snapshot}
        merged = list(snapshot) + [r for r in archive
                                   if (r.get("id"), r.get("就業日")) not in seen]
        return workers, merged, postings

    def _tm_reload():
        _tm_load.clear()

    def _tm_pct_or_dash(v) -> str:
        """「N%」形式の値だけそのまま、それ以外（空/「※公開されません」/誤値）は「—」"""
        import re as _re_pct
        s = str(v or "").strip()
        s = "".join(c for c in s if c not in "​‌‍﻿").strip()
        return s if _re_pct.match(r"^\d+%$", s) else "—"

    def _tm_month_nav(state_key: str, fallback: str):
        """⬅ 前月 / YYYY年M月 / 翌月 ➡ ナビUI。返り値: (year, month, 'YYYY-MM')"""
        cur = st.session_state.get(state_key, fallback)
        try:
            _yv, _mv = map(int, str(cur).split("-"))
        except Exception:
            cur = fallback
            _yv, _mv = map(int, str(cur).split("-"))
        _c1, _c2, _c3 = st.columns([1, 4, 1])
        if _c1.button("⬅ 前月", key=f"{state_key}_prev", use_container_width=True):
            _ny, _nm = (_yv, _mv - 1) if _mv > 1 else (_yv - 1, 12)
            st.session_state[state_key] = f"{_ny:04d}-{_nm:02d}"
            st.rerun()
        _c2.markdown(
            f"<div style='text-align:center;font-size:18px;font-weight:700;"
            f"padding:8px 0;'>{_yv}年{_mv}月</div>",
            unsafe_allow_html=True,
        )
        if _c3.button("翌月 ➡", key=f"{state_key}_next", use_container_width=True):
            _ny, _nm = (_yv, _mv + 1) if _mv < 12 else (_yv + 1, 1)
            st.session_state[state_key] = f"{_ny:04d}-{_nm:02d}"
            st.rerun()
        return _yv, _mv, f"{_yv:04d}-{_mv:02d}"

    # ---- 求人作成: GitHub Actions の workflow_dispatch をトリガー ----
    def _tm_trigger_post_job(post_type: str, headcount: int, dates: list[str]) -> tuple[bool, str]:
        import os as _os, requests as _rq
        pat = ""
        repo = "yoshidass0538-cell/sf-dashboard"
        try:
            if "github" in st.secrets:
                pat = st.secrets["github"].get("pat", "") or ""
                repo = st.secrets["github"].get("repo", repo) or repo
        except Exception:
            pass
        pat = pat or _os.environ.get("GH_PAT", "")
        if not pat:
            return False, "GH_PAT が未設定です。Streamlit Secrets [github] pat に GitHub PAT を設定してください。"
        url = f"https://api.github.com/repos/{repo}/actions/workflows/timee_post_job.yml/dispatches"
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {pat}",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        body = {
            "ref": "main",
            "inputs": {
                "post_type": post_type,
                "headcount": str(headcount),
                "dates": ",".join(dates),
                "group_name": "手かかからない人",
            },
        }
        try:
            r = _rq.post(url, headers=headers, json=body, timeout=15)
            if r.status_code == 204:
                return True, "求人作成ジョブを起動しました。Actions ログで進捗を確認してください。"
            return False, f"GitHub API エラー: HTTP {r.status_code} {r.text[:200]}"
        except Exception as _e:
            return False, f"通信エラー: {_e}"

    @st.dialog("📢 タイミー求人を作成")
    def _tm_post_job_dialog():
        from datetime import date as _d, timedelta as _td
        _stage = st.session_state.get("tm_post_stage", "type")

        if _stage == "type":
            st.write("どちらの求人を作成しますか？")
            _c1, _c2 = st.columns(2)
            # ※ ダイアログ内で st.rerun() を呼ぶとダイアログが閉じる仕様のため、
            #    session_state を書き換えるだけにし、ボタン押下による自動rerunに任せる
            if _c1.button("👥 リピーター", use_container_width=True, type="primary",
                          key="tm_post_btn_repeater"):
                st.session_state["tm_post_type"] = "repeater"
                st.session_state["tm_post_stage"] = "form"
            if _c2.button("🆕 新規", use_container_width=True, type="primary",
                          key="tm_post_btn_new"):
                st.session_state["tm_post_type"] = "new"
                st.session_state["tm_post_stage"] = "form"
            # 同一run内でステージが書き換わった場合は、その先の form 描画にフォールスルー
            if st.session_state.get("tm_post_stage") != "form":
                return

        # _stage == "form"
        _ptype = st.session_state.get("tm_post_type", "repeater")
        _label = "リピーター" if _ptype == "repeater" else "新規"
        st.markdown(f"#### 種別: {_label}")
        _n = st.selectbox("募集人数", list(range(1, 7)), index=0, key="tm_post_headcount")

        _today_d = _d.today()
        _opts = [_today_d + _td(days=_i) for _i in range(0, 60)]
        _wd_l = ["月", "火", "水", "木", "金", "土", "日"]
        _picked = st.multiselect(
            "求人日（最低1日選択）",
            _opts,
            format_func=lambda d: f"{d.isoformat()} ({_wd_l[d.weekday()]})",
            key="tm_post_dates",
        )

        _b1, _b2 = st.columns([1, 2])
        if _b1.button("← 戻る", use_container_width=True, key="tm_post_back"):
            st.session_state["tm_post_stage"] = "type"
        if _b2.button(
            "🚀 求人を作成", type="primary",
            disabled=not _picked,
            use_container_width=True, key="tm_post_submit",
        ):
            ok, msg = _tm_trigger_post_job(
                post_type=_ptype,
                headcount=int(_n),
                dates=[d.isoformat() for d in _picked],
            )
            if ok:
                st.success(f"✅ {msg}")
                st.info(f"種別: {_label} ／ 人数: {_n} ／ 日付: {len(_picked)}件")
                # 選択状態をクリア（次回再オープン時にtype選択から）
                st.session_state.pop("tm_post_stage", None)
                st.session_state.pop("tm_post_type", None)
                st.session_state.pop("tm_post_dates", None)
            else:
                st.error(f"❌ {msg}")

    try:
        _workers, _snapshot, _postings = _tm_load()
    except Exception as _e:
        st.error(f"タイミーデータの読み込みに失敗しました: {_e}")
        st.stop()

    # サマリー
    _today = _tm_date.today()
    _today_iso = _today.isoformat()
    _new_today = sum(1 for w in _workers.values() if w.get("初回登録日") == _today_iso)
    # 現在マッチング中の新規ワーカー = snapshot内で「グループ空欄(初回)」かつ「就業日が今日以降」のユニークID数
    _matching_new_ids = {
        r["id"] for r in _snapshot
        if not str(r.get("グループ", "")).strip()
        and str(r.get("就業日", "")) >= _today_iso
    }
    _cancel_total = sum(len(w.get("キャンセル履歴", [])) for w in _workers.values())

    _c1, _c2, _c3, _c4, _c5 = st.columns([2, 2, 2, 2, 1])
    _c1.metric("登録ワーカー総数", f"{len(_workers):,}")
    _c2.metric("現在マッチング中の新規ワーカー", f"{len(_matching_new_ids):,}")
    _c3.metric("本日新規ワーカー", f"{_new_today:,}")
    _c4.metric("キャンセル累計", f"{_cancel_total:,}")
    if _c5.button("🔄 更新", key="tm_reload", use_container_width=True):
        _tm_reload()
        st.rerun()

    # ----- 求人作成ボタン（タイミー管理直下） -----
    if st.button("📢 求人を作成する", use_container_width=True, type="primary",
                 key="tm_open_post_dialog"):
        st.session_state["tm_post_stage"] = "type"
        st.session_state.pop("tm_post_type", None)
        _tm_post_job_dialog()

    # ----- キャンセル推奨バナー（初回ワーカー × 基準未達） -----
    import re as _re_banner
    import html as _html_banner

    def _parse_pct_int(v):
        s = str(v or "").strip()
        m = _re_banner.search(r"(\d+)\s*%", s)
        return int(m.group(1)) if m else None

    # 出勤回数=0 かつ 未来日に就業予定があるワーカーの最早就業日
    _bn_next_shift: dict[str, str] = {}
    _bn_first_time: set[str] = set()
    for _r in _snapshot:
        _wid = _r.get("id")
        _ds = str(_r.get("就業日") or "")
        if not _wid or _ds < _today_iso:
            continue
        if int(_r.get("出勤回数", 0) or 0) != 0:
            continue
        _bn_first_time.add(_wid)
        _prev = _bn_next_shift.get(_wid)
        if not _prev or _ds < _prev:
            _bn_next_shift[_wid] = _ds

    _banner_lines: list[str] = []
    for _wid in _bn_first_time:
        _w = _workers.get(_wid, {})
        _good_int = _parse_pct_int(_w.get("good_rate"))
        _cancel_int = _parse_pct_int(_w.get("cancel_rate"))
        _name = _w.get("氏名") or "(氏名未登録)"
        _ds = _bn_next_shift[_wid]
        try:
            _d = _tm_date.fromisoformat(_ds)
            _date_str = f"{_d.month}/{_d.day}"
        except Exception:
            _date_str = _ds
        if _good_int is not None and _good_int < 80:
            _banner_lines.append(
                f"{_date_str}　{_name}　平均Good率　80％未満のためマッチングをキャンセルしてください"
            )
        if _cancel_int is not None and _cancel_int > 10:
            _banner_lines.append(
                f"{_date_str}　{_name}　直前キャンセル率　10％以上のためマッチングをキャンセルしてください"
            )

    if _banner_lines:
        _banner_html = "<br>".join(_html_banner.escape(l) for l in _banner_lines)
        st.markdown(
            f"""
            <div style='background:#fff3cd; border:2px solid #ffc107;
                        border-radius:6px; padding:12px 16px; margin:8px 0;
                        color:#856404; font-weight:600; font-size:14px; line-height:1.7;'>
              ⚠️ <b>キャンセル推奨ワーカー</b><br>{_banner_html}
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.divider()

    _tab_workers, _tab_calendar, _tab_schedule = st.tabs(
        ["👥 ワーカー一覧（編集可）", "📆 カレンダー", "📅 当月予定一覧"]
    )

    # スナップショットから「ワーカー別の業務(グループ)集合」を構築
    # 初回ワーカー判定 = 各レコードの「グループが空欄」かどうか（タイミー初稼働=履歴なしのため空）
    _worker_groups: dict[str, set[str]] = {}
    _first_time_wids: set[str] = set()  # 出勤回数=0 のレコードを持つワーカー
    for _r in _snapshot:
        _wid = _r.get("id")
        if not _wid:
            continue
        for _g in str(_r.get("グループ", "")).split(","):
            _g = _g.strip()
            if _g:
                _worker_groups.setdefault(_wid, set()).add(_g)
        if int(_r.get("出勤回数", 0) or 0) == 0:
            _first_time_wids.add(_wid)
    _all_group_tags = sorted({g for s in _worker_groups.values() for g in s})

    # ----- ワーカー一覧（編集可） -----
    with _tab_workers:
        st.caption("メモ・タグ・直雇勧誘済・チェック日 を編集して保存してください。タグはカンマ区切り。")

        # ---- 列の値から選ぶシンプルフィルタ ----
        # 各列の実在値を収集（空欄は「(空欄)」として選択肢化）
        _EMPTY = "(空欄)"
        _vals_gender: set[str] = set()
        _vals_promoted: set[str] = set()
        _vals_tags: set[str] = set()
        for wid, w in _workers.items():
            _vals_gender.add(str(w.get("性別") or "").strip() or _EMPTY)
            _vals_promoted.add("済" if w.get("直雇勧誘済") else "未")
            _tlist = w.get("タグ", []) or []
            if not _tlist:
                _vals_tags.add(_EMPTY)
            else:
                for _t in _tlist:
                    _t = str(_t).strip()
                    _vals_tags.add(_t if _t else _EMPTY)

        _opts_gender = sorted(_vals_gender)
        _opts_promoted = ["未", "済"]
        _opts_tags = sorted(_vals_tags)

        # 1段目: 自由検索
        _q = st.text_input("検索（氏名 / カナ / ID 部分一致）", key="tm_worker_search").strip()

        # 初回ワーカー(稼働実績なし)のみ表示
        _only_first_time = st.checkbox(
            "初回ワーカー（稼働実績なし）のみ表示",
            key="tm_worker_only_first",
        )

        # 2段目: 列値フィルタ（空＝全件）
        _f1, _f2, _f3, _f4 = st.columns(4)
        _sel_groups = _f1.multiselect("業務", _all_group_tags, key="tm_worker_groups")
        _sel_gender = _f2.multiselect("性別", _opts_gender, key="tm_worker_gender")
        _sel_promo = _f3.multiselect("直雇勧誘", _opts_promoted, key="tm_worker_promo")
        _sel_tags = _f4.multiselect("タグ", _opts_tags, key="tm_worker_tags")

        def _row_tag_set(_w) -> set[str]:
            _ts = _w.get("タグ", []) or []
            if not _ts:
                return {_EMPTY}
            return {(str(t).strip() or _EMPTY) for t in _ts}

        # フィルタ
        _filtered = []
        for wid, w in _workers.items():
            if _q:
                hay = f"{wid} {w.get('氏名','')} {w.get('カナ','')}"
                if _q not in hay:
                    continue
            if _sel_groups:
                if not _worker_groups.get(wid, set()).intersection(_sel_groups):
                    continue
            if _sel_gender:
                _g = str(w.get("性別") or "").strip() or _EMPTY
                if _g not in _sel_gender:
                    continue
            if _sel_promo:
                _p = "済" if w.get("直雇勧誘済") else "未"
                if _p not in _sel_promo:
                    continue
            if _sel_tags:
                if not _row_tag_set(w).intersection(_sel_tags):
                    continue
            if _only_first_time and wid not in _first_time_wids:
                continue
            _filtered.append((wid, w))
        _filtered.sort(key=lambda kv: kv[1].get("初回登録日", ""), reverse=True)

        # ワーカーごとの「現在マッチング中の出勤日」一覧（今日以降）
        _upcoming_shifts: dict[str, set[str]] = {}
        for _r in _snapshot:
            _wid = _r.get("id")
            if not _wid:
                continue
            _ds = str(_r.get("就業日") or "")
            if _ds < _today_iso:
                continue
            _upcoming_shifts.setdefault(_wid, set()).add(_ds)

        def _format_next_shift(wid: str) -> str:
            ds_set = _upcoming_shifts.get(wid)
            if not ds_set:
                return "未定"
            out = []
            for ds in sorted(ds_set):
                try:
                    d = _tm_date.fromisoformat(ds)
                    out.append(f"{d.month}/{d.day}")
                except Exception:
                    out.append(ds)
            return "\n".join(out)

        # data_editor 用 DataFrame
        _rows = []
        for wid, w in _filtered:
            _g_int = _parse_pct_int(w.get("good_rate"))
            _c_int = _parse_pct_int(w.get("cancel_rate"))
            _is_ft = wid in _first_time_wids
            _rows.append({
                "印": "🔴" if w.get("直雇勧誘済") else "",
                "ID": wid,
                "氏名": w.get("氏名", ""),
                "カナ": w.get("カナ", ""),
                "性別": w.get("性別", ""),
                "年齢": w.get("年齢"),
                "次回出勤日": _format_next_shift(wid),
                "業務": "\n".join(sorted(_worker_groups.get(wid, set()))),
                "初回登録日": w.get("初回登録日", ""),
                "Good率": _tm_pct_or_dash(w.get("good_rate")),
                "直前キャンセル率": _tm_pct_or_dash(w.get("cancel_rate")),
                "タイミーメモ": (str(w.get("timee_memo") or "").strip() or "—"),
                "メモ": w.get("メモ", ""),
                "タグ": ", ".join(w.get("タグ", []) or []),
                "直雇勧誘済": bool(w.get("直雇勧誘済", False)),
                "チェック日": w.get("チェック日"),
                "キャンセル数": len(w.get("キャンセル履歴", [])),
                "_good_alert": bool(_is_ft and _g_int is not None and _g_int < 80),
                "_cancel_alert": bool(_is_ft and _c_int is not None and _c_int > 10),
            })
        _wdf = pd.DataFrame(_rows)
        if _wdf.empty:
            st.info("該当ワーカーはありません。")
        else:
            st.caption("👆 行をクリックすると下に編集フォームが開きます。メモは Enter で改行できます。")

            # AgGrid: 行autoHeight + 行選択
            _gb = GridOptionsBuilder.from_dataframe(_wdf)
            _gb.configure_default_column(
                resizable=True, sortable=True, filter=False,
                wrapText=True, autoHeight=True,
                cellStyle={"whiteSpace": "pre-wrap", "lineHeight": "1.4",
                           "display": "flex", "alignItems": "center",
                           "justifyContent": "center", "textAlign": "center"},
            )
            # セル内のテキスト選択 → Ctrl+C コピーを許可
            _gb.configure_grid_options(
                enableCellTextSelection=True,
                ensureDomOrder=True,
            )
            # rerun後も選択を復元するため、保存中の wid に対応する行 index を渡す
            _persist_wid = st.session_state.get("tm_selected_wid")
            _pre_idx = []
            if _persist_wid:
                _idx_match = _wdf.index[_wdf["ID"] == _persist_wid].tolist()
                if _idx_match:
                    _pre_idx = [int(_idx_match[0])]
            _gb.configure_selection(
                selection_mode="single",
                use_checkbox=False,
                pre_selected_rows=_pre_idx,
            )
            # 固定幅カラム(数字/タグ/小さい列) と flex カラム(可変・残り幅を分配)
            _gb.configure_column("印", pinned="left", width=50, suppressSizeToFit=True)
            _gb.configure_column("ID", width=80, suppressSizeToFit=True)
            _gb.configure_column("氏名", flex=1, minWidth=100)
            _gb.configure_column("カナ", flex=1, minWidth=110)
            _gb.configure_column("性別", width=55, suppressSizeToFit=True)
            _gb.configure_column("年齢", width=60, type=["numericColumn"], suppressSizeToFit=True,
                cellStyle={"display": "flex", "alignItems": "center",
                           "justifyContent": "center", "textAlign": "center"})
            _gb.configure_column("次回出勤日", width=90, suppressSizeToFit=True)
            _gb.configure_column("業務", flex=2, minWidth=140,
                cellStyle={"whiteSpace": "pre-wrap", "lineHeight": "1.4",
                           "fontSize": "12px", "display": "flex", "alignItems": "center",
                           "justifyContent": "center", "textAlign": "center"})
            _gb.configure_column("初回登録日", width=100, suppressSizeToFit=True)
            _alert_good_style = JsCode("""
                function(params) {
                    var base = {'display': 'flex', 'alignItems': 'center',
                                'justifyContent': 'center', 'textAlign': 'center',
                                'whiteSpace': 'pre-wrap', 'lineHeight': '1.4'};
                    if (params.data && params.data._good_alert) {
                        base['backgroundColor'] = '#ffcdd2';
                        base['color'] = '#b71c1c';
                        base['fontWeight'] = 'bold';
                    }
                    return base;
                }
            """)
            _alert_cancel_style = JsCode("""
                function(params) {
                    var base = {'display': 'flex', 'alignItems': 'center',
                                'justifyContent': 'center', 'textAlign': 'center',
                                'whiteSpace': 'pre-wrap', 'lineHeight': '1.4'};
                    if (params.data && params.data._cancel_alert) {
                        base['backgroundColor'] = '#ffcdd2';
                        base['color'] = '#b71c1c';
                        base['fontWeight'] = 'bold';
                    }
                    return base;
                }
            """)
            _gb.configure_column("Good率", width=80, suppressSizeToFit=True,
                                 cellStyle=_alert_good_style)
            _gb.configure_column("直前キャンセル率", width=110, suppressSizeToFit=True,
                                 cellStyle=_alert_cancel_style)
            _gb.configure_column("_good_alert", hide=True)
            _gb.configure_column("_cancel_alert", hide=True)
            _gb.configure_column("タイミーメモ", flex=2, minWidth=160,
                cellStyle={"whiteSpace": "pre-wrap", "lineHeight": "1.4",
                           "fontSize": "12px", "background": "#f0f4f8",
                           "display": "flex", "alignItems": "center",
                           "justifyContent": "center", "textAlign": "center"})
            _gb.configure_column("メモ", flex=2, minWidth=160,
                cellStyle={"whiteSpace": "pre-wrap", "lineHeight": "1.5",
                           "background": "#fff8e1", "display": "flex", "alignItems": "center",
                           "justifyContent": "center", "textAlign": "center"})
            _gb.configure_column("タグ", flex=1, minWidth=120)
            _gb.configure_column("直雇勧誘済", width=95, suppressSizeToFit=True)
            _gb.configure_column("チェック日", width=110, suppressSizeToFit=True)
            _gb.configure_column("キャンセル数", width=90, type=["numericColumn"], suppressSizeToFit=True,
                cellStyle={"display": "flex", "alignItems": "center",
                           "justifyContent": "center", "textAlign": "center"})

            _ag_css_w = {
                ".ag-header-cell": {"background-color": "#E91E63", "color": "#fff",
                                    "font-weight": "bold", "text-align": "center"},
                ".ag-header-cell-label": {"justify-content": "center"},
                ".ag-row-odd": {"background-color": "#ffffff"},
                ".ag-row-even": {"background-color": "#fef0f4"},
                ".ag-row-selected": {"background-color": "#fce4ec !important"},
                # autoHeightで伸びた行内で、コンテンツを縦横中央寄せ
                ".ag-cell": {"display": "flex !important",
                             "align-items": "center !important",
                             "justify-content": "center !important"},
            }

            # 解除等で grid を再マウントするためのキーカウンタ
            _grid_key_n = st.session_state.get("tm_grid_key_n", 0)
            _grid = AgGrid(
                _wdf,
                gridOptions=_gb.build(),
                theme="balham",
                custom_css=_ag_css_w,
                fit_columns_on_grid_load=True,
                update_mode="SELECTION_CHANGED",
                allow_unsafe_jscode=True,
                height=600,
                key=f"tm_worker_grid_{_grid_key_n}",
            )

            # ----- 選択ワーカーの決定 -----
            # 行クリック検知: grid の selected_rows は再描画後もキャッシュを返すため、
            # 「前回検出した grid wid」と異なる時のみ「新しいクリック」と判定する。
            _sel = _grid.get("selected_rows")
            try:
                _has_grid_sel = (_sel is not None) and (len(_sel) > 0)
            except Exception:
                _has_grid_sel = False

            _grid_wid = None
            if _has_grid_sel:
                _sel_row = _sel.iloc[0] if hasattr(_sel, "iloc") else _sel[0]
                _grid_wid = str(_sel_row.get("ID") if hasattr(_sel_row, "get") else _sel_row["ID"])

            _prev_wid = st.session_state.get("tm_selected_wid")
            _last_grid_wid = st.session_state.get("tm_last_grid_wid")

            # grid 応答が前回と異なる = ユーザーが行を新規クリックした
            if _grid_wid != _last_grid_wid:
                st.session_state["tm_last_grid_wid"] = _grid_wid
                if _grid_wid and _grid_wid != _prev_wid:
                    st.session_state["tm_selected_wid"] = _grid_wid
                    st.rerun()

            _sel_wid = _prev_wid or _grid_wid
            if _sel_wid and _sel_wid in _workers:
                _sel_w = _workers.get(_sel_wid, {})

                st.divider()
                st.subheader(f"📝 編集中: {_sel_w.get('氏名','')}（{_sel_w.get('カナ','')}）　ID:{_sel_wid}")

                # タイミー詳細(読取専用): 平均Good率 / 直前キャンセル率 / 管理用メモ
                _good = _tm_pct_or_dash(_sel_w.get("good_rate"))
                _cancel = _tm_pct_or_dash(_sel_w.get("cancel_rate"))
                _tmm = str(_sel_w.get("timee_memo") or "").strip()
                _detail_at = str(_sel_w.get("timee_detail_fetched_at") or "").strip()
                _di1, _di2 = st.columns(2)
                _di1.metric("平均Good率（直近30回）", _good)
                _di2.metric("直前キャンセル率", _cancel)
                st.markdown("**タイミー管理用メモ** （タイミー上の値・読取専用）")
                if _tmm:
                    st.code(_tmm, language=None)
                else:
                    st.markdown("—")
                if _detail_at:
                    st.caption(f"タイミー側情報の最終取得: {_detail_at}")

                _ec1, _ec2 = st.columns([3, 2])
                with _ec1:
                    _new_memo = st.text_area(
                        "メモ（Enterで改行）",
                        value=_sel_w.get("メモ", ""),
                        height=200,
                        key=f"tm_memo_{_sel_wid}",
                    )
                with _ec2:
                    _new_tags = st.text_input(
                        "タグ（カンマ区切り）",
                        value=", ".join(_sel_w.get("タグ", []) or []),
                        key=f"tm_tags_{_sel_wid}",
                    )
                    _new_promoted = st.checkbox(
                        "直雇用勧誘済",
                        value=bool(_sel_w.get("直雇勧誘済", False)),
                        key=f"tm_promo_{_sel_wid}",
                    )
                    _existing_chk = str(_sel_w.get("チェック日") or "").strip()
                    if _existing_chk:
                        st.caption(f"📅 勧誘済日: {_existing_chk}")
                    else:
                        st.caption("📅 勧誘済日: （未記録）")

                _bs, _bc = st.columns([1, 1])
                if _bs.button("💾 保存", key=f"tm_save_{_sel_wid}", type="primary", use_container_width=True):
                    try:
                        _latest = _tms.load_workers()
                    except Exception as _e:
                        st.error(f"再読込に失敗: {_e}")
                        st.stop()
                    if _sel_wid not in _latest:
                        st.error("対象ワーカーがマスタにいません。")
                    else:
                        _latest[_sel_wid]["メモ"] = _new_memo
                        _latest[_sel_wid]["タグ"] = [t.strip() for t in _new_tags.split(",") if t.strip()]
                        _was_promoted = bool(_latest[_sel_wid].get("直雇勧誘済", False))
                        _latest[_sel_wid]["直雇勧誘済"] = bool(_new_promoted)
                        # 直雇用勧誘済を「未→済」にした保存時に、本日付をチェック日として自動記録
                        if (not _was_promoted) and _new_promoted:
                            _latest[_sel_wid]["チェック日"] = _today.isoformat()
                        try:
                            _tms.save_workers(_latest)
                        except Exception as _e:
                            st.error(f"保存に失敗: {_e}")
                            st.stop()
                        _tm_reload()
                        st.success("保存しました")
                        st.rerun()
                if _bc.button("選択解除", key=f"tm_clear_{_sel_wid}", use_container_width=True):
                    st.session_state.pop("tm_selected_wid", None)
                    st.session_state.pop("tm_last_grid_wid", None)
                    st.session_state.pop("tm_edit_pick", None)
                    # grid を再マウントしてキャッシュ済み selected_rows をクリア
                    st.session_state["tm_grid_key_n"] = st.session_state.get("tm_grid_key_n", 0) + 1
                    st.rerun()

        # キャンセル履歴展開
        with st.expander("📉 キャンセル履歴を確認"):
            _hist_rows = []
            for wid, w in _workers.items():
                for h in (w.get("キャンセル履歴") or []):
                    _hist_rows.append({
                        "ID": wid,
                        "氏名": w.get("氏名", ""),
                        "カナ": w.get("カナ", ""),
                        "検知日": h.get("検知日", ""),
                        "元就業日": h.get("元就業日", ""),
                    })
            if _hist_rows:
                _hdf = pd.DataFrame(_hist_rows).sort_values("検知日", ascending=False)
                st.dataframe(_hdf, hide_index=True, use_container_width=True)
            else:
                st.info("まだキャンセルは記録されていません。")

    # ----- カレンダー（月間グリッド: 日別人数表示） -----
    with _tab_calendar:
        if not _snapshot:
            st.info("予定データがまだ取り込まれていません。")
        else:
            import calendar as _tm_cal
            import html as _tm_html
            from datetime import date as _tm_d2

            _avail_months = sorted({r["就業日"][:7] for r in _snapshot
                                    if isinstance(r.get("就業日"), str) and len(r["就業日"]) >= 7})
            if not _avail_months:
                st.info("就業日データが正しく取り込まれていません。")
            else:
                _default_m = _today.strftime("%Y-%m")
                _y, _m, _sel_m = _tm_month_nav("tm_cal_month_nav", _default_m)

                # 業務(グループ)で絞り込み（任意）
                _cal_groups = st.multiselect(
                    "業務（グループ）で絞り込み（複数選択可・OR）",
                    _all_group_tags,
                    key="tm_cal_groups",
                )
                _cal_sel_set = set(_cal_groups)

                # 日別 求人ブロック一覧（タイミー求人カレンダー由来 / 5分同期で更新）
                _postings_by_day: dict[int, list[dict]] = {}
                for _p in _postings:
                    _pdate = str(_p.get("日付", "") or "")
                    if not _pdate.startswith(_sel_m):
                        continue
                    try:
                        _pday = int(_pdate[8:10])
                    except ValueError:
                        continue
                    _postings_by_day.setdefault(_pday, []).append(_p)
                # 同日内は開始時間→募集人数 で並べる
                for _lst in _postings_by_day.values():
                    _lst.sort(key=lambda x: (x.get("開始時間", ""), x.get("終了時間", ""), x.get("募集人数", 0)))

                # 日別人数を集計（業務フィルタ反映、カナ氏名）
                # 初回ワーカー = 「初回登録日 == その就業日」のワーカー
                # 直雇 = 直雇用勧誘済=Trueのワーカー
                _by_day_cnt: dict[int, int] = {}
                _by_day_kana: dict[int, list[tuple[str, bool, bool]]] = {}  # [(カナ, is_first, is_promoted)]
                for _r in _snapshot:
                    _ds = _r.get("就業日", "")
                    if not _ds.startswith(_sel_m):
                        continue
                    if _cal_sel_set:
                        _gset = {g.strip() for g in str(_r.get("グループ", "")).split(",") if g.strip()}
                        if not _gset.intersection(_cal_sel_set):
                            continue
                    try:
                        _dnum = int(_ds[8:10])
                    except ValueError:
                        continue
                    _by_day_cnt[_dnum] = _by_day_cnt.get(_dnum, 0) + 1
                    _w = _workers.get(_r["id"], {})
                    _is_first = not str(_r.get("グループ", "")).strip()
                    _is_promoted = bool(_w.get("直雇勧誘済", False))
                    _by_day_kana.setdefault(_dnum, []).append(
                        (_w.get("カナ", ""), _is_first, _is_promoted)
                    )

                # 曜日ヘッダー（月始まり: 月火水木金土日）
                _wd_labels = ["月", "火", "水", "木", "金", "土", "日"]
                _hcols = st.columns(7)
                for _i, _wd in enumerate(_wd_labels):
                    _wd_color = "#4a90e2" if _i == 5 else ("#e74c3c" if _i == 6 else "#444")
                    _hcols[_i].markdown(
                        f"<div style='text-align:center;font-weight:700;color:{_wd_color};"
                        f"padding:6px 0;border-bottom:2px solid #ddd;'>{_wd}</div>",
                        unsafe_allow_html=True,
                    )

                # monthcalendar は月始まり (firstweekday=0=月曜)
                _tm_cal.setfirstweekday(_tm_cal.MONDAY)
                _weeks = _tm_cal.monthcalendar(_y, _m)

                for _week in _weeks:
                    _cols = st.columns(7)
                    for _i, _day in enumerate(_week):
                        with _cols[_i]:
                            if _day == 0:
                                st.markdown("<div style='min-height:90px;'></div>", unsafe_allow_html=True)
                                continue
                            _d_obj = _tm_d2(_y, _m, _day)
                            _is_past = _d_obj < _today
                            _is_today = (_d_obj == _today)
                            _is_sat = _i == 5
                            _is_sun = _i == 6
                            _cnt = _by_day_cnt.get(_day, 0)

                            if _is_today:
                                _bg, _fg, _bd = "#fff3cd", "#664d03", "2px solid #f0c000"
                            elif _is_past:
                                _bg, _fg, _bd = "#f5f5f5", "#aaa", "1px solid #e0e0e0"
                            elif _is_sat:
                                _bg, _fg, _bd = "#e7f0fb", "#2c5fa0", "1px solid #c5d8ee"
                            elif _is_sun:
                                _bg, _fg, _bd = "#fde8ec", "#a5364c", "1px solid #f0c5cf"
                            else:
                                _bg, _fg, _bd = "#ffffff", "#222", "1px solid #d8dee5"

                            # 求人ブロックがあれば1日分を合算して N/M で表示
                            _postings_today = _postings_by_day.get(_day, [])
                            if _postings_today:
                                _sum_n = sum(int(_p.get("マッチ数", 0) or 0) for _p in _postings_today)
                                _sum_m = sum(int(_p.get("募集人数", 0) or 0) for _p in _postings_today)
                                if _is_past:
                                    _pcolor = "#888"
                                elif _sum_m > 0 and _sum_n >= _sum_m:
                                    _pcolor = "#28a745"
                                elif _sum_m > 0 and _sum_n < _sum_m:
                                    _pcolor = "#d97706"
                                else:
                                    _pcolor = "#1565c0"
                                _cnt_html = (
                                    f"<div style='font-size:16px;color:{_pcolor};font-weight:800;"
                                    f"margin-top:4px;line-height:1.2;'>{_sum_n}/{_sum_m}</div>"
                                )
                            elif _cnt > 0:
                                _cnt_html = (
                                    f"<div style='font-size:16px;font-weight:800;margin-top:4px;"
                                    f"color:{'#888' if _is_past else '#1565c0'};'>{_cnt}<span style='font-size:10px;'>名</span></div>"
                                )
                            else:
                                _cnt_html = "<div style='font-size:11px;color:#ccc;margin-top:6px;'>—</div>"

                            # マッチ済ワーカーのカナ氏名（印付き）。求人ブロック有無に関わらず表示。
                            if _cnt > 0:
                                _name_list = sorted(_by_day_kana.get(_day, []), key=lambda t: t[0])
                                _txt_color = "#bbb" if _is_past else "#444"
                                _blue = "#aaa" if _is_past else "#1976d2"
                                _red = "#aaa" if _is_past else "#e53935"
                                _yellow = "#ccc" if _is_past else "#f5b400"
                                _dot_style = "font-size:14px;font-weight:700;line-height:1;vertical-align:middle;"
                                _name_lines = []
                                for _kana, _is_first, _is_promoted in _name_list:
                                    _dots = ""
                                    if _is_promoted:
                                        _dots += f"<span style='color:{_red};{_dot_style}'>●</span>"
                                    if _is_first:
                                        _dots += f"<span style='color:{_blue};{_dot_style}'>●</span>"
                                    if not _is_promoted and not _is_first:
                                        _dots += f"<span style='color:{_yellow};{_dot_style}'>●</span>"
                                    if _dots:
                                        _dots += " "
                                    _name_lines.append(
                                        f"<span style='font-size:10px;color:{_txt_color};'>"
                                        f"{_dots}{_tm_html.escape(_kana)}</span>"
                                    )
                                _names_html = "<br>".join(_name_lines)
                            else:
                                _names_html = ""

                            st.markdown(
                                f"<div style='background:{_bg};color:{_fg};border:{_bd};"
                                f"border-radius:8px;padding:6px 6px;min-height:100px;text-align:center;"
                                f"margin-bottom:4px;overflow-wrap:break-word;'>"
                                f"<div style='font-size:14px;font-weight:700;'>{_day}</div>"
                                f"{_cnt_html}"
                                f"<div style='margin-top:4px;line-height:1.35;'>{_names_html}</div>"
                                f"</div>",
                                unsafe_allow_html=True,
                            )

                # 凡例
                st.caption(
                    f"📆 {_y}年{_m}月　|　🟨 本日　🩶 経過済　🟦 土曜　🟥 日曜　"
                    f"|　🔴 直雇用勧誘済　🔵 初回ワーカー　🟡 リピーター　"
                    f"|　業務フィルタ: {len(_cal_sel_set)}件選択中"
                )

    # ----- 就業日カレンダー（日別セクション・過去日は折りたたみ収納） -----
    with _tab_schedule:
        if not _snapshot:
            st.info("予定データがまだ取り込まれていません。")
        else:
            from datetime import datetime as _tm_dt
            import html as _tm_html

            # 月送りナビ
            _sch_default_m = _today.strftime("%Y-%m")
            _sch_y, _sch_m, _sch_sel_m = _tm_month_nav("tm_sch_month_nav", _sch_default_m)

            # フィルタUI
            _c_grp, _c_q = st.columns([3, 2])
            _sel_sch_groups = _c_grp.multiselect(
                "業務（グループ）で絞り込み（複数選択可・OR）",
                _all_group_tags,
                key="tm_sch_groups",
            )
            _qs = _c_q.text_input("検索（ID/氏名/カナ）", key="tm_sch_search").strip()

            # 日別グループ化
            _by_date: dict[str, list[dict]] = {}
            for _r in _snapshot:
                _by_date.setdefault(_r.get("就業日", ""), []).append(_r)

            _WEEKDAYS = ["月", "火", "水", "木", "金", "土", "日"]
            _total_shown = 0

            def _row_groups(r) -> set[str]:
                return {g.strip() for g in str(r.get("グループ", "")).split(",") if g.strip()}

            def _render_day_table_html(day_rows, is_past=False):
                _hcells = ["印", "ID", "氏名", "カナ", "性別", "年齢", "時間", "出勤回数", "業務", "キャンセル数"]
                _txt_color = "#888" if is_past else "#222"
                _row_bg = "#fafafa" if is_past else "#ffffff"
                _alt_bg = "#f5f5f5" if is_past else "#f8fafd"
                _blue = "#aaa" if is_past else "#1976d2"
                _red = "#aaa" if is_past else "#e53935"
                _head = "".join(
                    f"<th style='background:#eef2f7;color:#333;text-align:left;"
                    f"padding:8px 10px;border-bottom:2px solid #c5cdd6;font-size:13px;'>{h}</th>"
                    for h in _hcells
                )
                _body_rows = []
                for _i, _r in enumerate(day_rows):
                    _w = _workers.get(_r["id"], {})
                    _groups_html = "<br>".join(
                        _tm_html.escape(g) for g in sorted(_row_groups(_r))
                    ) or "—"
                    # 印（赤=直雇用勧誘済 / 青=グループ空欄=タイミー初回稼働ワーカー）
                    _is_first = not str(_r.get("グループ", "")).strip()
                    _is_promoted = bool(_w.get("直雇勧誘済", False))
                    _mark_html = ""
                    if _is_promoted:
                        _mark_html += f"<span style='color:{_red};font-size:16px;'>●</span>"
                    if _is_first:
                        _mark_html += f"<span style='color:{_blue};font-size:16px;'>●</span>"
                    _bg = _alt_bg if _i % 2 else _row_bg
                    _cells = [
                        _mark_html or "",
                        _tm_html.escape(str(_r["id"])),
                        _tm_html.escape(_w.get("氏名", "")),
                        _tm_html.escape(_w.get("カナ", "")),
                        _tm_html.escape(_w.get("性別", "")),
                        str(_w.get("年齢", "") if _w.get("年齢") is not None else ""),
                        _tm_html.escape(f"{_r.get('開始時間','')}-{_r.get('終了時間','')}"),
                        str(_r.get("出勤回数", 0)),
                        _groups_html,
                        str(len(_w.get("キャンセル履歴", []))),
                    ]
                    _body_rows.append(
                        f"<tr style='background:{_bg};'>" +
                        "".join(
                            f"<td style='color:{_txt_color};vertical-align:top;"
                            f"padding:8px 10px;border-bottom:1px solid #e6eaef;font-size:13px;'>{c}</td>"
                            for c in _cells
                        ) +
                        "</tr>"
                    )
                return (
                    "<table style='width:100%;border-collapse:collapse;"
                    "border:1px solid #d8dee5;border-radius:6px;overflow:hidden;margin:4px 0 12px 0;'>"
                    f"<thead><tr>{_head}</tr></thead>"
                    f"<tbody>{''.join(_body_rows)}</tbody></table>"
                )

            # 選択月のみを対象に、日付昇順で表示
            for _date_str in sorted(_by_date.keys()):
                if not _date_str.startswith(_sch_sel_m):
                    continue
                try:
                    _d_obj = _tm_dt.strptime(_date_str, "%Y-%m-%d").date()
                except ValueError:
                    continue

                # フィルタ適用
                _day_rows = _by_date[_date_str]
                if _sel_sch_groups:
                    _sel_set = set(_sel_sch_groups)
                    _day_rows = [r for r in _day_rows if _row_groups(r) & _sel_set]
                if _qs:
                    def _match(r, q=_qs):
                        w = _workers.get(r["id"], {})
                        return q in f"{r['id']} {w.get('氏名','')} {w.get('カナ','')}"
                    _day_rows = [r for r in _day_rows if _match(r)]
                if not _day_rows:
                    continue

                _wd = _WEEKDAYS[_d_obj.weekday()]
                _is_today = (_d_obj == _today)
                _is_weekend = _d_obj.weekday() >= 5
                _is_past = _d_obj < _today

                if _is_past:
                    _label = f"📅 {_date_str} ({_wd}) — {len(_day_rows)}名 ／ 経過済"
                    with st.expander(_label, expanded=False):
                        st.markdown(_render_day_table_html(_day_rows, is_past=True),
                                    unsafe_allow_html=True)
                else:
                    if _is_today:
                        _bg, _fg = "#fff3cd", "#664d03"
                        _label_prefix = "🔵 本日 "
                    elif _is_weekend:
                        _bg, _fg = "#fde8ec", "#a5364c"
                        _label_prefix = ""
                    else:
                        _bg, _fg = "#e6f3ff", "#0a3a6e"
                        _label_prefix = ""

                    _label = f"{_label_prefix}📅 {_date_str} ({_wd}) — {len(_day_rows)}名"
                    st.markdown(
                        f"<div style='background:{_bg}; color:{_fg}; padding:8px 14px; "
                        f"border-radius:8px; margin:14px 0 6px 0; font-weight:700; font-size:15px;'>"
                        f"{_label}</div>",
                        unsafe_allow_html=True,
                    )
                    st.markdown(_render_day_table_html(_day_rows, is_past=False),
                                unsafe_allow_html=True)

                _total_shown += len(_day_rows)

            if _total_shown == 0:
                st.info(f"{_sch_y}年{_sch_m}月 の予定はありません。")
            else:
                st.caption(f"表示中 {_total_shown:,} 件（{_sch_y}年{_sch_m}月）／ 全 {len(_snapshot):,} 件")

    st.stop()

# 単一DataFrame → dict に正規化
if isinstance(fetched, pd.DataFrame):
    tables = {metric.list_label: fetched}
else:
    tables = fetched


def _render_table(title: str, df: pd.DataFrame, key_suffix: str):
    if title and title != metric.label:
        st.subheader(title)
    if df is None or df.empty:
        st.info("該当データはありません。")
        return
    if metric.key in ("cs_shift", "shinsetsu_shift", "next_month_shift"):
        # AgGrid: 行ドラッグで並び替え可能
        import numpy as np
        df_ag = pd.DataFrame(
            {c: np.array([("" if pd.isna(v) else str(v)) for v in df[c]], dtype=object) for c in df.columns}
        )
        # カテゴリ別AgGrid配色
        AG_THEME = {
            "1週間後FC": {"headerBg": "#4A6FA5", "headerFg": "#fff", "oddBg": "#ffffff", "evenBg": "#f0f4fa", "fg": "#1a2a3a"},
            "促進": {"headerBg": "#2E8B57", "headerFg": "#fff", "oddBg": "#ffffff", "evenBg": "#edf7f1", "fg": "#1a2f22"},
            "TOTAL": {"headerBg": "#D4850A", "headerFg": "#fff", "oddBg": "#ffffff", "evenBg": "#fdf5e9", "fg": "#2a1f0a"},
            "責任者用": {"headerBg": "#8B5CF6", "headerFg": "#fff", "oddBg": "#ffffff", "evenBg": "#f3effe", "fg": "#2d1a5e"},
            "SECRET": {"headerBg": "#DC2626", "headerFg": "#fff", "oddBg": "#ffffff", "evenBg": "#fde8e8", "fg": "#3a0a0a"},
        }
        ag_t = AG_THEME.get(metric.category, AG_THEME["1週間後FC"])
        custom_css = {
            ".ag-header-cell": {"background-color": ag_t["headerBg"], "color": ag_t["headerFg"], "font-weight": "bold", "text-align": "center"},
            ".ag-header-cell-label": {"justify-content": "center"},
            ".ag-cell": {"text-align": "center", "display": "flex", "align-items": "center", "justify-content": "center", "color": ag_t["fg"], "font-weight": "bold"},
            ".ag-row-odd": {"background-color": ag_t["oddBg"]},
            ".ag-row-even": {"background-color": ag_t["evenBg"]},
        }
        if metric.key == "next_month_shift":
            custom_css[".ag-header-row"] = {"height": "50px"}
            custom_css[".ag-header-cell"] = {**custom_css[".ag-header-cell"], "height": "50px", "padding-top": "4px"}
            custom_css[".ag-header-cell-label"] = {"justify-content": "center", "white-space": "pre-wrap", "text-align": "center", "line-height": "1.2"}
        # 翌月シフト: 日付列ヘッダーに出勤人数を付与
        if metric.key == "next_month_shift" and not df_ag.empty:
            day_counts = {}
            for col in df_ag.columns:
                if col not in ("担当者", "合計"):
                    day_counts[col] = int((df_ag[col] != "").sum())
        else:
            day_counts = {}

        gb = GridOptionsBuilder.from_dataframe(df_ag)
        gb.configure_default_column(resizable=False, sortable=False, filter=False, suppressSizeToFit=True,
                                    cellStyle={"textAlign": "center", "display": "flex", "alignItems": "center", "justifyContent": "center"})
        # 列ごとに内容幅で固定
        for col in df_ag.columns:
            content_len = int(df_ag[col].map(len).max() or 0)
            header_len = len(str(col))
            max_len = max(content_len, header_len)
            if col == "担当者":
                width = max(130, max_len * 18 + 30)
                gb.configure_column(col, rowDrag=True, pinned="left", width=width, suppressSizeToFit=True)
            elif col == "合計":
                width = max(70, max_len * 9 + 16)
                gb.configure_column(col, pinned="left", width=width, suppressSizeToFit=True)
            elif col in day_counts:
                header_label = f"{col}\n({day_counts[col]}人)"
                width = max(60, max_len * 9 + 16)
                gb.configure_column(col, headerName=header_label, width=width, suppressSizeToFit=True)
            else:
                width = max(60, max_len * 9 + 16)
                gb.configure_column(col, width=width, suppressSizeToFit=True)
        grid_opts = dict(
            rowDragManaged=True,
            animateRows=True,
            suppressHorizontalScroll=False,
            alwaysShowHorizontalScroll=True,
        )
        ag_kwargs = dict(
            theme="balham",
            allow_unsafe_jscode=True,
            custom_css=custom_css,
            key=f"aggrid_{metric.key}_{key_suffix}",
        )
        if metric.key in ("next_month_shift", "cs_shift", "shinsetsu_shift"):
            grid_opts["domLayout"] = "autoHeight"
            gb.configure_grid_options(**grid_opts)
            AgGrid(df_ag, gridOptions=gb.build(), **ag_kwargs)
        else:
            gb.configure_grid_options(**grid_opts)
            AgGrid(df_ag, gridOptions=gb.build(), height=max(200, 45 + 32 * len(df_ag)), **ag_kwargs)
    else:
        # カテゴリ別配色
        THEME = {
            "1週間後FC": {
                "th_bg": "#4A6FA5", "th_border": "#3A5F95", "th_color": "#ffffff",
                "even_bg": "#f0f4fa", "odd_bg": "#ffffff", "hover_bg": "#dce6f5",
                "td_color": "#1a2a3a", "td_border": "#c8d4e3",
            },
            "促進": {
                "th_bg": "#2E8B57", "th_border": "#257A4A", "th_color": "#ffffff",
                "even_bg": "#edf7f1", "odd_bg": "#ffffff", "hover_bg": "#d4eddf",
                "td_color": "#1a2f22", "td_border": "#bdd8c9",
            },
            "TOTAL": {
                "th_bg": "#D4850A", "th_border": "#B8730A", "th_color": "#ffffff",
                "even_bg": "#fdf5e9", "odd_bg": "#ffffff", "hover_bg": "#f5e4c8",
                "td_color": "#2a1f0a", "td_border": "#e0d0b5",
            },
            "SECRET": {
                "th_bg": "#DC2626", "th_border": "#B91C1C", "th_color": "#ffffff",
                "even_bg": "#fde8e8", "odd_bg": "#ffffff", "hover_bg": "#fbcaca",
                "td_color": "#3a0a0a", "td_border": "#f0b8b8",
            },
        }
        t = THEME.get(metric.category, THEME["1週間後FC"])
        # テーブルごとにユニークなクラスを付与（同カテゴリ複数表でCSSが混線するのを防ぐ）
        css_class = f"table-{metric.category.replace(' ', '_')}-{key_suffix}"
        html = df.to_html(index=False, escape=False)
        st.markdown(
            f"""
            <style>
            .{css_class} {{
                width: 100%;
                border-collapse: collapse;
                font-size: 0.9rem;
            }}
            .{css_class} th {{
                text-align: center !important;
                vertical-align: middle !important;
                padding: 8px 10px;
                background: {t['th_bg']};
                color: {t['th_color']};
                font-weight: 600;
                border: 1px solid {t['th_border']};
                position: sticky;
                top: 0;
            }}
            .{css_class} td {{
                text-align: center !important;
                vertical-align: middle !important;
                padding: 6px 10px;
                color: {t['td_color']};
                border: 1px solid {t['td_border']};
                font-weight: bold;
            }}
            .{css_class} tr:nth-child(even) {{
                background: {t['even_bg']};
            }}
            .{css_class} tr:nth-child(odd) {{
                background: {t['odd_bg']};
            }}
            .{css_class} tr:hover {{
                background: {t['hover_bg']};
            }}
            @media screen and (max-width: 768px) {{
                .responsive-table-wrapper {{
                    overflow-x: auto;
                    -webkit-overflow-scrolling: touch;
                }}
                .{css_class} {{
                    font-size: 0.75rem;
                    min-width: 600px;
                }}
                .{css_class} th {{
                    padding: 5px 6px;
                    white-space: nowrap;
                }}
                .{css_class} td {{
                    padding: 4px 6px;
                    white-space: nowrap;
                }}
            }}
            </style>
            """,
            unsafe_allow_html=True,
        )
        # 開通進捗ハイライト
        # - 1日目〜7日目CX(数/率)を薄い赤で
        # - NURO「工事完了率」/ ソネット「入金率」を黄色で目立たせる
        # - 促進必要件数を青で目立たせる
        highlight_col = None
        if title and ("NURO" in title or "AU光" in title):
            highlight_col = "工事完了率"
        elif title and "ソネット" in title:
            highlight_col = "入金率"
        is_progress = bool(highlight_col)
        cols_list = list(df.columns)
        col_idx = cols_list.index(highlight_col) if highlight_col and highlight_col in cols_list else None
        sokushin_idx = cols_list.index("促進必要件数") if is_progress and "促進必要件数" in cols_list else None
        cx_target_cols = []
        if is_progress:
            for d in range(1, 8):  # 1日目〜7日目
                for suffix in ("CX数", "CX率"):
                    name = f"{d}日目{suffix}"
                    if name in cols_list:
                        cx_target_cols.append(cols_list.index(name))
        if col_idx is not None or cx_target_cols or sokushin_idx is not None:
            hl_rules = []
            for ci in cx_target_cols:
                n = ci + 1
                hl_rules.append(
                    f".{css_class} th:nth-child({n}), .{css_class} td:nth-child({n}) "
                    f"{{ background:#F5B7B1 !important; color:#641E16 !important; }}"
                )
            if col_idx is not None:
                n = col_idx + 1
                hl_rules.append(
                    f".{css_class} th:nth-child({n}), .{css_class} td:nth-child({n}) "
                    f"{{ background:#F1C40F !important; color:#1a1a1a !important; font-weight:700 !important; }}"
                )
            if sokushin_idx is not None:
                n = sokushin_idx + 1
                hl_rules.append(
                    f".{css_class} th:nth-child({n}), .{css_class} td:nth-child({n}) "
                    f"{{ background:#5DADE2 !important; color:#ffffff !important; font-weight:700 !important; }}"
                )
            st.markdown("<style>" + "\n".join(hl_rules) + "</style>", unsafe_allow_html=True)
        table_html = html.replace("<table", f'<table class="{css_class}"', 1)
        st.markdown(f'<div class="responsive-table-wrapper">{table_html}</div>', unsafe_allow_html=True)
    st.download_button(
        "CSV ダウンロード",
        df.to_csv(index=False).encode("utf-8-sig"),
        file_name=f"{metric.key}_{key_suffix}.csv",
        mime="text/csv",
        key=f"dl_{metric.key}_{key_suffix}",
    )


def _render_sokushin_details(title: str, details_df: pd.DataFrame, key_suffix: str):
    """促進必要件数の対象レコードを月別タブで表示。"""
    if details_df is None or details_df.empty:
        return
    months = sorted(details_df["月"].unique(), reverse=True)
    if not months:
        return
    # 表示列 = 月以外の全列(metrics側で順序指定済)
    display_cols = [c for c in details_df.columns if c != "月"]
    with st.expander(f"促進必要件数 一覧（{title}）", expanded=False):
        # 全月まとめCSV(月列も含めて出力)
        all_df = details_df[["月"] + display_cols].reset_index(drop=True)
        st.download_button(
            "全月まとめてCSVダウンロード",
            all_df.to_csv(index=False).encode("utf-8-sig"),
            file_name=f"sokushin_need_{title}_all.csv",
            mime="text/csv",
            key=f"dl_sokushin_all_{key_suffix}",
        )
        tab_labels = [f"{m}（{int((details_df['月']==m).sum())}件）" for m in months]
        tabs = st.tabs(tab_labels)
        for tab, month in zip(tabs, months):
            with tab:
                month_df = (
                    details_df[details_df["月"] == month][display_cols]
                    .reset_index(drop=True)
                )
                st.dataframe(month_df, use_container_width=True, hide_index=True)
                st.download_button(
                    f"{month} のCSVをダウンロード",
                    month_df.to_csv(index=False).encode("utf-8-sig"),
                    file_name=f"sokushin_need_{title}_{month}.csv",
                    mime="text/csv",
                    key=f"dl_sokushin_{key_suffix}_{month}",
                )


if metric.key == "daikon_kaitsu":
    # ET月ごとにタブ表示（新しい月が左）
    month_keys = list(tables.keys())
    if not month_keys:
        st.info("該当データはありません。")
    else:
        tab_labels = [f"📅 {ym}" for ym in month_keys]
        month_tabs = st.tabs(tab_labels)
        for ti, (tab, ym) in enumerate(zip(month_tabs, month_keys)):
            with tab:
                month_tables = tables[ym] or {}
                if not month_tables or all(
                    (df is None or df.empty) for df in month_tables.values()
                ):
                    st.info(f"{ym} の該当データはありません。")
                    continue
                for ji, (sub_title, sub_df) in enumerate(month_tables.items()):
                    _render_table(sub_title, sub_df, f"{ti}_{ji}")
else:
    for i, (title, value) in enumerate(tables.items()):
        if isinstance(value, dict):
            df_summary = value.get("summary")
            df_details = value.get("details")
            missing_labels = value.get("missing_labels") or []
        else:
            df_summary = value
            df_details = None
            missing_labels = []
        _render_table(title, df_summary, str(i))
        if df_details is not None:
            _render_sokushin_details(title, df_details, str(i))
            if missing_labels:
                st.caption(
                    f"⚠ Salesforce で見つからなかったラベル: " + ", ".join(f"`{l}`" for l in missing_labels)
                )
        st.divider()
