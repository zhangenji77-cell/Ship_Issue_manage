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


# ✅ 关键：组件初始化必须在最外层，Key 必须全局唯一
def get_manager():
    return stx.CookieManager(key="trust_ship_v11_final")


cookie_manager = get_manager()


@st.cache_resource
def get_engine():
    # 请确保在 .streamlit/secrets.toml 中配置了 postgres_url
    return sqlalchemy.create_engine(st.secrets["postgres_url"])


# --- 2. 增强型身份同步 (修复重复 Key 与刷新掉线) ---
def sync_auth():
    if st.session_state.get('logged_in'):
        return True

    # ✅ 核心修复：单点读取 Cookie，绝不在循环内调用
    all_cookies = cookie_manager.get_all()

    # 如果此时浏览器还未传回 Cookie，则通过重刷机制等待
    if not all_cookies:
        if 'retry_count' not in st.session_state:
            st.session_state.retry_count = 0

        if st.session_state.retry_count < 10:
            st.session_state.retry_count += 1
            time.sleep(0.1)  # 短暂等待
            st.rerun()  # 触发重刷，给 JS 组件握手时间
        return False

    # 握手成功，重置计数器
    st.session_state.retry_count = 0
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
                    # ✅ 核心修复：登录前物理清空内存，防止 Mike 看到 Thein 的旧数据
                    st.session_state.clear()
                    st.session_state.logged_in = True
                    st.session_state.username = u_in
                    st.session_state.role = res[0]
                    # 写入合并后的唯一 Cookie
                    cookie_manager.set("trust_session", f"{u_in}|{res[0]}",
                                       expires_at=datetime.now() + timedelta(days=7))
                    st.rerun()
                else:
                    st.error("❌ 验证失败，请核对账号密码")


# 执行验证流
if not sync_auth():
    login_ui()
    st.stop()

# --- 3. 侧边栏与登出 ---
st.sidebar.title(f"👤 {st.session_state.username}")
if st.sidebar.button("🚪 安全注销并登出"):
    st.session_state.clear()
    cookie_manager.delete("trust_session")
    st.rerun()


# 获取船舶列表 (严格基于当前用户名进行 SQL 过滤)
@st.cache_data(ttl=30)
def get_my_ships(role, user):
    with get_engine().connect() as conn:
        if role == 'admin':
            return pd.read_sql_query(text("SELECT id, ship_name FROM ships ORDER BY ship_name"), conn)
        return pd.read_sql_query(text("SELECT id, ship_name FROM ships WHERE manager_name = :u ORDER BY ship_name"),
                                 conn, params={"u": user})


ships_df = get_my_ships(st.session_state.role, st.session_state.username)

# --- 4. 权限隔离选项卡 ---
tabs_list = ["📝 船舶填报与历史回溯"]
if st.session_state.role == 'admin':
    tabs_list.append("🛠️ 管理员控制台")
tabs_list.append("📂 报表导出")
tabs = st.tabs(tabs_list)

# --- Tab 1: 填报与历史回溯 ---
with tabs[0]:
    if ships_df.empty:
        st.warning("⚠️ 暂无分配船舶，请联系系统管理员。")
    else:
        # 船舶选择
        selected_ship = st.selectbox("🚢 选择当前处理船舶", ships_df['ship_name'].tolist(),
                                     index=st.session_state.ship_index)
        ship_id = int(ships_df[ships_df['ship_name'] == selected_ship]['id'].iloc[0])

        st.divider()
        col_hist, col_input = st.columns([1.2, 1])

        # A. 历史记录 (带序号、当天修改及取消功能的二次确认)
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
                            new_val = st.text_area("修改填报内容:", value=row['this_week_issue'],
                                                   key=f"edit_{row['id']}")
                            if st.button("💾 保存更新", key=f"save_{row['id']}"):
                                with get_engine().begin() as conn:
                                    conn.execute(text("UPDATE reports SET this_week_issue = :t WHERE id = :id"),
                                                 {"t": new_val, "id": row['id']})
                                st.session_state.editing_id = None
                                st.rerun()
                        else:
                            # 竖向带序号显示
                            items = [f"{i + 1}. {x.strip()}" for i, x in enumerate(row['this_week_issue'].split('\n'))
                                     if x.strip()]
                            st.text("\n".join(items))
                            st.caption(f"备注: {row['remarks']}")

                            c_btn1, c_btn2 = st.columns(2)
                            with c_btn1:
                                if is_today and st.button("✏️ 修改 (仅限当天)", key=f"e_btn_{row['id']}"):
                                    st.session_state.editing_id = row['id']
                                    st.rerun()
                            with c_btn2:
                                if st.button("🗑️ 删除记录", key=f"d_btn_{row['id']}"):
                                    st.session_state.confirm_del_id = row['id']

                # 用户删除二次确认 (含取消)
                if st.session_state.confirm_del_id:
                    st.warning(f"确定隐藏此记录 (ID: {st.session_state.confirm_del_id})？")
                    cd1, cd2 = st.columns(2)
                    with cd1:
                        if st.button("❌ 取消操作", key="u_cancel"):
                            st.session_state.confirm_del_id = None
                            st.rerun()
                    with cd2:
                        if st.button("🔥 确认执行", key="u_confirm"):
                            with get_engine().begin() as conn:
                                conn.execute(text("UPDATE reports SET is_deleted_by_user = TRUE WHERE id = :id"),
                                             {"id": st.session_state.confirm_del_id})
                            st.session_state.confirm_del_id = None
                            st.rerun()
            else:
                st.info("该船暂无历史记录。")

        # B. 填报板块 (提交后自动清空)
        with col_input:
            st.subheader(f"✍️ 填报 - {selected_ship}")
            if ship_id not in st.session_state.drafts: st.session_state.drafts[ship_id] = ""

            # 使用 session_state 确保文字实时存留
            issue_text = st.text_area("本周问题描述 (分条填写):", value=st.session_state.drafts[ship_id], height=400,
                                      key=f"ta_{ship_id}")
            st.session_state.drafts[ship_id] = issue_text
            remark_text = st.text_input("备注 (选填)", key=f"rem_{ship_id}")

            if st.button("🚀 提交本周数据", use_container_width=True):
                if issue_text.strip():
                    with get_engine().begin() as conn:
                        conn.execute(text(
                            "INSERT INTO reports (ship_id, report_date, this_week_issue, remarks) VALUES (:sid, :dt, :iss, :rem)"),
                                     {"sid": ship_id, "dt": datetime.now().date(), "iss": issue_text,
                                      "rem": remark_text})
                    st.success("✅ 提交成功！已重置填报区。")
                    st.session_state.drafts[ship_id] = ""  # 清空
                    st.rerun()

        # C. 底部页面导航
        st.divider()
        nav_prev, nav_center, nav_next = st.columns([1, 4, 1])
        with nav_prev:
            if st.button("⬅️ 上一艘船", use_container_width=True):
                st.session_state.ship_index = (st.session_state.ship_index - 1) % len(ships_df)
                st.rerun()
        with nav_next:
            if st.button("下一艘船 ➡️", use_container_width=True):
                st.session_state.ship_index = (st.session_state.ship_index + 1) % len(ships_df)
                st.rerun()

# --- Tab 2: 管理员控制台 (物理删除 + 全选) ---
if st.session_state.get('role') == 'admin':
    with tabs[1]:
        st.subheader("🔍 历史填报全局管理")
        with get_engine().connect() as conn:
            m_df = pd.read_sql_query(text("""
                SELECT r.id, s.manager_name as "负责人", s.ship_name as "船名", 
                       r.report_date as "日期", r.this_week_issue as "问题内容", r.remarks as "备注"
                FROM reports r JOIN ships s ON r.ship_id = s.id ORDER BY r.report_date DESC
            """), conn)

        if not m_df.empty:
            m_df.insert(0, "选择", False)
            if st.checkbox("全选当前页记录"): m_df["选择"] = True

            ed_df = st.data_editor(m_df, hide_index=True, use_container_width=True)
            to_del_ids = ed_df[ed_df["选择"] == True]["id"].tolist()

            if to_del_ids:
                if st.button(f"🗑️ 删除选中的 {len(to_del_ids)} 条记录"):
                    st.session_state.admin_confirm = True

                if st.session_state.admin_confirm:
                    st.error("🚨 警告：数据将被永久从数据库抹除！")
                    ac1, ac2 = st.columns(2)
                    with ac1:
                        if st.button("❌ 取消删除", key="admin_cancel"):
                            st.session_state.admin_confirm = False
                            st.rerun()
                    with ac2:
                        if st.button("🔥 确认物理删除", key="admin_real_del"):
                            with get_engine().begin() as conn:
                                conn.execute(text("DELETE FROM reports WHERE id IN :ids"), {"ids": tuple(to_del_ids)})
                            st.session_state.admin_confirm = False
                            st.rerun()

# --- Tab 3: 报表导出 ---
with tabs[-1]:
    st.subheader("📂 会议与汇总报表生成")
    r_col1, r_col2 = st.columns(2)
    with r_col1:
        date_sel = st.date_input("设定报表范围", value=[datetime.now() - timedelta(days=7), datetime.now()])
    with r_col2:
        t = datetime.now().date()
        mon = t - timedelta(days=t.weekday())
        fri = mon + timedelta(days=4)
        if st.button(f"📅 一键定位本周 ({mon} ~ {fri})"):
            st.info("已选定。")

    if st.session_state.role == 'admin':
        st.button("📊 生成全员 Excel 汇总周报")
        st.button("📽️ 生成会议 PPT 汇总")
    else:
        st.button("📊 下载我的个人 Excel 记录")