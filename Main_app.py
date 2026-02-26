import time
import re
import io
from datetime import datetime, timedelta
import pandas as pd
import sqlalchemy
from sqlalchemy import text
import streamlit as st
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.enum.text import PP_ALIGN
import openpyxl
from openpyxl.styles import Alignment, Font, Border, Side

# --- 1. Basic Configuration & CSS ---
st.set_page_config(page_title="TSM Summary of Weekly Ship Reports", layout="wide")

st.markdown("""
    <style>
    .stButton>button { width: 100%; border-radius: 5px; height: 3em; }
    .stDownloadButton>button { width: 100%; border-radius: 5px; background-color: #004a99; color: white; }
    div.stButton > button[key^="import_"] {
        background-color: #f8f9fa !important;
        color: #004a99 !important;
        border: 1px solid #004a99 !important;
    }
    </style>
    """, unsafe_allow_html=True)

# Initialize Session State
if 'logged_in' not in st.session_state: st.session_state.logged_in = False
if 'username' not in st.session_state: st.session_state.username = None
if 'role' not in st.session_state: st.session_state.role = None
if 'ship_index' not in st.session_state: st.session_state.ship_index = 0
if 'drafts' not in st.session_state: st.session_state.drafts = {}
if 'editing_id' not in st.session_state: st.session_state.editing_id = None
if 'confirm_del_id' not in st.session_state: st.session_state.confirm_del_id = None

@st.cache_resource
def get_engine():
    return sqlalchemy.create_engine(st.secrets["postgres_url"])


# --- 2. Report Generation Tools ---

def generate_custom_excel(df):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Ship Report"

    font_yahei = Font(name='微软雅黑', size=10)
    font_yahei_bold = Font(name='微软雅黑', size=10, bold=True)
    thin_side = Side(style='thin', color='000000')
    black_border = Border(top=thin_side, left=thin_side, right=thin_side, bottom=thin_side)

    ws.merge_cells('A1:C1')
    ws['A1'] = f"Report Date: {datetime.now().strftime('%Y-%m-%d')}"
    ws['A1'].font = Font(name='微软雅黑', size=12, bold=True)
    ws['A1'].alignment = Alignment(horizontal='center', vertical='center')

    headers = ['Manager Name', 'Vessel Name', 'Issue']
    for col_num, header in enumerate(headers, 1):
        cell = ws.cell(row=2, column=col_num, value=header)
        cell.font = font_yahei_bold
        cell.alignment = Alignment(horizontal='center', vertical='center')
        cell.border = black_border

    def clean_and_reformat_issue(series):
        all_lines = []
        for content in series:
            if content:
                lines = str(content).split('\n')
                for line in lines:
                    clean_line = re.sub(r'^\d+[\.、\s]*', '', line.strip())
                    if clean_line:
                        all_lines.append(clean_line)
        if not all_lines: return ""
        return "\n".join([f"{i + 1}. {text}" for i, text in enumerate(all_lines)])

    df_grouped = df.groupby(['manager_name', 'ship_name'])['this_week_issue'].apply(
        clean_and_reformat_issue).reset_index()
    df_grouped = df_grouped.sort_values(by='manager_name')

    current_row = 3
    for manager, group in df_grouped.groupby('manager_name', sort=False):
        start_merge_row = current_row
        for _, row_data in group.iterrows():
            for col in [1, 2]:
                cell = ws.cell(row=current_row, column=col,
                               value=row_data['manager_name'] if col == 1 else row_data['ship_name'])
                cell.font = font_yahei
                cell.border = black_border
                cell.alignment = Alignment(horizontal='center', vertical='center')

            cell_c = ws.cell(row=current_row, column=3, value=row_data['this_week_issue'])
            cell_c.font = font_yahei
            cell_c.border = black_border
            cell_c.alignment = Alignment(wrap_text=True, horizontal='left', vertical='center')
            current_row += 1

        if len(group) > 1:
            ws.merge_cells(start_row=start_merge_row, start_column=1, end_row=current_row - 1, end_column=1)
            for r in range(start_merge_row, current_row):
                ws.cell(row=r, column=1).border = black_border

    ws.column_dimensions['A'].width = 20
    ws.column_dimensions['B'].width = 25
    ws.column_dimensions['C'].width = 70

    output = io.BytesIO()
    wb.save(output)
    return output.getvalue()


def create_ppt_report(df, start_date, end_date):
    prs = Presentation()

    slide_layout_title = prs.slide_layouts[0]
    slide = prs.slides.add_slide(slide_layout_title)

    try:
        slide.shapes.add_picture("TSM_Logo.png", left=Inches(4.25), top=Inches(1.2), width=Inches(1.8))
    except:
        pass

    title = slide.shapes.title
    subtitle = slide.placeholders[1]

    title.top = Inches(3.5)
    title.text = "TSM Summary of Weekly Ship Reports"

    current_date = datetime.now().strftime('%Y-%m-%d')
    subtitle.text = f"Creation Date: {current_date}"
    subtitle.top = Inches(4.5)

    def clean_and_reformat_ppt(series):
        all_lines = []
        for content in series:
            if content:
                lines = str(content).split('\n')
                for line in lines:
                    clean_line = re.sub(r'^\d+[\.、\s]*', '', line.strip())
                    if clean_line: all_lines.append(clean_line)
        if not all_lines: return ""
        return "\n".join([f"{i + 1}. {text}" for i, text in enumerate(all_lines)])

    df_ppt = df.groupby(['manager_name', 'ship_name'], sort=False)['this_week_issue'].apply(
        clean_and_reformat_ppt).reset_index()
    df_ppt = df_ppt.sort_values(by=['manager_name', 'ship_name'])

    for _, row in df_ppt.iterrows():
        manager = row['manager_name']
        ship = row['ship_name']
        issue_content = row['this_week_issue']

        slide_layout_content = prs.slide_layouts[1]
        slide = prs.slides.add_slide(slide_layout_content)

        slide.shapes.title.text = f" {ship} ({manager})"
        tf = slide.placeholders[1].text_frame
        tf.word_wrap = True

        if issue_content:
            for line in issue_content.split('\n'):
                p = tf.add_paragraph()
                p.text = line
                p.level = 0
                p.font.size = Pt(24)
                p.font.name = '微软雅黑'

    slide_layout_blank = prs.slide_layouts[6]
    end_slide = prs.slides.add_slide(slide_layout_blank)
    tx_box = end_slide.shapes.add_textbox(Inches(3), Inches(3.5), Inches(4), Inches(2))
    tf_end = tx_box.text_frame
    tf_end.text = "Thank you for watching."
    p_end = tf_end.paragraphs[0]
    p_end.alignment = PP_ALIGN.CENTER
    p_end.font.size = Pt(44)
    p_end.font.bold = True
    p_end.font.name = '微软雅黑'

    ppt_out = io.BytesIO()
    prs.save(ppt_out)
    ppt_out.seek(0)
    return ppt_out


# --- 3. Login UI ---
def login_ui():
    _, col_logo, _ = st.columns([2, 1, 2])
    with col_logo:
        try:
            st.image("TSM_Logo.png", use_container_width=True)
        except:
            pass
    st.markdown("<h2 style='text-align: center;'>TSM Ship Information Aggregation System</h2>", unsafe_allow_html=True)
    with st.form("login_form"):
        u_in = st.text_input("User Name")
        p_in = st.text_input("Password", type="password")
        if st.form_submit_button("Log In", use_container_width=True):
            with get_engine().connect() as conn:
                res = conn.execute(text("SELECT role FROM users WHERE username = :u AND password = :p"),
                                   {"u": u_in, "p": p_in}).fetchone()
                if res:
                    st.session_state.clear()
                    st.session_state.logged_in = True
                    st.session_state.username = u_in
                    st.session_state.role = res[0]
                    st.rerun()
                else:
                    st.error("Verification Failed. Please check your credentials.")

if not st.session_state.logged_in:
    login_ui()
    st.stop()


# --- 4. Sidebar ---
st.sidebar.title(f"User: {st.session_state.username}")
if st.sidebar.button("Log Out Safely"):
    st.session_state.clear()
    st.rerun()


# --- 5. Data Retrieval & Tabs ---
@st.cache_data(ttl=60)
def get_ships_list(role, user):
    with get_engine().connect() as conn:
        if role == 'admin':
            return pd.read_sql_query(text("SELECT id, ship_name FROM ships ORDER BY ship_name"), conn)
        return pd.read_sql_query(text("SELECT id, ship_name FROM ships WHERE manager_name = :u ORDER BY ship_name"),
                                 conn, params={"u": user})

ships_df = get_ships_list(st.session_state.role, st.session_state.username)

t_labels = ["Filling & Querying"]
if st.session_state.role == 'admin': t_labels.append("Admin Console")
t_labels.append("Report Center")
tabs = st.tabs(t_labels)

# --- Tab 1: Operations ---
with tabs[0]:
    if ships_df.empty:
        st.warning("No vessels have been assigned yet.")
    else:
        selected_ship = st.selectbox("Select a vessel", ships_df['ship_name'].tolist(), index=st.session_state.ship_index)
        ship_id = int(ships_df[ships_df['ship_name'] == selected_ship]['id'].iloc[0])
        st.divider()

        col_hist, col_input = st.columns([1.2, 1])

        # A. History Record
        with col_hist:
            st.subheader("History Record")

            if st.session_state.confirm_del_id:
                st.warning(f"Prepare to delete the record. (ID: {st.session_state.confirm_del_id})")
                d_col1, d_col2 = st.columns(2)
                with d_col1:
                    if st.button("Confirm deletion", key="confirm_real_del"):
                        with get_engine().begin() as conn:
                            conn.execute(text("DELETE FROM reports WHERE id = :id"),
                                         {"id": st.session_state.confirm_del_id})
                        st.session_state.confirm_del_id = None
                        st.success("The record has been permanently deleted.")
                        time.sleep(1)
                        st.rerun()
                with d_col2:
                    if st.button("Cancel Delete", key="cancel_real_del"):
                        st.session_state.confirm_del_id = None
                        st.rerun()
                st.divider()

            with get_engine().connect() as conn:
                h_df = pd.read_sql_query(text(
                    "SELECT id, report_date, this_week_issue, remarks FROM reports WHERE ship_id = :sid AND is_deleted_by_user = FALSE ORDER BY report_date DESC LIMIT 10"),
                    conn, params={"sid": ship_id})

            if not h_df.empty:
                for idx, row in h_df.iterrows():
                    is_editing = st.session_state.editing_id == row['id']
                    with st.expander(f"{row['report_date']} Content Details", expanded=is_editing):
                        if is_editing:
                            new_val = st.text_area("Modifications:", value=row['this_week_issue'], key=f"ed_{row['id']}")
                            if st.button("Save Updates", key=f"save_{row['id']}"):
                                with get_engine().begin() as conn:
                                    conn.execute(text("UPDATE reports SET this_week_issue = :t WHERE id = :id"),
                                                 {"t": new_val, "id": row['id']})
                                st.session_state.editing_id = None
                                st.rerun()
                        else:
                            raw_content = row['this_week_issue']
                            clean_lines = [re.sub(r'^\d+[\.、\s]*', '', l.strip()) for l in raw_content.split('\n') if l.strip()]
                            st.text("\n".join([f"{i + 1}. {text}" for i, text in enumerate(clean_lines)]))

                            cb1, cb2 = st.columns(2)
                            with cb1:
                                if st.button("Modify", key=f"eb_{row['id']}"):
                                    st.session_state.editing_id = row['id']
                                    st.rerun()
                            with cb2:
                                if st.button("Delete", key=f"db_{row['id']}"):
                                    st.session_state.confirm_del_id = row['id']
                                    st.rerun()
            else:
                st.info("The vessel has no history.")

        # B. Data Input (Indentation fixed to align perfectly with col_hist)
        with col_input:
            st.subheader(f"Fill in - {selected_ship}")

            def handle_submit(sid):
                latest_issue = st.session_state.get(f"ta_{sid}", "")
                latest_remark = st.session_state.get(f"rem_{sid}", "")

                if latest_issue.strip():
                    with get_engine().begin() as conn:
                        conn.execute(text(
                            "INSERT INTO reports (ship_id, report_date, this_week_issue, remarks) VALUES (:sid, :dt, :iss, :rem)"),
                            {"sid": sid, "dt": datetime.now().date(), "iss": latest_issue, "rem": latest_remark})

                    st.session_state[f"ta_{sid}"] = ""
                    st.session_state[f"rem_{sid}"] = ""
                    st.session_state.drafts[sid] = ""
                    st.toast(f"{selected_ship} Data submission successful!")

            if st.button("Import information about the ship from last week.", key=f"import_{ship_id}", use_container_width=True):
                with get_engine().connect() as conn:
                    last_rec = conn.execute(text(
                        "SELECT this_week_issue FROM reports WHERE ship_id = :sid AND is_deleted_by_user = FALSE ORDER BY report_date DESC LIMIT 1"),
                        {"sid": ship_id}).fetchone()
                    if last_rec:
                        st.session_state[f"ta_{ship_id}"] = last_rec[0]
                        st.success("The latest content has been loaded; you can continue editing.")
                        time.sleep(0.5)
                        st.rerun()
                    else:
                        st.warning("No history found.")

            if f"ta_{ship_id}" not in st.session_state:
                st.session_state[f"ta_{ship_id}"] = ""
            if f"rem_{ship_id}" not in st.session_state:
                st.session_state[f"rem_{ship_id}"] = ""

            st.text_area("This week's issue (one line per issue):", height=350, key=f"ta_{ship_id}")
            st.text_input("Remarks (optional)", key=f"rem_{ship_id}")

            st.button(
                "Submit Information",
                use_container_width=True,
                on_click=handle_submit,
                args=(ship_id,)
            )

        st.divider()
        n1, _, n3 = st.columns([1, 4, 1])
        with n1:
            if st.button("Previous"):
                st.session_state.ship_index = (st.session_state.ship_index - 1) % len(ships_df)
                st.rerun()
        with n3:
            if st.button("Next"):
                st.session_state.ship_index = (st.session_state.ship_index + 1) % len(ships_df)
                st.rerun()

# --- Tab 2: Admin Console ---
if st.session_state.role == 'admin':
    with tabs[1]:
        st.subheader("Global Management View")

        m_df = pd.read_sql_query(text("""
            SELECT r.id, s.manager_name as "Manager", s.ship_name as "Vessel", 
                   r.report_date as "Date", r.this_week_issue as "Content"
            FROM reports r JOIN ships s ON r.ship_id = s.id 
            ORDER BY r.report_date DESC
        """), get_engine())

        if not m_df.empty:
            m_df.insert(0, "Select", False)
            ed_df = st.data_editor(m_df, hide_index=True, use_container_width=True)

            to_del = ed_df[ed_df["Select"] == True]["id"].tolist()
            if to_del and st.button("Delete Selected Records"):
                with get_engine().begin() as conn:
                    conn.execute(text("DELETE FROM reports WHERE id IN :ids"), {"ids": tuple(to_del)})
                st.success(f"Successfully deleted {len(to_del)} records.")
                st.rerun()
        else:
            st.info("No global report data available.")

# --- Tab 3: Report Center ---
with tabs[-1]:
    st.subheader("Automated Information Preview & Export")

    c1, c2 = st.columns(2)
    with c1:
        start_d = st.date_input("Start Date", value=datetime.now() - timedelta(days=7), key="rep_start")
    with c2:
        end_d = st.date_input("End Date", value=datetime.now(), key="rep_end")

    with get_engine().connect() as conn:
        query = """
                SELECT r.report_date as "Date", s.ship_name as "Vessel", 
                       r.this_week_issue as "Report Content", s.manager_name as "Manager"
                FROM reports r 
                JOIN ships s ON r.ship_id = s.id
                WHERE r.report_date BETWEEN :s AND :e 
                AND r.is_deleted_by_user = FALSE
            """
        params = {"s": start_d, "e": end_d}

        if st.session_state.role != 'admin':
            query += " AND s.manager_name = :u"
            params["u"] = st.session_state.username

        query += " ORDER BY r.report_date DESC"
        export_df = pd.read_sql_query(text(query), conn, params=params)

    st.write("---")
    if st.button("Search and preview records within the selected date", use_container_width=True):
        if not export_df.empty:
            st.success(f"Found {len(export_df)} records.")

            preview_df = export_df.copy()

            def preview_clean(text):
                lines = [re.sub(r'^\d+[\.、\s]*', '', l.strip()) for l in str(text).split('\n') if l.strip()]
                return "\n".join([f"{i + 1}. {t}" for i, t in enumerate(lines)])

            preview_df["Report Content"] = preview_df["Report Content"].apply(preview_clean)

            st.dataframe(
                preview_df,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Report Content": st.column_config.TextColumn("Detailed Information (Automatically Numbered)", width="large"),
                    "Date": st.column_config.DateColumn("Date")
                }
            )
        else:
            st.warning("No reporting records were found within that date range.")

    st.write("---")

    if not export_df.empty:
        excel_prep_df = export_df.rename(columns={
            "Manager": "manager_name",
            "Vessel": "ship_name",
            "Report Content": "this_week_issue"
        })

        bc1, bc2 = st.columns(2)
        with bc1:
            excel_bin = generate_custom_excel(excel_prep_df)
            st.download_button(
                label="Download Excel Report",
                data=excel_bin,
                file_name=f"Trust_Ship_Report_{start_d}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )

        if st.session_state.role == 'admin':
            with bc2:
                if st.button("Generate PPT Summary Preview", use_container_width=True):
                    ppt_bin = create_ppt_report(excel_prep_df, start_d, end_d)

                    st.download_button(
                        label="Click to Download PPT File",
                        data=ppt_bin,
                        file_name=f"Ship_Meeting_{start_d}.pptx",
                        mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                        use_container_width=True
                    )
    else:
        st.info("There is currently no data available for you to view within this date range.")