
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
# --- Tab 1: 业务填报 (核心：全时段修改 + 修复填写框显示) ---
with tabs[0]:
    if ships_df.empty:
        st.warning("⚠️ 暂无分配船舶。")
    else:
        # 顶部选择与导航
        selected_ship = st.selectbox("选择船舶", ships_df['ship_name'].tolist(), index=st.session_state.ship_index)
        ship_id = int(ships_df[ships_df['ship_name'] == selected_ship]['id'].iloc[0])
        st.divider()

        # 布局：左侧历史，右侧填报
        col_hist, col_input = st.columns([1.2, 1])

        # A. 历史记录回溯 (左侧)
        # A. 历史记录回溯 (左侧)
        with col_hist:
            st.subheader("📊 历史记录")

            # ✅ 1. 二次确认逻辑移到最上方：如果有人点击了删除，这里会立刻弹出警告
            if st.session_state.confirm_del_id:
                st.warning(f"⚠️ 正在准备删除记录 (ID: {st.session_state.confirm_del_id})")
                d_col1, d_col2 = st.columns(2)
                with d_col1:
                    if st.button("🔥 确认执行物理删除", key="confirm_real_del"):
                        with get_engine().begin() as conn:
                            # 执行物理删除
                            conn.execute(text("DELETE FROM reports WHERE id = :id"),
                                         {"id": st.session_state.confirm_del_id})
                        st.session_state.confirm_del_id = None
                        st.success("记录已永久删除")
                        time.sleep(1)
                        st.rerun()
                with d_col2:
                    if st.button("❌ 取消删除", key="cancel_real_del"):
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
                    with st.expander(f" {row['report_date']} 内容详情", expanded=is_editing):
                        if is_editing:
                            new_val = st.text_area("修改内容:", value=row['this_week_issue'], key=f"ed_{row['id']}")
                            if st.button("保存更新", key=f"save_{row['id']}"):
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
                                if st.button("修改", key=f"eb_{row['id']}"):
                                    st.session_state.editing_id = row['id']
                                    st.rerun()
                            with cb2:
                                # ✅ 点击删除后，设置 ID 并触发页面刷新
                                if st.button("删除", key=f"db_{row['id']}"):
                                    st.session_state.confirm_del_id = row['id']
                                    st.rerun()
            else:
                st.info("该船暂无历史。")

        # B. ✅ 填报板块 (右侧 - 确保这部分代码完整且缩进正确)
        with col_input:
            st.subheader(f"填报 - {selected_ship}")
            # ✅ 更改位置 1：在此处定义回调函数
            def handle_submit(sid, iss, rem):
                if iss.strip():
                    with get_engine().begin() as conn:
                        conn.execute(text(
                            "INSERT INTO reports (ship_id, report_date, this_week_issue, remarks) VALUES (:sid, :dt, :iss, :rem)"),
                            {"sid": sid, "dt": datetime.now().date(), "iss": iss, "rem": rem})

                    # 在组件重新渲染前，安全地清空 Session State
                    st.session_state[f"ta_{sid}"] = ""
                    st.session_state.drafts[sid] = ""
                    # 使用 toast 提供轻量级成功反馈
                    st.toast(f"✅ {selected_ship} 数据提交成功！")

            # 1. 一键导入逻辑
            if st.button("一键导入最近填报", key=f"import_{ship_id}", use_container_width=True):
                with get_engine().connect() as conn:
                    last_rec = conn.execute(text(
                        "SELECT this_week_issue FROM reports WHERE ship_id = :sid AND is_deleted_by_user = FALSE ORDER BY report_date DESC LIMIT 1"),
                        {"sid": ship_id}).fetchone()
                    if last_rec:
                        # 强制刷新文本框状态
                        st.session_state[f"ta_{ship_id}"] = last_rec[0]
                        st.success("已载入最近内容，您可以继续编辑。")
                        time.sleep(0.5);
                        st.rerun()
                    else:
                        st.warning("未找到历史记录。")

            # 2. 文本输入框 (使用 key 绑定 session_state)
            if f"ta_{ship_id}" not in st.session_state:
                st.session_state[f"ta_{ship_id}"] = ""

            issue_v = st.text_area("本周问题 (每条一行):", height=350, key=f"ta_{ship_id}")
            remark_v = st.text_input("备注 (选填)", key=f"rem_{ship_id}")

            # ✅ 更改位置 2：使用 on_click 参数绑定回调函数
            st.button(
                "提交填报数据",
                use_container_width=True,
                on_click=handle_submit,
                args=(ship_id, issue_v, remark_v)  # 传递当前船只ID、内容和备注
            )

        # C. 底部导航
        st.divider()
        n1, _, n3 = st.columns([1, 4, 1])
        with n1:
            if st.button("⬅️ 上一艘"): st.session_state.ship_index = (st.session_state.ship_index - 1) % len(
                ships_df); st.rerun()
        with n3:
            if st.button("下一艘 ➡️"): st.session_state.ship_index = (st.session_state.ship_index + 1) % len(
                ships_df); st.rerun()
# --- Tab 1: 管理员控制台 (新增部分) ---
# --- Tab 1: 管理员控制台 (修正 PostgreSQL 别名引号) ---
if st.session_state.role == 'admin':
    with tabs[1]:
        st.subheader("🛠️ 全局管理视图")

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
    st.subheader("自动化报表导出")
    c1, c2 = st.columns(2)
    with c1:
        start_d = st.date_input("起始日期", value=datetime.now() - timedelta(days=7))
    with c2:
        end_d = st.date_input("截止日期", value=datetime.now())

    with get_engine().connect() as conn:
        # 1. 定义基础 SQL 语句
        # 注意：PostgreSQL 别名使用双引号
        query = """
            SELECT r.report_date, s.ship_name, r.this_week_issue, r.remarks, s.manager_name
            FROM reports r 
            JOIN ships s ON r.ship_id = s.id
            WHERE r.report_date BETWEEN :s AND :e 
            AND r.is_deleted_by_user = FALSE
        """
        params = {"s": start_d, "e": end_d}

        # ✅ 2. 权限隔离核心逻辑：
        # 如果角色不是 admin，则强制增加 manager_name 过滤条件
        if st.session_state.role != 'admin':
            query += " AND s.manager_name = :u"
            params["u"] = st.session_state.username

        query += " ORDER BY r.report_date DESC"

        # 3. 执行查询
        export_df = pd.read_sql_query(text(query), conn, params=params)

    if not export_df.empty:
        st.write(f"已检索到 {len(export_df)} 条相关记录")
        bc1, bc2 = st.columns(2)
        with bc1:
            # 调用之前优化过的 excel 生成函数
            excel_bin = generate_custom_excel(export_df)
            st.download_button(
                label="下载 Excel 报表",
                data=excel_bin,
                file_name=f"Ship_Report_{start_d}_to_{end_d}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )
        # 管理员可以额外生成 PPT
        if st.session_state.role == 'admin':
            with bc2:
                if st.button("生成 PPT 汇总"):
                    ppt_bin = create_ppt_report(export_df, start_d, end_d)
                    st.download_button("点击下载 PPT", ppt_bin, f"Summary_{start_d}.pptx")
    else:
        st.info("💡 该日期范围内暂无您可以查看的数据。")