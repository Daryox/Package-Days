import os
import glob
import pandas as pd
from datetime import date


EXCLUDED_STATUSES  = {"Entregado", "Return_to_seller_success", "Cancelar", "Attempt Failure"}
# LPs that have ever reached one of these statuses are dropped entirely
TERMINAL_STATUSES  = {"Entregado", "Return_to_seller_success"}


# Column indices in the Excel file (0-based):
#   1  → LP No.
#   5  → Estado de la Tarea
#   26 → Tiempo de creación
#   30 → Tiempo de Entrega
_SLIM_INDICES   = [1, 5, 26, 30]
_SLIM_COLS      = ["lp", "status", "created", "delivered"]
_STATUS_COL_IDX = 5

_mem_cache: dict[tuple, pd.DataFrame] = {}

# Full-column detail data, populated by load_full()
detail: dict = {"ready": False, "rows": []}


def latest_data_file(data_dir: str) -> str:
    files = glob.glob(os.path.join(data_dir, "*.xlsx"))
    if not files:
        raise FileNotFoundError(f"No .xlsx files found in {data_dir!r}")
    return max(files, key=os.path.getmtime)


def _load_slim(path: str) -> pd.DataFrame:
    raw = pd.read_excel(path, usecols=_SLIM_INDICES, engine="calamine")
    raw.columns = _SLIM_COLS
    return raw


def load_full(path: str):
    """Load all columns and populate detail dict (intended to run in a background thread)."""
    try:
        df = pd.read_excel(path, engine="calamine")
        status_col = df.columns[_STATUS_COL_IDX]
        df = df[~df[status_col].isin(EXCLUDED_STATUSES)].reset_index(drop=True)
        for col in df.columns:
            if pd.api.types.is_datetime64_any_dtype(df[col]):
                df[col] = df[col].dt.strftime("%Y-%m-%d %H:%M")
        detail["rows"] = (
            df.fillna("—").astype(str)
              .replace({"NaT": "—", "nan": "—", "<NA>": "—"})
              .to_dict(orient="records")
        )
        detail["ready"] = True
    except Exception as exc:
        print(f"Detail load error: {exc}")


def compute_days(raw: pd.DataFrame) -> pd.DataFrame:
    today = pd.Timestamp(date.today())
    df    = raw.copy()
    df["created"]   = pd.to_datetime(df["created"],   errors="coerce")
    df["delivered"] = pd.to_datetime(df["delivered"],  errors="coerce")

    df = df[df["lp"].notna() & (df["lp"].astype(str).str.strip() != "")]

    # Drop every LP that has ever reached a terminal state
    terminal_lps = set(df.loc[df["status"].isin(TERMINAL_STATUSES), "lp"])
    df = df[~df["lp"].isin(terminal_lps)]

    # Earliest created among remaining entries — true entry point into the system
    first_seen = df.groupby("lp")["created"].min().rename("first_created")

    # Latest in-transit row per LP — determines the status shown in the table
    in_transit = df[~df["status"].isin(EXCLUDED_STATUSES)]
    latest = (in_transit.sort_values("created", ascending=False)
                        .drop_duplicates(subset="lp", keep="first"))

    latest = latest.join(first_seen, on="lp")
    latest["days_in_system"] = (latest["delivered"].fillna(today) - latest["first_created"]).dt.days
    latest["days_in_system"] = latest["days_in_system"].where(latest["days_in_system"] >= 0, 0)
    return latest.drop(columns="first_created").reset_index(drop=True)


def load_data(source_path: str) -> pd.DataFrame:
    key = (source_path, os.path.getmtime(source_path))
    if key not in _mem_cache:
        _mem_cache.clear()
        _mem_cache[key] = compute_days(_load_slim(source_path))
    return _mem_cache[key]


def df_to_rows(df: pd.DataFrame) -> list[list]:
    fmt = df["created"].dt.strftime("%Y-%m-%d %H:%M").fillna("—")
    return [
        [str(lp), str(s), c, int(d)]
        for lp, s, c, d in zip(df["lp"], df["status"], fmt, df["days_in_system"])
    ]
