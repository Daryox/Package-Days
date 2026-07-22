import io
from datetime import date

import pandas as pd
import streamlit as st

from logic.data_loader import (
    EXCLUDED_STATUSES,
    TERMINAL_STATUSES,
    _SLIM_INDICES,
    _SLIM_COLS,
    _STATUS_COL_IDX,
)

st.set_page_config(page_title="Package Days in System", layout="wide")

st.title("Package Days in System")


# ── file upload ───────────────────────────────────────────────────────────────

uploaded = st.file_uploader("Upload the task list (.xlsx)", type=["xlsx"])
if not uploaded:
    st.info("Upload an Excel file to get started.")
    st.stop()


# ── load & process ────────────────────────────────────────────────────────────

@st.cache_data(show_spinner="Reading file…")
def process(file_bytes: bytes) -> pd.DataFrame:
    raw = pd.read_excel(io.BytesIO(file_bytes), usecols=_SLIM_INDICES, engine="calamine")
    raw.columns = _SLIM_COLS

    today = pd.Timestamp(date.today())
    df = raw.copy()
    df["created"]   = pd.to_datetime(df["created"],  errors="coerce")
    df["delivered"] = pd.to_datetime(df["delivered"], errors="coerce")
    df = df[df["lp"].notna() & (df["lp"].astype(str).str.strip() != "")]

    terminal_lps = set(df.loc[df["status"].isin(TERMINAL_STATUSES), "lp"])
    df = df[~df["lp"].isin(terminal_lps)]

    first_seen = df.groupby("lp")["created"].min().rename("first_created")

    in_transit = df[~df["status"].isin(EXCLUDED_STATUSES)]
    latest = (in_transit.sort_values("created", ascending=False)
                        .drop_duplicates(subset="lp", keep="first"))

    latest = latest.join(first_seen, on="lp")
    latest["days_in_system"] = (latest["delivered"].fillna(today) - latest["first_created"]).dt.days
    latest["days_in_system"] = latest["days_in_system"].where(latest["days_in_system"] >= 0, 0)
    return latest.drop(columns="first_created").reset_index(drop=True)


df = process(uploaded.read())


# ── summary bar ───────────────────────────────────────────────────────────────

c1, c2, c3 = st.columns(3)
c1.metric("In transit",  f"{len(df):,}")
c2.metric("Avg days",    f"{df['days_in_system'].mean():.1f}")
c3.metric("Max days",    str(int(df["days_in_system"].max())))


# ── filters & sort ────────────────────────────────────────────────────────────

col_search, col_days, col_sort = st.columns([3, 2, 1])
with col_search:
    query = st.text_input("Search LP No. or status", placeholder="Type to filter…")
with col_days:
    max_days = int(df["days_in_system"].max()) if len(df) else 0
    min_filter = st.slider(
        "Minimum days in system",
        min_value=0,
        max_value=max(max_days, 1),
        value=0,
        help="Show only packages with this many days or more",
    )
with col_sort:
    sort_order = st.selectbox("Days in system", ["↓ Descending", "↑ Ascending"])

view = df.copy()
if query:
    mask = (
        view["lp"].astype(str).str.lower().str.contains(query.lower(), na=False) |
        view["status"].astype(str).str.lower().str.contains(query.lower(), na=False)
    )
    view = view[mask]

if min_filter > 0:
    view = view[view["days_in_system"] >= min_filter]

view = view.sort_values("days_in_system", ascending=(sort_order == "↑ Ascending"))
view["created"] = view["created"].dt.strftime("%Y-%m-%d %H:%M")

display = view[["lp", "status", "created", "days_in_system"]].rename(columns={
    "lp":             "LP No.",
    "status":         "Status",
    "created":        "Created",
    "days_in_system": "Days in System",
})


# ── table ─────────────────────────────────────────────────────────────────────

filter_note = f"  •  ≥ {min_filter} days" if min_filter > 0 else ""
st.caption(f"As of {date.today()}  •  Showing {len(display):,} packages{filter_note}  •  Select a row for full details")

selection = st.dataframe(
    display,
    use_container_width=True,
    hide_index=True,
    on_select="rerun",
    selection_mode="single-row",
    column_config={
        "Days in System": st.column_config.NumberColumn(
            help="Days since first entry in system",
        ),
    },
)


# ── detail panel ─────────────────────────────────────────────────────────────

selected_rows = selection.selection.rows
if selected_rows:
    row_pos    = selected_rows[0]
    source_idx = view.index[row_pos]
    lp_val     = df.loc[source_idx, "lp"]

    st.divider()
    st.subheader(f"Package Detail — {lp_val}")

    with st.spinner("Loading full row data…"):
        @st.cache_data(show_spinner=False)
        def load_full_row(file_bytes: bytes, lp: str):
            full = pd.read_excel(io.BytesIO(file_bytes), engine="calamine")
            status_col = full.columns[_STATUS_COL_IDX]
            full = full[~full[status_col].isin(EXCLUDED_STATUSES)]
            for col in full.columns:
                if pd.api.types.is_datetime64_any_dtype(full[col]):
                    full[col] = full[col].dt.strftime("%Y-%m-%d %H:%M")
            full = (full.fillna("—").astype(str)
                        .replace({"NaT": "—", "nan": "—", "<NA>": "—"}))
            lp_col = full.columns[1]
            rows = full[full[lp_col] == lp]
            return rows

        rows = load_full_row(uploaded.getvalue(), str(lp_val))

    if rows.empty:
        st.warning("No detail rows found for this LP.")
    else:
        detail_df = rows.iloc[0].reset_index()
        detail_df.columns = ["Field", "Value"]
        st.dataframe(detail_df, use_container_width=True, hide_index=True)
