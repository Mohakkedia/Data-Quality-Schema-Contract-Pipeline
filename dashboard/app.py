"""
app.py — Streamlit dashboard for the data-quality trend log.

Reads outputs/quality_trend.jsonl (one record per processed batch) and
outputs/alerts.jsonl, and renders the pass/fail trend, drift trend, and
violation breakdown a data platform team would actually want to see.

Run:
    streamlit run dashboard/app.py
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
TREND_LOG = ROOT / "outputs" / "quality_trend.jsonl"
ALERT_LOG = ROOT / "outputs" / "alerts.jsonl"

st.set_page_config(page_title="Data Quality Trends", page_icon="✅", layout="wide")
st.title("✅ Data Quality / Schema Contract Dashboard")
st.caption("Reads outputs/quality_trend.jsonl, written by src/pipeline.py on every processed batch.")


@st.cache_data(ttl=5)
def load_trend() -> pd.DataFrame | None:
    if not TREND_LOG.exists():
        return None
    records = [json.loads(line) for line in open(TREND_LOG)]
    df = pd.DataFrame(records)
    df["run_date"] = pd.to_datetime(df["run_date"])
    return df.sort_values("run_date")


@st.cache_data(ttl=5)
def load_alerts() -> list[dict]:
    if not ALERT_LOG.exists():
        return []
    return [json.loads(line) for line in open(ALERT_LOG)]


with st.sidebar:
    if st.button("🔄 Refresh"):
        st.cache_data.clear()

df = load_trend()
alerts = load_alerts()

if df is None or df.empty:
    st.warning("No trend data yet. Run `python scripts/run_all_days.py` first.")
    st.stop()

# ---- KPI row ----
col1, col2, col3, col4 = st.columns(4)
col1.metric("Batches processed", len(df))
n_failed = int((~df["passed"]).sum())
col2.metric("Batches failed", n_failed, delta=None, delta_color="inverse")
total_rows = int(df["n_rows_total"].sum())
invalid_rows = int(df["n_rows_invalid"].sum())
col3.metric("Row-level pass rate", f"{100 * (1 - invalid_rows / total_rows):.1f}%")
col4.metric("Alerts sent", len(alerts))

st.markdown("---")

# ---- Pass/fail trend ----
st.subheader("Batch Pass/Fail Rate Over Time")
df_display = df.copy()
df_display["valid_pct"] = 100 * df_display["n_rows_valid"] / df_display["n_rows_total"]
st.bar_chart(df_display.set_index("run_date")["valid_pct"], height=250)

st.markdown("---")

# ---- Contract version over time ----
st.subheader("Contract Version Used Per Batch")
st.line_chart(df_display.set_index("run_date")["contract_version_used"], height=180)
st.caption("A visible step up marks a contract version cutover (e.g. the firmware_version field going live).")

st.markdown("---")

# ---- Violations table ----
st.subheader("Batch-by-Batch Detail")
detail_cols = ["run_date", "contract_version_used", "passed", "n_rows_total", "n_rows_valid",
               "n_rows_invalid", "n_violations", "violation_types", "drift_fields_flagged", "alert_sent"]
st.dataframe(df_display[detail_cols], use_container_width=True)

st.markdown("---")

# ---- Alerts ----
st.subheader(f"Alert History ({len(alerts)})")
if alerts:
    for a in reversed(alerts):
        with st.expander(f"{a['run_date']} — {a['n_invalid']}/{a['n_total']} rows failed (delivered to: {', '.join(a['delivered_to'])})"):
            st.code(a["message"], language=None)
else:
    st.success("No alerts sent.")
