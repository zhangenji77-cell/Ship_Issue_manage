
import time
from pptx import Presentation
import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import sqlalchemy
from sqlalchemy import text
import io
import openpyxl
from openpyxl.styles import Alignment, Font, Border, Side  # <--- 必须有这一行

# --- 1. 基础配置与品牌样式 ---
st.set_page_config(page_title="Trust Ship 船舶管理系统", layout="wide")

# 注入 CSS：美化按钮并实现导入按钮的灰色样式
st.markdown("""
    <style>
    .stButton>button { width: 100%; border-radius: 5px; height: 3em; }
    .stDownloadButton>button { width: 100%; border-radius: 5px; background-color: #004a99; color: white; }
    /* 导入按钮专属样式 */
    div.stButton > button[key^="import_"] {
        background-color: #f8f9fa !important;
        color: #004a99 !important;
        border: 1px solid #004a99 !important;
    }
    </style>
    """, unsafe_allow_html=True)

# 初始化 Session 状态
if 'logged_in' not in st.session_state: st.session_state.logged_in = False
if 'username' not in st.session_state: st.session_state.username = None
if 'role' not in st.session_state: st.session_state.role = None
if 'ship_index' not in st.session_state: st.session_state.ship_index = 0
if 'drafts' not in st.session_state: st.session_state.drafts = {}
if 'editing_id' not in st.session_state: st.session_state.editing_id = None
if 'confirm_del_id' not in st.session_state: st.session_state.confirm_del_id = None


@st.cache_resource
def get_engine():
    # 从 st.secrets 获取数据库连接
    return sqlalchemy.create_engine(st.secrets["postgres_url"])


# --- 2. 报表工具逻辑 ---

# --- 2. 报表工具逻辑 ---

def generate_custom_excel(df):
    """
    生成带黑色边框、微软雅黑字体、全居中对齐的 Excel 报表
    """
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Ship Report"

    # 定义统一的字体：微软雅黑
    font_yahei = Font(name='微软雅黑', size=10)
    font_yahei_bold = Font(name='微软雅黑', size=10, bold=True)

    # 定义黑色细边框样式
    thin_black_side = Side(style='thin', color='000000')
    black_border = Border(top=thin_black_side, left=thin_black_side,
                          right=thin_black_side, bottom=thin_black_side)

    # --- 1. 第一行：Report Date (设置为居中) ---
    today_str = datetime.now().strftime('%Y-%m-%d')
    ws.merge_cells('A1:C1')
    ws['A1'] = f"Report Date: {today_str}"
    ws['A1'].font = Font(name='微软雅黑', size=12, bold=True)
    # ✅ 修改为 horizontal='center'
    ws['A1'].alignment = Alignment(horizontal='center', vertical='center')

    # --- 2. 第二行：表头 (微软雅黑 + 居中) ---
    headers = ['manager name', 'ship name', 'Issue']
    for col_num, header in enumerate(headers, 1):
        cell = ws.cell(row=2, column=col_num, value=header)
        cell.font = font_yahei_bold
        cell.alignment = Alignment(horizontal='center', vertical='center')
        cell.border = black_border

    # --- 3 & 4 & 5. 数据填充与合并 ---
    current_row = 3
    df = df.sort_values(by='manager_name')

    for manager, group in df.groupby('manager_name', sort=False):
        start_merge_row = current_row
        num_ships = len(group)

        for _, row_data in group.iterrows():
            # A列：管理人员
            cell_a = ws.cell(row=current_row, column=1, value=manager)
            cell_a.font = font_yahei
            cell_a.border = black_border
            cell_a.alignment = Alignment(horizontal='center', vertical='center')

            # B列：船舶名字
            cell_b = ws.cell(row=current_row, column=2, value=row_data['ship_name'])
            cell_b.font = font_yahei
            cell_b.border = black_border
            cell_b.alignment = Alignment(horizontal='center', vertical='center')

            # C列：船舶情况
            cell_c = ws.cell(row=current_row, column=3, value=row_data['this_week_issue'])
            cell_c.font = font_yahei
            cell_c.border = black_border
            # ✅ 修改为 horizontal='center' 且保留换行
            cell_c.alignment = Alignment(wrap_text=True, horizontal='center', vertical='center')
            current_row += 1

        # 合并 A 列管理人员单元格
        if num_ships > 1:
            ws.merge_cells(start_row=start_merge_row, start_column=1,
                           end_row=current_row - 1, end_column=1)
            for r in range(start_merge_row, current_row):
                ws.cell(row=r, column=1).border = black_border

        ws.cell(row=start_merge_row, column=1).alignment = Alignment(horizontal='center', vertical='center')

    # 设置列宽
    ws.column_dimensions['A'].width = 20
    ws.column_dimensions['B'].width = 25
    ws.column_dimensions['C'].width = 60

    output = io.BytesIO()
    wb.save(output)
    return output.getvalue()


def create_ppt_report(df, start_date, end_date):
    """Admin 专用的 PPT 汇总生成"""
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
    _, col_logo, _ = st.columns([2, 1, 2])
    with col_logo:
        try:
            st.image("TSM_Logo.png", use_container_width=True)
        except:
            pass
    st.markdown("<h2 style='text-align: center;'>Trust Ship 系统登录</h2>", unsafe_allow_html=True)
    with st.form("login_form"):
        u_in = st.text_input("用户名")
        p_in = st.text_input("密码", type="password")
        if st.form_submit_button("立即进入系统", use_container_width=True):
            with get_engine().connect() as conn:
                res = conn.execute(text("SELECT role FROM users WHERE username = :u AND password = :p"),
                                   {"u": u_in, "p": p_in}).fetchone()
                if res:
                    st.session_state.clear()  # 强制清理，防止 Mike/Thein 身份混淆
                    st.session_state.logged_in = True
                    st.session_state.username = u_in
                    st.session_state.role = res[0]
                    st.rerun()
                else:
                    st.error("❌ 验证失败")


if not st.session_state.logged_in:
    login_ui()
    st.stop()

# --- 4. 侧边栏 ---
st.sidebar.title(f" {st.session_state.username}")
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

t_labels = ["填报与查询"]
if st.session_state.role == 'admin': t_labels.append("管理控制台")
t_labels.append("报表中心")
tabs = st.tabs(t_labels)

# --- Tab 1: 业务填报 (核心：全时段修改 + 删除确认) ---
with tabs[0]:
    if ships_df.empty:
        st.warning("⚠️ 暂无分配船舶。")
    else:
        selected_ship = st.selectbox("选择船舶", ships_df['ship_name'].tolist(), index=st.session_state.ship_index)
        ship_id = int(ships_df[ships_df['ship_name'] == selected_ship]['id'].iloc[0])
        st.divider()
        col_hist, col_input = st.columns([1.2, 1])

        # A. 历史记录回溯 (左侧)
        with col_hist:
            st.subheader("历史记录")
            with get_engine().connect() as conn:
                h_df = pd.read_sql_query(text(
                    "SELECT id, report_date, this_week_issue, remarks FROM reports WHERE ship_id = :sid AND is_deleted_by_user = FALSE ORDER BY report_date DESC LIMIT 10"),
                                         conn, params={"sid": ship_id})

            if not h_df.empty:
                for idx, row in h_df.iterrows():
                    with st.expander(f"{row['report_date']} 内容详情"):
                        # ✅ 修改功能：移除日期限制，现在可以一直修改
                        if st.session_state.editing_id == row['id']:
                            new_val = st.text_area("正在修改内容:", value=row['this_week_issue'],
                                                   key=f"edit_v_{row['id']}")
                            new_rem = st.text_input("修改备注:", value=row['remarks'] or "", key=f"edit_r_{row['id']}")
                            c1, c2 = st.columns(2)
                            with c1:
                                if st.button("保存更新", key=f"save_{row['id']}"):
                                    with get_engine().begin() as conn:
                                        conn.execute(text(
                                            "UPDATE reports SET this_week_issue = :t, remarks = :r WHERE id = :id"),
                                                     {"t": new_val, "r": new_rem, "id": row['id']})
                                    st.session_state.editing_id = None;
                                    st.rerun()
                            with c2:
                                if st.button("取消", key=f"canc_e_{row['id']}"):
                                    st.session_state.editing_id = None;
                                    st.rerun()
                        else:
                            st.text(row['this_week_issue'])
                            st.caption(f"备注: {row['remarks'] or '无'}")
                            cb1, cb2 = st.columns(2)
                            with cb1:
                                if st.button("修改", key=f"eb_{row['id']}"):
                                    st.session_state.editing_id = row['id'];
                                    st.rerun()
                            with cb2:
                                if st.button("删除", key=f"db_{row['id']}"):
                                    st.session_state.confirm_del_id = row['id'];
                                    st.rerun()

                # ✅ 删除二次确认逻辑
                if st.session_state.confirm_del_id:
                    st.error(f"确定删除记录 (ID: {st.session_state.confirm_del_id})？")
                    d_b1, d_b2 = st.columns(2)
                    with d_b1:
                        if st.button("取消", key="no_del"): st.session_state.confirm_del_id = None; st.rerun()
                    with d_b2:
                        if st.button("确认执行", key="yes_del"):
                            with get_engine().begin() as conn:
                                conn.execute(text("UPDATE reports SET is_deleted_by_user = TRUE WHERE id = :id"),
                                             {"id": st.session_state.confirm_del_id})
                            st.session_state.confirm_del_id = None;
                            st.rerun()
            else:
                st.info("该船暂无历史。")

        # B. 填报板块 (右侧)
        with col_input:
            st.subheader(f"填报 - {selected_ship}")

            # ✅ 一键导入该船最新内容 (修正后的 SQL)
            if st.button("一键导入该船最近填报内容", key=f"import_{ship_id}", use_container_width=True):
                with get_engine().connect() as conn:
                    last_rec = conn.execute(text(
                        "SELECT this_week_issue FROM reports WHERE ship_id = :sid AND is_deleted_by_user = FALSE ORDER BY report_date DESC LIMIT 1"),
                                            {"sid": ship_id}).fetchone()
                    if last_rec:
                        st.session_state.drafts[ship_id] = last_rec[0]
                        st.success("已载入最新内容。");
                        time.sleep(0.5);
                        st.rerun()
                    else:
                        st.warning("未找到历史记录。")

            if ship_id not in st.session_state.drafts: st.session_state.drafts[ship_id] = ""
            issue_v = st.text_area("本周问题 (分条换行):", value=st.session_state.drafts[ship_id], height=350,
                                   key=f"ta_{ship_id}")
            st.session_state.drafts[ship_id] = issue_v
            remark_v = st.text_input("备注 (选填)", key=f"rem_{ship_id}")

            if st.button("提交填报数据", use_container_width=True):
                if issue_v.strip():
                    with get_engine().begin() as conn:
                        conn.execute(text(
                            "INSERT INTO reports (ship_id, report_date, this_week_issue, remarks) VALUES (:sid, :dt, :iss, :rem)"),
                                     {"sid": ship_id, "dt": datetime.now().date(), "iss": issue_v, "rem": remark_v})
                    st.success("提交成功！");
                    st.session_state.drafts[ship_id] = "";
                    st.rerun()

        # C. 底部导航
        st.divider()
        n1, n2, n3 = st.columns([1, 4, 1])
        with n1:
            if st.button("⬅️ 上一艘"): st.session_state.ship_index = (st.session_state.ship_index - 1) % len(
                ships_df); st.rerun()
        with n3:
            if st.button("下一艘 ➡️"): st.session_state.ship_index = (st.session_state.ship_index + 1) % len(
                ships_df); st.rerun()
# --- Tab 1: 管理员控制台 (新增部分) ---
if st.session_state.role == 'admin':
    with tabs[1]:
        st.subheader("全局管理视图")
        # 从数据库读取所有记录
        m_df = pd.read_sql_query(text("""
            SELECT r.id, s.manager_name as '负责人', s.ship_name as '船名', r.report_date as '日期', r.this_week_issue as '内容'
            FROM reports r JOIN ships s ON r.ship_id = s.id 
            ORDER BY r.report_date DESC
        """), get_engine())

        if not m_df.empty:
            m_df.insert(0, "选择", False)
            # 使用数据编辑器展示，支持勾选
            ed_df = st.data_editor(m_df, hide_index=True, use_container_width=True)

            # 获取勾选的 ID 并执行删除
            to_del = ed_df[ed_df["选择"] == True]["id"].tolist()
            if to_del and st.button("执行删除"):
                with get_engine().begin() as conn:
                    conn.execute(text("DELETE FROM reports WHERE id IN :ids"), {"ids": tuple(to_del)})
                st.rerun()
        else:
            st.info("暂无全局填报数据。")

# --- Tab 最后: 报表导出 ---
with tabs[-1]:
    st.subheader("自动化报表导出")
    c1, c2 = st.columns(2)
    with c1:
        start_d = st.date_input("起始日期", value=datetime.now() - timedelta(days=7))
    with c2:
        end_d = st.date_input("截止日期", value=datetime.now())

    with get_engine().connect() as conn:
        # SQL 顺序：日期, 船名, 问题, 备注, 负责人
        export_df = pd.read_sql_query(text("""
            SELECT r.report_date, s.ship_name, r.this_week_issue, r.remarks, s.manager_name
            FROM reports r JOIN ships s ON r.ship_id = s.id
            WHERE r.report_date BETWEEN :s AND :e AND r.is_deleted_by_user = FALSE
            ORDER BY r.report_date DESC
        """), conn, params={"s": start_d, "e": end_d})

    if not export_df.empty:
        bc1, bc2 = st.columns(2)
        with bc1:
            if not export_df.empty:
                bc1, bc2 = st.columns(2)
                with bc1:
                    # ✅ 这里改用新的函数名
                    excel_bin = generate_custom_excel(export_df)

                    st.download_button(
                        label="下载自定义格式 Excel",
                        data=excel_bin,
                        file_name=f"Report_{start_d}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        use_container_width=True
                    )
        with bc2:
            if st.session_state.role == 'admin':
                if st.button("生成 PPT 汇总"):
                    ppt_bin = create_ppt_report(export_df, start_d, end_d)
                    st.download_button("点击下载 PPT", ppt_bin, f"Meeting_{start_d}.pptx")