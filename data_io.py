# asm_register/data_io.py
from __future__ import annotations
import io
from datetime import datetime
from pathlib import Path
from typing import Tuple
import pandas as pd
from filelock import FileLock

EXCEL_FILE = Path("conference_registrations.xlsx")
LOCK_FILE = EXCEL_FILE.with_suffix(".lock")

REQUIRED_BASE_COLS = [
    "NO.",
    "Name",
    "Name of Co-operative/Association",
    "District",
    "Province",
]
TRACKING_COLS = ["Registered_On", "Day1_Attended", "Day2_Attended", "Signature"]

def ensure_schema(df: pd.DataFrame) -> pd.DataFrame:
    for col in REQUIRED_BASE_COLS + TRACKING_COLS:
        if col not in df.columns:
            if col == "Registered_On":
                df[col] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            elif col in ("Day1_Attended", "Day2_Attended"):
                df[col] = False
            elif col == "Signature":
                df[col] = ""
            elif col == "NO.":
                df[col] = pd.Series(dtype="Int64")
            else:
                df[col] = ""
    # dtypes
    try:
        df["NO."] = pd.to_numeric(df["NO."], errors="coerce").astype("Int64")
    except Exception:
        pass
    for c in ("Day1_Attended", "Day2_Attended"):
        if df[c].dtype != bool:
            df[c] = df[c].fillna(False)
            if df[c].dtype == object:
                df[c] = (
                    df[c]
                    .astype(str).str.strip().str.lower()
                    .map({"true": True, "yes": True, "1": True})
                    .fillna(False)
                )
            df[c] = df[c].astype(bool)
    if df["Registered_On"].isna().any():
        df["Registered_On"] = df["Registered_On"].fillna(
            datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        )
    return df[REQUIRED_BASE_COLS + TRACKING_COLS]

def load_df() -> pd.DataFrame:
    with FileLock(str(LOCK_FILE)):
        if EXCEL_FILE.exists():
            df = pd.read_excel(EXCEL_FILE)
        else:
            df = pd.DataFrame(columns=REQUIRED_BASE_COLS + TRACKING_COLS)
        return ensure_schema(df)

def save_df(df: pd.DataFrame) -> None:
    with FileLock(str(LOCK_FILE)):
        ensure_schema(df).to_excel(EXCEL_FILE, index=False)

def read_imported_excel(content: bytes) -> pd.DataFrame:
    imported = pd.read_excel(io.BytesIO(content))
    # fill tracking cols if missing
    for col in TRACKING_COLS:
        if col not in imported.columns:
            if col == "Registered_On":
                imported[col] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            elif col in ("Day1_Attended", "Day2_Attended"):
                imported[col] = False
            elif col == "Signature":
                imported[col] = ""
    if "NO." not in imported.columns or imported["NO."].isna().all():
        imported["NO."] = range(1, len(imported) + 1)
    imported["NO."] = pd.to_numeric(imported["NO."], errors="coerce").astype("Int64")

    for col in ["Name", "Name of Co-operative/Association", "District", "Province", "Signature"]:
        if col in imported.columns:
            imported[col] = imported[col].astype(str).str.strip()
    return imported

def build_export_workbook(df: pd.DataFrame) -> Tuple[io.BytesIO, str]:
    total = len(df)
    d1 = int(df["Day1_Attended"].sum())
    d2 = int(df["Day2_Attended"].sum())
    both = int((df["Day1_Attended"] & df["Day2_Attended"]).sum())
    none = int((~df["Day1_Attended"] & ~df["Day2_Attended"]).sum())

    summary = pd.DataFrame([
        {"Metric": "Total Registered", "Count": total},
        {"Metric": "Attended Day 1", "Count": d1},
        {"Metric": "Attended Day 2", "Count": d2},
        {"Metric": "Attended Both Days", "Count": both},
        {"Metric": "Attended Neither Day", "Count": none},
    ])
    summary["Rate_%"] = (summary["Count"] / max(total, 1) * 100).round(2)

    by_district = df.groupby("District").agg(
        Registered=("NO.", "count"),
        Day1_Attended=("Day1_Attended", "sum"),
        Day2_Attended=("Day2_Attended", "sum"),
    ).reset_index()
    by_district["Day1_Rate_%"] = (by_district["Day1_Attended"] / by_district["Registered"] * 100).round(2)
    by_district["Day2_Rate_%"] = (by_district["Day2_Attended"] / by_district["Registered"] * 100).round(2)

    by_province = df.groupby("Province").agg(
        Registered=("NO.", "count"),
        Day1_Attended=("Day1_Attended", "sum"),
        Day2_Attended=("Day2_Attended", "sum"),
    ).reset_index()
    by_province["Day1_Rate_%"] = (by_province["Day1_Attended"] / by_province["Registered"] * 100).round(2)
    by_province["Day2_Rate_%"] = (by_province["Day2_Attended"] / by_province["Registered"] * 100).round(2)

    out = io.BytesIO()
    with pd.ExcelWriter(out, engine="openpyxl") as writer:
        summary.to_excel(writer, sheet_name="Summary", index=False)
        by_district.to_excel(writer, sheet_name="By District", index=False)
        by_province.to_excel(writer, sheet_name="By Province", index=False)
        ensure_schema(df).to_excel(writer, sheet_name="Raw Data", index=False)

    out.seek(0)
    fname = f"attendance_report_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
    return out, fname
