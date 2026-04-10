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
from metrics import METRICS, get_metric

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
_REALTIME_KEYS = {"day_calls", "today", "cs_shift", "list_volume", "shinsetsu_today", "shinsetsu_shift"}
# 2時間キャッシュ
_CACHE_2H_KEYS = {"total_calls", "fc_1week", "sokushin_monthly"}
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


@st.cache_data(ttl=7200, show_spinner="Salesforce から取得中...")
def _load_2h(metric_key: str) -> pd.DataFrame:
    return get_metric(metric_key).fetch(_sf())


@st.cache_data(ttl=86400, show_spinner="Salesforce から取得中...")
def _load_daily(metric_key: str, _cache_day: str) -> pd.DataFrame:
    return get_metric(metric_key).fetch(_sf())


def _load(metric_key: str):
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
with open("5065e1e637de06a018cf1dbbf567009a.png", "rb") as f:
    _icon_b64 = base64.b64encode(f.read()).decode()
st.sidebar.markdown(
    f'<div style="display:flex;align-items:center;gap:10px;margin-bottom:10px;">'
    f'<img src="data:image/png;base64,{_icon_b64}" width="80">'
    f'<span style="font-size:1.5rem;font-weight:bold;">CS促進</span>'
    f'</div>',
    unsafe_allow_html=True,
)

# カテゴリでグルーピング
categories: dict[str, list] = {}
for m in METRICS:
    categories.setdefault(m.category, []).append(m)
label_to_key = {m.label: m.key for m in METRICS}

# セッションに並び順を保持
if "board_order" not in st.session_state:
    st.session_state["board_order"] = [
        {"header": cat, "items": [m.label for m in ms]}
        for cat, ms in categories.items()
    ]

# カテゴリ別配色
_CAT_COLORS = {
    "1週間後FC": {"bg": "#4A6FA5", "fg": "#ffffff"},
    "促進":      {"bg": "#2E8B57", "fg": "#ffffff"},
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
                else:
                    st.session_state[toggle_key] = not is_open
                    st.rerun()
        if is_open:
            for label in container["items"]:
                mkey = label_to_key.get(label)
                if mkey and st.sidebar.button(label, key=f"btn_{mkey}", use_container_width=True):
                    st.session_state["selected"] = mkey
valid_keys = {m.key for m in METRICS} | {"_master", "_responsible_auth"}
if st.session_state.get("selected") not in valid_keys:
    st.session_state["selected"] = METRICS[0].key

selected_key = st.session_state["selected"]

if st.sidebar.button("🔄 キャッシュ更新", width="stretch"):
    _load_2h.clear()
    _load_daily.clear()
    st.rerun()

st.sidebar.caption("データは5分間キャッシュされます")

# カテゴリトグルボタンの配色をJSで適用
import streamlit.components.v1 as components
components.html("""
<script>
const colorMap = {
    '1週間後FC': {bg: '#4A6FA5', hover: '#3A5F95'},
    '促進':      {bg: '#2E8B57', hover: '#257A4A'},
    '責任者用':  {bg: '#8B5CF6', hover: '#7C3AED'},
};
function styleCatButtons() {
    const sidebar = window.parent.document.querySelector('[data-testid="stSidebar"]');
    if (!sidebar) return;
    const buttons = sidebar.querySelectorAll('button');
    buttons.forEach(btn => {
        const text = btn.textContent.trim().replace(/^[▶▼]\\s*/, '');
        const c = colorMap[text];
        if (c) {
            btn.style.cssText = 'background:'+c.bg+' !important;color:#fff !important;font-weight:700 !important;font-size:1.05rem !important;border:none !important;border-radius:8px !important;';
            btn.onmouseenter = () => btn.style.background = c.hover;
            btn.onmouseleave = () => btn.style.background = c.bg;
        }
    });
}
styleCatButtons();
const obs = new MutationObserver(styleCatButtons);
obs.observe(window.parent.document.body, {childList: true, subtree: true});
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
    st.subheader("ボード並び順の変更")
    st.caption("ドラッグ＆ドロップで並び替えてください。変更は即座にサイドバーへ反映されます。")
    new_order = sort_items(
        st.session_state["board_order"],
        multi_containers=True,
        direction="vertical",
    )
    st.session_state["board_order"] = new_order
    st.stop()

metric = get_metric(selected_key)
st.markdown(f'<h1 translate="no">{metric.label}</h1>', unsafe_allow_html=True)

# 育成KPI: カテゴリ→メンバータブ表示
if selected_key == "ikusei_kpi":
    _IKUSEI_DEFAULT = [
        {"header": "1週間後FC", "items": ["堀田 輝斗", "角田 心華"]},
        {"header": "促進", "items": ["半田 さくら", "菊地 隆真", "栗田 優衣", "高橋 真友香"]},
    ]
    if "ikusei_order" not in st.session_state:
        st.session_state["ikusei_order"] = _IKUSEI_DEFAULT

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

    # カテゴリ→メンバータブ
    groups = st.session_state["ikusei_order"]
    cat_names = [g["header"] for g in groups if g["items"]]
    if cat_names:
        cat_tabs = st.tabs(cat_names)
        for cat_tab, group in zip(cat_tabs, [g for g in groups if g["items"]]):
            with cat_tab:
                member_tabs = st.tabs(group["items"])
                for m_tab, member in zip(member_tabs, group["items"]):
                    with m_tab:
                        import numpy as np
                        from datetime import datetime, timezone, timedelta

                        member_key = member.replace(" ", "").replace("\u3000", "")
                        data_key = f"ikusei_data_{member_key}"

                        # 初期データ
                        if data_key not in st.session_state:
                            st.session_state[data_key] = pd.DataFrame({
                                "項目": [""] * 20,
                                "取得したいスキル": [""] * 20,
                                "進捗": [False] * 20,
                                "完了日": [""] * 20,
                                "メモ": [""] * 20,
                            })

                        df_ag = st.session_state[data_key].copy()
                        # AgGrid用に文字列化
                        for c in ["項目", "取得したいスキル", "完了日", "メモ"]:
                            df_ag[c] = df_ag[c].fillna("").astype(str)
                        df_ag["進捗"] = df_ag["進捗"].astype(bool)

                        # Enterで改行できるカスタムポップアップエディタ
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
                                        if (e.key === 'Enter' && !e.shiftKey) {
                                            e.stopPropagation();
                                        }
                                        if (e.key === 'Escape') {
                                            params.stopEditing();
                                        }
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
                        # 項目: ポップアップ編集 + 自動改行
                        gb.configure_column("項目", editable=True,
                            cellEditor=popup_editor,
                            cellEditorPopup=True,
                            wrapText=True, autoHeight=True,
                            flex=2, minWidth=200,
                            cellStyle=_popup_col_style,
                        )
                        gb.configure_column("取得したいスキル", flex=2, minWidth=150,
                            cellEditor=popup_editor,
                            cellEditorPopup=True,
                            wrapText=True, autoHeight=True,
                            cellStyle=_popup_col_style,
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
                                    refresh(params) {
                                        this.eGui.checked = params.value === true;
                                        return true;
                                    }
                                }
                            """),
                        )
                        gb.configure_column("完了日", width=90, editable=False)
                        gb.configure_column("メモ", flex=2, minWidth=150,
                            cellEditor=popup_editor,
                            cellEditorPopup=True,
                            wrapText=True, autoHeight=True,
                            cellStyle=_popup_col_style,
                        )

                        # 進捗チェック時に完了日を自動設定するJS
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
                            key=f"ikusei_ag_{member_key}",
                            update_mode="VALUE_CHANGED",
                        )
                        # 編集結果をセッションに保存
                        if ag_result and ag_result.data is not None:
                            st.session_state[data_key] = ag_result.data
    st.stop()

try:
    fetched = _load(selected_key)
except Exception as e:
    st.error(f"取得に失敗しました: {e}")
    st.stop()

# DAYコール数: 帯グラフ表示
if selected_key == "day_calls":
    import plotly.express as px

    def _render_bar_chart(title: str, df_src):
        st.subheader(title)
        if df_src is None or not isinstance(df_src, pd.DataFrame) or df_src.empty or "担当者" not in df_src.columns:
            st.info("該当データはありません。")
            return
        df_c = df_src.copy()
        totals = df_c.groupby("担当者")["コール数"].sum().sort_values(ascending=False)
        order = totals.index.tolist()
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
    if metric.key in ("cs_shift", "shinsetsu_shift"):
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
        }
        ag_t = AG_THEME.get(metric.category, AG_THEME["1週間後FC"])
        custom_css = {
            ".ag-header-cell": {"background-color": ag_t["headerBg"], "color": ag_t["headerFg"], "font-weight": "bold", "text-align": "center"},
            ".ag-header-cell-label": {"justify-content": "center"},
            ".ag-cell": {"text-align": "center", "display": "flex", "align-items": "center", "justify-content": "center", "color": ag_t["fg"], "font-weight": "bold"},
            ".ag-row-odd": {"background-color": ag_t["oddBg"]},
            ".ag-row-even": {"background-color": ag_t["evenBg"]},
        }
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
            else:
                width = max(60, max_len * 9 + 16)
                gb.configure_column(col, width=width, suppressSizeToFit=True)
        gb.configure_grid_options(
            rowDragManaged=True,
            animateRows=True,
            suppressHorizontalScroll=False,
            alwaysShowHorizontalScroll=True,
        )
        AgGrid(
            df_ag,
            gridOptions=gb.build(),
            height=max(200, 45 + 32 * len(df_ag)),
            theme="balham",
            allow_unsafe_jscode=True,
            custom_css=custom_css,
            key=f"aggrid_{metric.key}_{key_suffix}",
        )
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
