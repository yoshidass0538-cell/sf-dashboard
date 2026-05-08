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
def _load_daily(metric_key: str, _cache_day: str, _v: int = 2) -> pd.DataFrame:
    return get_metric(metric_key).fetch(_sf())


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
}

# サイドバー: TOTAL はそのまま表示、他カテゴリはトグル式
for container in st.session_state["board_order"]:
    cat = container["header"]
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
                else:
                    st.session_state[toggle_key] = not is_open
                    st.rerun()
        if is_open:
            # ツールは「メンバー → ボード」の2階層ネスト描画
            # メンバー順は board_order の保存済みitemsを使用
            if cat == "ツール":
                from tool_members_store import get_member_assignments, get_all_member_names, is_excluded_member as _tool_excluded
                _all_names = get_all_member_names()
                for _member_name in container["items"]:
                    if _member_name not in _all_names:
                        continue
                    if _tool_excluded(_member_name):
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
valid_keys = {m.key for m in METRICS} | {"_master", "_responsible_auth", "_timee_auth"}
_sel = st.session_state.get("selected")
# talk_script_* は動的生成のため、キャッシュ未更新でも有効とみなす
if _sel not in valid_keys and not (_sel and _sel.startswith("talk_script_")):
    st.session_state["selected"] = METRICS[0].key

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
    clear_check_cache()
    clear_members_cache()
    clear_template_cache()
    _clear_ts_caches()
    reload_talk_script_metrics()
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

if st.sidebar.button("🔒 マスタ", key="btn_master", width="stretch"):
    st.session_state["selected"] = "_master"


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
    if info is None:
        st.warning(f"電話番号 `{phone_clean}` に該当する顧客情報が見つかりません。")
        st.stop()

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
    from orikaeshi_check_store import get_checks, save_checks

    # 10分ごとに自動更新（キャッシュ更新ボタンを押さなくてもデータが新しくなる）
    try:
        from streamlit_autorefresh import st_autorefresh as _ok_autorefresh
        _ok_autorefresh(interval=600000, key="orikaeshi_autorefresh")
    except ImportError:
        pass

    checks = get_checks()
    changed = False

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

        # --- 件数テーブル (HTML) ---
        css_cls = f"table-orikaeshi-{i}"
        html = df.to_html(index=False, escape=False)
        st.markdown(
            f"""
            <style>
            .{css_cls} {{ width:100%; border-collapse:collapse; font-size:0.9rem; }}
            .{css_cls} th {{ text-align:center!important; vertical-align:middle!important; padding:8px 10px; background:{t['th_bg']}; color:{t['th_color']}; font-weight:600; border:1px solid {t['th_border']}; position:sticky; top:0; }}
            .{css_cls} td {{ text-align:center!important; vertical-align:middle!important; padding:6px 10px; color:{t['td_color']}; border:1px solid {t['td_border']}; font-weight:bold; }}
            .{css_cls} tr:nth-child(even) {{ background:{t['even_bg']}; }}
            .{css_cls} tr:nth-child(odd) {{ background:{t['odd_bg']}; }}
            .{css_cls} tr:hover {{ background:{t['hover_bg']}; }}
            @media screen and (max-width:768px) {{
                .{css_cls} {{ font-size:0.75rem; min-width:600px; }}
                .{css_cls} th {{ padding:5px 6px; white-space:nowrap; }}
                .{css_cls} td {{ padding:4px 6px; white-space:nowrap; }}
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
                time_vals[tc] = checks.get(key, False)
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
                this.g.style.width='16px';
                this.g.style.height='16px';
                this.h=e=>{p.node.setDataValue(p.column.colId,e.target.checked);};
                this.g.addEventListener('click',this.h);
            }
            getGui(){return this.g;}
            refresh(p){this.g.checked=p.value===true;return true;}
            destroy(){this.g.removeEventListener('click',this.h);}
        }
        """)

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
            flex=2, minWidth=140,
            cellStyle={"fontWeight": "bold", "textAlign": "left",
                       "display": "flex", "alignItems": "center"})
        gb.configure_column("ALL",
            editable=True, flex=1, minWidth=50,
            headerClass="orikaeshi-all-hdr",
            cellStyle={"backgroundColor": "rgba(212,133,10,0.25)",
                       "display": "flex", "alignItems": "center",
                       "justifyContent": "center"})
        for tc in check_time_cols:
            gb.configure_column(tc, editable=True, flex=1, minWidth=50,
                cellStyle={"display": "flex", "alignItems": "center",
                           "justifyContent": "center"})
        gb.configure_grid_options(
            onCellValueChanged=_all_toggle,
        )

        _ag_css = {
            ".ag-header-cell": {
                "background-color": "#555",
                "color": "#fff",
                "font-weight": "bold",
                "text-align": "center",
            },
            ".ag-header-cell-label": {"justify-content": "center"},
            ".orikaeshi-all-hdr": {
                "background-color": "#D4850A !important",
                "color": "#fff !important",
                "font-weight": "900 !important",
                "font-size": "0.95rem !important",
            },
            ".ag-row-odd": {"background-color": "#ffffff"},
            ".ag-row-even": {"background-color": "#fdf5e9"},
        }

        ag_result = AgGrid(
            check_df,
            gridOptions=gb.build(),
            height=max(120, 42 + 35 * len(check_df)),
            theme="balham",
            allow_unsafe_jscode=True,
            custom_css=_ag_css,
            fit_columns_on_grid_load=True,
            update_mode="VALUE_CHANGED",
            key=f"orikaeshi_chk_{i}",
        )

        # 変更検知 → 共有ストアに反映
        if ag_result and ag_result.data is not None:
            for _, row in ag_result.data.iterrows():
                cat = row["種別"]
                for tc in check_time_cols:
                    key = f"{date_str}|{cat}|{tc}"
                    val = bool(row[tc])
                    old_val = checks.get(key, False)
                    if val != old_val:
                        if val:
                            checks[key] = True
                        else:
                            checks.pop(key, None)
                        changed = True

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

    st.divider()

    _tab_workers, _tab_calendar, _tab_schedule = st.tabs(
        ["👥 ワーカー一覧（編集可）", "📆 カレンダー", "📅 当月予定一覧"]
    )

    # スナップショットから「ワーカー別の業務(グループ)集合」を構築
    # 初回ワーカー判定 = 各レコードの「グループが空欄」かどうか（タイミー初稼働=履歴なしのため空）
    _worker_groups: dict[str, set[str]] = {}
    for _r in _snapshot:
        _wid = _r.get("id")
        if not _wid:
            continue
        for _g in str(_r.get("グループ", "")).split(","):
            _g = _g.strip()
            if _g:
                _worker_groups.setdefault(_wid, set()).add(_g)
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
            _gb.configure_column("印", pinned="left", width=60)
            _gb.configure_column("ID", width=90)
            _gb.configure_column("氏名", width=130)
            _gb.configure_column("カナ", width=140)
            _gb.configure_column("性別", width=60)
            _gb.configure_column("年齢", width=70, type=["numericColumn"])
            _gb.configure_column("次回出勤日", width=100)
            _gb.configure_column("業務", width=240,
                cellStyle={"whiteSpace": "pre-wrap", "lineHeight": "1.4",
                           "fontSize": "12px", "display": "flex", "alignItems": "center",
                           "justifyContent": "center", "textAlign": "center"})
            _gb.configure_column("初回登録日", width=110)
            _gb.configure_column("Good率", width=90)
            _gb.configure_column("直前キャンセル率", width=120)
            _gb.configure_column("タイミーメモ", width=240,
                cellStyle={"whiteSpace": "pre-wrap", "lineHeight": "1.4",
                           "fontSize": "12px", "background": "#f0f4f8",
                           "display": "flex", "alignItems": "center",
                           "justifyContent": "center", "textAlign": "center"})
            _gb.configure_column("メモ", width=260,
                cellStyle={"whiteSpace": "pre-wrap", "lineHeight": "1.5",
                           "background": "#fff8e1", "display": "flex", "alignItems": "center",
                           "justifyContent": "center", "textAlign": "center"})
            _gb.configure_column("タグ", width=180)
            _gb.configure_column("直雇勧誘済", width=110)
            _gb.configure_column("チェック日", width=120)
            _gb.configure_column("キャンセル数", width=100, type=["numericColumn"])

            _ag_css_w = {
                ".ag-header-cell": {"background-color": "#E91E63", "color": "#fff",
                                    "font-weight": "bold", "text-align": "center"},
                ".ag-header-cell-label": {"justify-content": "center"},
                ".ag-row-odd": {"background-color": "#ffffff"},
                ".ag-row-even": {"background-color": "#fef0f4"},
                ".ag-row-selected": {"background-color": "#fce4ec !important"},
            }

            # 解除等で grid を再マウントするためのキーカウンタ
            _grid_key_n = st.session_state.get("tm_grid_key_n", 0)
            _grid = AgGrid(
                _wdf,
                gridOptions=_gb.build(),
                theme="balham",
                custom_css=_ag_css_w,
                fit_columns_on_grid_load=False,
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
        }
        t = THEME.get(metric.category, THEME["1週間後FC"])
        css_class = f"table-{metric.category.replace(' ', '_')}"
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
        # 開通進捗: 特定列以降をハイライト（NURO=4日目〜, ソネット=5日目〜）
        highlight_from = None
        if title and "NURO" in title:
            highlight_from = "4日目CX数"
        elif title and "ソネット" in title:
            highlight_from = "5日目CX数"
        if highlight_from and highlight_from in df.columns:
            import re
            col_idx = list(df.columns).index(highlight_from)
            def _highlight_row(m):
                tag = m.group(0)
                cells = re.findall(r"<(th|td)\b[^>]*>.*?</\1>", tag, re.DOTALL)
                if not cells:
                    return tag
                for i, cell in enumerate(cells):
                    if i >= col_idx:
                        new_cell = re.sub(r"<(th|td)\b", r'<\1 class="cx-hl"', cell, count=1)
                        tag = tag.replace(cell, new_cell, 1)
                return tag
            html = re.sub(r"<tr\b[^>]*>.*?</tr>", _highlight_row, html, flags=re.DOTALL)
            hl_css = f"""
            .{css_class} .cx-hl {{
                background: #C0392B !important;
                color: #ffffff !important;
            }}
            .{css_class} tr:hover .cx-hl {{
                background: #A93226 !important;
            }}
            """
            st.markdown(f"<style>{hl_css}</style>", unsafe_allow_html=True)
        table_html = html.replace("<table", f'<table class="{css_class}"', 1)
        st.markdown(f'<div class="responsive-table-wrapper">{table_html}</div>', unsafe_allow_html=True)
    st.download_button(
        "CSV ダウンロード",
        df.to_csv(index=False).encode("utf-8-sig"),
        file_name=f"{metric.key}_{key_suffix}.csv",
        mime="text/csv",
        key=f"dl_{metric.key}_{key_suffix}",
    )


for i, (title, df) in enumerate(tables.items()):
    _render_table(title, df, str(i))
    st.divider()
