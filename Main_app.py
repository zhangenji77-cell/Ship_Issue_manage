import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import sqlalchemy
from sqlalchemy import text
import extra_streamlit_components as stx  # 用于处理浏览器 Cookie

# --- 1. 初始化配置与 Cookie 管理 ---
st.set_page_config(page_title="Trust Ship 船舶管理系统", layout="wide", page_icon="🚢")


@st.cache_resource
def get_manager():
    return stx.CookieManager()


cookie_manager = get_manager()

# 初始化 Session State
if 'drafts' not in st.session_state: st.session_state.drafts = {}
if 'confirm_delete_target' not in st.session_state: st.session_state.confirm_delete_target = None
if 'ship_index' not in st.session_state: st.session_state.ship_index = 0


@st.cache_resource
def get_engine():
    return sqlalchemy.create_engine(st.secrets["postgres_url"])


# --- 2. 登录持久化逻辑 (核心优化) ---
# 自动从浏览器读取 Cookie
saved_user = cookie_manager.get("trust_user")
saved_role = cookie_manager.get("trust_role")

if 'logged_in' not in st.session_state:
    if saved_user and saved_role:
        st.session_state.logged_in = True
        st.session_state.username = saved_user
        st.session_state.role = saved_role
    else:
        st.session_state.logged_in = False


def login_ui():
    st.title("🔒 Trust Ship 系统登录")
    with st.form("login"):
        u = st.text_input("用户名")
        p = st.text_input("密码", type="password")
        if st.form_submit_button("登录"):
            with get_engine().connect() as conn:
                res = conn.execute(text("SELECT role FROM users WHERE username = :u AND password = :p"),
                                   {"u": u, "p": p}).fetchone()
                if res:
                    # 写入 Session State
                    st.session_state.logged_in = True
                    st.session_state.username = u
                    st.session_state.role = res[0]
                    # 写入浏览器 Cookie (有效期 7 天)
                    cookie_manager.set("trust_user", u, expires_at=datetime.now() + timedelta(days=7))
                    cookie_manager.set("trust_role", res[0], expires_at=datetime.now() + timedelta(days=7))
                    st.rerun()
                else:
                    st.error("❌ 验证失败")


if not st.session_state.logged_in:
    login_ui()
    st.stop()

# --- 3. 页面内容 ---
st.sidebar.title(f"👤 {st.session_state.username}")
if st.sidebar.button("🚪 安全登出"):
    # 只有点击此按钮才会彻底清除状态
    st.session_state.logged_in = False
    cookie_manager.delete("trust_user")
    cookie_manager.delete("trust_role")
    st.rerun()

# 数据获取与角色过滤
ships_df = pd.read_sql_query(
    text(
        "SELECT id, ship_name FROM ships" if st.session_state.role == 'admin' else "SELECT id, ship_name FROM ships WHERE manager_name = :u"),
    get_engine(), params={"u": st.session_state.username}
)

tabs = st.tabs(["📝 数据填报", "🛠️ 管理员控制台", "📂 报表导出"])

# --- Tab 1: 数据填报 (带二次确认删除) ---
with tabs[0]:
    if not ships_df.empty:
        selected_ship = st.selectbox("选择船舶", ships_df['ship_name'].tolist(), index=st.session_state.ship_index)
        ship_id = int(ships_df[ships_df['ship_name'] == selected_ship]['id'].iloc[0])

        c1, c2 = st.columns([1, 1.2])

        with c1:
            st.subheader("📊 历史记录")
            h_df = pd.read_sql_query(text(
                "SELECT id, report_date, this_week_issue FROM reports WHERE ship_id = :sid AND is_deleted_by_user = FALSE ORDER BY report_date DESC"),
                                     get_engine(), params={"sid": ship_id})

            for _, row in h_df.iterrows():
                with st.expander(f"📅 {row['report_date']}"):
                    st.text(row['this_week_issue'])
                    # 优化1：删除二次确认
                    if st.button("🗑️ 删除", key=f"del_{row['id']}"):
                        st.session_state.confirm_delete_target = row['id']

            if st.session_state.confirm_delete_target:
                st.warning(f"⚠️ 确定删除记录 #{st.session_state.confirm_delete_target} 吗？")
                if st.button("🔥 确认执行删除", key="confirm_user_del"):
                    with get_engine().begin() as conn:
                        conn.execute(text("UPDATE reports SET is_deleted_by_user = TRUE WHERE id = :id"),
                                     {"id": st.session_state.confirm_delete_target})
                    st.session_state.confirm_delete_target = None
                    st.success("已标记删除")
                    st.rerun()

        with c2:
            st.subheader("✍️ 本周填报")
            # 优化3：提交后自动清除
            if ship_id not in st.session_state.drafts: st.session_state.drafts[ship_id] = ""
            txt = st.text_area("内容:", value=st.session_state.drafts[ship_id], height=300, key=f"ta_{ship_id}")
            st.session_state.drafts[ship_id] = txt

            if st.button("🚀 提交并清空"):
                if txt.strip():
                    with get_engine().begin() as conn:
                        conn.execute(text(
                            "INSERT INTO reports (ship_id, report_date, this_week_issue) VALUES (:sid, :dt, :iss)"),
                                     {"sid": ship_id, "dt": datetime.now().date(), "iss": txt})
                    st.session_state.drafts[ship_id] = ""  # 彻底清空
                    st.success("提交成功")
                    st.rerun()

# --- Tab 2: 管理员 (带全选与二次确认) ---
if st.session_state.role == 'admin':
    with tabs[1]:
        st.subheader("🗑️ 管理员数据清理")
        m_df = pd.read_sql_query(
            text("SELECT r.id, s.ship_name, r.report_date FROM reports r JOIN ships s ON r.ship_id = s.id"),
            get_engine())
        m_df.insert(0, "选择", False)
        if st.checkbox("全选"): m_df["选择"] = True

        edited = st.data_editor(m_df, hide_index=True)
        to_del = edited[edited["选择"] == True]["id"].tolist()

        if to_del:
            if st.button(f"🔥 彻底物理删除选中的 {len(to_del)} 项"):
                st.session_state.admin_confirm = True

            if st.session_state.get('admin_confirm'):
                st.error(f"🚨 警告：此操作将从数据库永久抹除这 {len(to_del)} 条数据！")
                if st.button("确认无误，永久删除"):
                    with get_engine().begin() as conn:
                        conn.execute(text("DELETE FROM reports WHERE id IN :ids"), {"ids": tuple(to_del)})
                    st.session_state.admin_confirm = False
                    st.success("清理完成")
                    st.rerun()