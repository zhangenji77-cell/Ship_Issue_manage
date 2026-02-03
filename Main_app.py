import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import sqlalchemy
from sqlalchemy import text

# --- 1. 基础页面配置 ---
st.set_page_config(page_title="Trust Ship 船舶管理系统", layout="wide", page_icon="🚢")

# 初始化 Session 状态 (仅限当前页面生命周期)
if 'logged_in' not in st.session_state: st.session_state.logged_in = False
if 'username' not in st.session_state: st.session_state.username = None
if 'role' not in st.session_state: st.session_state.role = None
if 'drafts' not in st.session_state: st.session_state.drafts = {}
if 'ship_index' not in st.session_state: st.session_state.ship_index = 0
if 'editing_id' not in st.session_state: st.session_state.editing_id = None
if 'confirm_del_id' not in st.session_state: st.session_state.confirm_del_id = None


@st.cache_resource
def get_engine():
    # 确保在 .streamlit/secrets.toml 中配置了 postgres_url
    return sqlalchemy.create_engine(st.secrets["postgres_url"])


# --- 2. 登录界面逻辑 ---
def login_ui():
    st.title("🔒 Trust Ship 系统登录")
    st.info("提示：系统不保存登录状态，刷新页面需重新验证。")
    with st.form("login_form"):
        u_in = st.text_input("用户名 (Username)")
        p_in = st.text_input("密码 (Password)", type="password")
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
                    st.error("❌ 验证失败，请检查账号密码")


# 权限拦截
if not st.session_state.logged_in:
    login_ui()
    st.stop()

# --- 3. 登录后的内容 ---

# 侧边栏：显示身份与登出
st.sidebar.title(f"👤 {st.session_state.username}")
st.sidebar.write(f"当前角色: `{st.session_state.role}`")
if st.sidebar.button("🚪 安全退出"):
    st.session_state.logged_in = False
    st.rerun()


# 获取当前用户的船舶列表
@st.cache_data(ttl=60)
def get_my_ships(role, user):
    with get_engine().connect() as conn:
        if role == 'admin':
            return pd.read_sql_query(text("SELECT id, ship_name FROM ships ORDER BY ship_name"), conn)
        return pd.read_sql_query(text("SELECT id, ship_name FROM ships WHERE manager_name = :u ORDER BY ship_name"),
                                 conn, params={"u": user})


ships_df = get_my_ships(st.session_state.role, st.session_state.username)

# --- 4. 选项卡布局 (Tabs 定义) ---
tabs_list = ["📝 船舶问题填报"]
if st.session_state.role == 'admin':
    tabs_list.append("🛠️ 管理员控制台")
tabs_list.append("📂 报表导出")
tabs = st.tabs(tabs_list)

# --- Tab 1: 填报与历史 ---
with tabs[0]:
    if ships_df.empty:
        st.warning("⚠️ 暂无分配船舶，请联系系统管理员。")
    else:
        # 船舶选择
        selected_ship = st.selectbox("🚢 选择船舶", ships_df['ship_name'].tolist(), index=st.session_state.ship_index)
        ship_id = int(ships_df[ships_df['ship_name'] == selected_ship]['id'].iloc[0])

        st.divider()
        col_hist, col_input = st.columns([1.2, 1])

        # A. 历史记录 (回溯最近 10 条)
        with col_hist:
            st.subheader("📊 历史记录回溯")
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
                            # 编辑模式
                            new_val = st.text_area("修改填报:", value=row['this_week_issue'], key=f"e_{row['id']}")
                            if st.button("💾 保存", key=f"s_{row['id']}"):
                                with get_engine().begin() as conn:
                                    conn.execute(text("UPDATE reports SET this_week_issue = :t WHERE id = :id"),
                                                 {"t": new_val, "id": row['id']})
                                st.session_state.editing_id = None
                                st.rerun()
                        else:
                            # 竖排序号显示
                            lines = [f"{i + 1}. {l.strip()}" for i, l in enumerate(row['this_week_issue'].split('\n'))
                                     if l.strip()]
                            st.text("\n".join(lines))
                            st.caption(f"备注: {row['remarks']}")

                            c1, c2 = st.columns(2)
                            with c1:
                                if is_today and st.button("✏️ 修改", key=f"eb_{row['id']}"):
                                    st.session_state.editing_id = row['id']
                                    st.rerun()
                            with c2:
                                if st.button("🗑️ 删除", key=f"db_{row['id']}"):
                                    st.session_state.confirm_del_id = row['id']

                # 二次确认删除 (带取消)
                if st.session_state.confirm_del_id:
                    st.warning(f"⚠️ 确定隐藏此记录 (ID: {st.session_state.confirm_del_id})？")
                    b1, b2 = st.columns(2)
                    with b1:
                        if st.button("❌ 取消", key="u_cancel"):
                            st.session_state.confirm_del_id = None
                            st.rerun()
                    with b2:
                        if st.button("🔥 确认", key="u_confirm"):
                            with get_engine().begin() as conn:
                                conn.execute(text("UPDATE reports SET is_deleted_by_user = TRUE WHERE id = :id"),
                                             {"id": st.session_state.confirm_del_id})
                            st.session_state.confirm_del_id = None
                            st.rerun()
            else:
                st.info("暂无历史记录。")

        # B. 填报板块
        with col_input:
            st.subheader(f"✍️ 填报 - {selected_ship}")
            if ship_id not in st.session_state.drafts: st.session_state.drafts[ship_id] = ""
            issue_val = st.text_area("描述问题 (换行分条):", value=st.session_state.drafts[ship_id], height=400,
                                     key=f"ta_{ship_id}")
            st.session_state.drafts[ship_id] = issue_val
            remark_val = st.text_input("备注 (选填)", key=f"rem_{ship_id}")

            if st.button("🚀 提交数据", use_container_width=True):
                if issue_val.strip():
                    with get_engine().begin() as conn:
                        conn.execute(text(
                            "INSERT INTO reports (ship_id, report_date, this_week_issue, remarks) VALUES (:sid, :dt, :iss, :rem)"),
                                     {"sid": ship_id, "dt": datetime.now().date(), "iss": issue_val, "rem": remark_val})
                    st.success("✅ 提交成功！")
                    st.session_state.drafts[ship_id] = ""
                    st.rerun()

        # C. 底部切船
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

# --- Tab 2: 管理员控制台 (全选删除) ---
if st.session_state.role == 'admin':
    with tabs[1]:
        st.subheader("🔍 管理员全局视图")
        with get_engine().connect() as conn:
            m_df = pd.read_sql_query(text(
                "SELECT r.id, s.manager_name, s.ship_name, r.report_date, r.this_week_issue FROM reports r JOIN ships s ON r.ship_id = s.id ORDER BY r.report_date DESC"),
                                     conn)

        if not m_df.empty:
            m_df.insert(0, "选择", False)
            if st.checkbox("全选"): m_df["选择"] = True
            ed_df = st.data_editor(m_df, hide_index=True, use_container_width=True)
            to_del = ed_df[ed_df["选择"] == True]["id"].tolist()
            if to_del and st.button("🗑️ 执行物理删除"):
                with get_engine().begin() as conn:
                    conn.execute(text("DELETE FROM reports WHERE id IN :ids"), {"ids": tuple(to_del)})
                st.rerun()

# --- Tab 3: 报表导出 ---
with tabs[-1]:
    st.subheader("📂 报表导出")
    st.date_input("选择范围", value=[datetime.now() - timedelta(days=7), datetime.now()])
    st.button("📊 生成全员工作日 Excel 汇总")