# app_4.py
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
except Exception as e:
    # PermissionError or other issues -> fallback to temp dir
    # st.warning("⚠️ /mount/data not writable — falling back to temporary directory.")
    LOCAL_DATA_DIR = tempfile.gettempdir()

# Ensure final MASTER_LOG path is defined after LOCAL_DATA_DIR is final
MASTER_LOG = os.path.join(LOCAL_DATA_DIR, "master_log.xlsx")
ANNEX_DIR = os.path.join(LOCAL_DATA_DIR, "annexes")
os.makedirs(ANNEX_DIR, exist_ok=True)

# ------------------------------------------------
# Load Streamlit secrets (allow override)
# ------------------------------------------------
GITHUB_TOKEN = st.secrets.get("GITHUB_TOKEN", None)
GITHUB_REPO = st.secrets.get("GITHUB_REPO", DEFAULT_GITHUB_REPO)
GITHUB_BRANCH = st.secrets.get("GITHUB_BRANCH", "main")

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

def next_step():
    st.session_state.step += 1

# ------------------------------------------------
# Save to master Excel (robust)
# ------------------------------------------------
def save_to_master_excel(row_dict):
    """
    Safely append a row to MASTER_LOG (xlsx). Falls back to tempdir if needed.
    Also attempts to push to GitHub (master_log.xlsx at repo root).
    Returns (success: bool, message: str)
    """
    local_master = MASTER_LOG
    try:
        df_new = pd.DataFrame([row_dict])
        if os.path.exists(local_master):
            try:
                df_old = pd.read_excel(local_master)
            except Exception as e:
                # If reader fails (corrupt), replace it
                df_old = pd.DataFrame()
            df_final = pd.concat([df_old, df_new], ignore_index=True)
        else:
            df_final = df_new

        # Try saving to MASTER_LOG
        df_final.to_excel(local_master, index=False)
    except PermissionError:
        # Fallback to temp dir
        fallback = os.path.join(tempfile.gettempdir(), "master_log.xlsx")
        try:
            df_final.to_excel(fallback, index=False)
            local_master = fallback
        except Exception as e:
            return (False, f"Failed to write master log even to fallback: {e}")
    except Exception as e:
        return (False, f"Failed to write master log: {e}")

    # Attempt GitHub push (best-effort) and return result
    success, msg = push_file_to_github(local_master, "master_log.xlsx")
    if success:
        return (True, "")
        #return (True, f"Master log written and uploaded. {msg}")
    else:
        # Return success with warning if local write succeeded but github failed
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
# Optionally save annexes uploaded by user
# ------------------------------------------------
def save_annexes(uploaded_files):
    saved = []
    for f in uploaded_files:
        try:
            out_path = os.path.join(ANNEX_DIR, f.name)
            with open(out_path, "wb") as out:
                out.write(f.getbuffer())
            # try to push to GitHub under annexes/
            gh_path = f"annexes/{f.name}"
            success, msg = push_file_to_github(out_path, gh_path)
            saved.append((f.name, True, msg if success else f"Saved locally, GH: {msg}"))
        except Exception as e:
            saved.append((f.name, False, f"Failed to save: {e}"))
    return saved

# ------------------------------------------------
# APP: Steps 1–9 (UI)
# ------------------------------------------------

# --- STEP 1 ---
if st.session_state.step == 1:
    st.title("Step 1 — Division Workplan Cover Page")
    division = st.text_input("Division Name", key="division")
    director = st.text_input("Director's Name", key="director")
    date_entry = st.date_input("Date of Workplan", key="date_entry")
    version = st.text_input("Version of Workplan", key="version")
    ftes = st.text_input("Divisional FTEs", key="ftes")
    financial = st.text_input("Divisional Financial Resources", key="financial")
    signature = st.radio("Director's Signature Provided?", ["Yes", "No"], key="signature")

    if st.button("Next", key="next_step_1"):
        st.session_state.submission["Cover"] = {
            "Division": division,
            "Director": director,
            "Date": str(date_entry),
            "Version": version,
            "FTEs": ftes,
            "Financial Resources": financial,
            "Director Signature": signature
        }
        next_step()

# --- STEP 2 ---
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
    selected_goals = st.multiselect("Select Strategic Goals", goals, key="selected_goals")

    if st.button("Next", key="next_step_2"):
        st.session_state.submission["Selected Goals"] = selected_goals
        st.session_state.submission["Aggregate Objectives"] = {}
        next_step()

# --- STEP 3 ---
if st.session_state.step == 3:
    st.title("Step 3 — Aggregate Divisional Objectives")
    df = pd.read_excel(ALIGNMENT_FILE)
    goal_to_agg = {}

    for g_idx, g in enumerate(st.session_state.submission.get("Selected Goals", [])):
        st.subheader(f"Strategic Goal: {g}")
        agg_list = df[df["strategic_goal"] == g]["aggregate_divisional_objectives"].dropna().unique().tolist()

        selected_agg = st.multiselect(f"Select Aggregate Objectives for {g}", agg_list, key=f"agg_{g_idx}")

        other_flag = st.checkbox(f"Add custom aggregate objectives for {g}?", key=f"other_flag_{g_idx}")
        custom_items = []
        if other_flag:
            num = st.number_input(f"How many custom aggregate objectives for {g}?", 1, 10, key=f"num_custom_{g_idx}")
            for i in range(num):
                custom_items.append(st.text_input(f"Custom Objective {i+1} for {g}", key=f"custom_{g_idx}_{i}"))

        goal_to_agg[g] = selected_agg + custom_items

    if st.button("Next", key="next_step_3"):
        st.session_state.submission["Aggregate Objectives"] = goal_to_agg
        st.session_state.submission["Specific Objectives"] = {}
        next_step()

# --- STEP 4 ---
if st.session_state.step == 4:
    st.title("Step 4 — Specific Divisional Objectives")
    spec_map = {}

    for g_idx, (g, agg_list) in enumerate(st.session_state.submission.get("Aggregate Objectives", {}).items()):
        st.subheader(f"Strategic Goal: {g}")
        for a_idx, agg in enumerate(agg_list):
            st.markdown(f"### Aggregate Objective: {agg}")
            key_radio = f"radio_{g_idx}_{a_idx}_{agg}".replace(" ", "_")
            choice = st.radio(f"Add specific objectives for '{agg}'?", ["No", "Yes"], key=key_radio)

            key_text = f"spec_{g_idx}_{a_idx}_{agg}".replace(" ", "_")
            if choice == "Yes":
                entries = st.text_area(f"Enter one per line:", key=key_text)
                specific_list = [x.strip() for x in entries.split("\n") if x.strip()]
                if not specific_list:
                    specific_list = ["None provided"]
            else:
                specific_list = ["None"]

            spec_map[(g, agg)] = specific_list

    if st.button("Next", key="next_step_4"):
        st.session_state.submission["Specific Objectives"] = spec_map
        st.session_state.submission["Activities"] = {}
        next_step()

# --- STEP 5 ---
if st.session_state.step == 5:
    st.title("Step 5 — Activities & Results")
    act_map = {}

    for g_idx, (g, agg_list) in enumerate(st.session_state.submission.get("Aggregate Objectives", {}).items()):
        st.subheader(f"Strategic Goal: {g}")
        for a_idx, agg in enumerate(agg_list):
            st.markdown(f"### Aggregate Objective: {agg}")
            key_act = f"act_{g_idx}_{a_idx}"
            key_res = f"res_{g_idx}_{a_idx}"

            activities = st.text_area("Planned activities (one per line)", key=key_act)
            results = st.text_area("Expected results (one per line)", key=key_res)

            act_map[(g, agg)] = {
                "activities": [x.strip() for x in activities.split("\n") if x.strip()],
                "results": [x.strip() for x in results.split("\n") if x.strip()]
            }

    if st.button("Next", key="next_step_5"):
        st.session_state.submission["Activities"] = act_map
        st.session_state.submission["Goal Metrics"] = {}
        next_step()

# --- STEP 6 ---
if st.session_state.step == 6:
    st.title("Step 6 — Metrics per Strategic Goal")
    metrics = {}

    for g_idx, g in enumerate(st.session_state.submission.get("Selected Goals", [])):
        st.subheader(f"Strategic Goal: {g}")
        fte = st.text_input(f"FTEs for {g}", key=f"fte_{g_idx}")
        fin = st.text_input(f"Financial Resources for {g}", key=f"fin_{g_idx}")
        kpi = st.text_area(f"Key Performance Indicators for {g}", key=f"kpi_{g_idx}")
        other = st.text_area(f"Other Metrics for {g}", key=f"other_{g_idx}")
        metrics[g] = {"FTEs": fte, "Financial Resources": fin, "KPIs": kpi, "Other Metrics": other}

    if st.button("Next", key="next_step_6"):
        st.session_state.submission["Goal Metrics"] = metrics
        st.session_state.submission["Objective/Result Metrics"] = {}
        next_step()

# --- STEP 7 ---
if st.session_state.step == 7:
    st.title("Step 7 — Optional Objective/Result Metrics")
    opt = st.radio("Would you like to report metrics for objectives/results?", ["No", "Yes"], key="opt_obj_res")
    obj_res_metrics = {}

    if opt == "Yes":
        for g_idx, ((g, agg), spec_list) in enumerate(st.session_state.submission.get("Specific Objectives", {}).items()):
            st.subheader(f"Aggregate Objective: {agg}")
            for s_idx, item in enumerate(spec_list):
                st.markdown(f"### Item: {item}")
                fte = st.text_input(f"FTEs for '{item}'", key=f"obj_fte_{g_idx}_{s_idx}")
                fin = st.text_input(f"Financial Resources for '{item}'", key=f"obj_fin_{g_idx}_{s_idx}")
                kpi = st.text_area(f"KPIs for '{item}'", key=f"obj_kpi_{g_idx}_{s_idx}")
                other = st.text_area(f"Other Metrics for '{item}'", key=f"obj_other_{g_idx}_{s_idx}")
                obj_res_metrics[(g, agg, item)] = {"FTEs": fte, "Financial Resources": fin, "KPIs": kpi, "Other Metrics": other}

    if st.button("Next", key="next_step_7"):
        st.session_state.submission["Objective/Result Metrics"] = obj_res_metrics
        next_step()

# --- STEP 8 ---
if st.session_state.step == 8:
    st.title("Step 8 — Additional Information")
    additional_info = {
        "Partnerships": st.text_area("Partnerships"),
        "Events": st.text_area("Events"),
        "Knowledge Products": st.text_area("Knowledge Products"),
        "Knowledge Management": st.text_area("Knowledge Management Practices"),
        "Cross-Divisional Initiatives": st.text_area("Cross-divisional initiatives"),
        "Projects/Networks": st.text_area("Projects or networks"),
        "Risks": st.text_area("Risks"),
        "Other Information": st.text_area("Other Information")
    }

    if st.button("Next", key="next_step_8"):
        st.session_state.submission["Additional"] = additional_info
        next_step()

# --- STEP 9 ---
if st.session_state.step == 9:
    st.title("Step 9 — Upload Annexes & Export")
    annexes = st.file_uploader("Upload annex files", accept_multiple_files=True, key="annex_uploader")
    st.session_state.submission["Annexes"] = annexes

    if st.button("Finish & Generate Report", key="next_step_9"):
        # Optionally save annexes
        annex_results = []
        if annexes:
            annex_results = save_annexes(annexes)

        try:
            filepath, filename, push_result = export_word(st.session_state.submission)
            if not filepath:
                st.error("Failed to generate Word document.")
            else:
                # st.success(f"Word report generated: {filename}")
                # Show GitHub push result
                gh_ok, gh_msg = push_result
                if gh_ok:
                    pass
                    # st.info(f"Uploaded to GitHub: {gh_msg}")
                else:
                    pass
                    # st.warning(f"GitHub upload: {gh_msg}")

                # Save to master log
                save_result, save_msg = save_to_master_excel({
                    "timestamp": datetime.now(),
                    "division": st.session_state.submission.get("Cover", {}).get("Division", "Unknown"),
                    "goals": ", ".join(st.session_state.submission.get("Selected Goals", [])),
                    "data": str(st.session_state.submission)
                })

                if save_result:
                    st.success(save_msg)
                else:
                    st.error(save_msg)

                # Provide download to user
                try:
                    with open(filepath, "rb") as f:
                        file_bytes = f.read()
                        st.download_button(
                            label="Download Word Report",
                            data=file_bytes,
                            file_name=filename,
                            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                            key="download_workplan"
                        )
                except Exception as e:
                    st.error(f"Failed to offer download: {e}")

                # Optionally show annex save results
                if annex_results:
                    st.write("Annex upload results:")
                    for name, ok, msg in annex_results:
                        if ok:
                            st.write(f"- {name}: saved. {msg}")
                        else:
                            st.write(f"- {name}: failed. {msg}")

        except Exception as e:
            st.error(f"Unexpected error when generating report: {e}")
            st.error(traceback.format_exc())
