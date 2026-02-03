import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import sqlalchemy
from sqlalchemy import text

# --- 1. 初始化页面配置 ---
st.set_page_config(page_title="Trust Ship 船舶管理系统", layout="wide", page_icon="🚢")

# 初始化 Session State (全局状态管理)
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.username = None
    st.session_state.role = None
if 'drafts' not in st.session_state:
    st.session_state.drafts = {}  # 格式为 {ship_id: "内容"}
if 'show_confirm' not in st.session_state:
    st.session_state.show_confirm = False


# --- 2. 数据库连接函数 ---
@st.cache_resource
def get_engine():
    # 使用您在 .streamlit/secrets.toml 中配置的连接字符串
    db_url = st.secrets["postgres_url"]
    return sqlalchemy.create_engine(db_url)


# --- 3. 登录逻辑 ---
def login_page():
    st.title("🔒 Trust Ship 系统登录")
    with st.form("login_form"):
        user_input = st.text_input("用户名 (Username)")
        pw_input = st.text_input("密码 (Password)", type="password")
        submit = st.form_submit_button("登录")

        if submit:
            engine = get_engine()
            with engine.connect() as conn:
                # 验证用户信息
                query = text("SELECT role FROM users WHERE username = :u AND password = :p")
                res = conn.execute(query, {"u": user_input, "p": pw_input}).fetchone()

                if res:
                    st.session_state.logged_in = True
                    st.session_state.username = user_input
                    st.session_state.role = res[0]
                    st.rerun()
                else:
                    st.error("❌ 用户名或密码错误")


# 如果未登录，则显示登录页并停止向下运行
if not st.session_state.logged_in:
    login_page()
    st.stop()

# --- 4. 侧边栏及登出 ---
st.sidebar.title(f"👤 {st.session_state.username}")
st.sidebar.info(f"当前角色: {st.session_state.role}")
if st.sidebar.button("登出系统"):
    st.session_state.logged_in = False
    st.session_state.drafts = {}
    st.rerun()


# --- 5. 获取船舶列表 (根据权限过滤) ---
@st.cache_data(ttl=600)
def get_ships_list(role, username):
    engine = get_engine()
    with engine.connect() as conn:
        if role == 'admin':
            # 管理员可查看 50 艘船的所有数据
            query = text("SELECT id, ship_name, manager_name FROM ships ORDER BY ship_name")
            return pd.read_sql_query(query, conn)
        else:
            # 普通员工只能看到属于自己的船舶
            query = text("SELECT id, ship_name, manager_name FROM ships WHERE manager_name = :u ORDER BY ship_name")
            return pd.read_sql_query(query, conn, params={"u": username})


ships_df = get_ships_list(st.session_state.role, st.session_state.username)

# --- 6. 定义页面选项卡 (Tabs) ---
tabs_list = ["📝 数据填写"]
if st.session_state.role == 'admin':
    tabs_list.append("🛠️ 管理员控制台")
tabs_list.append("📂 报表与会议材料")

current_tab = st.tabs(tabs_list)

# --- Tab 1: 数据填写 ---
with current_tab[0]:
    if ships_df.empty:
        st.warning("⚠️ 暂无分配给您的船舶，请联系管理员。")
    else:
        # 1. 选择船舶
        selected_ship = st.selectbox("🚢 请选择船舶进行填报", ships_df['ship_name'].tolist())
        ship_row = ships_df[ships_df['ship_name'] == selected_ship].iloc[0]
        ship_id = int(ship_row['id'])

        # 初始化该船的独立草稿
        if ship_id not in st.session_state.drafts:
            st.session_state.drafts[ship_id] = ""

        st.divider()
        col1, col2 = st.columns([1, 1.2])

        # 历史记录板块 (带日期查询)
        with col1:
            st.subheader("📊 历史记录回溯")
            date_range = st.date_input(
                "查询时间范围",
                value=[datetime.now() - timedelta(days=30), datetime.now()],
                key=f"dr_{ship_id}"
            )

            if len(date_range) == 2:
                start_d, end_d = date_range
                with get_engine().connect() as conn:
                    h_query = text("""
                        SELECT report_date as "日期", this_week_issue as "船舶问题", remarks as "备注"
                        FROM reports 
                        WHERE ship_id = :sid AND report_date BETWEEN :s AND :e
                        ORDER BY report_date DESC
                    """)
                    history_df = pd.read_sql_query(h_query, conn, params={"sid": ship_id, "s": start_d, "e": end_d})

                if not history_df.empty:
                    st.write(f"📅 共找到 {len(history_df)} 条填报记录")
                    st.dataframe(history_df, use_container_width=True, hide_index=True)
                else:
                    st.info("💡 该时间段内无填报记录。")

        # 船舶问题填报板块
        with col2:
            st.subheader(f"✍️ 本周填报: {selected_ship}")

            # 使用大输入框并绑定独立草稿逻辑
            input_issue = st.text_area(
                "本周发现的船舶问题描述：",
                value=st.session_state.drafts[ship_id],
                height=350,
                key=f"area_{ship_id}"
            )
            # 实时保存草稿到内存
            st.session_state.drafts[ship_id] = input_issue

            remark_input = st.text_input("备注 (选填)", key=f"rem_{ship_id}")

            if st.button("🚀 确认提交本周数据", use_container_width=True):
                if input_issue.strip():
                    with get_engine().begin() as conn:
                        conn.execute(
                            text(
                                "INSERT INTO reports (ship_id, report_date, this_week_issue, remarks) VALUES (:sid, :dt, :iss, :rem)"),
                            {"sid": ship_id, "dt": datetime.now().date(), "iss": input_issue, "rem": remark_input}
                        )
                    st.success(f"✅ {selected_ship} 数据已成功上传至新加坡服务器！")
                    # 提交成功后彻底清空该船的独立草稿
                    st.session_state.drafts[ship_id] = ""
                    st.cache_data.clear()
                    st.rerun()
                else:
                    st.warning("⚠️ 填报内容不能为空，请输入船舶问题。")

# --- Tab 2: 管理员控制台 (仅 admin 可见) ---
if st.session_state.role == 'admin':
    with current_tab[1]:
        st.header("🛠️ 管理员控制台")

        # 1. 批量上传船舶 (Excel)
        st.subheader("1. 批量导入/覆盖船舶清单")
        up_file = st.file_uploader("选择 Excel 文件 (需包含 ship_name 和 manager_name 列)", type=["xlsx"])
        if up_file:
            if st.button("开始导入并重置名单"):
                df_excel = pd.read_excel(up_file)
                with get_engine().begin() as conn:
                    # 重置船舶表
                    conn.execute(text("TRUNCATE TABLE ships RESTART IDENTITY CASCADE"))
                    for _, row in df_excel.iterrows():
                        conn.execute(
                            text("INSERT INTO ships (ship_name, manager_name) VALUES (:s, :m)"),
                            {"s": row['ship_name'], "m": row['manager_name']}
                        )
                st.success("✅ 船舶清单已更新。")
                st.cache_data.clear()

        st.divider()

        # 2. 选择性删除功能
        st.subheader("2. 填报记录管理")
        with get_engine().connect() as conn:
            manage_q = text("""
                SELECT r.id, s.ship_name as "船名", r.report_date as "日期", r.this_week_issue as "问题描述"
                FROM reports r JOIN ships s ON r.ship_id = s.id ORDER BY r.report_date DESC
            """)
            manage_df = pd.read_sql_query(manage_q, conn)

        if not manage_df.empty:
            manage_df.insert(0, "选择", False)
            if st.checkbox("全选 (Select All)"):
                manage_df["选择"] = True

            # 使用数据编辑器实现勾选
            edited_df = st.data_editor(
                manage_df,
                hide_index=True,
                column_config={"选择": st.column_config.CheckboxColumn(required=True)},
                disabled=["船名", "日期", "问题描述"],
                use_container_width=True
            )

            selected_ids = edited_df[edited_df["选择"] == True]["id"].tolist()

            if selected_ids:
                if st.button(f"🗑️ 删除选中的 {len(selected_ids)} 条记录"):
                    st.session_state.show_confirm = True

            # 二次确认逻辑
            if st.session_state.show_confirm:
                st.warning(f"⚠️ 确定要从数据库中永久删除这 {len(selected_ids)} 条记录吗？")
                c1, c2 = st.columns(2)
                with c1:
                    if st.button("❌ 取消"):
                        st.session_state.show_confirm = False
                        st.rerun()
                with c2:
                    if st.button("🔥 确认删除"):
                        with get_engine().begin() as conn:
                            conn.execute(text("DELETE FROM reports WHERE id IN :ids"), {"ids": tuple(selected_ids)})
                        st.success("数据已清理。")
                        st.session_state.show_confirm = False
                        st.cache_data.clear()
                        st.rerun()
        else:
            st.info("当前数据库中暂无记录。")

# --- Tab 3: 报表导出 ---
with current_tab[-1]:
    st.subheader("📊 报表与会议材料导出")
    st.write("点击下方按钮汇总本周所有船舶的问题记录，并导出为 PowerPoint 或 Excel 格式。")
    if st.button("生成汇总报表预览"):
        with get_engine().connect() as conn:
            summary_q = text("""
                SELECT s.ship_name, r.report_date, r.this_week_issue, r.remarks
                FROM reports r JOIN ships s ON r.ship_id = s.id
                WHERE r.report_date >= :dt
            """)
            summary_df = pd.read_sql_query(summary_q, conn, params={"dt": datetime.now() - timedelta(days=7)})

        if not summary_df.empty:
            st.dataframe(summary_df, use_container_width=True)
            st.info("💡 导出功能 (PPT/XLSX) 正在与 export_utils 模块集成中...")
        else:
            st.warning("本周暂无填报数据。")