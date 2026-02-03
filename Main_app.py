import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import sqlalchemy
from sqlalchemy import text
import extra_streamlit_components as stx
import time

# --- 1. 基础配置 ---
st.set_page_config(page_title="Trust Ship 船舶管理系统", layout="wide", page_icon="🚢")

# 初始化状态
if 'drafts' not in st.session_state: st.session_state.drafts = {}
if 'ship_index' not in st.session_state: st.session_state.ship_index = 0
if 'editing_id' not in st.session_state: st.session_state.editing_id = None
if 'confirm_del_id' not in st.session_state: st.session_state.confirm_del_id = None
if 'admin_confirm' not in st.session_state: st.session_state.admin_confirm = False


def get_manager():
    # 必须保留 key，不使用缓存
    return stx.CookieManager(key="trust_ship_v3")


cookie_manager = get_manager()


@st.cache_resource
def get_engine():
    # 请确保 st.secrets 中配置了 postgres_url
    return sqlalchemy.create_engine(st.secrets["postgres_url"])


# --- 2. 增强型持久化登录逻辑 (解决刷新掉线) ---
def check_auth():
    # 1. 如果当前 Session 已经是登录状态，直接通过
    if st.session_state.get('logged_in'):
        return True

    # 2. 如果未登录，尝试从 Cookie 获取
    with st.spinner("正在同步登录状态..."):
        # 给 JavaScript 组件一点点握手时间 (0.5秒)
        time.sleep(0.5)
        all_cookies = cookie_manager.get_all()
        saved_session = all_cookies.get("trust_session")

        if saved_session and "|" in saved_session:
            try:
                s_user, s_role = saved_session.split("|")
                st.session_state.logged_in = True
                st.session_state.username = s_user
                st.session_state.role = s_role
                st.rerun()  # 状态同步后重刷页面进入主界面
                return True
            except:
                pass
    return False


def login_ui():
    st.title("🔒 Trust Ship 系统登录")
    with st.form("login_form"):
        u = st.text_input("用户名")
        p = st.text_input("密码", type="password")
        if st.form_submit_button("登录"):
            with get_engine().connect() as conn:
                res = conn.execute(text("SELECT role FROM users WHERE username = :u AND password = :p"),
                                   {"u": u, "p": p}).fetchone()
                if res:
                    st.session_state.logged_in = True
                    st.session_state.username = u
                    st.session_state.role = res[0]
                    # 合并存储，避免 Duplicate Key 报错
                    cookie_manager.set("trust_session", f"{u}|{res[0]}", expires_at=datetime.now() + timedelta(days=7))
                    st.rerun()
                else:
                    st.error("❌ 验证失败，请检查账号密码")


# 执行登录检查
if not check_auth():
    login_ui()
    st.stop()

# --- 3. 侧边栏 ---
st.sidebar.title(f"👤 {st.session_state.username}")
if st.sidebar.button("🚪 安全登出"):
    st.session_state.logged_in = False
    cookie_manager.delete("trust_session")
    st.rerun()


# --- 4. 数据获取 ---
@st.cache_data(ttl=60)
def get_ships(role, user):
    with get_engine().connect() as conn:
        if role == 'admin':
            return pd.read_sql_query(text("SELECT id, ship_name FROM ships ORDER BY ship_name"), conn)
        return pd.read_sql_query(text("SELECT id, ship_name FROM ships WHERE manager_name = :u ORDER BY ship_name"),
                                 conn, params={"u": user})


ships_df = get_ships(st.session_state.role, st.session_state.username)

# --- 5. 页面布局 ---
tabs = st.tabs(["📝 数据填报与查询", "🛠️ 管理员控制台", "📂 报表导出"])

# --- Tab 1: 数据填报与历史 ---
with tabs[0]:
    if ships_df.empty:
        st.warning("⚠️ 暂无分配船舶。")
    else:
        # A. 船舶选择 (基于索引)
        selected_ship = st.selectbox("🚢 选择船舶", ships_df['ship_name'].tolist(), index=st.session_state.ship_index)
        ship_id = int(ships_df[ships_df['ship_name'] == selected_ship]['id'].iloc[0])

        st.divider()
        col_l, col_r = st.columns([1.2, 1])

        # B. 历史记录 (含当天修改及二次确认删除)
        with col_l:
            st.subheader("📊 历史记录")
            with get_engine().connect() as conn:
                h_df = pd.read_sql_query(text("""
                    SELECT id, report_date, this_week_issue, remarks 
                    FROM reports WHERE ship_id = :sid AND is_deleted_by_user = FALSE
                    ORDER BY report_date DESC LIMIT 10
                """), conn, params={"sid": ship_id})

            if not h_df.empty:
                for idx, row in h_df.iterrows():
                    with st.expander(f"📅 {row['report_date']} 内容详情"):
                        is_today = (row['report_date'] == datetime.now().date())

                        if st.session_state.editing_id == row['id']:
                            # 编辑模式 (仅限当天)
                            new_t = st.text_area("修改内容", value=row['this_week_issue'], key=f"e_{row['id']}")
                            if st.button("💾 保存", key=f"s_{row['id']}"):
                                with get_engine().begin() as conn:
                                    conn.execute(text("UPDATE reports SET this_week_issue = :t WHERE id = :id"),
                                                 {"t": new_t, "id": row['id']})
                                st.session_state.editing_id = None
                                st.rerun()
                        else:
                            # 竖列序号显示
                            items = [f"{i + 1}. {x.strip()}" for i, x in enumerate(row['this_week_issue'].split('\n'))
                                     if x.strip()]
                            st.text("\n".join(items))
                            st.caption(f"备注: {row['remarks']}")

                            c1, c2 = st.columns(2)
                            with c1:
                                if is_today and st.button("✏️ 修改", key=f"eb_{row['id']}"):
                                    st.session_state.editing_id = row['id']
                                    st.rerun()
                            with c2:
                                if st.button("🗑️ 删除", key=f"db_{row['id']}"):
                                    st.session_state.confirm_del_id = row['id']

                # 用户删除二次确认
                if st.session_state.confirm_del_id:
                    st.warning(f"确定隐藏此记录 (ID: {st.session_state.confirm_del_id})？")
                    if st.button("🔥 确认隐藏", key="u_del_confirm"):
                        with get_engine().begin() as conn:
                            conn.execute(text("UPDATE reports SET is_deleted_by_user = TRUE WHERE id = :id"),
                                         {"id": st.session_state.confirm_del_id})
                        st.session_state.confirm_del_id = None
                        st.rerun()
            else:
                st.info("暂无记录")

        # C. 填报板块 (提交后自动清除)
        with col_r:
            st.subheader(f"✍️ 填报 - {selected_ship}")
            if ship_id not in st.session_state.drafts: st.session_state.drafts[ship_id] = ""

            issue_val = st.text_area("问题描述 (换行分条):", value=st.session_state.drafts[ship_id], height=400,
                                     key=f"ta_{ship_id}")
            st.session_state.drafts[ship_id] = issue_val
            rem_val = st.text_input("备注", key=f"rem_{ship_id}")

            if st.button("🚀 提交数据", use_container_width=True):
                if issue_val.strip():
                    with get_engine().begin() as conn:
                        conn.execute(text(
                            "INSERT INTO reports (ship_id, report_date, this_week_issue, remarks) VALUES (:sid, :dt, :iss, :rem)"),
                                     {"sid": ship_id, "dt": datetime.now().date(), "iss": issue_val, "rem": rem_val})
                    st.success("提交成功！已清空填报框。")
                    st.session_state.drafts[ship_id] = ""  # 自动清除文字
                    st.rerun()

        # D. 底部导航按钮
        st.divider()
        n1, n2, n3 = st.columns([1, 4, 1])
        with n1:
            if st.button("⬅️ 上一艘船", use_container_width=True):
                st.session_state.ship_index = (st.session_state.ship_index - 1) % len(ships_df)
                st.rerun()
        with n3:
            if st.button("下一艘船 ➡️", use_container_width=True):
                st.session_state.ship_index = (st.session_state.ship_index + 1) % len(ships_df)
                st.rerun()

# --- Tab 2: 管理员控制台 (全选与物理删除) ---
if st.session_state.role == 'admin':
    with tabs[1]:
        st.subheader("🔍 记录管理 (负责人名/备注可见)")
        with get_engine().connect() as conn:
            m_df = pd.read_sql_query(text("""
                SELECT r.id, s.manager_name as "负责人", s.ship_name as "船名", 
                       r.report_date as "日期", r.this_week_issue as "内容", r.remarks as "备注"
                FROM reports r JOIN ships s ON r.ship_id = s.id ORDER BY r.report_date DESC
            """), conn)

        if not m_df.empty:
            m_df.insert(0, "选择", False)
            if st.checkbox("全选所有记录"): m_df["选择"] = True

            ed_df = st.data_editor(m_df, hide_index=True, use_container_width=True)
            to_del = ed_df[ed_df["选择"] == True]["id"].tolist()

            if to_del:
                if st.button(f"🔥 物理删除选中的 {len(to_del)} 项"):
                    st.session_state.admin_confirm = True

                if st.session_state.admin_confirm:
                    st.error("🚨 警告：数据将被永久抹除！")
                    if st.button("确认无误，执行物理删除"):
                        with get_engine().begin() as conn:
                            conn.execute(text("DELETE FROM reports WHERE id IN :ids"), {"ids": tuple(to_del)})
                        st.session_state.admin_confirm = False
                        st.rerun()
        else:
            st.info("无记录")

# --- Tab 3: 报表导出 ---
with tabs[2]:
    st.subheader("📂 智能报表生成")
    r_c1, r_c2 = st.columns(2)
    with r_c1:
        date_sel = st.date_input("选择范围", value=[datetime.now() - timedelta(days=7), datetime.now()])
    with r_c2:
        t = datetime.now().date()
        mon = t - timedelta(days=t.weekday())
        fri = mon + timedelta(days=4)
        if st.button(f"📅 一键选定本周工作日 ({mon} ~ {fri})"):
            st.info("已选定范围。")

    if st.session_state.role == 'admin':
        b1, b2 = st.columns(2)
        with b1:
            st.button("📊 生成汇总 Excel")
        with b2:
            st.button("📽️ 生成汇总 PPT")
    else:
        st.button("📊 下载我的填报 Excel")