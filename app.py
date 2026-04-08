"""
Salesforce 集計ダッシュボード（Streamlit）

ローカル実行:
    py -m streamlit run app.py

新しい集計を追加するには metrics.py に Metric を追記するだけ。
"""

import pandas as pd
import streamlit as st

from sf_client import get_sf
from metrics import METRICS, get_metric

st.set_page_config(page_title="SF 集計ダッシュボード", page_icon="📊", layout="wide")


# ----------------------------------------------------------------------
# 接続 & データ取得（キャッシュ）
# ----------------------------------------------------------------------
@st.cache_resource
def _sf():
    return get_sf()


@st.cache_data(ttl=300, show_spinner="Salesforce から取得中...")
def _load(metric_key: str) -> pd.DataFrame:
    return get_metric(metric_key).fetch(_sf())


# ----------------------------------------------------------------------
# サイドバー: 指標選択
# ----------------------------------------------------------------------
st.sidebar.title("📊 指標一覧")

# カテゴリでグルーピング
categories: dict[str, list] = {}
for m in METRICS:
    categories.setdefault(m.category, []).append(m)

selected_key = None
for cat, ms in categories.items():
    st.sidebar.subheader(cat)
    for m in ms:
        if st.sidebar.button(m.label, key=f"btn_{m.key}", width="stretch"):
            st.session_state["selected"] = m.key

valid_keys = {m.key for m in METRICS}
if st.session_state.get("selected") not in valid_keys:
    st.session_state["selected"] = METRICS[0].key

selected_key = st.session_state["selected"]

if st.sidebar.button("🔄 キャッシュ更新", width="stretch"):
    _load.clear()
    st.rerun()

st.sidebar.caption("データは5分間キャッシュされます")


# ----------------------------------------------------------------------
# メイン
# ----------------------------------------------------------------------
metric = get_metric(selected_key)
st.title(metric.label)

try:
    fetched = _load(selected_key)
except Exception as e:
    st.error(f"取得に失敗しました: {e}")
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
    st.dataframe(df, width="stretch", hide_index=True)
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
