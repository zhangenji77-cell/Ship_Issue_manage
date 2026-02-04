import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import sqlalchemy
from sqlalchemy import text
import io
import time
import openpyxl
from openpyxl.utils.dataframe import dataframe_to_rows
from pptx import Presentation

# --- 1. 基础配置与样式 ---
st.set_page_config(page_title="Trust Ship 船舶管理系统", layout="wide")

st.markdown("""
    <style>
    .stButton>button { width: 100%; border-radius: 5px; height: 3em; }
    .stDownloadButton>button { width: 100%; border-radius: 5px; background-color: #004a99; color: white; }
    /* 导入按钮样式：淡灰色背景，蓝色文字 */
    div.stButton > button:first-child[key^="import_"] {
        background-color: #f8f9fa;
        color: #004a99;
        border: 1px solid #004a99;
        font-weight: bold;
    }
    </style>
    """, unsafe_allow_html=True)

if 'logged_in' not in st.session_state: st.session_state.logged_in = False
if 'username' not in st.session_state: st.session_state.username = None
if 'role' not in st.session_state: st.session_state.role = None
if 'ship_index' not in st.session_state: st.session_state.ship_index = 0
if 'drafts' not in st.session_state: st.session_state.drafts = {}
if 'confirm_del_id' not in st.session_state: st.session_state.confirm_del_id = None


@st.cache_resource
def get_engine():
    return sqlalchemy.create_engine(st.secrets["postgres_url"])


# --- 2. 报表导出逻辑 (匹配上传的模版) ---

def generate_excel_with_template(df):
    try:
        # 1. 加载服务器上的模版文件
        wb = openpyxl.load_workbook("导出excel模版.xlsx")
        sheet = wb.active

        # 2. 定位写入位置：根据您的模版，从第 2 行开始填入数据
        start_row = 2

        # 3. 整理列顺序以匹配模版：日期(A), 船名(B), 问题内容(C), 备注(D), 负责人(E)
        # 假设原始 df 的列顺序正是：report_date, ship_name, this_week_issue, remarks, manager_name
        for r_idx, row in enumerate(dataframe_to_rows(df, index=False, header=False), start_row):
            for c_idx, value in enumerate(row, 1):
                cell = sheet.cell(row=r_idx, column=c_idx, value=value)
                # 保持模版字体大小（可选）
                cell.font = openpyxl.styles.Font(size=10)

        output = io.BytesIO()
        wb.save(output)
        return output.getvalue()
    except Exception as e:
        st.error(f"Excel 模版写入失败: {e}")
        return None


def create_ppt_report(df, start_date, end_date):
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[0])
    slide.shapes.title.text = "Trust Ship 船舶周报汇总"
    slide.placeholders[1].text = f"周期: {start_date} ~ {end_date}"
    for ship_name, group in df.groupby('ship_name'):
        slide = prs.slides.add_slide(prs.slide_layouts[1])
        slide.shapes.title.text = f"船舶: {ship_name}"
        tf = slide.placeholders[1].text_frame
        for _, row in group.iterrows():
            p = tf.add_paragraph()
            p.text = f"• {row['report_date']}: {row['this_week_issue']}"
    ppt_output = io.BytesIO()
    prs.save(ppt_output)
    ppt_output.seek(0)
    return ppt_output


# --- 3. 登录界面 (Logo 仅在此显示且缩小) ---
def login_ui():
    _, col_logo, _ = st.columns([2, 1, 2])  # 比例 [2,1,2] 实现 Logo 缩小
    with col_logo:
        try:
            st.image("TSM_Logo.png", use_container_width=True)
        except:
            pass

    st.markdown("<h2 style='text-align: center;'>🚢 Trust Ship 系统登录</h2>", unsafe_allow_html=True)
    with st.form("login_form"):
        u_in = st.text_input("用户名")
        p_in = st.text_input("密码", type="password")
        if st.form_submit_button("立即进入系统", use_container_width=True):
            with get_engine().connect() as conn:
                res = conn.execute(text("SELECT role FROM users WHERE username = :u AND password = :p"),
                                   {"u": u_in, "p": p_in}).fetchone()
                if res:
                    st.session_state.logged_in = True
                    st.session_state.username = u_in
                    st.session_state.role = res[0]
                    st.rerun()
                else:
                    st.error("❌ 身份验证失败")


if not st.session_state.logged_in:
    login_ui()
    st.stop()

# --- 4. 侧边栏 (登录成功后不显示 Logo) ---
st.sidebar.title(f"{st.session_state.username}")
if st.sidebar.button("安全退出"):
    st.session_state.clear();
    st.rerun()


# --- 5. 获取数据与选项卡 ---
@st.cache_data(ttl=60)
def get_ships_list(role, user):
    with get_engine().connect() as conn:
        if role == 'admin':
            return pd.read_sql_query(text("SELECT id, ship_name FROM ships ORDER BY ship_name"), conn)
        return pd.read_sql_query(text("SELECT id, ship_name FROM ships WHERE manager_name = :u ORDER BY ship_name"),
                                 conn, params={"u": user})


ships_df = get_ships_list(st.session_state.role, st.session_state.username)
tabs = st.tabs(["填报与历史", "报表中心"])
if st.session_state.role == 'admin':
    tabs = st.tabs(["填报与历史", "管理控制台", "报表中心"])

# --- Tab 1: 业务填报 ---
with tabs[0]:
    if ships_df.empty:
        st.warning("⚠️ 暂无分配船舶。")
    else:
        selected_ship = st.selectbox("选择船舶", ships_df['ship_name'].tolist(), index=st.session_state.ship_index)
        ship_id = int(ships_df[ships_df['ship_name'] == selected_ship]['id'].iloc[0])
        st.divider()
        col_l, col_r = st.columns([1.2, 1])

        with col_l:
            st.subheader("历史记录")
            with get_engine().connect() as conn:
                h_df = pd.read_sql_query(text(
                    "SELECT id, report_date, this_week_issue FROM reports WHERE ship_id = :sid AND is_deleted_by_user = FALSE ORDER BY report_date DESC LIMIT 10"),
                                         conn, params={"sid": ship_id})
            if not h_df.empty:
                for idx, row in h_df.iterrows():
                    with st.expander(f"{row['report_date']}"):
                        st.text(row['this_week_issue'])
                        if st.button("删除记录", key=f"db_{row['id']}"): st.session_state.confirm_del_id = row[
                            'id']; st.rerun()
            else:
                st.info("暂无记录。")

        with col_r:
            st.subheader(f"填报 - {selected_ship}")

            # ✅ 功能：一键导入上周内容
            if st.button("一键导入该船历史最新内容", key=f"import_{ship_id}", use_container_width=True):
                with get_engine().connect() as conn:
                    last_rec = conn.execute(text(
                        "SELECT this_week_issue FROM reports WHERE ship_id = :sid AND is_deleted_by_user = FALSE ORDER BY report_date DESC LIMIT 1).fetchone()"),
                                            {"sid": ship_id}).fetchone()
                    if last_rec:
                        st.session_state.drafts[ship_id] = last_rec[0]
                        st.success("已载入最近一次内容。")
                        time.sleep(0.5);
                        st.rerun()
                    else:
                        st.warning("未找到历史记录。")

            if ship_id not in st.session_state.drafts: st.session_state.drafts[ship_id] = ""
            issue_v = st.text_area("内容 (分条换行):", value=st.session_state.drafts[ship_id], height=350,
                                   key=f"ta_{ship_id}")
            st.session_state.drafts[ship_id] = issue_v
            if st.button("提交本周填报", use_container_width=True):
                if issue_v.strip():
                    with get_engine().begin() as conn:
                        conn.execute(text(
                            "INSERT INTO reports (ship_id, report_date, this_week_issue) VALUES (:sid, :dt, :iss)"),
                                     {"sid": ship_id, "dt": datetime.now().date(), "iss": issue_v})
                    st.success("提交成功！");
                    st.session_state.drafts[ship_id] = "";
                    st.rerun()

        # 底部切船
        st.divider()
        n1, n2, n3 = st.columns([1, 4, 1])
        with n1:
            if st.button("⬅️ 上一艘"): st.session_state.ship_index = (st.session_state.ship_index - 1) % len(
                ships_df); st.rerun()
        with n3:
            if st.button("下一艘 ➡️"): st.session_state.ship_index = (st.session_state.ship_index + 1) % len(
                ships_df); st.rerun()

# --- Tab 最后: 报表中心 (使用模版) ---
with tabs[-1]:
    st.subheader("自动化报表导出")
    c1, c2 = st.columns(2)
    with c1:
        start_d = st.date_input("起始日期", value=datetime.now() - timedelta(days=7))
    with c2:
        end_d = st.date_input("截止日期", value=datetime.now())

    with get_engine().connect() as conn:
        # SQL 查询字段顺序必须与模版列一致：日期, 船名, 问题, 备注, 负责人
        export_df = pd.read_sql_query(text("""
            SELECT r.report_date, s.ship_name, r.this_week_issue, r.remarks, s.manager_name
            FROM reports r JOIN ships s ON r.ship_id = s.id
            WHERE r.report_date BETWEEN :s AND :e AND r.is_deleted_by_user = FALSE
            ORDER BY r.report_date DESC
        """), conn, params={"s": start_d, "e": end_d})

    if not export_df.empty:
        b_c1, b_c2 = st.columns(2)
        with b_c1:
            # ✅ 调用模版生成 Excel
            excel_bin = generate_excel_with_template(export_df)
            if excel_bin:
                st.download_button("下载样式 Excel", excel_bin, f"Ship_Report_{start_d}.xlsx",
                                   "application/vnd.ms-excel")
        with b_c2:
            if st.session_state.role == 'admin':
                if st.button("生成 PPT 汇总"):
                    ppt_bin = create_ppt_report(export_df, start_d, end_d)
                    st.download_button("点击下载 PPT", ppt_bin, f"Meeting_{start_d}.pptx")