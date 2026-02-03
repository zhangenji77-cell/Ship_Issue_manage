import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import sqlalchemy
from sqlalchemy import text

# --- 1. 基础配置 ---
st.set_page_config(page_title="Trust Ship 船舶管理系统", layout="wide", page_icon="🚢")

# 状态初始化
if 'logged_in' not in st.session_state: st.session_state.logged_in = False
if 'drafts' not in st.session_state: st.session_state.drafts = {}
if 'ship_index' not in st.session_state: st.session_state.ship_index = 0
if 'editing_id' not in st.session_state: st.session_state.editing_id = None  # 用于记录正在修改的记录ID


@st.cache_resource
def get_engine():
    return sqlalchemy.create_engine(st.secrets["postgres_url"])


# --- 2. 登录与权限 ---
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
                    st.error("❌ 验证失败")
    st.stop()


# --- 3. 数据抓取 ---
@st.cache_data(ttl=60)
def get_ships_list(role, user):
    with get_engine().connect() as conn:
        if role == 'admin':
            return pd.read_sql_query(text("SELECT id, ship_name FROM ships ORDER BY ship_name"), conn)
        return pd.read_sql_query(text("SELECT id, ship_name FROM ships WHERE manager_name = :u ORDER BY ship_name"),
                                 conn, params={"u": user})


ships_df = get_ships_list(st.session_state.role, st.session_state.username)

# --- 4. 页面选项卡 ---
tabs_list = ["📝 数据填报与查询"]
if st.session_state.role == 'admin':
    tabs_list.append("🛠️ 管理员控制台")
tabs_list.append("📂 报表与会议材料")
current_tab = st.tabs(tabs_list)

# --- Tab 1: 数据填报与历史回溯 ---
with current_tab[0]:
    if ships_df.empty:
        st.warning("⚠️ 暂无分配给您的船舶。")
    else:
        # 选项框联动
        selected_ship_name = st.selectbox("🚢 选择船舶", ships_df['ship_name'].tolist(),
                                          index=st.session_state.ship_index)
        ship_id = int(ships_df[ships_df['ship_name'] == selected_ship_name]['id'].iloc[0])

        st.divider()
        c_left, c_right = st.columns([1.2, 1])

        # A. 历史记录板块
        with c_left:
            st.subheader("📊 历史记录回溯")
            with get_engine().connect() as conn:
                h_query = text("""
                    SELECT id, report_date, this_week_issue, remarks 
                    FROM reports WHERE ship_id = :sid AND is_deleted_by_user = FALSE
                    ORDER BY report_date DESC LIMIT 10
                """)
                h_df = pd.read_sql_query(h_query, conn, params={"sid": ship_id})

            if not h_df.empty:
                for idx, row in h_df.iterrows():
                    with st.expander(f"📅 {row['report_date']} 的填报内容"):
                        # --- 优化4：当天修改权限功能 ---
                        is_today = (row['report_date'] == datetime.now().date())

                        if st.session_state.editing_id == row['id']:
                            # 编辑模式
                            new_text = st.text_area("修改内容", value=row['this_week_issue'],
                                                    key=f"edit_ta_{row['id']}")
                            if st.button("💾 保存修改", key=f"save_{row['id']}"):
                                with get_engine().begin() as conn:
                                    conn.execute(text("UPDATE reports SET this_week_issue = :t WHERE id = :id"),
                                                 {"t": new_text, "id": row['id']})
                                st.session_state.editing_id = None
                                st.rerun()
                        else:
                            # 优化3：内容序号显示
                            issues = [f"{i + 1}. {x.strip()}" for i, x in enumerate(row['this_week_issue'].split('\n'))
                                      if x.strip()]
                            st.text("\n".join(issues))
                            st.caption(f"备注: {row['remarks']}")

                            col_btn1, col_btn2 = st.columns(2)
                            with col_btn1:
                                if is_today and st.button("✏️ 修改 (仅限当天)", key=f"btn_edit_{row['id']}"):
                                    st.session_state.editing_id = row['id']
                                    st.rerun()
                            with col_btn2:
                                # 保持原有的删除并二次确认逻辑
                                if st.button("🗑️ 删除记录", key=f"btn_del_{row['id']}"):
                                    st.session_state.confirm_id = row['id']
            else:
                st.info("暂无记录")

        # B. 填报板块
        with c_right:
            st.subheader(f"✍️ 填报 - {selected_ship_name}")
            if ship_id not in st.session_state.drafts: st.session_state.drafts[ship_id] = ""

            # 优化1 & 3：填写框清空逻辑
            issue_val = st.text_area("问题描述:", value=st.session_state.drafts[ship_id], height=400,
                                     key=f"main_ta_{ship_id}")
            st.session_state.drafts[ship_id] = issue_val  # 实时存草稿

            if st.button("🚀 提交本周数据", use_container_width=True):
                if issue_val.strip():
                    with get_engine().begin() as conn:
                        conn.execute(text(
                            "INSERT INTO reports (ship_id, report_date, this_week_issue) VALUES (:sid, :dt, :iss)"),
                                     {"sid": ship_id, "dt": datetime.now().date(), "iss": issue_val})
                    st.success("✅ 提交成功！")
                    # 优化3：彻底清除草稿
                    st.session_state.drafts[ship_id] = ""
                    st.rerun()

        # 优化1：按钮移至页面底部
        st.divider()
        nav_c1, nav_c2, nav_c3 = st.columns([1, 4, 1])
        with nav_c1:
            if st.button("⬅️ 上一艘船", use_container_width=True):
                st.session_state.ship_index = (st.session_state.ship_index - 1) % len(ships_df)
                st.rerun()
        with nav_c3:
            if st.button("下一艘船 ➡️", use_container_width=True):
                st.session_state.ship_index = (st.session_state.ship_index + 1) % len(ships_df)
                st.rerun()

# --- Tab 2: 管理员控制台 ---
if st.session_state.role == 'admin':
    with current_tab[1]:
        st.subheader("🗑️ 记录全选删除管理")
        with get_engine().connect() as conn:
            m_df = pd.read_sql_query(text("""
                SELECT r.id, s.manager_name as "负责人", s.ship_name as "船名", r.report_date as "日期", r.this_week_issue as "内容"
                FROM reports r JOIN ships s ON r.ship_id = s.id ORDER BY r.report_date DESC
            """), conn)

        if not m_df.empty:
            # 优化2：保留全选与删除功能
            m_df.insert(0, "选择", False)
            if st.checkbox("全选所有记录"): m_df["选择"] = True

            edited_m = st.data_editor(m_df, hide_index=True, use_container_width=True)
            selected_ids = edited_m[edited_m["选择"] == True]["id"].tolist()

            if selected_ids and st.button(f"🔥 物理删除选中的 {len(selected_ids)} 项"):
                with get_engine().begin() as conn:
                    conn.execute(text("DELETE FROM reports WHERE id IN :ids"), {"ids": tuple(selected_ids)})
                st.success("已清理数据库")
                st.rerun()

# --- Tab 3: 报表导出 ---
with current_tab[-1]:
    st.subheader("📂 智能报表生成")

    # 优化5：日期选择与一键按钮
    col_rpt1, col_rpt2 = st.columns(2)
    with col_rpt1:
        date_sel = st.date_input("选择报表日期范围", value=[datetime.now() - timedelta(days=7), datetime.now()])

    with col_rpt2:
        # 一键计算本周一到周五
        today = datetime.now().date()
        monday = today - timedelta(days=today.weekday())
        friday = monday + timedelta(days=4)
        if st.button(f"📅 一键选择本周工作日 ({monday} 至 {friday})"):
            st.info(f"已选定本周数据范围。")
            date_sel = [monday, friday]

    # 优化3：角色差异化展示
    if st.session_state.role == 'admin':
        c_btn1, c_btn2 = st.columns(2)
        with c_btn1:
            st.button("📊 生成范围内汇总 Excel")
        with c_btn2:
            st.button("📽️ 生成范围内汇总 PPT")
    else:
        st.button("📊 生成我的范围内 Excel")