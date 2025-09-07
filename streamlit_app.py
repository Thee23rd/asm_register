# streamlit_app.py
from __future__ import annotations
import os, json
from pathlib import Path
from typing import List, Dict, Any
from datetime import datetime

import streamlit as st
import pandas as pd

# ---- Page config ----
st.set_page_config(page_title="ASM Conference Register", page_icon="🦅", layout="wide")

# ---- Services ----
from service import (
    get_df, get_summary, filter_df,
    register_participant, checkin_bulk, import_block, build_report_bytes
)

def set_kiosk_mode(enable: bool = True):
    """Hide Streamlit chrome (menu/header/footer/toolbars) for a clean kiosk UI."""
    if not enable:
        return
    st.set_page_config(
        page_title="ASM Conference Register",
        page_icon="🦅",
        layout="wide",
        initial_sidebar_state="collapsed",
        menu_items={},  # empties the hamburger menu if it’s shown
    )
    st.markdown(
        """
        <style>
        /* hide global chrome */
        #MainMenu {visibility: hidden;}
        header {visibility: hidden;}
        footer {visibility: hidden;}
        [data-testid="stToolbar"] {display: none !important;}
        [data-testid="stDecoration"] {display: none !important;}
        [data-testid="viewerBadgeLink"] {display: none !important;}
        .stDeployButton {display: none !important;}
        /* optional: hide fullscreen buttons on charts/dataframes */
        button[title="View fullscreen"] {display: none !important;}
        </style>
        """,
        unsafe_allow_html=True,
    )

# =========================
# Branding / Theme
# =========================
ZAMBIA = {
    "green":  "#198A00",  # flag green
    "red":    "#D10000",
    "black":  "#000000",
    "orange": "#FF9500",  # eagle orange
    "ink":    "#F3F4F6",
    "paper":  "#000000",
    "panel":  "#101827",
}

def apply_brand():
    p = ZAMBIA
    st.markdown(
        f"""
        <style>
        .stApp {{
            background: {p["paper"]}; color: {p["ink"]};
        }}
        section.main > div {{ padding-top: .5rem; }}
        div[data-testid="stVerticalBlock"] > div:has(> .stMarkdown + .stDataFrame) {{
            background: {p["panel"]}; border-radius: 12px; padding: 8px 8px 2px;
        }}
        .stButton > button {{
            background: {p["green"]} !important; color: white !important;
            border: 1px solid {p["green"]} !important; border-radius: 10px !important; font-weight: 600 !important;
        }}
        .stButton > button:hover {{ filter: brightness(0.96); }}
        .stDownloadButton > button {{
            background: {p["orange"]} !important; border-color: {p["orange"]} !important;
            color: #1b1b1b !important; font-weight: 700 !important; border-radius: 10px !important;
        }}
        .badge-yes {{
            background: {p["green"]}; color:#fff; padding:2px 8px; border-radius:999px; font-size:.75rem; font-weight:700;
        }}
        .badge-no {{
            background: #94A3B8; color:#0b1220; padding:2px 8px; border-radius:999px; font-size:.75rem; font-weight:700;
        }}
        [data-testid="stHeader"] {{
            background: linear-gradient(90deg,
                {p["green"]} 0 40%,
                {p["red"]}   40% 55%,
                {p["black"]} 55% 70%,
                {p["orange"]} 70% 100%) !important;
            border-bottom: none;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )

apply_brand()

def hide_chrome():
    st.markdown("""
        <style>#MainMenu{visibility:hidden;} footer{visibility:hidden;} header{visibility:hidden;}</style>
    """, unsafe_allow_html=True)

# =========================
# Admin / Role helpers
# =========================
ADMIN_PIN = os.environ.get("ADMIN_PIN", "").strip()
if not ADMIN_PIN:
    try:
        ADMIN_PIN = st.secrets["ADMIN_PIN"].strip()
    except Exception:
        ADMIN_PIN = ""

def registrar_login(pin: str) -> bool:
    return bool(ADMIN_PIN) and (pin.strip() == ADMIN_PIN)

# Session state init
defaults = {
    "role": None,                # "registrar" or "attendee"
    "is_admin": False,           # registrar authenticated
    "locked": False,             # attendee: hides gateway
    "attendee_stage": "checkin", # "checkin" or "resources"
}
for k, v in defaults.items():
    st.session_state.setdefault(k, v)

# Deep links (?role=attendee&stage=resources)
qs = st.query_params
if "role" in qs and st.session_state.role is None:
    if qs["role"] == "attendee":
        st.session_state.role = "attendee"
        st.session_state.locked = True
if "stage" in qs and st.session_state.role == "attendee":
    if qs["stage"] == "resources":
        st.session_state.attendee_stage = "resources"

def go_role(role: str, lock: bool = False):
    st.session_state.role = role
    st.session_state.locked = lock
    st.query_params.clear()
    st.rerun()

def go_stage_resources():
    st.session_state.attendee_stage = "resources"
    st.rerun()

# =========================
# Materials
# =========================
MATERIALS_DIR = Path("materials")
MATERIALS_CFG = Path("materials.json")

def load_material_links() -> List[Dict[str, Any]]:
    if MATERIALS_CFG.exists():
        try:
            return json.loads(MATERIALS_CFG.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []

def list_local_materials() -> List[Path]:
    if MATERIALS_DIR.exists() and MATERIALS_DIR.is_dir():
        return sorted([p for p in MATERIALS_DIR.glob("*") if p.is_file()])
    return []

# =========================
# Views
# =========================
def view_header():
    left, mid, right = st.columns([1, 3, 2])
    logo_path = Path("coat of arms.PNG")
    with left:
        if logo_path.exists():
            st.image(str(logo_path), width=80)
    with mid:
        st.title("Zambian ASM Conference — Registrar")
    with right:
        st.caption(datetime.now().strftime("Today: %B %d, %Y • %H:%M"))

        

def view_gateway():
    st.markdown("")  # spacing
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("I am **Registering Others**")
        pin_val = st.text_input("Admin PIN", type="password", placeholder="••••", key="gw_pin")

        # Handle button inline (NO on_click)
        if st.button("Enter Registrar Mode", type="primary", key="btn_registrar"):
            if not ADMIN_PIN:
                st.error("Admin PIN is not configured. Set ADMIN_PIN via environment or .streamlit/secrets.toml.")
            elif registrar_login(pin_val):
                # set state and rerun inline (allowed)
                st.session_state.is_admin = True
                st.session_state.role = "registrar"
                st.session_state.locked = False
                st.query_params.clear()
                st.rerun()
            else:
                st.error("Invalid PIN")

        # Small hint during setup (never shows the actual PIN)
        if not ADMIN_PIN:
            st.caption("⚠️ Admin PIN not set. Configure ENV var `ADMIN_PIN` or add it to `.streamlit/secrets.toml`.")

    with col2:
        st.subheader("I am a **Participant**")
        st.caption("Confirm or register yourself, then access conference materials.")
        if st.button("Continue to Attendee Page", key="btn_attendee"):
            st.session_state.role = "attendee"
            st.session_state.locked = True
            st.query_params.clear()
            st.rerun()

    st.stop()



def view_attendee_resources():
    hide_chrome()
    left, mid, right = st.columns([1, 2, 2])
    logo_path = Path("coat of arms.PNG")
    with left:
        if logo_path.exists():
            st.image(str(logo_path), width=80)
    with mid:
       st.title("ASM Conference Materials & Info")
    with right:
        st.caption(datetime.now().strftime("Today: %B %d, %Y • %H:%M"))

    

    st.markdown("""
    - **Wi-Fi:** KKIC-WIFI |  Password: **KKIC@2025!**  
    - **Help Desk:** Near the main entrance  
    - **Agenda:** See **Agenda** section below  
    """)

    links = load_material_links()
    if links:
        st.subheader("Online Resources")
        for item in links:
            title = item.get("title", "Untitled")
            desc  = item.get("description", "")
            url   = item.get("url", "#")
            st.markdown(f"- [{title}]({url})  \n  <span style='opacity:.75'>{desc}</span>", unsafe_allow_html=True)

    files = list_local_materials()
    if files:
        st.subheader("Downloads")
        for p in files:
            try:
                data = p.read_bytes()
                st.download_button(
                    label=f"Download {p.name}",
                    data=data,
                    file_name=p.name,
                    mime="application/octet-stream",
                    use_container_width=True,
                )
            except Exception as e:
                st.caption(f"Could not read {p.name}: {e}")

    # with st.expander("Agenda"):
    #     st.markdown("""
    #     **Day 1**
    #     - 08:30 Opening Remarks  
    #     - 09:00 Keynote  
    #     - 10:30 Break  
    #     - 11:00 Session A / Session B  
    #     - 12:30 Lunch  
    #     - 14:00 Workshops  
    #     - 17:00 Close  

    #     **Day 2**
    #     - 09:00 Panel Discussion  
    #     - 10:30 Break  
    #     - 11:00 Sessions  
    #     - 12:30 Lunch  
    #     - 14:00 Closing & Certificates  
    #     """)

def view_attendee_checkin():
    hide_chrome()
     # Quick nav: allow attendees to jump to materials immediately
    top_left, top_right = st.columns([1, 1])
    with top_left:
        if st.button("↪  Go to Conference Materials", key="att_top_materials", use_container_width=True):
            st.session_state.attendee_stage = "resources"
            st.rerun()
    with top_right:
        st.caption("Or search below to confirm/check yourself in.")

    # Keep a few small states to survive reruns
    ss = st.session_state
    ss.setdefault("att_q_name", "")
    ss.setdefault("att_q_dist", "")
    ss.setdefault("att_q_coop", "")
    ss.setdefault("att_pick_idx", 0)  # which result row was chosen last

    df = get_df()
    st.subheader("Attendee check-in / self-registration")
    st.caption("Search your registration. If not found, you can register yourself. After confirming or registering, continue to the Conference Materials page.")

    # Select day
    cday = st.radio("I'm checking in for:", ["Day 1", "Day 2"], index=0, horizontal=True, key="att_day_radio")
    day_num = 1 if cday == "Day 1" else 2
    att_col = "Day1_Attended" if day_num == 1 else "Day2_Attended"

    # --- Search form ---
    with st.form("attendee_lookup_form", clear_on_submit=False):
        c1, c2, c3 = st.columns([1.2, 1, 1])
        with c1:
            ss.att_q_name = st.text_input("Your Name *", ss.att_q_name, key="att_q_name_w")
        with c2:
            ss.att_q_dist = st.text_input("District (optional)", ss.att_q_dist, key="att_q_dist_w")
        with c3:
            ss.att_q_coop = st.text_input("Co-operative/Association (optional)", ss.att_q_coop, key="att_q_coop_w")

        find_clicked = st.form_submit_button("Find my registration", type="primary", use_container_width=False)

    def _badge(ok: bool) -> str:
        return f'<span class="badge-yes">Yes</span>' if bool(ok) else f'<span class="badge-no">No</span>'

    def _norm(s: str) -> str:
        return (s or "").strip().lower()

    if find_clicked:
        # Run search and store the results (indexes) in session to preserve across reruns
        results = filter_df(df, ss.att_q_name, ss.att_q_dist, ss.att_q_coop)
        ss["att_results_index"] = list(results.index)  # store underlying row indices
        ss["att_pick_idx"] = 0
        st.rerun()

    # If we have stored results, render them
    if "att_results_index" in ss:
        results = df.loc[ss["att_results_index"]].copy()

        if not results.empty:
            view_cols = ["NO.", "Name", "Name of Co-operative/Association", "District", "Province"]
            slim = results[view_cols].copy()

            def _opt(row):
                no_val = int(row["NO."]) if pd.notna(row["NO."]) else "-"
                coop = (row["Name of Co-operative/Association"] or "").strip()
                coop_part = f" • {coop}" if coop else ""
                return f"{no_val} — {row['Name']}{coop_part} • {row['District']}"

            options = [_opt(r) for _, r in slim.iterrows()]

            # selection persists via att_pick_idx
            picked_label = st.selectbox(
                "Select your record",
                options,
                index=min(ss["att_pick_idx"], max(len(options)-1, 0)),
                key="att_pick_box"
            )
            ss["att_pick_idx"] = options.index(picked_label)
            picked = results.iloc[ss["att_pick_idx"]]

            no_val   = int(picked["NO."]) if pd.notna(picked["NO."]) else "-"
            name_val = picked["Name"]
            coop_val = picked.get("Name of Co-operative/Association") or "—"
            dist_val = picked.get("District") or "—"
            prov_val = picked.get("Province") or "—"
            reg_val  = picked.get("Registered_On", "—")

            d1_badge = _badge(picked.get("Day1_Attended", False))
            d2_badge = _badge(picked.get("Day2_Attended", False))

            st.markdown(
                f"""
                <div style="background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.10); padding: 12px 14px; border-radius: 10px;">
                  <h4 style="margin: 0 0 8px 0;">Registration Found ✅</h4>
                  <div><strong>NO.:</strong> {no_val}</div>
                  <div><strong>Name:</strong> {name_val}</div>
                  <div><strong>Co-operative/Association:</strong> {coop_val}</div>
                  <div><strong>District / Province:</strong> {dist_val} / {prov_val}</div>
                  <div><strong>Registered On:</strong> {reg_val}</div>
                  <div style="margin-top:10px;">
                    <strong>Day 1:</strong> {d1_badge} &nbsp;&nbsp; <strong>Day 2:</strong> {d2_badge}
                  </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            already = bool(picked.get(att_col, False))
            c1, c2 = st.columns([1, 1])
            with c1:
                if already:
                    st.info(f"You are already checked in for {cday}.")
                else:
                    if st.button(f"Check me in for {cday}", type="primary", key="att_self_check"):
                        try:
                            pid = int(picked["NO."])
                            upd, alr, nf = checkin_bulk([pid], day_num)
                            if upd == 1:
                                st.success(f"Checked in for {cday}.")
                                st.session_state.attendee_stage = "resources"
                                st.rerun()
                            elif alr == 1:
                                st.info(f"You were already checked in for {cday}.")
                                st.session_state.attendee_stage = "resources"
                                st.rerun()
                            else:
                                st.warning("Could not update your check-in. Please visit the registration desk.")
                        except Exception as e:
                            st.error(f"Failed to check in: {e}")

            with c2:
                if st.button("Continue to Conference Materials →", key="att_go_materials"):
                    st.session_state.attendee_stage = "resources"
                    st.rerun()

        else:
            # No matches -> show self-register form
            st.warning("No matching registration found. Please register yourself below.")
            with st.form("self_register_form", clear_on_submit=False):
                n1, n2 = st.columns([1.2, 1])
                with n1:
                    name_new = st.text_input("Full Name *", ss.att_q_name, key="att_reg_name")
                    coop_new = st.text_input("Co-operative/Association/Oganization/Institution (optional)", ss.att_q_coop, key="att_reg_coop")
                with n2:
                    dist_new = st.text_input("District *", ss.att_q_dist, key="att_reg_dist")
                    prov_new = st.text_input("Province *", "", key="att_reg_prov")
                auto_check = st.checkbox(f"Also check me in for {cday} now", value=True, key="att_reg_auto")
                do_reg = st.form_submit_button("Register me", type="primary")

            if do_reg:
                if not name_new or not dist_new or not prov_new:
                    st.error("Please provide at least Name, District, and Province.")
                else:
                    ok, msg = register_participant(name_new.strip(), coop_new.strip(), dist_new.strip(), prov_new.strip())
                    if not ok:
                        # Important: show backend reason (e.g., duplicate)
                        st.warning(msg)
                    else:
                        st.success("Registration successful!")
                        if auto_check:
                            # Re-load to fetch new NO. and check-in
                            df2 = get_df()
                            candidates = df2[
                                (df2["Name"].astype(str).str.strip().str.lower() == _norm(name_new)) &
                                (df2["District"].astype(str).str.strip().str.lower() == _norm(dist_new))
                            ]
                            if not candidates.empty:
                                pid = int(candidates["NO."].max())
                                try:
                                    upd, alr, nf = checkin_bulk([pid], day_num)
                                    if upd == 1:
                                        st.success(f"Checked in for {cday}.")
                                    elif alr == 1:
                                        st.info(f"You were already checked in for {cday}.")
                                except Exception as e:
                                    st.error(f"Failed to check in: {e}")
                        # Move to materials
                        st.session_state.attendee_stage = "resources"
                        st.rerun()
    else:
        # No search performed yet → gentle prompt
        st.info("Enter your name and click **Find my registration** to continue.")

    


def view_registrar_dashboard():
    
    view_header()

    df = get_df()
    summary = get_summary(df)

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Total Registered", summary.total)
    m2.metric("Attended Day 1", summary.d1)
    m3.metric("Attended Day 2", summary.d2)
    m4.metric("Attended Both", summary.both)
    m5.metric("Attended Neither", summary.none)
    

    st.divider()
  
    

    

    tab_checkin, tab_register, tab_import, tab_export, tab_data = st.tabs(
        ["✅ Check-in", "➕ Register", "⬆️ Import Excel", "⬇️ Export Report", "📋 Data"]
    )

    with tab_checkin:
        st.subheader("Bulk Check-in")
        fc1, fc2, fc3, fc4 = st.columns([1, 1, 1, 1])
        with fc1:
            f_name = st.text_input("Name contains", "", key="adm_f_name")
        with fc2:
            f_dist = st.text_input("District contains", "", key="adm_f_dist")
        with fc3:
            f_coop = st.text_input("Co-operative/Association contains", "", key="adm_f_coop")
        with fc4:
            day = st.radio("Mark for", ["Day 1", "Day 2"], index=0, horizontal=True, key="adm_day")

        filtered = filter_df(df, f_name, f_dist, f_coop)
        att_col = "Day1_Attended" if day == "Day 1" else "Day2_Attended"
        view_cols = ["NO.", "Name", "Name of Co-operative/Association", "District", "Province", att_col]
        display = filtered[view_cols].rename(columns={att_col: "Already Attended"})
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
            key="adm_editor",
        )

        if st.button("Mark Selected as Attended", type="primary", key="adm_mark"):
            picked = edited[edited["Select"] == True]  # noqa: E712
            if picked.empty:
                st.warning("No rows selected.")
            else:
                ids = [int(x) for x in picked["NO."].tolist() if pd.notna(x)]
                updated, already, not_found = checkin_bulk(ids, 1 if day == "Day 1" else 2)
                st.success(f"Marked: {updated} • Already: {already} • Not found: {not_found}")
                st.rerun()

        st.caption(f"Showing {len(filtered)} row(s).")

    with tab_register:
        st.subheader("Register New Participant")
        with st.form("reg_form", clear_on_submit=True):
            name = st.text_input("Name*", "", key="adm_reg_name")
            coop = st.text_input("Co-operative/Association", "", key="adm_reg_coop")
            dist = st.text_input("District*", "", key="adm_reg_dist")
            prov = st.text_input("Province*", "", key="adm_reg_prov")
            if st.form_submit_button("Save", use_container_width=True):
                ok, msg = register_participant(name, coop, dist, prov)
                st.success(msg) if ok else st.warning(msg)
                if ok:
                    st.rerun()

    with tab_import:
        st.subheader("Import Excel")
        st.caption("Required columns: NO., Name, Name of Co-operative/Association, District, Province")
        up = st.file_uploader("Choose an Excel file (.xlsx or .xls)", type=["xlsx", "xls"], key="adm_upl")
        if up is not None:
            try:
                content = up.read()
                count, dupes = import_block(content)
                st.success(f"Imported {count} new; skipped {dupes} duplicates.")
                st.rerun()
            except Exception as e:
                st.error(f"Failed to import: {e}")

    with tab_export:
        st.subheader("Export Attendance Report (Excel)")
        data, fname = build_report_bytes()
        st.download_button(
            "Download Excel Report",
            data=data,
            file_name=fname,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary",
            use_container_width=True,
        )

    with tab_data:
        st.subheader("All Data")
        st.dataframe(df, use_container_width=True, height=520)

# =========================
# Router
# =========================
def main():
    # If no role chosen or attendee not locked, show gateway first
    needs_gateway = (
        (st.session_state.role is None)
        or (st.session_state.role == "attendee" and not st.session_state.locked)
    )
    if needs_gateway:
        view_gateway()

    # Attendee flow (no big header; kiosk-like)
    if st.session_state.role == "attendee":
        if st.session_state.attendee_stage == "resources":
            view_attendee_resources()
            return
        view_attendee_checkin()
        return

    # Registrar (requires admin)
    if st.session_state.role == "registrar" and st.session_state.is_admin:
        view_registrar_dashboard()
        return

    # Fallback (not authenticated registrar)
    st.warning("You need the Admin PIN to access the registrar dashboard.")
    view_gateway()

if __name__ == "__main__":
    main()
