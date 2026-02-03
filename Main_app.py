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


# 必须在逻辑最开始初始化 CookieManager
@st.cache_resource
def get_manager():
    return stx.CookieManager(key="trust_ship_v6")  # 再次升级 key 以强制浏览器刷新


cookie_manager = get_manager()


@st.cache_resource
def get_engine():
    return sqlalchemy.create_engine(st.secrets["postgres_url"])


# --- 2. 核心优化：防掉线预加载逻辑 ---
def sync_auth():
    # 如果 Session 里已经是 True，说明已经握手成功，直接放行
    if st.session_state.get('logged_in'):
        return True

    # 如果没有登录，尝试从 Cookie 恢复
    # 增加一个 loading 状态，防止 Python 跑得太快
    with st.empty():
        for _ in range(10):  # 最多尝试 10 次，每次等待 0.2 秒
            all_cookies = cookie_manager.get_all()
            if not all_cookies:
                time.sleep(0.2)
                continue

            saved_session = all_cookies.get("trust_session")
            if saved_session and "|" in saved_session:
                try:
                    u, r = saved_session.split("|")
                    st.session_state.logged_in = True
                    st.session_state.username = u
                    st.session_state.role = r
                    st.rerun()  # 发现 Cookie 成功，立即重刷进入主页
                    return True
                except:
                    break
            else:
                # 如果握手完成但确实没有 cookie，说明真没登录
                break
    return False


def login_ui():
    st.title("🔒 Trust Ship 系统登录")
    with st.form("login_form"):
        u = st.text_input("用户名")
        p = st.text_input("密码", type="password")
        if st.form_submit_button("登录"):
            with get_engine().connect() as conn:
                query = text("SELECT role FROM users WHERE username = :u AND password = :p")
                res = conn.execute(query, {"u": u, "p": p}).fetchone()
                if res:
                    st.session_state.logged_in = True
                    st.session_state.username = u
                    st.session_state.role = res[0]
                    # 写入 Cookie
                    cookie_manager.set("trust_session", f"{u}|{res[0]}", expires_at=datetime.now() + timedelta(days=7))
                    st.rerun()
                else:
                    st.error("❌ 验证失败")


# 先检查静默登录，不行再跳登录框
if not sync_auth():
    login_ui()
    st.stop()

# --- 3. 登录后的内容 (以下逻辑保持不变，确保权限隔离) ---
st.sidebar.title(f"👤 {st.session_state.username}")
if st.sidebar.button("🚪 安全登出"):
    st.session_state.logged_in = False
    cookie_manager.delete("trust_session")
    st.rerun()

# 严格的权限过滤逻辑
tabs_list = ["📝 数据填报与查询"]
if st.session_state.get('role') == 'admin':
    tabs_list.append("🛠️ 管理员控制台")
tabs_list.append("📂 报表导出")
current_tab = st.tabs(tabs_list)

# (后续代码... Tab 1, Tab 2 等保持与之前整合的一致)

# --- Tab 1: 数据填报与历史 ---
with current_tab[0]:
    if ships_df.empty:
        st.warning("⚠️ 暂无分配船舶。")
    else:
        # 船舶选择
        selected_ship = st.selectbox("🚢 选择船舶", ships_df['ship_name'].tolist(), index=st.session_state.ship_index)
        ship_id = int(ships_df[ships_df['ship_name'] == selected_ship]['id'].iloc[0])

        st.divider()
        col_l, col_r = st.columns([1.2, 1])

        # A. 历史记录 (含取消功能的二次确认)
        with col_l:
            st.subheader("📊 历史记录回溯")
            with get_engine().connect() as conn:
                h_df = pd.read_sql_query(text("""
                    SELECT id, report_date, this_week_issue, remarks 
                    FROM reports WHERE ship_id = :sid AND is_deleted_by_user = FALSE
                    ORDER BY report_date DESC LIMIT 10
                """), conn, params={"sid": ship_id})

            if not h_df.empty:
                for idx, row in h_df.iterrows():
                    with st.expander(f"📅 {row['report_date']} 内容回溯"):
                        is_today = (row['report_date'] == datetime.now().date())

                        if st.session_state.editing_id == row['id']:
                            # 编辑模式
                            new_text = st.text_area("修改填报:", value=row['this_week_issue'], key=f"e_{row['id']}")
                            if st.button("💾 保存修改", key=f"s_{row['id']}"):
                                with get_engine().begin() as conn:
                                    conn.execute(text("UPDATE reports SET this_week_issue = :t WHERE id = :id"),
                                                 {"t": new_text, "id": row['id']})
                                st.session_state.editing_id = None
                                st.rerun()
                        else:
                            # 竖向列表序号显示
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
                                if st.button("🗑️ 删除记录", key=f"db_{row['id']}"):
                                    st.session_state.confirm_del_id = row['id']

                # ✅ 核心优化：User 删除增加取消按钮
                if st.session_state.confirm_del_id:
                    st.warning(f"⚠️ 确定从您的页面删除此记录 (ID: {st.session_state.confirm_del_id})？")
                    cd_col1, cd_col2 = st.columns(2)
                    with cd_col1:
                        if st.button("❌ 取消操作", key="u_cancel_del", use_container_width=True):
                            st.session_state.confirm_del_id = None
                            st.rerun()
                    with cd_col2:
                        if st.button("🔥 确认删除", key="u_confirm_del", use_container_width=True):
                            with get_engine().begin() as conn:
                                conn.execute(text("UPDATE reports SET is_deleted_by_user = TRUE WHERE id = :id"),
                                             {"id": st.session_state.confirm_del_id})
                            st.session_state.confirm_del_id = None
                            st.rerun()
            else:
                st.info("暂无记录。")

        # B. 填报区域
        with col_r:
            st.subheader(f"✍️ 填报 - {selected_ship}")
            if ship_id not in st.session_state.drafts: st.session_state.drafts[ship_id] = ""

            issue_v = st.text_area("问题详情:", value=st.session_state.drafts[ship_id], height=400, key=f"ta_{ship_id}")
            st.session_state.drafts[ship_id] = issue_v
            remark_v = st.text_input("备注", key=f"rem_{ship_id}")

            if st.button("🚀 提交数据", use_container_width=True):
                if issue_v.strip():
                    with get_engine().begin() as conn:
                        conn.execute(text(
                            "INSERT INTO reports (ship_id, report_date, this_week_issue, remarks) VALUES (:sid, :dt, :iss, :rem)"),
                                     {"sid": ship_id, "dt": datetime.now().date(), "iss": issue_v, "rem": remark_v})
                    st.success("✅ 提交成功！")
                    st.session_state.drafts[ship_id] = ""
                    st.rerun()

        # C. 底部切船按钮
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

# --- Tab 2: 管理员控制台 ---
if st.session_state.role == 'admin':
    with current_tab[1]:
        st.subheader("🔍 全局填报管理")
        with get_engine().connect() as conn:
            m_df = pd.read_sql_query(text("""
                SELECT r.id, s.manager_name as "负责人", s.ship_name as "船名", 
                       r.report_date as "日期", r.this_week_issue as "内容", r.remarks as "备注"
                FROM reports r JOIN ships s ON r.ship_id = s.id ORDER BY r.report_date DESC
            """), conn)

        if not m_df.empty:
            m_df.insert(0, "选择", False)
            if st.checkbox("全选"): m_df["选择"] = True

            ed_df = st.data_editor(m_df, hide_index=True, use_container_width=True)
            to_del_ids = ed_df[ed_df["选择"] == True]["id"].tolist()

            if to_del_ids:
                if st.button(f"🗑️ 删除选中的 {len(to_del_ids)} 条"):
                    st.session_state.admin_confirm = True

                # 管理员二次确认增加取消按钮
                if st.session_state.admin_confirm:
                    st.error(f"🚨 警告：将从数据库永久抹除这 {len(to_del_ids)} 条数据！")
                    ac_col1, ac_col2 = st.columns(2)
                    with ac_col1:
                        if st.button("❌ 取消删除", key="admin_cancel"):
                            st.session_state.admin_confirm = False
                            st.rerun()
                    with ac_col2:
                        if st.button("🔥 确认永久删除", key="admin_real_del"):
                            with get_engine().begin() as conn:
                                conn.execute(text("DELETE FROM reports WHERE id IN :ids"), {"ids": tuple(to_del_ids)})
                            st.session_state.admin_confirm = False
                            st.rerun()

# --- Tab 3: 报表导出 ---
with current_tab[-1]:
    st.subheader("📂 导出中心")
    if st.session_state.role == 'admin':
        st.button("📊 生成全员工作日报表")
    else:
        st.button("📊 下载我的个人填报记录")