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
