# asm_register/streamlit_app.py
from __future__ import annotations
import streamlit as st
from datetime import datetime
from pathlib import Path
import pandas as pd

from service import (
    get_df, get_summary, filter_df,
    register_participant, checkin_bulk, import_block, build_report_bytes
)

# ---------- Page config ----------
st.set_page_config(page_title="ASM Conference Register", page_icon="🦅", layout="wide")

import streamlit as st

# Brand palette (hex)
ZAMBIA = {
    "green":  "#198A00",  # Flag green
    "red":    "#D10000",  # Accessible red
    "black":  "#000000",
    "orange": "#FF9500",  # Eagle orange
    "ink":    "#0F172A",  # Text
    "paper":  "#FDFCFC",  # Page bg
    "panel":  "#FFFFFF",  # Card bg
}

ZAMBIA_DARK = {
    "green":  "#32B525",
    "red":     "#D10000",
    "black":  "#030303",
     "orange": "#FF9500",  # Eagle orange
    "ink":    "#F3F4F6",
    "paper":  "#000000",
    "panel":  "#101827",
}

def apply_brand(mode: str = "light"):
    p = ZAMBIA if mode == "light" else ZAMBIA_DARK
    st.markdown(
        f"""
        <style>
        /* Page + main blocks */
        .stApp {{
            background: {p["paper"]};
            color: {p["ink"]};
        }}
        section.main > div {{
            padding-top: 0.5rem;
        }}
        /* Cards/panels */
        div[data-testid="stVerticalBlock"] > div:has(> .stMarkdown + .stDataFrame) {{
            background: {p["panel"]};
            border-radius: 12px;
            padding: 8px 8px 2px;
        }}
        /* Buttons */
        .stButton > button {{
            background: {p["green"]} !important;
            color: white !important;
            border: 1px solid {p["green"]} !important;
            border-radius: 10px !important;
            font-weight: 600 !important;
        }}
        .stButton > button:hover {{
            filter: brightness(0.95);
        }}
        /* Download button */
        .stDownloadButton > button {{
            background: {p["orange"]} !important;
            border-color: {p["orange"]} !important;
            color: #1b1b1b !important;
            font-weight: 700 !important;
            border-radius: 10px !important;
        }}
        /* Radio/checkbox accent */
        input[type="radio"]:checked + div, input[type="checkbox"]:checked + div {{
            border-color: {p["green"]} !important;
        }}
        /* Table badges (Day1/Day2) */
        .badge-yes {{
            background: {p["green"]};
            color: #fff;
            padding: 2px 8px;
            border-radius: 999px;
            font-size: 0.75rem;
            font-weight: 700;
        }}
        .badge-no {{
            background: #94A3B8;
            color: #0b1220;
            padding: 2px 8px;
            border-radius: 999px;
            font-size: 0.75rem;
            font-weight: 700;
        }}
        /* Header stripe (subtle flag) */
        [data-testid="stHeader"] {{
            background: linear-gradient(90deg,
                {p["green"]} 0 40%,
                {p["red"]} 40% 55%,
                {p["black"]} 55% 70%,
                {p["orange"]} 70% 100%) !important;
            border-bottom: none;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )

# Example toggle (put in your header area)
st.session_state.theme_mode = "dark"
apply_brand("dark")

# Keep the page title without a mode switcher
# st.title("ASM Conference Register")


# ---------- Header ----------
left, mid, right = st.columns([1, 3, 2])
logo_path = Path("coat of arms.PNG")
with left:
    if logo_path.exists():
        st.image(str(logo_path), width=80)
with mid:
    st.title("ASM Conference Register")
with right:
    st.caption(datetime.now().strftime("Today: %B %d, %Y • %H:%M"))

# ---------- Load snapshot ----------
df = get_df()
summary = get_summary(df)

m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("Total Registered", summary.total)
m2.metric("Attended Day 1", summary.d1)
m3.metric("Attended Day 2", summary.d2)
m4.metric("Attended Both", summary.both)
m5.metric("Attended Neither", summary.none)

st.divider()

# ---------- Tabs ----------
tab_checkin, tab_register, tab_import, tab_export, tab_data = st.tabs(
    ["✅ Check-in", "➕ Register", "⬆️ Import Excel", "⬇️ Export Report", "📋 Data"]
)

# === Check-in ===
with tab_checkin:
    st.subheader("Bulk Check-in")
    fc1, fc2, fc3, fc4 = st.columns([1, 1, 1, 1])
    with fc1:
        f_name = st.text_input("Name contains", "")
    with fc2:
        f_dist = st.text_input("District contains", "")
    with fc3:
        f_coop = st.text_input("Co-operative/Association contains", "")
    with fc4:
        day = st.radio("Mark for", ["Day 1", "Day 2"], index=0, horizontal=True)

    filtered = filter_df(df, f_name, f_dist, f_coop)
    att_col = "Day1_Attended" if day == "Day 1" else "Day2_Attended"
    view_cols = ["NO.", "Name", "Name of Co-operative/Association", "District", "Province", att_col]
    display = filtered[view_cols].rename(columns={att_col: "Already Attended"})

    # Add selection checkbox column
    display.insert(0, "Select", False)
    st.caption("Tick rows to check in, then click **Mark Selected**.")
    edited = st.data_editor(
        display,
        use_container_width=True,
        hide_index=True,
        num_rows="fixed",
        column_config={
            "Select": st.column_config.CheckboxColumn(help="Select to check in."),
            "Already Attended": st.column_config.CheckboxColumn(disabled=True),
        },
    )

    if st.button("Mark Selected as Attended", type="primary"):
        picked = edited[edited["Select"] == True]  # noqa: E712
        if picked.empty:
            st.warning("No rows selected.")
        else:
            ids = [int(x) for x in picked["NO."].tolist() if pd.notna(x)]
            updated, already, not_found = checkin_bulk(ids, 1 if day == "Day 1" else 2)
            st.success(f"Marked: {updated} • Already: {already} • Not found: {not_found}")
            st.rerun()

    st.caption(f"Showing {len(filtered)} row(s).")

# === Register ===
with tab_register:
    st.subheader("Register New Participant")
    with st.form("reg_form", clear_on_submit=True):
        name = st.text_input("Name*", "")
        coop = st.text_input("Co-operative/Association", "")
        dist = st.text_input("District*", "")
        prov = st.text_input("Province*", "")
        if st.form_submit_button("Save"):
            ok, msg = register_participant(name, coop, dist, prov)
            st.success(msg) if ok else st.warning(msg)
            if ok:
                st.rerun()

# === Import ===
with tab_import:
    st.subheader("Import Excel")
    st.caption("Required columns: NO., Name, Name of Co-operative/Association, District, Province")
    up = st.file_uploader("Choose an Excel file (.xlsx or .xls)", type=["xlsx", "xls"])
    if up is not None:
        try:
            content = up.read()
            count, dupes = import_block(content)
            st.success(f"Imported {count} new; skipped {dupes} duplicates.")
            st.rerun()
        except Exception as e:
            st.error(f"Failed to import: {e}")

# === Export ===
with tab_export:
    st.subheader("Export Attendance Report (Excel)")
    data, fname = build_report_bytes()
    st.download_button(
        "Download Excel Report",
        data=data,
        file_name=fname,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        type="primary",
    )

# === Data ===
with tab_data:
    st.subheader("All Data")
    st.dataframe(df, use_container_width=True, height=520)
