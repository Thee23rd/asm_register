# asm_register/service.py
from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import io
from datetime import datetime
from typing import Tuple, List

import pandas as pd

# Import data I/O utilities whether the app is run as a package or as scripts
try:
    # When running as a package (e.g., python -m ...)
    from .data_io import (
        load_df,
        save_df,
        ensure_schema,
        read_imported_excel,
        REQUIRED_BASE_COLS,
        build_export_workbook,
    )
except ImportError:
    # When running scripts directly (e.g., streamlit run streamlit_app.py)
    from data_io import (
        load_df,
        save_df,
        ensure_schema,
        read_imported_excel,
        REQUIRED_BASE_COLS,
        build_export_workbook,
    )


# -----------------------------
# Helpers & Data Structures
# -----------------------------
DEDUP_KEY_COL = "Dedup_Key"

def _norm(s: pd.Series) -> pd.Series:
    """Normalize a text series for matching/deduping."""
    return s.astype(str).str.strip().str.lower()

def _make_key(name: str, district: str) -> str:
    """Create a normalized deduplication key from Name and District."""
    return f"{str(name).strip().lower()}|{str(district).strip().lower()}"


@dataclass
class Summary:
    total: int
    d1: int
    d2: int
    both: int
    none: int


# -----------------------------
# Core getters
# -----------------------------
def get_df() -> pd.DataFrame:
    """Load the primary dataframe and guarantee the schema."""
    return ensure_schema(load_df())


def get_summary(df: pd.DataFrame) -> Summary:
    total = len(df)
    d1 = int(df["Day1_Attended"].sum())
    d2 = int(df["Day2_Attended"].sum())
    both = int((df["Day1_Attended"] & df["Day2_Attended"]).sum())
    none = int((~df["Day1_Attended"] & ~df["Day2_Attended"]).sum())
    return Summary(total, d1, d2, both, none)


# -----------------------------
# Filters & Mutations
# -----------------------------
def filter_df(df: pd.DataFrame, name: str = "", district: str = "", coop: str = "") -> pd.DataFrame:
    """Filter by fuzzy contains on Name, District, and Co-op/Association."""
    out = df.copy()
    if name.strip():
        out = out[_norm(out["Name"]).str.contains(name.strip().lower(), na=False)]
    if district.strip():
        out = out[_norm(out["District"]).str.contains(district.strip().lower(), na=False)]
    if coop.strip():
        out = out[_norm(out["Name of Co-operative/Association"]).str.contains(coop.strip().lower(), na=False)]
    if out["NO."].notna().any():
        out = out.sort_values(by="NO.", kind="stable")
    return out


def register_participant(name: str, coop: str, district: str, province: str) -> Tuple[bool, str]:
    """Register a single participant; dedupe by (Name, District)."""
    if not name.strip() or not district.strip() or not province.strip():
        return False, "Name, District and Province are required."

    df = get_df()
    if ((_norm(df["Name"]) == name.strip().lower()) & (_norm(df["District"]) == district.strip().lower())).any():
        return False, "This participant is already registered."

    max_no = int(df["NO."].max()) if df["NO."].notna().any() else 0
    row = {
        "NO.": max_no + 1,
        "Name": name.strip(),
        "Name of Co-operative/Association": coop.strip(),
        "District": district.strip(),
        "Province": province.strip(),
        "Registered_On": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
        "Day1_Attended": False,
        "Day2_Attended": False,
        "Signature": "",
    }
    df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    save_df(df)
    return True, "Registration saved."


def checkin_bulk(ids: List[int], day: int) -> Tuple[int, int, int]:
    """Mark a list of NO. ids attended for a given day (1 or 2)."""
    assert day in (1, 2), "day must be 1 or 2"
    df = get_df()
    col = "Day1_Attended" if day == 1 else "Day2_Attended"
    updated = already = not_found = 0

    for no_ in ids:
        mask = df["NO."] == int(no_)
        if not mask.any():
            not_found += 1
            continue
        if bool(df.loc[mask, col].values[0]):
            already += 1
        else:
            df.loc[mask, col] = True
            updated += 1

    if updated:
        save_df(df)
    return updated, already, not_found


# -----------------------------
# Robust Import (dedupe in-file & vs existing)
# -----------------------------
def import_block(file_bytes: bytes) -> tuple[int, int]:
    """
    Import an Excel block safely.

    - Skips rows with missing Name or District
    - Drops INTERNAL duplicates within the uploaded file (by Name+District)
    - Skips duplicates that already exist in our Excel (by Name+District)
    - Assigns fresh sequential NO. to rows being added

    Returns: (added_count, skipped_total)
    """
    # --- Read and normalize the incoming sheet ---
    incoming = pd.read_excel(io.BytesIO(file_bytes))
    incoming = ensure_schema(incoming)  # make sure expected cols exist

    # Keep only rows that have at least Name & District
    mask_valid = (incoming["Name"].astype(str).str.strip() != "") & \
                 (incoming["District"].astype(str).str.strip() != "")
    cleaned = incoming[mask_valid].copy()
    skipped_empty = int(len(incoming) - len(cleaned))

    # Build a local (temp) key for incoming: Name|District
    def _series_key(df: pd.DataFrame) -> pd.Series:
        return (
            df["Name"].astype(str).str.strip().str.lower()
            + "|"
            + df["District"].astype(str).str.strip().str.lower()
        )

    cleaned["__Key"] = _series_key(cleaned)

    # --- De-dupe INSIDE the uploaded file ---
    before_internal = len(cleaned)
    cleaned = cleaned.drop_duplicates(subset=["__Key"], keep="first")
    skipped_internal = int(before_internal - len(cleaned))

    # --- De-dupe AGAINST existing storage (compute keys on the fly) ---
    existing = get_df()
    existing_keys = set(_series_key(existing).fillna("").astype(str))

    mask_new = ~cleaned["__Key"].isin(existing_keys)
    to_add = cleaned[mask_new].copy()
    skipped_existing = int(len(cleaned) - len(to_add))

    # Nothing new to add?
    if to_add.empty:
        return 0, skipped_empty + skipped_internal + skipped_existing

    # Assign fresh sequential NO. values
    start_no = int(existing["NO."].max()) + 1 if existing["NO."].notna().any() else 1
    to_add["NO."] = range(start_no, start_no + len(to_add))

    # Clean up temp column and ensure schema/dtypes before saving
    to_add = to_add.drop(columns=["__Key"], errors="ignore")
    to_add = ensure_schema(to_add)

    # Append and save
    final = pd.concat([existing, to_add], ignore_index=True)
    save_df(final)

    added = int(len(to_add))
    skipped_total = skipped_empty + skipped_internal + skipped_existing
    return added, skipped_total




# (Optional) maintenance helper to remove historical dupes already in storage
def dedupe_existing_on_name_district() -> Tuple[int, int]:
    """
    Keep the first row for each normalized (Name, District) in stored data.
    Returns: (kept_rows, removed_rows)
    """
    df = get_df().copy()
    df["__Name_norm__"] = _norm(df["Name"])
    df["__District_norm__"] = _norm(df["District"])

    before = len(df)
    df = df.drop_duplicates(subset=["__Name_norm__", "__District_norm__"], keep="first").reset_index(drop=True)
    removed = before - len(df)

    df = df.drop(columns=["__Name_norm__", "__District_norm__"], errors="ignore")
    if removed > 0:
        save_df(df)
    return len(df), removed


# -----------------------------
# Reporting
# -----------------------------
def _ensure_schema_for_reports(df: pd.DataFrame) -> pd.DataFrame:
    """Make sure the columns we need exist with safe defaults."""
    cols = [
        "NO.",
        "Name",
        "Name of Co-operative/Association",
        "District",
        "Province",
        "Day1_Attended",
        "Day2_Attended",
    ]
    for c in cols:
        if c not in df.columns:
            if c in ("Day1_Attended", "Day2_Attended"):
                df[c] = False
            else:
                df[c] = ""
    return df


def build_report_bytes() -> Tuple[bytes, str]:
    """
    Build a multi-sheet Excel report:
      - Summary
      - By District
      - By Province
      - By Association (Co-operative/Association)
      - Raw Data
    """
    df = get_df().copy()
    df = _ensure_schema_for_reports(df)

    # --- Summary ---
    total = len(df)
    d1 = int(df["Day1_Attended"].sum())
    d2 = int(df["Day2_Attended"].sum())
    both = int((df["Day1_Attended"] & df["Day2_Attended"]).sum())
    either = int((df["Day1_Attended"] | df["Day2_Attended"]).sum())
    none = int((~df["Day1_Attended"] & ~df["Day2_Attended"]).sum())

    summary = pd.DataFrame(
        [
            {"Metric": "Total Registered", "Count": total},
            {"Metric": "Attended Day 1", "Count": d1},
            {"Metric": "Attended Day 2", "Count": d2},
            {"Metric": "Attended Either Day", "Count": either},
            {"Metric": "Attended Both Days", "Count": both},
            {"Metric": "Attended Neither Day", "Count": none},
        ]
    )
    summary["Rate_%"] = (summary["Count"] / max(total, 1) * 100).round(2)

    # --- By District ---
    by_district = (
        df.groupby("District", dropna=False)
        .agg(
            Registered=("NO.", "count"),
            Day1_Attended=("Day1_Attended", "sum"),
            Day2_Attended=("Day2_Attended", "sum"),
        )
        .reset_index()
    )
    both_district = (
        df.groupby("District", dropna=False)
        .apply(lambda g: (g["Day1_Attended"] & g["Day2_Attended"]).sum())
    )
    by_district["Both_Attended"] = both_district.reindex(by_district["District"]).values
    by_district["Either_Attended"] = (
        by_district["Day1_Attended"] + by_district["Day2_Attended"] - by_district["Both_Attended"]
    )
    by_district["None_Attended"] = by_district["Registered"] - by_district["Either_Attended"]
    by_district["Day1_Rate_%"] = (by_district["Day1_Attended"] / by_district["Registered"] * 100).round(2)
    by_district["Day2_Rate_%"] = (by_district["Day2_Attended"] / by_district["Registered"] * 100).round(2)
    by_district["Either_Rate_%"] = (by_district["Either_Attended"] / by_district["Registered"] * 100).round(2)
    by_district["Both_Rate_%"] = (by_district["Both_Attended"] / by_district["Registered"] * 100).round(2)
    by_district = by_district.sort_values("Registered", ascending=False)

    # --- By Province ---
    by_province = (
        df.groupby("Province", dropna=False)
        .agg(
            Registered=("NO.", "count"),
            Day1_Attended=("Day1_Attended", "sum"),
            Day2_Attended=("Day2_Attended", "sum"),
        )
        .reset_index()
    )
    both_province = (
        df.groupby("Province", dropna=False)
        .apply(lambda g: (g["Day1_Attended"] & g["Day2_Attended"]).sum())
    )
    by_province["Both_Attended"] = both_province.reindex(by_province["Province"]).values
    by_province["Either_Attended"] = by_province["Day1_Attended"] + by_province["Day2_Attended"] - by_province["Both_Attended"]
    by_province["None_Attended"] = by_province["Registered"] - by_province["Either_Attended"]
    by_province["Day1_Rate_%"] = (by_province["Day1_Attended"] / by_province["Registered"] * 100).round(2)
    by_province["Day2_Rate_%"] = (by_province["Day2_Attended"] / by_province["Registered"] * 100).round(2)
    by_province["Either_Rate_%"] = (by_province["Either_Attended"] / by_province["Registered"] * 100).round(2)
    by_province["Both_Rate_%"] = (by_province["Both_Attended"] / by_province["Registered"] * 100).round(2)
    by_province = by_province.sort_values("Registered", ascending=False)

    # --- By Association ---
    assoc_col = "Name of Co-operative/Association"
    if assoc_col not in df.columns:
        df[assoc_col] = ""

    by_assoc = (
        df.groupby(assoc_col, dropna=False)
        .agg(
            Registered=("NO.", "count"),
            Day1_Attended=("Day1_Attended", "sum"),
            Day2_Attended=("Day2_Attended", "sum"),
        )
        .reset_index()
        .rename(columns={assoc_col: "Association"})
    )
    both_assoc = (
        df.groupby(assoc_col, dropna=False)
        .apply(lambda g: (g["Day1_Attended"] & g["Day2_Attended"]).sum())
    )
    by_assoc["Both_Attended"] = both_assoc.reindex(by_assoc["Association"]).values
    by_assoc["Either_Attended"] = by_assoc["Day1_Attended"] + by_assoc["Day2_Attended"] - by_assoc["Both_Attended"]
    by_assoc["None_Attended"] = by_assoc["Registered"] - by_assoc["Either_Attended"]
    by_assoc["Day1_Rate_%"] = (by_assoc["Day1_Attended"] / by_assoc["Registered"] * 100).round(2)
    by_assoc["Day2_Rate_%"] = (by_assoc["Day2_Attended"] / by_assoc["Registered"] * 100).round(2)
    by_assoc["Either_Rate_%"] = (by_assoc["Either_Attended"] / by_assoc["Registered"] * 100).round(2)
    by_assoc["Both_Rate_%"] = (by_assoc["Both_Attended"] / by_assoc["Registered"] * 100).round(2)
    by_assoc = by_assoc.sort_values(["Registered", "Association"], ascending=[False, True])

    # --- Write Excel ---
    out = BytesIO()
    with pd.ExcelWriter(out, engine="openpyxl") as writer:
        summary.to_excel(writer, sheet_name="Summary", index=False)
        by_district.to_excel(writer, sheet_name="By District", index=False)
        by_province.to_excel(writer, sheet_name="By Province", index=False)
        by_assoc.to_excel(writer, sheet_name="By Association", index=False)
        df.to_excel(writer, sheet_name="Raw Data", index=False)

    out.seek(0)
    fname = f"attendance_report_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
    return out.read(), fname
