import streamlit as st
import pandas as pd
import os
from datetime import datetime
from docx import Document

# ----------------------------
# CONFIG
# ----------------------------
ALIGNMENT_FILE = "strategic_alignment.xlsx"
MASTER_LOG = "master_log.xlsx"

# Initialize session state
if "step" not in st.session_state:
    st.session_state.step = 1
if "submission" not in st.session_state:
    st.session_state.submission = {}

# ----------------------------
# HELPER FUNCTIONS
# ----------------------------
def next_step():
    st.session_state.step += 1

def save_to_master_excel(row_dict):
    if os.path.exists(MASTER_LOG):
        df_log = pd.read_excel(MASTER_LOG)
        df_new = pd.DataFrame([row_dict])
        df_final = pd.concat([df_log, df_new], ignore_index=True)
    else:
        df_final = pd.DataFrame([row_dict])
    df_final.to_excel(MASTER_LOG, index=False)

def export_word(summary_dict):
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
    doc.save(filename)
    return filename

# ----------------------------
# STEP 1 — Division Cover Page
# ----------------------------
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

# ----------------------------
# STEP 2 — Strategic Goals
# ----------------------------
if st.session_state.step == 2:
    st.title("Step 2 — Select Strategic Goals")
    df = pd.read_excel(ALIGNMENT_FILE)
    goals = sorted(df["strategic_goal"].unique())
    selected_goals = st.multiselect("Select Strategic Goals", goals, key="selected_goals")

    if st.button("Next", key="next_step_2"):
        st.session_state.submission["Selected Goals"] = selected_goals
        st.session_state.submission["Aggregate Objectives"] = {}
        next_step()

# ----------------------------
# STEP 3 — Aggregate Objectives + Other
# ----------------------------
if st.session_state.step == 3:
    st.title("Step 3 — Aggregate Divisional Objectives Per Strategic Goal")
    df = pd.read_excel(ALIGNMENT_FILE)
    goal_to_agg = {}

    for g_idx, g in enumerate(st.session_state.submission["Selected Goals"]):
        st.subheader(f"Strategic Goal: {g}")
        agg_list = df[df["strategic_goal"] == g]["aggregate_divisional_objectives"].unique().tolist()

        selected_agg = st.multiselect(f"Select Aggregate Objectives for {g}", agg_list, key=f"agg_{g_idx}")
        
        # Custom 'Other' objectives
        other_flag = st.checkbox(f"Add custom aggregate objectives for {g}?", key=f"other_flag_{g_idx}")
        custom_items = []
        if other_flag:
            num = st.number_input(f"How many custom aggregate objectives for {g}?", min_value=1, step=1, key=f"num_custom_{g_idx}")
            for i in range(num):
                custom_items.append(st.text_input(f"Custom Objective {i+1} for {g}", key=f"custom_{g_idx}_{i}"))

        goal_to_agg[g] = selected_agg + custom_items

    if st.button("Next", key="next_step_3"):
        st.session_state.submission["Aggregate Objectives"] = goal_to_agg
        st.session_state.submission["Specific Objectives"] = {}
        next_step()

# ----------------------------
# STEP 4 — Specific Divisional Objectives
# ----------------------------
if st.session_state.step == 4:
    st.title("Step 4 — Specific Divisional Objectives (Optional)")
    spec_map = {}

    for g_idx, (g, agg_list) in enumerate(st.session_state.submission["Aggregate Objectives"].items()):
        st.subheader(f"Strategic Goal: {g}")
        for a_idx, agg in enumerate(agg_list):
            st.markdown(f"### Aggregate Objective: {agg}")

            key_radio = f"radio_{g_idx}_{a_idx}_{agg}".replace(" ", "_").replace("/", "_")
            choice = st.radio(
                f"Would you like to enter specific divisional objectives for: '{agg}'?",
                ["No", "Yes"],
                key=key_radio
            )

            key_text = f"spec_{g_idx}_{a_idx}_{agg}".replace(" ", "_").replace("/", "_")
            if choice == "Yes":
                entries = st.text_area(f"Enter specific objectives (one per line) for '{agg}':", key=key_text)
                specific_list = [x.strip() for x in entries.split("\n") if x.strip()]
                if len(specific_list) == 0:
                    specific_list = ["None provided"]
            else:
                specific_list = ["None"]

            spec_map[(g, agg)] = specific_list

    if st.button("Next", key="next_step_4"):
        st.session_state.submission["Specific Objectives"] = spec_map
        st.session_state.submission["Activities"] = {}
        next_step()

# ----------------------------
# STEP 5 — Activities & Results
# ----------------------------
if st.session_state.step == 5:
    st.title("Step 5 — Activities and Expected Results")
    act_map = {}
    for g_idx, (g, agg_list) in enumerate(st.session_state.submission["Aggregate Objectives"].items()):
        st.subheader(f"Strategic Goal: {g}")
        for a_idx, agg in enumerate(agg_list):
            st.markdown(f"### Aggregate Objective: {agg}")
            key_act = f"act_{g_idx}_{a_idx}".replace(" ", "_")
            key_res = f"res_{g_idx}_{a_idx}".replace(" ", "_")
            activities = st.text_area(f"List planned activities (one per line) for '{agg}':", key=key_act)
            results = st.text_area(f"List expected results (one per line) for '{agg}':", key=key_res)

            act_map[(g, agg)] = {
                "activities": [x.strip() for x in activities.split("\n") if x.strip()],
                "results": [x.strip() for x in results.split("\n") if x.strip()]
            }

    if st.button("Next", key="next_step_5"):
        st.session_state.submission["Activities"] = act_map
        st.session_state.submission["Goal Metrics"] = {}
        next_step()

# ----------------------------
# STEP 6 — Metrics per Strategic Goal
# ----------------------------
if st.session_state.step == 6:
    st.title("Step 6 — Metrics for Strategic Goals")
    metrics = {}
    for g_idx, g in enumerate(st.session_state.submission["Selected Goals"]):
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

# ----------------------------
# STEP 7 — Optional Objective/Result Metrics
# ----------------------------
if st.session_state.step == 7:
    st.title("Step 7 — Objective and Result Metrics (Optional)")
    opt = st.radio("Would you like to report metrics for objectives and results?", ["No", "Yes"], key="opt_obj_res")
    obj_res_metrics = {}

    if opt == "Yes":
        for g_idx, ((g, agg), spec_list) in enumerate(st.session_state.submission["Specific Objectives"].items()):
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

# ----------------------------
# STEP 8 — Additional Information
# ----------------------------
if st.session_state.step == 8:
    st.title("Step 8 — Additional Information")
    additional_info = {
        "Partnerships": st.text_area("Partnerships", key="add_partnerships"),
        "Events": st.text_area("Events", key="add_events"),
        "Knowledge Products": st.text_area("Knowledge Products", key="add_products"),
        "Knowledge Management": st.text_area("Knowledge Management Practices", key="add_km"),
        "Cross-Divisional Initiatives": st.text_area("Participation in cross-divisional initiatives", key="add_cross"),
        "Projects/Networks": st.text_area("Projects or Networks", key="add_projects"),
        "Risks": st.text_area("Risks", key="add_risks"),
        "Other Information": st.text_area("Other Information", key="add_other")
    }
    if st.button("Next", key="next_step_8"):
        st.session_state.submission["Additional"] = additional_info
        next_step()

# ----------------------------
# STEP 9 — Annex Upload + Export
# ----------------------------
if st.session_state.step == 9:
    st.title("Step 9 — Upload Annexes")
    annexes = st.file_uploader("Upload annex files", accept_multiple_files=True, key="annex_upload")
    st.session_state.submission["Annexes"] = annexes

    if st.button("Finish and Generate Report", key="finish"):
        filename = export_word(st.session_state.submission)
        st.success(f"Word report generated: {filename}")

        save_to_master_excel({
            "timestamp": datetime.now(),
            "division": st.session_state.submission["Cover"]["Division"],
            "goals": ", ".join(st.session_state.submission["Selected Goals"]),
            "data": str(st.session_state.submission)
        })

        st.write("Submission saved to master_log.xlsx")
        st.download_button("Download Workplan Document", open(filename, "rb"), file_name=filename)
