import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import sqlalchemy
from sqlalchemy import text

# --- 1. 页面配置 ---
st.set_page_config(page_title="Trust Ship 船舶管理系统", layout="wide", page_icon="🚢")

# 初始化状态
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
if 'drafts' not in st.session_state:
    st.session_state.drafts = {}
if 'ship_index' not in st.session_state:
    st.session_state.ship_index = 0
if 'confirm_delete_id' not in st.session_state:
    st.session_state.confirm_delete_id = None


@st.cache_resource
def get_engine():
    return sqlalchemy.create_engine(st.secrets["postgres_url"])


# --- 2. 登录逻辑 ---
if not st.session_state.logged_in:
    st.title("🔒 Trust Ship 系统登录")
    with st.form("login"):
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
                    st.rerun()
                else:
                    st.error("账号或密码错误")
    st.stop()

# --- 3. 侧边栏 ---
st.sidebar.title(f"👤 {st.session_state.username}")
if st.sidebar.button("登出"):
    st.session_state.logged_in = False
    st.rerun()


# --- 4. 数据获取 ---
@st.cache_data(ttl=60)
def get_ships_list(role, user):
    with get_engine().connect() as conn:
        if role == 'admin':
            return pd.read_sql_query(text("SELECT id, ship_name FROM ships ORDER BY ship_name"), conn)
        return pd.read_sql_query(text("SELECT id, ship_name FROM ships WHERE manager_name = :u ORDER BY ship_name"),
                                 conn, params={"u": user})


ships_df = get_ships_list(st.session_state.role, st.session_state.username)

# --- 5. 选项卡定义 ---
tabs_list = ["📝 本周填报与查询"]
if st.session_state.role == 'admin':
    tabs_list.append("🛠️ 管理员控制台")
tabs_list.append("📂 报表与会议材料")
current_tab = st.tabs(tabs_list)

# --- Tab 1: 填报与历史 ---
with current_tab[0]:
    if ships_df.empty:
        st.warning("暂无船舶分配。")
    else:
        # 优化2：切船功能
        col_nav1, col_nav2, col_nav3 = st.columns([1, 4, 1])
        with col_nav1:
            if st.button("⬅️ 上一艘", use_container_width=True):
                st.session_state.ship_index = (st.session_state.ship_index - 1) % len(ships_df)
        with col_nav3:
            if st.button("下一艘 ➡️", use_container_width=True):
                st.session_state.ship_index = (st.session_state.ship_index + 1) % len(ships_df)

        selected_ship_name = st.selectbox("当前选定船舶", ships_df['ship_name'].tolist(),
                                          index=st.session_state.ship_index)
        ship_id = int(ships_df[ships_df['ship_name'] == selected_ship_name]['id'].iloc[0])

        st.divider()
        c1, c2 = st.columns([1, 1.2])

        # 优化1 & 3: 填报板块与历史显示
        with c1:
            st.subheader("📊 历史记录回溯")
            with get_engine().connect() as conn:
                # 优化4: 员工只能看到没被自己“删除”的记录
                h_query = text("""
                    SELECT id, report_date, this_week_issue, remarks 
                    FROM reports 
                    WHERE ship_id = :sid AND is_deleted_by_user = FALSE
                    ORDER BY report_date DESC
                """)
                h_df = pd.read_sql_query(h_query, conn, params={"sid": ship_id})

            if not h_df.empty:
                for idx, row in h_df.iterrows():
                    with st.expander(f"📅 {row['report_date']} 的填报内容"):
                        # 优化3：内容按照序号竖列显示
                        issues = row['this_week_issue'].split('\n')
                        formatted_issue = "\n".join(
                            [f"{i + 1}. {item.strip()}" for i, item in enumerate(issues) if item.strip()])
                        st.text(formatted_issue)
                        st.caption(f"备注: {row['remarks']}")

                        # 优化4：员工端二次确认删除
                        if st.button(f"🗑️ 删除此条记录", key=f"del_{row['id']}"):
                            st.session_state.confirm_delete_id = row['id']

                if st.session_state.confirm_delete_id:
                    st.warning("⚠️ 确定删除此记录吗？管理员端仍会保留备份。")
                    if st.button("🔥 确认执行"):
                        with get_engine().begin() as conn:
                            conn.execute(text("UPDATE reports SET is_deleted_by_user = TRUE WHERE id = :id"),
                                         {"id": st.session_state.confirm_delete_id})
                        st.success("已移除显示")
                        st.session_state.confirm_delete_id = None
                        st.rerun()

        with c2:
            st.subheader(f"✍️ 填报区域 - {selected_ship_name}")
            if ship_id not in st.session_state.drafts: st.session_state.drafts[ship_id] = ""

            # 优化1：填写框自动清空逻辑
            issue_input = st.text_area("船舶问题描述 (每条换行):", value=st.session_state.drafts[ship_id], height=400,
                                       key=f"area_{ship_id}")
            st.session_state.drafts[ship_id] = issue_input
            rem_input = st.text_input("备注", key=f"rem_{ship_id}")

            if st.button("🚀 提交数据", use_container_width=True):
                if issue_input.strip():
                    with get_engine().begin() as conn:
                        conn.execute(text(
                            "INSERT INTO reports (ship_id, report_date, this_week_issue, remarks) VALUES (:sid, :dt, :iss, :rem)"),
                                     {"sid": ship_id, "dt": datetime.now().date(), "iss": issue_input,
                                      "rem": rem_input})
                    st.success("提交成功！")
                    # 关键优化：清空草稿
                    st.session_state.drafts[ship_id] = ""
                    st.rerun()

# --- Tab 2: 管理员控制台 ---
if st.session_state.role == 'admin':
    with current_tab[1]:
        st.subheader("🔍 填报记录管理")
        with get_engine().connect() as conn:
            # 优化5：换成负责人姓名 + 增加备注列
            m_query = text("""
                SELECT r.id, s.manager_name as "负责人", s.ship_name as "船名", 
                       r.report_date as "日期", r.this_week_issue as "内容", r.remarks as "备注"
                FROM reports r JOIN ships s ON r.ship_id = s.id 
                ORDER BY r.report_date DESC
            """)
            m_df = pd.read_sql_query(m_query, conn)

        if not m_df.empty:
            st.dataframe(m_df, use_container_width=True, hide_index=True)
            if st.button("🗑️ 物理删除所有选定数据"):
                st.info("请使用勾选框逻辑（如需集成请告知）")

# --- Tab 3: 报表导出 ---
with current_tab[-1]:
    st.subheader("📂 导出选项")
    # 优化3：权限差异化按钮
    if st.session_state.role == 'admin':
        c_ex1, c_ex2 = st.columns(2)
        with c_ex1:
            st.button("📊 生成全员 Excel 汇总")
        with c_ex2:
            st.button("📽️ 生成会议 PPT 演示稿")
    else:
        st.button("📊 下载我的个人填报 Excel")