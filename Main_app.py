import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import sqlalchemy
from sqlalchemy import text
import io
from pptx import Presentation
from pptx.util import Inches, Pt

# --- 1. 基础配置与样式 ---
st.set_page_config(page_title="Trust Ship 船舶管理系统", layout="wide", page_icon="🚢")

# 注入 CSS 优化 UI 视觉效果
st.markdown("""
    <style>
    .stButton>button { width: 100%; border-radius: 5px; height: 3em; }
    .stDownloadButton>button { width: 100%; border-radius: 5px; background-color: #004a99; color: white; }
    [data-testid="stMetricValue"] { font-size: 24px; }
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
    # 需在 .streamlit/secrets.toml 中配置 postgres_url
    return sqlalchemy.create_engine(st.secrets["postgres_url"])


# --- 2. 报表生成核心逻辑 (PPT & Excel) ---
def create_ppt_report(df, start_date, end_date):
    prs = Presentation()
    # 标题页
    slide = prs.slides.add_slide(prs.slide_layouts[0])
    slide.shapes.title.text = "Trust Ship 船舶问题汇总周报"
    slide.placeholders[1].text = f"周期: {start_date} 至 {end_date}\n生成人: {st.session_state.username}"

    # 遍历每艘船生成一页 PPT
    for ship_name, group in df.groupby('ship_name'):
        slide = prs.slides.add_slide(prs.slide_layouts[1])
        slide.shapes.title.text = f"船舶: {ship_name}"
        tf = slide.placeholders[1].text_frame
        tf.word_wrap = True

        for _, row in group.iterrows():
            p = tf.add_paragraph()
            p.text = f"• {row['report_date']}: {row['this_week_issue']}"
            if row['remarks']:
                p_rem = tf.add_paragraph()
                p_rem.text = f"  (备注: {row['remarks']})"
                p_rem.level = 1

    ppt_output = io.BytesIO()
    prs.save(ppt_output)
    ppt_output.seek(0)
    return ppt_output


# --- 3. 登录界面 ---
def login_ui():
    st.title("Trust Ship 系统登录")
    st.caption("注：为保障 50 艘船的数据安全，本系统不保存登录状态，刷新页面需重新登录。")
    with st.form("login_form"):
        u_in = st.text_input("用户名")
        p_in = st.text_input("密码", type="password")
        if st.form_submit_button("立即进入系统"):
            with get_engine().connect() as conn:
                res = conn.execute(text("SELECT role FROM users WHERE username = :u AND password = :p"),
                                   {"u": u_in, "p": p_in}).fetchone()
                if res:
                    st.session_state.logged_in = True
                    st.session_state.username = u_in
                    st.session_state.role = res[0]
                    st.rerun()
                else:
                    st.error("❌ 验证失败，请核对信息")


if not st.session_state.logged_in:
    login_ui()
    st.stop()

# --- 4. 侧边栏 ---
st.sidebar.title(f"{st.session_state.username}")
st.sidebar.write(f"角色: `{st.session_state.role}`")
if st.sidebar.button("安全退出"):
    st.session_state.clear()
    st.rerun()


# 获取船舶列表
@st.cache_data(ttl=60)
def get_ships_list(role, user):
    with get_engine().connect() as conn:
        if role == 'admin':
            return pd.read_sql_query(text("SELECT id, ship_name FROM ships ORDER BY ship_name"), conn)
        return pd.read_sql_query(text("SELECT id, ship_name FROM ships WHERE manager_name = :u ORDER BY ship_name"),
                                 conn, params={"u": user})


ships_df = get_ships_list(st.session_state.role, st.session_state.username)

# --- 5. 选项卡布局 ---
tabs_list = ["填报与查询"]
if st.session_state.role == 'admin':
    tabs_list.append("管理员控制台")
tabs_list.append("报表导出")
tabs = st.tabs(tabs_list)

# --- Tab 1: 填报与历史记录 ---
with tabs[0]:
    if ships_df.empty:
        st.warning("⚠️ 暂无分配船舶，请联系 Admin。")
    else:
        # 船舶选择
        selected_ship = st.selectbox("选择船舶", ships_df['ship_name'].tolist(), index=st.session_state.ship_index)
        ship_id = int(ships_df[ships_df['ship_name'] == selected_ship]['id'].iloc[0])

        st.divider()
        col_l, col_r = st.columns([1.2, 1])

        # A. 历史记录
        with col_l:
            st.subheader("历史记录")
            with get_engine().connect() as conn:
                h_df = pd.read_sql_query(text("""
                    SELECT id, report_date, this_week_issue, remarks 
                    FROM reports WHERE ship_id = :sid AND is_deleted_by_user = FALSE
                    ORDER BY report_date DESC LIMIT 10
                """), conn, params={"sid": ship_id})

            if not h_df.empty:
                for idx, row in h_df.iterrows():
                    with st.expander(f"{row['report_date']} 填报内容"):
                        is_today = (row['report_date'] == datetime.now().date())
                        if st.session_state.editing_id == row['id']:
                            new_val = st.text_area("修改内容:", value=row['this_week_issue'], key=f"e_{row['id']}")
                            if st.button("保存", key=f"s_{row['id']}"):
                                with get_engine().begin() as conn:
                                    conn.execute(text("UPDATE reports SET this_week_issue = :t WHERE id = :id"),
                                                 {"t": new_val, "id": row['id']})
                                st.session_state.editing_id = None
                                st.rerun()
                        else:
                            st.text(row['this_week_issue'])
                            c1, c2 = st.columns(2)
                            with c1:
                                if is_today and st.button("修改", key=f"eb_{row['id']}"):
                                    st.session_state.editing_id = row['id'];
                                    st.rerun()
                            with c2:
                                if st.button("🗑删除", key=f"db_{row['id']}"):
                                    st.session_state.confirm_del_id = row['id']

                if st.session_state.confirm_del_id:
                    st.warning(f"⚠️ 确定删除记录 (ID: {st.session_state.confirm_del_id})？")
                    b1, b2 = st.columns(2)
                    with b1:
                        if st.button("取消", key="u_cancel"): st.session_state.confirm_del_id = None; st.rerun()
                    with b2:
                        if st.button("确认", key="u_confirm"):
                            with get_engine().begin() as conn:
                                conn.execute(text("UPDATE reports SET is_deleted_by_user = TRUE WHERE id = :id"),
                                             {"id": st.session_state.confirm_del_id})
                            st.session_state.confirm_del_id = None;
                            st.rerun()
            else:
                st.info("暂无记录。")

        # B. 填报
        with col_r:
            st.subheader(f"填报 - {selected_ship}")
            if ship_id not in st.session_state.drafts: st.session_state.drafts[ship_id] = ""
            issue_v = st.text_area("本周问题描述 (分条换行):", value=st.session_state.drafts[ship_id], height=350,
                                   key=f"ta_{ship_id}")
            st.session_state.drafts[ship_id] = issue_v
            rem_v = st.text_input("备注", key=f"rem_{ship_id}")
            if st.button("提交数据", use_container_width=True):
                if issue_v.strip():
                    with get_engine().begin() as conn:
                        conn.execute(text(
                            "INSERT INTO reports (ship_id, report_date, this_week_issue, remarks) VALUES (:sid, :dt, :iss, :rem)"),
                                     {"sid": ship_id, "dt": datetime.now().date(), "iss": issue_v, "rem": rem_v})
                    st.success("提交成功！");
                    st.session_state.drafts[ship_id] = "";
                    st.rerun()

        # C. 底部切船导航
        st.divider()
        n1, n2, n3 = st.columns([1, 4, 1])
        with n1:
            if st.button("⬅️ 上一艘", use_container_width=True):
                st.session_state.ship_index = (st.session_state.ship_index - 1) % len(ships_df);
                st.rerun()
        with n3:
            if st.button("下一艘 ➡️", use_container_width=True):
                st.session_state.ship_index = (st.session_state.ship_index + 1) % len(ships_df);
                st.rerun()

# --- Tab 2: 管理员控制台 ---
if st.session_state.role == 'admin':
    with tabs[1]:
        st.subheader("管理员全局视图")
        with get_engine().connect() as conn:
            m_df = pd.read_sql_query(text(
                "SELECT r.id, s.manager_name, s.ship_name, r.report_date, r.this_week_issue FROM reports r JOIN ships s ON r.ship_id = s.id ORDER BY r.report_date DESC"),
                                     conn)
        if not m_df.empty:
            m_df.insert(0, "选择", False)
            if st.checkbox("全选"): m_df["选择"] = True
            ed_df = st.data_editor(m_df, hide_index=True)
            to_del = ed_df[ed_df["选择"] == True]["id"].tolist()
            if to_del and st.button("删除"):
                with get_engine().begin() as conn:
                    conn.execute(text("DELETE FROM reports WHERE id IN :ids"), {"ids": tuple(to_del)})
                st.rerun()

# --- Tab 3: 报表导出中心 ---
with tabs[-1]:
    st.subheader("自动化报表导出")
    c_d1, c_d2 = st.columns(2)
    with c_d1:
        start_d = st.date_input("开始日期", value=datetime.now() - timedelta(days=7))
    with c_d2:
        end_d = st.date_input("结束日期", value=datetime.now())

    # 获取选定范围内的数据用于导出
    with get_engine().connect() as conn:
        export_q = """
            SELECT r.report_date, s.ship_name, r.this_week_issue, r.remarks, s.manager_name
            FROM reports r JOIN ships s ON r.ship_id = s.id
            WHERE r.report_date BETWEEN :s AND :e AND r.is_deleted_by_user = FALSE
        """
        params = {"s": start_d, "e": end_d}
        if st.session_state.role != 'admin':
            export_q += " AND s.manager_name = :u"
            params["u"] = st.session_state.username
        export_df = pd.read_sql_query(text(export_q), conn, params=params)

    if export_df.empty:
        st.warning("⚠️ 该范围内暂无数据。")
    else:
        st.write(f"已检索到 **{len(export_df)}** 条填报记录。")
        b_col1, b_col2 = st.columns(2)
        with b_col1:
            excel_data = io.BytesIO()
            export_df.to_excel(excel_data, index=False)
            st.download_button("下载 Excel 汇总表", excel_data.getvalue(), f"Report_{start_d}.xlsx",
                               "application/vnd.ms-excel")
        with b_col2:
            if st.session_state.role == 'admin':
                if st.button("生成 PPT 演示文稿"):
                    ppt_file = create_ppt_report(export_df, start_d, end_d)
                    st.download_button("点击下载 PPT 报表", ppt_file, f"Meeting_{start_d}.pptx")
            else:
                st.caption("注：PPT 汇总仅限管理员使用。")