# asm_register/service.py
from __future__ import annotations
from dataclasses import dataclass
import pandas as pd
# service.py
try:
    # works if you run as a package (python -m ...)
    from .data_io import (
        load_df, save_df, ensure_schema, read_imported_excel,
        REQUIRED_BASE_COLS, build_export_workbook
    )
except ImportError:
    # works if you run scripts directly (streamlit run streamlit_app.py)
    from data_io import (
        load_df, save_df, ensure_schema, read_imported_excel,
        REQUIRED_BASE_COLS, build_export_workbook
    )


def _norm(s: pd.Series) -> pd.Series:
    return s.astype(str).str.strip().str.lower()

@dataclass
class Summary:
    total: int
    d1: int
    d2: int
    both: int
    none: int

def get_df() -> pd.DataFrame:
    return ensure_schema(load_df())

def get_summary(df: pd.DataFrame) -> Summary:
    total = len(df)
    d1 = int(df["Day1_Attended"].sum())
    d2 = int(df["Day2_Attended"].sum())
    both = int((df["Day1_Attended"] & df["Day2_Attended"]).sum())
    none = int((~df["Day1_Attended"] & ~df["Day2_Attended"]).sum())
    return Summary(total, d1, d2, both, none)

def filter_df(df: pd.DataFrame, name: str = "", district: str = "", coop: str = "") -> pd.DataFrame:
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

def register_participant(name: str, coop: str, district: str, province: str) -> tuple[bool, str]:
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

def checkin_bulk(ids: list[int], day: int) -> tuple[int, int, int]:
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

def import_block(content: bytes) -> tuple[int, int]:
    imported = read_imported_excel(content)
    missing = [c for c in REQUIRED_BASE_COLS if c not in imported.columns]
    if missing:
        raise ValueError(f"Missing required columns: {', '.join(missing)}")
    df = get_df()
    new_block = imported.copy()

    # Deduplicate by Name + District
    existing_norm = pd.DataFrame({"Name_norm": _norm(df["Name"]), "District_norm": _norm(df["District"])})
    new_block["Name_norm"] = _norm(new_block["Name"])
    new_block["District_norm"] = _norm(new_block["District"])

    merged = new_block.merge(existing_norm, on=["Name_norm", "District_norm"], how="left", indicator=True)
    deduped_new = merged[merged["_merge"] == "left_only"].drop(columns=["_merge", "Name_norm", "District_norm"]).reset_index(drop=True)

    if deduped_new.empty:
        return 0, len(new_block)

    current_max = int(df["NO."].max()) if df["NO."].notna().any() else 0
    deduped_new["NO."] = pd.Series(range(current_max + 1, current_max + 1 + len(deduped_new)), dtype="Int64")
    df = pd.concat([df, deduped_new], ignore_index=True)
    save_df(df)
    dupes = len(new_block) - len(deduped_new)
    return int(len(deduped_new)), int(dupes)

def build_report_bytes() -> tuple[bytes, str]:
    df = get_df()
    buff, fname = build_export_workbook(df)
    return buff.getvalue(), fname

# service.py
from io import BytesIO
from datetime import datetime
import pandas as pd

# ... keep your other imports and functions (get_df, etc.)

def _ensure_schema_for_reports(df: pd.DataFrame) -> pd.DataFrame:
    """Make sure the columns we need exist with safe defaults."""
    cols = [
        'NO.', 'Name', 'Name of Co-operative/Association',
        'District', 'Province', 'Day1_Attended', 'Day2_Attended'
    ]
    for c in cols:
        if c not in df.columns:
            if c in ('Day1_Attended', 'Day2_Attended'):
                df[c] = False
            else:
                df[c] = ""
    return df

def build_report_bytes() -> tuple[bytes, str]:
    """Build a multi-sheet Excel report and return (bytes, filename)."""
    df = get_df().copy()
    df = _ensure_schema_for_reports(df)

    # --- Summary ---
    total = len(df)
    d1 = int(df['Day1_Attended'].sum())
    d2 = int(df['Day2_Attended'].sum())
    both = int((df['Day1_Attended'] & df['Day2_Attended']).sum())
    either = int((df['Day1_Attended'] | df['Day2_Attended']).sum())
    none = int((~df['Day1_Attended'] & ~df['Day2_Attended']).sum())

    summary = pd.DataFrame([
        {"Metric": "Total Registered", "Count": total},
        {"Metric": "Attended Day 1", "Count": d1},
        {"Metric": "Attended Day 2", "Count": d2},
        {"Metric": "Attended Either Day", "Count": either},
        {"Metric": "Attended Both Days", "Count": both},
        {"Metric": "Attended Neither Day", "Count": none},
    ])
    summary["Rate_%"] = (summary["Count"] / max(total, 1) * 100).round(2)

    # --- By District ---
    by_district = (
        df.groupby('District', dropna=False)
          .agg(
              Registered=('NO.', 'count'),
              Day1_Attended=('Day1_Attended', 'sum'),
              Day2_Attended=('Day2_Attended', 'sum'),
          )
          .reset_index()
    )
    by_district['Either_Attended'] = (by_district['Day1_Attended'] + by_district['Day2_Attended']
                                      - (df.groupby('District', dropna=False)
                                             .apply(lambda g: (g['Day1_Attended'] & g['Day2_Attended']).sum())
                                             .reindex(by_district['District']).values))
    by_district['Both_Attended'] = (
        df.groupby('District', dropna=False)
          .apply(lambda g: (g['Day1_Attended'] & g['Day2_Attended']).sum())
          .reindex(by_district['District']).values
    )
    by_district['None_Attended'] = by_district['Registered'] - by_district['Either_Attended']
    by_district['Day1_Rate_%'] = (by_district['Day1_Attended'] / by_district['Registered'] * 100).round(2)
    by_district['Day2_Rate_%'] = (by_district['Day2_Attended'] / by_district['Registered'] * 100).round(2)
    by_district['Either_Rate_%'] = (by_district['Either_Attended'] / by_district['Registered'] * 100).round(2)
    by_district['Both_Rate_%'] = (by_district['Both_Attended'] / by_district['Registered'] * 100).round(2)
    by_district = by_district.sort_values('Registered', ascending=False)

    # --- By Province ---
    by_province = (
        df.groupby('Province', dropna=False)
          .agg(
              Registered=('NO.', 'count'),
              Day1_Attended=('Day1_Attended', 'sum'),
              Day2_Attended=('Day2_Attended', 'sum'),
          )
          .reset_index()
    )
    by_province['Both_Attended'] = (
        df.groupby('Province', dropna=False)
          .apply(lambda g: (g['Day1_Attended'] & g['Day2_Attended']).sum())
          .reindex(by_province['Province']).values
    )
    by_province['Either_Attended'] = by_province['Day1_Attended'] + by_province['Day2_Attended'] - by_province['Both_Attended']
    by_province['None_Attended'] = by_province['Registered'] - by_province['Either_Attended']
    by_province['Day1_Rate_%'] = (by_province['Day1_Attended'] / by_province['Registered'] * 100).round(2)
    by_province['Day2_Rate_%'] = (by_province['Day2_Attended'] / by_province['Registered'] * 100).round(2)
    by_province['Either_Rate_%'] = (by_province['Either_Attended'] / by_province['Registered'] * 100).round(2)
    by_province['Both_Rate_%'] = (by_province['Both_Attended'] / by_province['Registered'] * 100).round(2)
    by_province = by_province.sort_values('Registered', ascending=False)

    # --- NEW: By Association ---
    assoc_col = 'Name of Co-operative/Association'
    if assoc_col not in df.columns:
        df[assoc_col] = ""

    by_assoc = (
        df.groupby(assoc_col, dropna=False)
          .agg(
              Registered=('NO.', 'count'),
              Day1_Attended=('Day1_Attended', 'sum'),
              Day2_Attended=('Day2_Attended', 'sum'),
          )
          .reset_index()
          .rename(columns={assoc_col: 'Association'})
    )
    # both/either/none per association
    both_series = (
        df.groupby(assoc_col, dropna=False)
          .apply(lambda g: (g['Day1_Attended'] & g['Day2_Attended']).sum())
    )
    by_assoc['Both_Attended'] = both_series.reindex(by_assoc['Association']).values
    by_assoc['Either_Attended'] = by_assoc['Day1_Attended'] + by_assoc['Day2_Attended'] - by_assoc['Both_Attended']
    by_assoc['None_Attended'] = by_assoc['Registered'] - by_assoc['Either_Attended']

    # rates
    by_assoc['Day1_Rate_%'] = (by_assoc['Day1_Attended'] / by_assoc['Registered'] * 100).round(2)
    by_assoc['Day2_Rate_%'] = (by_assoc['Day2_Attended'] / by_assoc['Registered'] * 100).round(2)
    by_assoc['Either_Rate_%'] = (by_assoc['Either_Attended'] / by_assoc['Registered'] * 100).round(2)
    by_assoc['Both_Rate_%'] = (by_assoc['Both_Attended'] / by_assoc['Registered'] * 100).round(2)

    # sort: most participants first, then alphabetically
    by_assoc = by_assoc.sort_values(['Registered', 'Association'], ascending=[False, True])

    # --- Write Excel ---
    out = BytesIO()
    with pd.ExcelWriter(out, engine='openpyxl') as writer:
        summary.to_excel(writer, sheet_name='Summary', index=False)
        by_district.to_excel(writer, sheet_name='By District', index=False)
        by_province.to_excel(writer, sheet_name='By Province', index=False)
        by_assoc.to_excel(writer, sheet_name='By Association', index=False)
        # Raw data last for troubleshooting
        df.to_excel(writer, sheet_name='Raw Data', index=False)

    out.seek(0)
    fname = f"attendance_report_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
    return out.read(), fname

