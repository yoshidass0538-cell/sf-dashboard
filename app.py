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
        if st.sidebar.button(m.label, key=f"btn_{m.key}", use_container_width=True):
            st.session_state["selected"] = m.key

if "selected" not in st.session_state:
    st.session_state["selected"] = METRICS[0].key

selected_key = st.session_state["selected"]

if st.sidebar.button("🔄 キャッシュ更新", use_container_width=True):
    _load.clear()
    st.rerun()

st.sidebar.caption("データは5分間キャッシュされます")


# ----------------------------------------------------------------------
# メイン
# ----------------------------------------------------------------------
metric = get_metric(selected_key)
st.title(metric.label)
st.caption(metric.description)

try:
    df = _load(selected_key)
except Exception as e:
    st.error(f"取得に失敗しました: {e}")
    st.stop()

if df.empty:
    st.info("該当データはありません。")
    st.stop()

# サマリー
if metric.value_col and metric.value_col in df.columns:
    c1, c2, c3 = st.columns(3)
    c1.metric("合計", int(df[metric.value_col].sum()))
    c2.metric("対象数", len(df))
    c3.metric("平均", round(df[metric.value_col].mean(), 1))

# テーブル & グラフ
left, right = st.columns([1, 2])
with left:
    st.subheader("一覧")
    st.dataframe(df, use_container_width=True, hide_index=True)
    st.download_button(
        "CSV ダウンロード",
        df.to_csv(index=False).encode("utf-8-sig"),
        file_name=f"{metric.key}.csv",
        mime="text/csv",
    )

with right:
    if metric.group_col and metric.value_col:
        st.subheader("グラフ")
        chart_df = df.set_index(metric.group_col)[metric.value_col]
        st.bar_chart(chart_df)
