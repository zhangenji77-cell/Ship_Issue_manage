import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import sqlalchemy
from sqlalchemy import text
import io
from pptx import Presentation
from pptx.util import Inches, Pt

# --- 1. 基础配置与样式优化 ---
st.set_page_config(page_title="Trust Ship 船舶管理系统", layout="wide", page_icon="🚢")

st.markdown("""
    <style>
    .stButton>button { width: 100%; border-radius: 5px; height: 3em; }
    .stDownloadButton>button { width: 100%; border-radius: 5px; background-color: #004a99; color: white; }
    /* 侧边栏图片边距调整 */
    [data-testid="stSidebarNav"] { margin-top: 20px; }
    </style>
    """, unsafe_allow_html=True)

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


# --- 2. 报表生成逻辑 (PPT) ---
def create_ppt_report(df, start_date, end_date):
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[0])
    slide.shapes.title.text = "Trust Ship 船舶问题汇总周报"
    slide.placeholders[1].text = f"周期: {start_date} 至 {end_date}\n汇报人: {st.session_state.username}"
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


# --- 3. 登录界面 (优化 Logo 尺寸) ---
def login_ui():
    # ✅ 调整列比例为 [2, 1, 2]，使中间的 Logo 占据空间更小
    _, col_logo, _ = st.columns([2, 1, 2])
    with col_logo:
        try:
            st.image("TSM_Logo.png", use_container_width=True)
        except:
            st.warning("⚠️ 未找到 TSM_Logo.png")

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

# --- 4. 登录后的内容 ---

# ✅ 侧边栏顶部显式显示 Logo，固定宽度防止过大
st.sidebar.image("TSM_Logo.png", width=150)
st.sidebar.title(f"👤 {st.session_state.username}")
if st.sidebar.button("🚪 安全注销"):
    st.session_state.clear();
    st.rerun()

# 主页面顶部也可以放置一个小型 Logo 作为页眉
main_col1, main_col2 = st.columns([5, 1])
with main_col2:
    st.image("TSM_Logo.png", width=100)


# 获取船舶列表逻辑
@st.cache_data(ttl=60)
def get_ships_list(role, user):
    with get_engine().connect() as conn:
        if role == 'admin':
            return pd.read_sql_query(text("SELECT id, ship_name FROM ships ORDER BY ship_name"), conn)
        return pd.read_sql_query(text("SELECT id, ship_name FROM ships WHERE manager_name = :u ORDER BY ship_name"),
                                 conn, params={"u": user})


ships_df = get_ships_list(st.session_state.role, st.session_state.username)

# 选项卡
tabs_list = ["📝 数据填报与回溯"]
if st.session_state.role == 'admin': tabs_list.append("🛠️ 管理员控制台")
tabs_list.append("📂 报表中心")
tabs = st.tabs(tabs_list)

# Tab 内容 (填报逻辑)
with tabs[0]:
    if ships_df.empty:
        st.warning("⚠️ 暂无分配船舶。")
    else:
        selected_ship = st.selectbox("🚢 选择船舶", ships_df['ship_name'].tolist(), index=st.session_state.ship_index)
        ship_id = int(ships_df[ships_df['ship_name'] == selected_ship]['id'].iloc[0])
        st.divider()
        col_l, col_r = st.columns([1.2, 1])
        with col_l:
            st.subheader("📊 历史记录回溯")
            with get_engine().connect() as conn:
                h_df = pd.read_sql_query(text(
                    "SELECT id, report_date, this_week_issue FROM reports WHERE ship_id = :sid AND is_deleted_by_user = FALSE ORDER BY report_date DESC LIMIT 10"),
                                         conn, params={"sid": ship_id})
            if not h_df.empty:
                for idx, row in h_df.iterrows():
                    with st.expander(f"📅 {row['report_date']}"):
                        st.text(row['this_week_issue'])
                        if st.button("🗑️ 删除", key=f"db_{row['id']}"):
                            st.session_state.confirm_del_id = row['id'];
                            st.rerun()
            else:
                st.info("暂无记录。")
        with col_r:
            st.subheader(f"✍️ 填报 - {selected_ship}")
            issue_v = st.text_area("描述问题:", key=f"ta_{ship_id}")
            if st.button("🚀 提交数据"):
                if issue_v.strip():
                    with get_engine().begin() as conn: conn.execute(
                        text("INSERT INTO reports (ship_id, report_date, this_week_issue) VALUES (:sid, :dt, :iss)"),
                        {"sid": ship_id, "dt": datetime.now().date(), "iss": issue_v})
                    st.success("✅ 提交成功！");
                    st.rerun()

# 导出中心 (Tab 3)
with tabs[-1]:
    st.subheader("📂 自动化报表导出")
    # (保持之前的导出代码逻辑即可)
