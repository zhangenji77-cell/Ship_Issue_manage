import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import sqlalchemy
from sqlalchemy import text
import extra_streamlit_components as stx

# --- 1. 基础配置与 Cookie 管理 ---
st.set_page_config(page_title="Trust Ship 船舶管理系统", layout="wide", page_icon="🚢")


def get_manager():
    # 注意：此处不使用 @st.cache_resource，防止 CachedWidgetWarning
    return stx.CookieManager(key="trust_ship_manager")


cookie_manager = get_manager()

# 初始化 Session State
if 'drafts' not in st.session_state: st.session_state.drafts = {}
if 'ship_index' not in st.session_state: st.session_state.ship_index = 0
if 'editing_id' not in st.session_state: st.session_state.editing_id = None
if 'confirm_del_id' not in st.session_state: st.session_state.confirm_del_id = None


@st.cache_resource
def get_engine():
    return sqlalchemy.create_engine(st.secrets["postgres_url"])


# --- 2. 持久化登录逻辑 ---
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
    with st.form("login_form"):
        u = st.text_input("用户名")
        p = st.text_input("密码", type="password")
        if st.form_submit_button("登录"):
            engine = get_engine()
            with engine.connect() as conn:
                res = conn.execute(text("SELECT role FROM users WHERE username = :u AND password = :p"),
                                   {"u": u, "p": p}).fetchone()
                if res:
                    st.session_state.logged_in = True
                    st.session_state.username = u
                    st.session_state.role = res[0]
                    # 写入 Cookie，有效期 7 天
                    cookie_manager.set("trust_user", u, expires_at=datetime.now() + timedelta(days=7))
                    cookie_manager.set("trust_role", res[0], expires_at=datetime.now() + timedelta(days=7))
                    st.rerun()
                else:
                    st.error("❌ 用户名或密码错误")


if not st.session_state.logged_in:
    login_ui()
    st.stop()

# --- 3. 页面公用部分 ---
st.sidebar.title(f"👤 {st.session_state.username}")
if st.sidebar.button("🚪 安全登出"):
    st.session_state.logged_in = False
    cookie_manager.delete("trust_user")
    cookie_manager.delete("trust_role")
    st.rerun()


# 获取船舶列表
@st.cache_data(ttl=60)
def get_ships(role, user):
    engine = get_engine()
    with engine.connect() as conn:
        if role == 'admin':
            return pd.read_sql_query(text("SELECT id, ship_name FROM ships ORDER BY ship_name"), conn)
        return pd.read_sql_query(text("SELECT id, ship_name FROM ships WHERE manager_name = :u ORDER BY ship_name"),
                                 conn, params={"u": user})


ships_df = get_ships(st.session_state.role, st.session_state.username)

# --- 4. 核心选项卡 ---
tabs = st.tabs(["📝 数据填报与查询", "🛠️ 管理员控制台", "📂 报表导出"])

# --- Tab 1: 数据填报与历史回溯 ---
with tabs[0]:
    if ships_df.empty:
        st.warning("⚠️ 暂无分配船舶。")
    else:
        # 船舶选择
        selected_ship = st.selectbox("🚢 选择船舶", ships_df['ship_name'].tolist(), index=st.session_state.ship_index)
        ship_id = int(ships_df[ships_df['ship_name'] == selected_ship]['id'].iloc[0])

        st.divider()
        col_left, col_right = st.columns([1.2, 1])

        # A. 历史记录 (含当天修改及二次确认删除)
        with col_left:
            st.subheader("📊 历史记录")
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
                            new_text = st.text_area("修改填报内容", value=row['this_week_issue'],
                                                    key=f"edit_{row['id']}")
                            if st.button("💾 保存修改", key=f"save_{row['id']}"):
                                with get_engine().begin() as conn:
                                    conn.execute(text("UPDATE reports SET this_week_issue = :t WHERE id = :id"),
                                                 {"t": new_text, "id": row['id']})
                                st.session_state.editing_id = None
                                st.rerun()
                        else:
                            # 显示模式（带序号）
                            issues = [f"{i + 1}. {x.strip()}" for i, x in enumerate(row['this_week_issue'].split('\n'))
                                      if x.strip()]
                            st.text("\n".join(issues))
                            st.caption(f"备注: {row['remarks']}")

                            c_btn1, c_btn2 = st.columns(2)
                            with c_btn1:
                                if is_today and st.button("✏️ 修改 (仅限当天)", key=f"ebtn_{row['id']}"):
                                    st.session_state.editing_id = row['id']
                                    st.rerun()
                            with c_btn2:
                                if st.button("🗑️ 删除记录", key=f"dbtn_{row['id']}"):
                                    st.session_state.confirm_del_id = row['id']

                # 二次确认逻辑
                if st.session_state.confirm_del_id:
                    st.warning(f"⚠️ 确定删除 ID 为 {st.session_state.confirm_del_id} 的记录吗？")
                    if st.button("🔥 确认删除", key="confirm_real_del"):
                        with get_engine().begin() as conn:
                            conn.execute(text("UPDATE reports SET is_deleted_by_user = TRUE WHERE id = :id"),
                                         {"id": st.session_state.confirm_del_id})
                        st.session_state.confirm_del_id = None
                        st.rerun()
            else:
                st.info("暂无记录。")

        # B. 填报板块 (提交后自动清空)
        with col_right:
            st.subheader(f"✍️ 填报 - {selected_ship}")
            if ship_id not in st.session_state.drafts: st.session_state.drafts[ship_id] = ""

            issue_val = st.text_area("描述本周船舶问题:", value=st.session_state.drafts[ship_id], height=400,
                                     key=f"ta_{ship_id}")
            st.session_state.drafts[ship_id] = issue_val
            remark_val = st.text_input("备注", key=f"rem_{ship_id}")

            if st.button("🚀 提交数据", use_container_width=True):
                if issue_val.strip():
                    with get_engine().begin() as conn:
                        conn.execute(text(
                            "INSERT INTO reports (ship_id, report_date, this_week_issue, remarks) VALUES (:sid, :dt, :iss, :rem)"),
                                     {"sid": ship_id, "dt": datetime.now().date(), "iss": issue_val, "rem": remark_val})
                    st.success("✅ 提交成功！内容已同步至服务器。")
                    st.session_state.drafts[ship_id] = ""  # 清空草稿
                    st.rerun()

        # 底部导航按钮
        st.divider()
        nav1, nav2, nav3 = st.columns([1, 4, 1])
        with nav1:
            if st.button("⬅️ 上一艘船", use_container_width=True):
                st.session_state.ship_index = (st.session_state.ship_index - 1) % len(ships_df)
                st.rerun()
        with nav3:
            if st.button("下一艘船 ➡️", use_container_width=True):
                st.session_state.ship_index = (st.session_state.ship_index + 1) % len(ships_df)
                st.rerun()

# --- Tab 2: 管理员控制台 ---
if st.session_state.role == 'admin':
    with tabs[1]:
        st.subheader("🗑️ 填报记录管理 (全选删除)")
        with get_engine().connect() as conn:
            m_df = pd.read_sql_query(text("""
                SELECT r.id, s.manager_name as "负责人", s.ship_name as "船名", 
                       r.report_date as "日期", r.this_week_issue as "内容", r.remarks as "备注"
                FROM reports r JOIN ships s ON r.ship_id = s.id 
                ORDER BY r.report_date DESC
            """), conn)

        if not m_df.empty:
            m_df.insert(0, "选择", False)
            if st.checkbox("全选所有内容"): m_df["选择"] = True

            edited_m = st.data_editor(m_df, hide_index=True, use_container_width=True)
            to_del = edited_m[edited_m["选择"] == True]["id"].tolist()

            if to_del:
                if st.button(f"🔥 彻底物理删除选中的 {len(to_del)} 条数据"):
                    st.session_state.admin_confirm = True

                if st.session_state.get('admin_confirm'):
                    st.error("🚨 警告：数据将被永久抹除！")
                    if st.button("确认无误，执行物理删除"):
                        with get_engine().begin() as conn:
                            conn.execute(text("DELETE FROM reports WHERE id IN :ids"), {"ids": tuple(to_del)})
                        st.session_state.admin_confirm = False
                        st.rerun()

# --- Tab 3: 报表导出 ---
with tabs[2]:
    st.subheader("📂 报表导出中心")
    c_rpt1, c_rpt2 = st.columns(2)
    with c_rpt1:
        date_range = st.date_input("选择日期范围", value=[datetime.now() - timedelta(days=7), datetime.now()])
    with c_rpt2:
        # 一键周一到周五逻辑
        t = datetime.now().date()
        mon = t - timedelta(days=t.weekday())
        fri = mon + timedelta(days=4)
        if st.button(f"📅 一键选定本周工作日 ({mon} ~ {fri})"):
            st.info("已选定本周数据范围。")

    if st.session_state.role == 'admin':
        b1, b2 = st.columns(2)
        with b1:
            st.button("📊 生成范围内 Excel 汇总")
        with b2:
            st.button("📽️ 生成范围内汇总 PPT")
    else:
        st.button("📊 下载我的填报 Excel")