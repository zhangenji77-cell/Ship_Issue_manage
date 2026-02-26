
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
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.util import Inches, Pt
from pptx.enum.text import PP_ALIGN  # ✅ 新增：用于致谢页文字居中对齐
# 如果您还没安装，请在服务器终端运行: pip install python-pptx

# --- 1. 基础配置与品牌样式 ---
st.set_page_config(page_title="TSM Summary of Weekly Ship Reports", layout="wide")

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

import re  # 必须在文件顶部导入 re 库


def generate_custom_excel(df):
    """
    生成 Excel：清洗旧编号，重新进行顺序编码，C列左对齐
    """
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Ship Report"

    # 定义样式
    font_yahei = Font(name='微软雅黑', size=10)
    font_yahei_bold = Font(name='微软雅黑', size=10, bold=True)
    thin_side = Side(style='thin', color='000000')
    black_border = Border(top=thin_side, left=thin_side, right=thin_side, bottom=thin_side)

    # --- 1. 第一行：Report Date (居中) ---
    ws.merge_cells('A1:C1')
    ws['A1'] = f"Report Date: {datetime.now().strftime('%Y-%m-%d')}"
    ws['A1'].font = Font(name='微软雅黑', size=12, bold=True)
    ws['A1'].alignment = Alignment(horizontal='center', vertical='center')

    # --- 2. 第二行：表头 (全部居中) ---
    headers = ['manager name', 'ship name', 'Issue']
    for col_num, header in enumerate(headers, 1):
        cell = ws.cell(row=2, column=col_num, value=header)
        cell.font = font_yahei_bold
        cell.alignment = Alignment(horizontal='center', vertical='center')
        cell.border = black_border

    # --- 3. 数据预处理：清洗内容并重新编号 ---
    def clean_and_reformat_issue(series):
        all_lines = []
        for content in series:
            if content:
                # 按行拆分
                lines = str(content).split('\n')
                for line in lines:
                    # ✅ 核心逻辑：使用正则剔除行首的数字、点、顿号和空格
                    # 例如把 "1. 内容" 或 "2、内容" 变成 "内容"
                    clean_line = re.sub(r'^\d+[\.、\s]*', '', line.strip())
                    if clean_line:
                        all_lines.append(clean_line)

        if not all_lines: return ""
        # ✅ 核心逻辑：对所有提取出的纯内容重新进行 1. 2. 3. 编码
        return "\n".join([f"{i + 1}. {text}" for i, text in enumerate(all_lines)])

    # 按负责人和船名分组
    df_grouped = df.groupby(['manager_name', 'ship_name'])['this_week_issue'].apply(
        clean_and_reformat_issue).reset_index()
    df_grouped = df_grouped.sort_values(by='manager_name')

    # --- 4. 填充数据 ---
    current_row = 3
    for manager, group in df_grouped.groupby('manager_name', sort=False):
        start_merge_row = current_row
        for _, row_data in group.iterrows():
            # A列/B列：负责人/船名 (居中)
            for col in [1, 2]:
                cell = ws.cell(row=current_row, column=col,
                               value=row_data['manager_name'] if col == 1 else row_data['ship_name'])
                cell.font = font_yahei
                cell.border = black_border
                cell.alignment = Alignment(horizontal='center', vertical='center')

            # C列：Issue (左对齐 + 重新编号后的内容)
            cell_c = ws.cell(row=current_row, column=3, value=row_data['this_week_issue'])
            cell_c.font = font_yahei
            cell_c.border = black_border
            # ✅ C列内容左对齐，垂直居中
            cell_c.alignment = Alignment(wrap_text=True, horizontal='left', vertical='center')
            current_row += 1

        # 合并 A 列负责人
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


# ✅ 在 generate_custom_excel 下方添加此函数
# ✅ 完全替换此函数
def create_ppt_report(df, start_date, end_date):
    # --- 1. 创建标题页 ---
    prs = Presentation()
    slide_layout_title = prs.slide_layouts[0]
    slide = prs.slides.add_slide(slide_layout_title)

    # 获取标题和副标题对象
    title = slide.shapes.title
    subtitle = slide.placeholders[1]

    # ✅ 调整标题位置：数值越大越靠下
    # 默认通常在 1.5 到 2.5 左右，您可以尝试设为 3.0 或更大
    title.top = Inches(3.5)
    title.text = "TSM Summary of Weekly Ship Reports"

    # ✅ 调整副标题位置：为了防止重叠，通常副标题也要跟着下移
    # 确保 subtitle.top 大于 title.top
    current_date = datetime.now().strftime('%Y-%m-%d')
    subtitle.text = f"Creation Date: {current_date}"
    subtitle.top = Inches(4.5)
    """
    生成 PPT：完全复刻 Excel 排序逻辑，24号字，含 Logo 和致谢页
    """
    prs = Presentation()

    # --- 1. 创建标题页 ---
    slide_layout_title = prs.slide_layouts[0]
    slide = prs.slides.add_slide(slide_layout_title)

    # 插入 Logo (保持较小尺寸并居中)
    try:
        slide.shapes.add_picture("TSM_Logo.png", left=Inches(4.25), top=Inches(1.2), width=Inches(1.8))
    except:
        pass

    slide.shapes.title.text = "TSM Summary of Weekly Ship Reports"

    # --- 2. ✅ 核心修正：同步 Excel 的预处理逻辑 ---
    # 定义清洗与编号内部函数
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

    # 严格按照 Excel 的方式进行聚合与排序
    # 1. 按负责人和船名分组并合并内容
    df_ppt = df.groupby(['manager_name', 'ship_name'], sort=False)['this_week_issue'].apply(
        clean_and_reformat_ppt).reset_index()
    # 2. 核心排序：先按负责人，再按船名，确保与 Excel 顺序百分百同步
    df_ppt = df_ppt.sort_values(by=['manager_name', 'ship_name'])

    # --- 3. 遍历处理后的数据生成详情页 ---
    for _, row in df_ppt.iterrows():
        manager = row['manager_name']
        ship = row['ship_name']
        issue_content = row['this_week_issue']

        slide_layout_content = prs.slide_layouts[1]
        slide = prs.slides.add_slide(slide_layout_content)

        # 标题：船名 (负责人)
        slide.shapes.title.text = f" {ship} ({manager})"

        body_shape = slide.placeholders[1]
        tf = body_shape.text_frame
        tf.word_wrap = True

        # 将合并后的内容拆分为行，逐行添加为项目符号
        if issue_content:
            for line in issue_content.split('\n'):
                p = tf.add_paragraph()
                p.text = line
                p.level = 0
                p.font.size = Pt(24)  # 字体大小设为 24
                p.font.name = '微软雅黑'

    # --- 4. 致谢页 ---
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

    # --- 5. 保存 ---
    ppt_out = io.BytesIO()
    prs.save(ppt_out)
    ppt_out.seek(0)
    return ppt_out


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
        u_in = st.text_input("User Name")
        p_in = st.text_input("Password", type="password")
        if st.form_submit_button("Log In", use_container_width=True):
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
                    st.error("Verification Failed")


if not st.session_state.logged_in:
    login_ui()
    st.stop()

# --- 4. 侧边栏 ---
st.sidebar.title(f" {st.session_state.username}")
if st.sidebar.button("Log Out Safely"):
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

t_labels = ["Filling in and Querying"]
if st.session_state.role == 'admin': t_labels.append("管理控制台")
t_labels.append("Report Center")
tabs = st.tabs(t_labels)

# --- Tab 1: 业务填报 (核心：全时段修改 + 删除确认) ---
# --- Tab 1: 业务填报 (核心：全时段修改 + 修复填写框显示) ---
with tabs[0]:
    if ships_df.empty:
        st.warning("No vessels have been assigned yet.")
    else:
        # 顶部选择与导航
        selected_ship = st.selectbox("Select a vessel", ships_df['ship_name'].tolist(), index=st.session_state.ship_index)
        ship_id = int(ships_df[ships_df['ship_name'] == selected_ship]['id'].iloc[0])
        st.divider()

        # 布局：左侧历史，右侧填报
        col_hist, col_input = st.columns([1.2, 1])

        # A. 历史记录回溯 (左侧)
        # A. 历史记录回溯 (左侧)
        with col_hist:
            st.subheader("History Record")

            # ✅ 1. 二次确认逻辑移到最上方：如果有人点击了删除，这里会立刻弹出警告
            if st.session_state.confirm_del_id:
                st.warning(f"Prepare to delete the record. (ID: {st.session_state.confirm_del_id})")
                d_col1, d_col2 = st.columns(2)
                with d_col1:
                    if st.button("Confirm deletion", key="confirm_real_del"):
                        with get_engine().begin() as conn:
                            # 执行物理删除
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

            # 2. 获取并展示历史列表
            with get_engine().connect() as conn:
                h_df = pd.read_sql_query(text(
                    "SELECT id, report_date, this_week_issue, remarks FROM reports WHERE ship_id = :sid AND is_deleted_by_user = FALSE ORDER BY report_date DESC LIMIT 10"),
                    conn, params={"sid": ship_id})

            if not h_df.empty:
                for idx, row in h_df.iterrows():
                    # ✅ 增加 expanded=True 的判断：如果正在编辑该行，保持展开
                    is_editing = st.session_state.editing_id == row['id']
                    with st.expander(f" {row['report_date']} Content Details", expanded=is_editing):
                        if is_editing:
                            new_val = st.text_area("Modifications:", value=row['this_week_issue'], key=f"ed_{row['id']}")
                            if st.button("Save Updates", key=f"save_{row['id']}"):
                                with get_engine().begin() as conn:
                                    conn.execute(text("UPDATE reports SET this_week_issue = :t WHERE id = :id"),
                                                 {"t": new_val, "id": row['id']})
                                st.session_state.editing_id = None
                                st.rerun()
                        else:
                            # 展示逻辑（保持之前的清洗编号展示）
                            raw_content = row['this_week_issue']
                            clean_lines = [re.sub(r'^\d+[\.、\s]*', '', l.strip()) for l in raw_content.split('\n') if
                                           l.strip()]
                            st.text("\n".join([f"{i + 1}. {text}" for i, text in enumerate(clean_lines)]))

                            cb1, cb2 = st.columns(2)
                            with cb1:
                                if st.button("Modify", key=f"eb_{row['id']}"):
                                    st.session_state.editing_id = row['id']
                                    st.rerun()
                            with cb2:
                                # ✅ 点击删除后，设置 ID 并触发页面刷新
                                if st.button("Delete", key=f"db_{row['id']}"):
                                    st.session_state.confirm_del_id = row['id']
                                    st.rerun()
            else:
                st.info("The vessel has no history.")

        # B. ✅ 填报板块 (右侧 - 确保这部分代码完整且缩进正确)
                # B. ✅ 填报板块 (右侧 - 修复提交旧数据和需要点两次的Bug)
                with col_input:
                    st.subheader(f"Fill in - {selected_ship}")


                    # ✅ 更改位置 1：修改回调函数，不再接收 iss 和 rem 参数
                    def handle_submit(sid):
                        # 💡 核心修复：直接从 session_state 获取用户刚刚输入的最新鲜的数据
                        latest_issue = st.session_state.get(f"ta_{sid}", "")
                        latest_remark = st.session_state.get(f"rem_{sid}", "")

                        if latest_issue.strip():
                            with get_engine().begin() as conn:
                                conn.execute(text(
                                    "INSERT INTO reports (ship_id, report_date, this_week_issue, remarks) VALUES (:sid, :dt, :iss, :rem)"),
                                    {"sid": sid, "dt": datetime.now().date(), "iss": latest_issue,
                                     "rem": latest_remark})

                            # 在组件重新渲染前，安全地清空 Session State
                            st.session_state[f"ta_{sid}"] = ""
                            st.session_state[f"rem_{sid}"] = ""  # 顺便把备注也清空
                            st.session_state.drafts[sid] = ""
                            # 使用 toast 提供轻量级成功反馈
                            st.toast(f" {selected_ship} Data submission successful!")


                    # 1. 一键导入逻辑
                    if st.button("Import information about the ship from last week.", key=f"import_{ship_id}", use_container_width=True):
                        with get_engine().connect() as conn:
                            last_rec = conn.execute(text(
                                "SELECT this_week_issue FROM reports WHERE ship_id = :sid AND is_deleted_by_user = FALSE ORDER BY report_date DESC LIMIT 1"),
                                {"sid": ship_id}).fetchone()
                            if last_rec:
                                # 强制刷新文本框状态
                                st.session_state[f"ta_{ship_id}"] = last_rec[0]
                                st.success("The latest content has been loaded; you can continue editing.")
                                time.sleep(0.5)
                                st.rerun()
                            else:
                                st.warning("No history found")

                    # 2. 文本输入框 (使用 key 绑定 session_state)
                    if f"ta_{ship_id}" not in st.session_state:
                        st.session_state[f"ta_{ship_id}"] = ""
                    if f"rem_{ship_id}" not in st.session_state:
                        st.session_state[f"rem_{ship_id}"] = ""

                    # 注意这里：即使不把返回值赋给变量也没关系，因为 key 已经让它们自动写入系统大脑了
                    st.text_area("This week's question (one line per question):", height=350, key=f"ta_{ship_id}")
                    st.text_input("Remarks (optional)", key=f"rem_{ship_id}")

                    # ✅ 更改位置 2：使用 on_click 触发函数，只传船只ID，不传文本内容
                    st.button(
                        "Submit the information",
                        use_container_width=True,
                        on_click=handle_submit,
                        args=(ship_id,)  # 💡 这里只传 sid 即可
                    )

        # C. 底部导航
        st.divider()
        n1, _, n3 = st.columns([1, 4, 1])
        with n1:
            if st.button("Previous"): st.session_state.ship_index = (st.session_state.ship_index - 1) % len(
                ships_df); st.rerun()
        with n3:
            if st.button("Next"): st.session_state.ship_index = (st.session_state.ship_index + 1) % len(
                ships_df); st.rerun()
# --- Tab 1: 管理员控制台 (新增部分) ---
# --- Tab 1: 管理员控制台 (修正 PostgreSQL 别名引号) ---
if st.session_state.role == 'admin':
    with tabs[1]:
        st.subheader("全局管理视图")

        # ✅ 这里是修正核心：将别名从 '负责人' 改为 "负责人" (使用双引号)
        m_df = pd.read_sql_query(text("""
            SELECT r.id, s.manager_name as "负责人", s.ship_name as "船名", 
                   r.report_date as "日期", r.this_week_issue as "内容"
            FROM reports r JOIN ships s ON r.ship_id = s.id 
            ORDER BY r.report_date DESC
        """), get_engine())

        if not m_df.empty:
            m_df.insert(0, "选择", False)
            # 使用数据编辑器展示
            ed_df = st.data_editor(m_df, hide_index=True, use_container_width=True)

            # 批量删除逻辑
            to_del = ed_df[ed_df["选择"] == True]["id"].tolist()
            if to_del and st.button("删除"):
                with get_engine().begin() as conn:
                    conn.execute(text("DELETE FROM reports WHERE id IN :ids"), {"ids": tuple(to_del)})
                st.success(f"已删除 {len(to_del)} 条记录")
                st.rerun()
        else:
            st.info("暂无全局填报数据。")

# --- Tab 最后: 报表导出 ---
# --- Tab 最后: 报表中心 (权限隔离导出) ---
with tabs[-1]:
    st.subheader("Automated information preview and export")

    # 1. 日期选择区域
    c1, c2 = st.columns(2)
    with c1:
        start_d = st.date_input("Start Date", value=datetime.now() - timedelta(days=7), key="rep_start")
    with c2:
        end_d = st.date_input("Expiration Date", value=datetime.now(), key="rep_end")

    # 2. 获取数据 (包含权限隔离逻辑)
    with get_engine().connect() as conn:
        query = """
                SELECT r.report_date as "日期", s.ship_name as "船名", 
                       r.this_week_issue as "填报内容", s.manager_name as "负责人"
                FROM reports r 
                JOIN ships s ON r.ship_id = s.id
                WHERE r.report_date BETWEEN :s AND :e 
                AND r.is_deleted_by_user = FALSE
            """
        params = {"s": start_d, "e": end_d}

        # ✅ 只有普通用户才进行负责人过滤
        if st.session_state.role != 'admin':
            query += " AND s.manager_name = :u"
            params["u"] = st.session_state.username

        query += " ORDER BY r.report_date DESC"
        export_df = pd.read_sql_query(text(query), conn, params=params)

    # --- ✅ 新增功能：搜索预览选项 ---
    st.write("---")
    # 使用 use_container_width 让按钮铺满，更易点击
    if st.button("Search and preview the information entered within the selected date", use_container_width=True):
        if not export_df.empty:
            st.success(f"Found {len(export_df)} records")

            # 为了让预览更整洁，这里对预览数据也进行一次编号处理
            preview_df = export_df.copy()


            def preview_clean(text):
                lines = [re.sub(r'^\d+[\.、\s]*', '', l.strip()) for l in str(text).split('\n') if l.strip()]
                return "\n".join([f"{i + 1}. {t}" for i, t in enumerate(lines)])


            preview_df["Fill in the content"] = preview_df["Fill in the content"].apply(preview_clean)

            # 在网页上展示交互式表格
            st.dataframe(
                preview_df,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Fill in the content": st.column_config.TextColumn("Detailed information (automatically numbered)", width="large"),
                    "Date": st.column_config.DateColumn("Date")
                }
            )
        else:
            st.warning("No reporting records were found within that date range")

    st.write("---")

    # 3. 下载功能区域 (保持原有 generate_custom_excel 调用不变)
    if not export_df.empty:
        # 将预览用的中文列名转回函数需要的英文名
        excel_prep_df = export_df.rename(columns={
            "负责人": "manager_name",
            "船名": "ship_name",
            "填报内容": "this_week_issue"
        })

        bc1, bc2 = st.columns(2)
        with bc1:
            excel_bin = generate_custom_excel(excel_prep_df)
            st.download_button(
                label="Download Excel version information",
                data=excel_bin,
                file_name=f"Trust_Ship_Report_{start_d}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )

        if st.session_state.role == 'admin':
            with bc2:
                if st.button("生成 PPT 汇总预览", use_container_width=True):
                    # ✅ 确保传入 excel_prep_df，因为它已经包含了 manager_name 列
                    ppt_bin = create_ppt_report(excel_prep_df, start_d, end_d)

                    st.download_button(
                        label="点击下载 PPT 文件",
                        data=ppt_bin,
                        file_name=f"Ship_Meeting_{start_d}.pptx",
                        mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                        use_container_width=True
                    )
    else:
        st.info("There is currently no data available for you to view within this date range")















