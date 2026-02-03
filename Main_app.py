import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import sqlalchemy
from sqlalchemy import text
import extra_streamlit_components as stx
import time

# --- 1. 基础页面配置 ---
st.set_page_config(page_title="Trust Ship 船舶管理系统", layout="wide", page_icon="🚢")

# 初始化 Session 状态
if 'drafts' not in st.session_state: st.session_state.drafts = {}
if 'ship_index' not in st.session_state: st.session_state.ship_index = 0
if 'editing_id' not in st.session_state: st.session_state.editing_id = None
if 'confirm_del_id' not in st.session_state: st.session_state.confirm_del_id = None
if 'admin_confirm' not in st.session_state: st.session_state.admin_confirm = False


# ✅ 关键修复：CookieManager 绝对不能加 @st.cache_resource
def get_manager():
    return stx.CookieManager(key="trust_ship_v8")


cookie_manager = get_manager()


@st.cache_resource
def get_engine():
    # 需在 st.secrets 中配置 postgres_url
    return sqlalchemy.create_engine(st.secrets["postgres_url"])


# --- 2. 增强型身份同步 (解决刷新掉线问题) ---
def sync_auth():
    if st.session_state.get('logged_in'):
        return True

    # 给浏览器 JS 足够的“握手”时间
    with st.empty():
        for _ in range(15):  # 尝试轮询 15 次
            all_cookies = cookie_manager.get_all()
            if not all_cookies:
                time.sleep(0.1)
                continue

            session_data = all_cookies.get("trust_session")
            if session_data and "|" in session_data:
                try:
                    u, r = session_data.split("|")
                    st.session_state.logged_in = True
                    st.session_state.username = u
                    st.session_state.role = r
                    st.rerun()
                    return True
                except:
                    break
            else:
                break
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
                    # 写入合并 Cookie (7天有效)
                    cookie_manager.set("trust_session", f"{u}|{res[0]}",
                                       expires_at=datetime.now() + timedelta(days=7))
                    st.rerun()
                else:
                    st.error("❌ 用户名或密码错误")


# 执行验证流
if not sync_auth():
    login_ui()
    st.stop()

# --- 3. 侧边栏 ---
st.sidebar.title(f"👤 {st.session_state.username}")
if st.sidebar.button("🚪 安全登出"):
    st.session_state.logged_in = False
    cookie_manager.delete("trust_session")
    st.rerun()


# 获取所属船舶 (50 艘船权限隔离)
@st.cache_data(ttl=60)
def get_ships(role, user):
    with get_engine().connect() as conn:
        if role == 'admin':
            return pd.read_sql_query(text("SELECT id, ship_name FROM ships ORDER BY ship_name"), conn)
        return pd.read_sql_query(text("SELECT id, ship_name FROM ships WHERE manager_name = :u ORDER BY ship_name"),
                                 conn, params={"u": user})


ships_df = get_ships(st.session_state.role, st.session_state.username)

# --- 4. 严格权限选项卡布局 ---
tabs_list = ["📝 数据填报与查询"]
if st.session_state.role == 'admin':
    tabs_list.append("🛠️ 管理员控制台")
tabs_list.append("📂 报表导出")
tabs = st.tabs(tabs_list)

# --- Tab 1: 数据填报与历史回溯 ---
with tabs[0]:
    if ships_df.empty:
        st.warning("⚠️ 暂无分配船舶，请联系 Admin。")
    else:
        # 船舶选择
        selected_ship = st.selectbox("🚢 选择船舶", ships_df['ship_name'].tolist(), index=st.session_state.ship_index)
        ship_id = int(ships_df[ships_df['ship_name'] == selected_ship]['id'].iloc[0])

        st.divider()
        col_l, col_r = st.columns([1.2, 1])

        # A. 历史板块
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
                    with st.expander(f"📅 {row['report_date']} 内容详情"):
                        is_today = (row['report_date'] == datetime.now().date())

                        if st.session_state.editing_id == row['id']:
                            # 编辑模式
                            new_text = st.text_area("编辑内容", value=row['this_week_issue'], key=f"e_{row['id']}")
                            if st.button("💾 保存", key=f"s_{row['id']}"):
                                with get_engine().begin() as conn:
                                    conn.execute(text("UPDATE reports SET this_week_issue = :t WHERE id = :id"),
                                                 {"t": new_text, "id": row['id']})
                                st.session_state.editing_id = None
                                st.rerun()
                        else:
                            # 竖向序号显示
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

                # 二次确认删除 (带取消按钮)
                if st.session_state.confirm_del_id:
                    st.warning(f"⚠️ 确定从您的视图中隐藏记录 (ID: {st.session_state.confirm_del_id})？")
                    cd1, cd2 = st.columns(2)
                    with cd1:
                        if st.button("❌ 取消操作", key="u_cancel"):
                            st.session_state.confirm_del_id = None
                            st.rerun()
                    with cd2:
                        if st.button("🔥 确认隐藏", key="u_confirm"):
                            with get_engine().begin() as conn:
                                conn.execute(text("UPDATE reports SET is_deleted_by_user = TRUE WHERE id = :id"),
                                             {"id": st.session_state.confirm_del_id})
                            st.session_state.confirm_del_id = None
                            st.rerun()
            else:
                st.info("暂无记录")

        # B. 填报板块 (提交后清除)
        with col_r:
            st.subheader(f"✍️ 填报 - {selected_ship}")
            if ship_id not in st.session_state.drafts: st.session_state.drafts[ship_id] = ""

            issue_val = st.text_area("问题详情:", value=st.session_state.drafts[ship_id], height=400,
                                     key=f"ta_{ship_id}")
            st.session_state.drafts[ship_id] = issue_val
            remark_val = st.text_input("备注", key=f"rem_{ship_id}")

            if st.button("🚀 提交本周数据", use_container_width=True):
                if issue_val.strip():
                    with get_engine().begin() as conn:
                        conn.execute(text(
                            "INSERT INTO reports (ship_id, report_date, this_week_issue, remarks) VALUES (:sid, :dt, :iss, :rem)"),
                                     {"sid": ship_id, "dt": datetime.now().date(), "iss": issue_val, "rem": remark_val})
                    st.success("✅ 提交成功！已清空填报区。")
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

# --- Tab 2: 管理员控制台 (全选删除 + 负责人显示) ---
if st.session_state.role == 'admin':
    with tabs[1]:
        st.subheader("🔍 记录管理")
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

                if st.session_state.admin_confirm:
                    st.error("🚨 警告：数据将被永久抹除！")
                    ac1, ac2 = st.columns(2)
                    with ac1:
                        if st.button("❌ 取消删除"):
                            st.session_state.admin_confirm = False
                            st.rerun()
                    with ac2:
                        if st.button("🔥 确认执行物理删除"):
                            with get_engine().begin() as conn:
                                conn.execute(text("DELETE FROM reports WHERE id IN :ids"), {"ids": tuple(to_del_ids)})
                            st.session_state.admin_confirm = False
                            st.rerun()

# --- Tab 3: 报表导出 ---
with tabs[-1]:
    st.subheader("📂 智能报表生成")
    r1, r2 = st.columns(2)
    with r1:
        date_sel = st.date_input("选择报表日期范围", value=[datetime.now() - timedelta(days=7), datetime.now()])
    with r2:
        t = datetime.now().date()
        mon = t - timedelta(days=t.weekday())
        fri = mon + timedelta(days=4)
        if st.button(f"📅 一键选取本周工作日 ({mon} ~ {fri})"):
            st.info("已选定。")

    if st.session_state.role == 'admin':
        st.button("📊 生成汇总 Excel")
        st.button("📽️ 生成会议 PPT")
    else:
        st.button("📊 下载我的填报 Excel")