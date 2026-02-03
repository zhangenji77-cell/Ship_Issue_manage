import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import sqlalchemy
from sqlalchemy import text
import extra_streamlit_components as stx
import time

# --- 1. 基础配置 ---
st.set_page_config(page_title="Trust Ship 船舶管理系统", layout="wide", page_icon="🚢")

# 初始化 Session 状态
if 'drafts' not in st.session_state: st.session_state.drafts = {}
if 'ship_index' not in st.session_state: st.session_state.ship_index = 0
if 'editing_id' not in st.session_state: st.session_state.editing_id = None
if 'confirm_del_id' not in st.session_state: st.session_state.confirm_del_id = None
if 'admin_confirm' not in st.session_state: st.session_state.admin_confirm = False


# ✅ 核心：定义 Cookie 管理器（使用 v13 密钥彻底隔离旧数据）
def get_manager():
    return stx.CookieManager(key="trust_ship_v13_final")


cookie_manager = get_manager()


@st.cache_resource
def get_engine():
    # 必须在 .streamlit/secrets.toml 中配置 postgres_url
    return sqlalchemy.create_engine(st.secrets["postgres_url"])


# --- 2. 身份验证逻辑 (解决 Mike 变 Thein & 刷新掉线) ---
def sync_auth():
    if st.session_state.get('logged_in'):
        return True

    all_cookies = cookie_manager.get_all()

    # 如果浏览器还没传回 Cookie，通过重刷机制等待 (最多尝试 10 次)
    if not all_cookies:
        if 'retry' not in st.session_state: st.session_state.retry = 0
        if st.session_state.retry < 10:
            st.session_state.retry += 1
            time.sleep(0.2)
            st.rerun()
        return False

    # 尝试恢复会话
    st.session_state.retry = 0
    session_val = all_cookies.get("trust_session")
    if session_val and "|" in session_val:
        try:
            u, r = session_val.split("|")
            st.session_state.logged_in = True
            st.session_state.username = u
            st.session_state.role = r
            st.rerun()
            return True
        except:
            return False
    return False


def login_ui():
    st.title("🔒 Trust Ship 系统登录")
    with st.form("login_form"):
        u_in = st.text_input("用户名 (Username)")
        p_in = st.text_input("密码 (Password)", type="password")
        if st.form_submit_button("立即登录"):
            with get_engine().connect() as conn:
                res = conn.execute(text("SELECT role FROM users WHERE username = :u AND password = :p"),
                                   {"u": u_in, "p": p_in}).fetchone()
                if res:
                    # ✅ 核心修复：登录前物理清空 Mike 的内存，防止看到 Thein 的缓存
                    st.session_state.clear()
                    st.session_state.logged_in = True
                    st.session_state.username = u_in
                    st.session_state.role = res[0]
                    # 覆盖旧 Cookie
                    cookie_manager.set("trust_session", f"{u_in}|{res[0]}",
                                       expires_at=datetime.now() + timedelta(days=7))
                    st.success(f"登录成功！欢迎 {u_in}")
                    time.sleep(1)
                    st.rerun()
                else:
                    st.error("❌ 验证失败，请核对信息")


# 执行验证
if not sync_auth():
    login_ui()
    st.stop()

# --- 3. 登录后内容 ---
st.sidebar.title(f"👤 {st.session_state.username}")
if st.sidebar.button("🚪 安全注销"):
    st.session_state.clear()
    cookie_manager.delete("trust_session")
    st.rerun()


# 严格按当前用户名获取船舶
@st.cache_data(ttl=30)
def get_my_ships(role, user):
    with get_engine().connect() as conn:
        if role == 'admin':
            return pd.read_sql_query(text("SELECT id, ship_name FROM ships ORDER BY ship_name"), conn)
        return pd.read_sql_query(text("SELECT id, ship_name FROM ships WHERE manager_name = :u ORDER BY ship_name"),
                                 conn, params={"u": user})


ships_df = get_my_ships(st.session_state.role, st.session_state.username)

# --- 4. 选项卡布局 (这里就是定义 tabs 的地方！) ---
tabs_list = ["📝 船舶填报"]
if st.session_state.role == 'admin':
    tabs_list.append("🛠️ 管理员控制台")
tabs_list.append("📂 报表导出")
tabs = st.tabs(tabs_list)

# --- Tab 1: 数据填报 ---
with tabs[0]:
    if ships_df.empty:
        st.warning("⚠️ 暂无分配船舶。")
    else:
        selected_ship = st.selectbox("🚢 选择船舶", ships_df['ship_name'].tolist(), index=st.session_state.ship_index)
        ship_id = int(ships_df[ships_df['ship_name'] == selected_ship]['id'].iloc[0])

        st.divider()
        c_l, c_r = st.columns([1.2, 1])

        with c_l:
            st.subheader("📊 历史记录")
            with get_engine().connect() as conn:
                h_df = pd.read_sql_query(text("""
                    SELECT id, report_date, this_week_issue, remarks 
                    FROM reports WHERE ship_id = :sid AND is_deleted_by_user = FALSE
                    ORDER BY report_date DESC LIMIT 10
                """), conn, params={"sid": ship_id})

            if not h_df.empty:
                for idx, row in h_df.iterrows():
                    with st.expander(f"📅 {row['report_date']}"):
                        is_today = (row['report_date'] == datetime.now().date())
                        if st.session_state.editing_id == row['id']:
                            new_t = st.text_area("修改内容", value=row['this_week_issue'], key=f"e_{row['id']}")
                            if st.button("💾 保存", key=f"s_{row['id']}"):
                                with get_engine().begin() as conn:
                                    conn.execute(text("UPDATE reports SET this_week_issue = :t WHERE id = :id"),
                                                 {"t": new_t, "id": row['id']})
                                st.session_state.editing_id = None
                                st.rerun()
                        else:
                            st.text(row['this_week_issue'])
                            if is_today and st.button("✏️ 修改", key=f"eb_{row['id']}"):
                                st.session_state.editing_id = row['id']
                                st.rerun()
                            if st.button("🗑️ 删除", key=f"db_{row['id']}"):
                                st.session_state.confirm_del_id = row['id']

                if st.session_state.confirm_del_id:
                    st.warning("⚠️ 确定隐藏此记录？")
                    b1, b2 = st.columns(2)
                    with b1:
                        if st.button("❌ 取消", key="u_c"):
                            st.session_state.confirm_del_id = None
                            st.rerun()
                    with b2:
                        if st.button("🔥 确认", key="u_f"):
                            with get_engine().begin() as conn:
                                conn.execute(text("UPDATE reports SET is_deleted_by_user = TRUE WHERE id = :id"),
                                             {"id": st.session_state.confirm_del_id})
                            st.session_state.confirm_del_id = None
                            st.rerun()

        with c_r:
            st.subheader(f"✍️ 填报 - {selected_ship}")
            if ship_id not in st.session_state.drafts: st.session_state.drafts[ship_id] = ""
            issue_v = st.text_area("描述问题:", value=st.session_state.drafts[ship_id], height=350, key=f"ta_{ship_id}")
            st.session_state.drafts[ship_id] = issue_v
            if st.button("🚀 提交数据", use_container_width=True):
                if issue_v.strip():
                    with get_engine().begin() as conn:
                        conn.execute(text(
                            "INSERT INTO reports (ship_id, report_date, this_week_issue) VALUES (:sid, :dt, :iss)"),
                                     {"sid": ship_id, "dt": datetime.now().date(), "iss": issue_v})
                    st.success("✅ 成功！")
                    st.session_state.drafts[ship_id] = ""
                    st.rerun()

        st.divider()
        n1, n2, n3 = st.columns([1, 4, 1])
        with n1:
            if st.button("⬅️ 上一艘", use_container_width=True):
                st.session_state.ship_index = (st.session_state.ship_index - 1) % len(ships_df)
                st.rerun()
        with n3:
            if st.button("下一艘 ➡️", use_container_width=True):
                st.session_state.ship_index = (st.session_state.ship_index + 1) % len(ships_df)
                st.rerun()

# --- Tab 2: 管理员 (仅 admin 可见) ---
if st.session_state.role == 'admin':
    with tabs[1]:
        st.subheader("🔍 管理员控制台")
        with get_engine().connect() as conn:
            m_df = pd.read_sql_query(text(
                "SELECT r.id, s.manager_name, s.ship_name, r.report_date FROM reports r JOIN ships s ON r.ship_id = s.id ORDER BY r.report_date DESC"),
                                     conn)
        if not m_df.empty:
            m_df.insert(0, "选择", False)
            if st.checkbox("全选"): m_df["选择"] = True
            ed_df = st.data_editor(m_df, hide_index=True)
            to_del = ed_df[ed_df["选择"] == True]["id"].tolist()
            if to_del and st.button("🗑️ 物理删除"):
                with get_engine().begin() as conn:
                    conn.execute(text("DELETE FROM reports WHERE id IN :ids"), {"ids": tuple(to_del)})
                st.rerun()

# --- Tab 3: 报表导出 ---
with tabs[-1]:
    st.subheader("📂 报表导出")
    st.date_input("选择日期范围", value=[datetime.now() - timedelta(days=7), datetime.now()])
    if st.button("📊 生成汇总 Excel"):
        st.info("导出逻辑集成中...")