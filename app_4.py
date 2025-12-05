# app_4.py (full persistence, single-click navigation, steps 1-9)
import streamlit as st
import pandas as pd
import os
from datetime import datetime
from docx import Document
import base64
import requests
import tempfile
import traceback

# ------------------------------------------------
# CONFIG
# ------------------------------------------------
ALIGNMENT_FILE = "strategic_alignment.xlsx"

# Candidate persistent dir on Streamlit Cloud
DATA_DIR_CANDIDATE = "/mount/data/workplan_data"

# GitHub defaults (you provided repo)
DEFAULT_GITHUB_REPO = "sergioalf14/repo"

USE_GITHUB = True   # Keep GitHub syncing enabled (Option A)

# ------------------------------------------------
# SAFE DATA DIRECTORY INITIALIZATION
# ------------------------------------------------
try:
    os.makedirs(DATA_DIR_CANDIDATE, exist_ok=True)
    LOCAL_DATA_DIR = DATA_DIR_CANDIDATE
except Exception:
    LOCAL_DATA_DIR = tempfile.gettempdir()

# Ensure final MASTER_LOG path is defined after LOCAL_DATA_DIR is final
MASTER_LOG = os.path.join(LOCAL_DATA_DIR, "master_log.xlsx")
ANNEX_DIR = os.path.join(LOCAL_DATA_DIR, "annexes")
os.makedirs(ANNEX_DIR, exist_ok=True)

# ------------------------------------------------
# Load Streamlit secrets (allow override)
# ------------------------------------------------
GITHUB_TOKEN = st.secrets.get("GITHUB_TOKEN", None) if hasattr(st, "secrets") else None
GITHUB_REPO = st.secrets.get("GITHUB_REPO", DEFAULT_GITHUB_REPO) if hasattr(st, "secrets") else DEFAULT_GITHUB_REPO
GITHUB_BRANCH = st.secrets.get("GITHUB_BRANCH", "main") if hasattr(st, "secrets") else "main"

# If user disabled GitHub, allow override
if not USE_GITHUB:
    GITHUB_TOKEN = None

# ------------------------------------------------
# Helper: Push a file to GitHub (safe)
# ------------------------------------------------
def push_file_to_github(local_path, github_path):
    """
    Uploads (creates or updates) a file to the GitHub repo path.
    Returns a tuple: (success: bool, message: str)
    """
    if not USE_GITHUB:
        return (False, "GitHub upload disabled by configuration.")
    if not GITHUB_TOKEN:
        return (False, "GITHUB_TOKEN missing in Streamlit secrets.")
    if not GITHUB_REPO:
        return (False, "GITHUB_REPO not configured.")

    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{github_path}"
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
    }

    try:
        with open(local_path, "rb") as f:
            content_b64 = base64.b64encode(f.read()).decode("utf-8")
    except Exception as e:
        return (False, f"Failed to read local file for upload: {e}")

    # Check if file already exists to get sha
    try:
        r = requests.get(url, headers=headers, timeout=30)
    except Exception as e:
        return (False, f"GitHub API GET failed: {e}")

    sha = None
    if r.status_code == 200:
        try:
            resp = r.json()
            sha = resp.get("sha")
        except Exception:
            sha = None
    elif r.status_code not in (404,):
        # Unexpected error
        return (False, f"GitHub API GET error: {r.status_code} - {r.text}")

    commit_msg = f"Update {github_path}" if sha else f"Add {github_path}"
    payload = {
        "message": commit_msg,
        "content": content_b64,
        "branch": GITHUB_BRANCH
    }
    if sha:
        payload["sha"] = sha

    try:
        r2 = requests.put(url, json=payload, headers=headers, timeout=60)
    except Exception as e:
        return (False, f"GitHub API PUT failed: {e}")

    if r2.status_code in (200, 201):
        return (True, f"Pushed to GitHub: {github_path}")
    else:
        # return API error text to help debugging
        return (False, f"GitHub upload failed: {r2.status_code} - {r2.text}")

# ------------------------------------------------
# FILE EXISTENCE CHECK
# ------------------------------------------------
if not os.path.exists(ALIGNMENT_FILE):
    st.error("❌ Missing file: strategic_alignment.xlsx — please add it to your repository.")
    st.stop()

# ------------------------------------------------
# SESSION STATE INITIALIZATION
# ------------------------------------------------
if "step" not in st.session_state:
    st.session_state.step = 1
if "submission" not in st.session_state:
    st.session_state.submission = {}
if "last_file" not in st.session_state:
    st.session_state.last_file = None
if "annex_saved_list" not in st.session_state:
    st.session_state.annex_saved_list = []  # list of tuples (filename, saved_path)

# ----------------------------
# NAVIGATION FUNCTIONS
# ----------------------------
def next_step():
    st.session_state.step += 1

def prev_step():
    if st.session_state.step > 1:
        st.session_state.step -= 1


# ------------------------------------------------
# Save to master Excel (robust and append-only)
# ------------------------------------------------
def save_to_master_excel(row_dict):
    """
    Safely append a row to MASTER_LOG (xlsx). Falls back to tempdir if needed.
    Also attempts to push to GitHub (master_log.xlsx at repo root).
    Returns (success: bool, message: str)
    """

    local_master = MASTER_LOG

    # ------------------------------------------------
    # 1. Always build the full DataFrame BEFORE writing
    # ------------------------------------------------
    df_new = pd.DataFrame([row_dict])  # new row must be list of dict

    if os.path.exists(local_master):
        try:
            df_old = pd.read_excel(local_master)
        except Exception:
            df_old = pd.DataFrame()
    else:
        df_old = pd.DataFrame()

    # Append new entry
    df_final = pd.concat([df_old, df_new], ignore_index=True)

    # ------------------------------------------------
    # 2. Try writing to the actual location
    # ------------------------------------------------
    try:
        df_final.to_excel(local_master, index=False)

    except PermissionError:
        # ------------------------------------------------
        # 3. Permission error → save to temp directory fallback
        # ------------------------------------------------
        fallback = os.path.join(tempfile.gettempdir(), "master_log.xlsx")
        try:
            df_final.to_excel(fallback, index=False)
            local_master = fallback
        except Exception as e:
            return (False, f"Failed to write master log even to fallback: {e}")

    except Exception as e:
        return (False, f"Failed to write master log: {e}")

    # ------------------------------------------------
    # 4. Push to GitHub (if enabled)
    # ------------------------------------------------
    success, msg = push_file_to_github(local_master, "master_log.xlsx")

    if success:
        return (True, "")
    else:
        # Local write succeeded, GitHub failed → still OK
        return (True, f"Master log written locally at {local_master}. GitHub push: {msg}")

# ------------------------------------------------
# Export Word (generate + push + return filepath)
# ------------------------------------------------
def export_word(summary_dict):
    """
    Creates a Word document (docx), saves it to LOCAL_DATA_DIR (or fallback),
    uploads to GitHub under generated_reports/, and returns (filepath, filename, push_result).
    """
    doc = Document()
    doc.add_heading("Divisional Workplan Summary", level=1)

    for section, content in summary_dict.items():
        doc.add_heading(section, level=2)
        if isinstance(content, dict):
            for k, v in content.items():
                doc.add_paragraph(f"{k}: {v}")
        elif isinstance(content, list):
            for item in content:
                doc.add_paragraph(f"- {item}")
        else:
            doc.add_paragraph(str(content))

    filename = f"workplan_{datetime.now().strftime('%Y%m%d_%H%M%S')}.docx"
    filepath = os.path.join(LOCAL_DATA_DIR, filename)

    try:
        doc.save(filepath)
    except PermissionError:
        # fallback to temp dir
        filepath = os.path.join(tempfile.gettempdir(), filename)
        try:
            doc.save(filepath)
        except Exception as e:
            return (None, None, (False, f"Failed to save docx: {e}"))

    # Attempt to push to GitHub; best-effort
    gh_path = f"generated_reports/{filename}"
    success, msg = push_file_to_github(filepath, gh_path)
    return (filepath, filename, (success, msg))

# ------------------------------------------------
# Save annexes immediately and persist their saved paths
# ------------------------------------------------
def save_annexes_immediate(uploaded_files):
    """
    Saves uploaded File-like objects to ANNEX_DIR immediately so they persist across steps.
    Records saved file paths in st.session_state.annex_saved_list.
    Returns list of tuples (orig_name, saved_path, success, message)
    """
    saved = []
    for f in uploaded_files:
        try:
            safe_name = f.name
            out_path = os.path.join(ANNEX_DIR, safe_name)
            # If same filename exists, append timestamp to avoid overwrite
            if os.path.exists(out_path):
                base, ext = os.path.splitext(safe_name)
                out_path = os.path.join(ANNEX_DIR, f"{base}_{int(datetime.now().timestamp())}{ext}")
            with open(out_path, "wb") as out:
                out.write(f.getbuffer())
            # record in session_state
            st.session_state.annex_saved_list.append((f.name, out_path))
            # Attempt push to GitHub annexes/ folder (best-effort)
            success, msg = push_file_to_github(out_path, f"annexes/{os.path.basename(out_path)}")
            saved.append((f.name, out_path, True, msg if success else f"Saved locally; GH: {msg}"))
        except Exception as e:
            saved.append((f.name, None, False, f"Failed to save: {e}"))
    return saved

# ------------------------------------------------
# Finish callback: export docx + save master log + store filename for download
# ------------------------------------------------
def finish_and_save():
    try:
        # Save annexes already handled on upload; here we just ensure annex list is in submission
        st.session_state.submission["Annexes_Saved"] = [p for (_, p) in st.session_state.annex_saved_list]

        filepath, filename, push_result = export_word(st.session_state.submission)
        if not filepath:
            st.session_state.last_file = None
            st.session_state.finish_msg = f"Failed to generate Word doc: {push_result}"
            return

        # Save to master log (best-effort)
        save_ok, save_msg = save_to_master_excel({
            "timestamp": datetime.now(),
            "division": st.session_state.submission.get("Cover", {}).get("Division", ""),
            "goals": ", ".join(st.session_state.submission.get("Selected Goals", [])),
            "data": str(st.session_state.submission)
        })

        st.session_state.last_file = filepath
        st.session_state.finish_msg = ""
        if save_ok and save_msg:
            # success with message
            st.session_state.finish_msg = save_msg
        elif not save_ok:
            st.session_state.finish_msg = save_msg
        else:
            # save_ok True and no msg -> good
            st.session_state.finish_msg = ""

        # store push_result as well
        st.session_state.last_push_result = push_result

    except Exception as e:
        st.session_state.last_file = None
        st.session_state.finish_msg = f"Unexpected error: {e}\n{traceback.format_exc()}"

# ------------------------------------------------
# APP: Steps 1–9 (UI) — FULL PERSISTENCE (Option A)
# ------------------------------------------------

# ----------------------------
# STEP 1 — Division Cover Page
# ----------------------------
if st.session_state.step == 1:
    st.title("Step 1 — Division Workplan Cover Page")

    # Widgets with keys (widget state maintained by Streamlit)
    division = st.text_input("Division Name", key="division")
    director = st.text_input("Director's Name", key="director")
    date_entry = st.date_input("Date of Workplan", key="date_entry")
    version = st.text_input("Version of Workplan", key="version")
    ftes = st.text_input("Divisional FTEs", key="ftes")
    financial = st.text_input("Divisional Financial Resources", key="financial")
    signature = st.radio("Director's Signature Provided?", ["Yes", "No"], key="signature")

    # Persist ALWAYS so values reappear when navigating back
    st.session_state.submission["Cover"] = {
        "Division": division,
        "Director": director,
        "Date": str(date_entry),
        "Version": version,
        "FTEs": ftes,
        "Financial Resources": financial,
        "Director Signature": signature
    }

    # Navigation
    col1, col2 = st.columns([1, 1])
    with col1:
        st.write("")  # placeholder — no Previous on step 1
    with col2:
        st.button("Next", on_click=next_step, key="next_1")

# ----------------------------
# STEP 2 — Strategic Goals
# ----------------------------
if st.session_state.step == 2:
    st.title("Step 2 — Select Strategic Goals")

    try:
        df = pd.read_excel(ALIGNMENT_FILE)
    except Exception as e:
        st.error(f"Failed to read {ALIGNMENT_FILE}: {e}")
        st.stop()

    if "strategic_goal" not in df.columns:
        st.error(f"{ALIGNMENT_FILE} must contain a 'strategic_goal' column.")
        st.stop()

    goals = sorted(df["strategic_goal"].dropna().unique().tolist())

    # default from saved submission so selections reappear
    default_goals = st.session_state.submission.get("Selected Goals", [])

    selected_goals = st.multiselect(
        "Select Strategic Goals",
        options=goals,
        default=default_goals,
        key="selected_goals"
    )

    # persist immediately
    st.session_state.submission["Selected Goals"] = selected_goals

    col1, col2 = st.columns(2)
    with col1:
        st.button("Previous", on_click=prev_step, key="prev_2")
    with col2:
        st.button("Next", on_click=next_step, key="next_2")

# ----------------------------
# STEP 3 — Aggregate Objectives + Other (dynamic)
# ----------------------------
if st.session_state.step == 3:
    st.title("Step 3 — Aggregate Divisional Objectives")
    df = pd.read_excel(ALIGNMENT_FILE)

    selected_goals = st.session_state.submission.get("Selected Goals", [])
    goal_to_agg = {}

    for g_idx, g in enumerate(selected_goals):
        st.subheader(f"Strategic Goal: {g}")

        agg_list = df[df["strategic_goal"] == g]["aggregate_divisional_objectives"].dropna().unique().tolist()

        # recover old values (both standard + custom)
        old_selected = st.session_state.submission.get("Aggregate Objectives", {}).get(g, [])
        default_standard = [x for x in old_selected if x in agg_list]

        sel = st.multiselect(
            f"Select Aggregate Objectives for {g}",
            options=agg_list,
            default=default_standard,
            key=f"agg_{g_idx}"
        )

        # Custom objectives — full persistence
        st.write("Custom Aggregate Objectives:")

        old_custom = [x for x in old_selected if x not in agg_list]
        prev_num_custom = len(old_custom)

        num_custom = st.number_input(
            f"How many custom aggregate objectives for {g}?",
            min_value=0,
            value=prev_num_custom,
            step=1,
            key=f"num_custom_{g_idx}"
        )

        custom_items = []
        for i in range(int(num_custom)):
            default_val = old_custom[i] if i < len(old_custom) else ""
            txt = st.text_input(
                f"Custom Objective {i+1} for {g}",
                value=default_val,
                key=f"custom_{g_idx}_{i}"
            )
            if txt.strip():
                custom_items.append(txt.strip())

        goal_to_agg[g] = sel + custom_items

    # save always
    st.session_state.submission["Aggregate Objectives"] = goal_to_agg

    col1, col2 = st.columns(2)
    with col1:
        st.button("Previous", on_click=prev_step, key="prev_3")
    with col2:
        st.button("Next", on_click=next_step, key="next_3")

# ----------------------------
# STEP 4 — Specific Divisional Objectives
# ----------------------------
if st.session_state.step == 4:
    st.title("Step 4 — Specific Divisional Objectives")
    spec_map = st.session_state.submission.get("Specific Objectives", {})

    # iterate aggregate objectives (if absent, warn)
    aggregate_objectives = st.session_state.submission.get("Aggregate Objectives", {})
    if not aggregate_objectives:
        st.warning("No aggregate objectives found. Please select aggregate objectives in Step 3.")
    for g_idx, (g, agg_list) in enumerate(aggregate_objectives.items()):
        st.subheader(f"Strategic Goal: {g}")
        for a_idx, agg in enumerate(agg_list):
            st.markdown(f"### Aggregate Objective: {agg}")
            key_radio = f"radio_{g_idx}_{a_idx}_{agg}".replace(" ", "_")
            prev_choice = "Yes" if (g, agg) in spec_map and spec_map.get((g, agg)) and spec_map.get((g, agg)) != ["None"] else "No"
            # Provide radio with default based on previous data
            choice = st.radio(
                f"Add specific objectives for '{agg}'?",
                ["No", "Yes"],
                index=0 if prev_choice == "No" else 1,
                key=key_radio
            )

            key_text = f"spec_{g_idx}_{a_idx}_{agg}".replace(" ", "_")
            if choice == "Yes":
                default_text = "\n".join(spec_map.get((g, agg), [])) if spec_map.get((g, agg)) and spec_map.get((g, agg)) != ["None"] else ""
                entries = st.text_area(f"Enter specific objectives (one per line):", value=default_text, key=key_text)
                specific_list = [x.strip() for x in entries.split("\n") if x.strip()]
                if not specific_list:
                    specific_list = ["None provided"]
            else:
                specific_list = ["None"]

            spec_map[(g, agg)] = specific_list

    st.session_state.submission["Specific Objectives"] = spec_map

    col1, col2 = st.columns(2)
    with col1:
        st.button("Previous", on_click=prev_step, key="prev_4")
    with col2:
        st.button("Next", on_click=next_step, key="next_4")

# ----------------------------
# STEP 5 — Activities & Results
# ----------------------------
if st.session_state.step == 5:
    st.title("Step 5 — Activities & Results")

    act_map = st.session_state.submission.get("Activities", {})
    new_map = {}

    aggregate_objectives = st.session_state.submission.get("Aggregate Objectives", {})
    if not aggregate_objectives:
        st.warning("No aggregate objectives found. Please go back to Step 3 and add them.")

    for g_idx, (g, agg_list) in enumerate(aggregate_objectives.items()):
        st.subheader(f"Strategic Goal: {g}")
        for a_idx, agg in enumerate(agg_list):
            st.markdown(f"### Aggregate Objective: {agg}")

            key_act = f"act_{g_idx}_{a_idx}"
            key_res = f"res_{g_idx}_{a_idx}"

            prev_vals = act_map.get((g, agg), {"activities": [], "results": []})
            activities_text = "\n".join(prev_vals.get("activities", []))
            results_text = "\n".join(prev_vals.get("results", []))

            activities = st.text_area(
                f"Planned activities (one per line) for '{agg}':",
                value=activities_text,
                key=key_act
            )
            results = st.text_area(
                f"Expected results (one per line) for '{agg}':",
                value=results_text,
                key=key_res
            )

            new_map[(g, agg)] = {
                "activities": [x.strip() for x in activities.split("\n") if x.strip()],
                "results": [x.strip() for x in results.split("\n") if x.strip()]
            }

    st.session_state.submission["Activities"] = new_map

    col1, col2 = st.columns(2)
    with col1:
        st.button("Previous", on_click=prev_step, key="prev_5")
    with col2:
        st.button("Next", on_click=next_step, key="next_5")

# ----------------------------
# STEP 6 — Metrics per Strategic Goal
# ----------------------------
if st.session_state.step == 6:
    st.title("Step 6 — Metrics per Strategic Goal")

    old_metrics = st.session_state.submission.get("Goal Metrics", {})
    metrics = {}

    selected_goals = st.session_state.submission.get("Selected Goals", [])
    if not selected_goals:
        st.warning("No strategic goals selected. Please go back to Step 2 to select goals.")

    for g_idx, g in enumerate(selected_goals):
        st.subheader(f"Strategic Goal: {g}")
        old = old_metrics.get(g, {})

        fte = st.text_input(f"FTEs for {g}", value=old.get("FTEs", ""), key=f"fte_{g_idx}")
        fin = st.text_input(f"Financial Resources for {g}", value=old.get("Financial Resources", ""), key=f"fin_{g_idx}")
        kpi = st.text_area(f"Key Performance Indicators for {g}", value=old.get("KPIs", ""), key=f"kpi_{g_idx}")
        other = st.text_area(f"Other Metrics for {g}", value=old.get("Other Metrics", ""), key=f"other_{g_idx}")

        metrics[g] = {
            "FTEs": fte,
            "Financial Resources": fin,
            "KPIs": kpi,
            "Other Metrics": other
        }

    st.session_state.submission["Goal Metrics"] = metrics

    col1, col2 = st.columns(2)
    with col1:
        st.button("Previous", on_click=prev_step, key="prev_6")
    with col2:
        st.button("Next", on_click=next_step, key="next_6")

# ----------------------------
# STEP 7 — Optional Objective/Result Metrics
# ----------------------------
if st.session_state.step == 7:
    st.title("Step 7 — Optional Objective/Result Metrics")
    opt = st.radio("Would you like to report metrics for objectives/results?", ["No", "Yes"], key="opt_obj_res")
    obj_res_metrics = st.session_state.submission.get("Objective/Result Metrics", {})

    if opt == "Yes":
        # The original code used Specific Objectives to populate items. We'll use that mapping.
        spec_map = st.session_state.submission.get("Specific Objectives", {})
        # Loop over spec_map and for each item provide inputs with defaults from obj_res_metrics
        for idx, ((g, agg), spec_list) in enumerate(spec_map.items()):
            st.subheader(f"Aggregate Objective: {agg}")
            for s_idx, item in enumerate(spec_list):
                st.markdown(f"### Item: {item}")
                prev_vals = obj_res_metrics.get((g, agg, item), {})
                fte = st.text_input(f"FTEs for '{item}'", value=prev_vals.get("FTEs", ""), key=f"obj_fte_{idx}_{s_idx}")
                fin = st.text_input(f"Financial Resources for '{item}'", value=prev_vals.get("Financial Resources", ""), key=f"obj_fin_{idx}_{s_idx}")
                kpi = st.text_area(f"KPIs for '{item}'", value=prev_vals.get("KPIs", ""), key=f"obj_kpi_{idx}_{s_idx}")
                other = st.text_area(f"Other Metrics for '{item}'", value=prev_vals.get("Other Metrics", ""), key=f"obj_other_{idx}_{s_idx}")
                obj_res_metrics[(g, agg, item)] = {"FTEs": fte, "Financial Resources": fin, "KPIs": kpi, "Other Metrics": other}

    st.session_state.submission["Objective/Result Metrics"] = obj_res_metrics

    col1, col2 = st.columns(2)
    with col1:
        st.button("Previous", on_click=prev_step, key="prev_7")
    with col2:
        st.button("Next", on_click=next_step, key="next_7")

# ----------------------------
# STEP 8 — Additional Information
# ----------------------------
if st.session_state.step == 8:
    st.title("Step 8 — Additional Information")

    old = st.session_state.submission.get("Additional", {})

    additional_info = {
        "Partnerships": st.text_area("Partnerships", value=old.get("Partnerships", ""), key="add_partnerships"),
        "Events": st.text_area("Events", value=old.get("Events", ""), key="add_events"),
        "Knowledge Products": st.text_area("Knowledge Products", value=old.get("Knowledge Products", ""), key="add_products"),
        "Knowledge Management": st.text_area("Knowledge Management Practices", value=old.get("Knowledge Management", ""), key="add_km"),
        "Cross-Divisional Initiatives": st.text_area("Participation in cross-divisional initiatives", value=old.get("Cross-Divisional Initiatives", ""), key="add_cross"),
        "Projects/Networks": st.text_area("Projects or Networks", value=old.get("Projects/Networks", ""), key="add_projects"),
        "Risks": st.text_area("Risks", value=old.get("Risks", ""), key="add_risks"),
        "Other Information": st.text_area("Other Information", value=old.get("Other Information", ""), key="add_other")
    }

    st.session_state.submission["Additional"] = additional_info

    col1, col2 = st.columns(2)
    with col1:
        st.button("Previous", on_click=prev_step, key="prev_8")
    with col2:
        st.button("Next", on_click=next_step, key="next_8")

# ----------------------------
# STEP 9 — Annex Upload + Export
# ----------------------------
if st.session_state.step == 9:
    st.title("Step 9 — Upload Annexes & Export")

    # Show previously saved annexes (if any)
    if st.session_state.annex_saved_list:
        st.write("Previously uploaded annexes (saved):")
        for orig_name, saved_path in st.session_state.annex_saved_list:
            st.write(f"- {orig_name} (saved at {saved_path})")

    # File uploader: when files are uploaded, immediately save them to ANNEX_DIR and record paths
    uploaded = st.file_uploader("Upload annex files (multiple)", accept_multiple_files=True, key="annex_uploader")
    if uploaded:
        # Save all uploaded (immediately) and update session_state
        saved_info = save_annexes_immediate(uploaded)
        for name, path, ok, msg in saved_info:
            if ok:
                st.success(f"Saved annex: {name}")
            else:
                st.error(f"Failed to save annex {name}: {msg}")

    # Always reflect saved annex filenames in submission
    st.session_state.submission["Annexes_Saved"] = [p for (_, p) in st.session_state.annex_saved_list]

    col1, col2 = st.columns(2)
    with col1:
        st.button("Previous", on_click=prev_step, key="prev_9")
    with col2:
        st.button("Finish and Generate Report", on_click=finish_and_save, key="finish")

    # If finish_and_save has been run and produced a file, show it and allow download
    if st.session_state.get("last_file"):
        try:
            st.success("Word report generated.")
            if st.session_state.get("finish_msg"):
                st.info(st.session_state.get("finish_msg"))
            last_path = st.session_state.last_file
            with open(last_path, "rb") as f:
                file_bytes = f.read()
                st.download_button(
                    label="Download Word Report",
                    data=file_bytes,
                    file_name=os.path.basename(last_path),
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    key="download_workplan"
                )
            # show GitHub push result for the generated report
            pr = st.session_state.get("last_push_result", (None, None))
            if pr and pr != (None, None):
                ok, msg = pr
                if ok:
                    st.info(f"Generated report push: {msg}")
                else:
                    st.warning(f"Generated report push: {msg}")
        except FileNotFoundError:
            st.error("Generated file not found on server (it may have been removed).")
        except Exception as e:
            st.error(f"Error preparing download: {e}")
            st.error(traceback.format_exc())
