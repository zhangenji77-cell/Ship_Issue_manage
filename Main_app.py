import streamlit as st
import pandas as pd
from datetime import datetime
import sqlalchemy
from sqlalchemy import text
import export_utils

# --- 1. 初始化配置 ---
st.set_page_config(page_title="Trust Ship 管理系统", layout="wide", page_icon="🚢")


@st.cache_resource
def get_engine():
    db_url = st.secrets["postgres_url"]
    return sqlalchemy.create_engine(db_url)


# --- 2. 登录系统逻辑 ---
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.username = None
    st.session_state.role = None


def login():
    st.title("🔒 Trust Ship 系统登录")
    with st.form("login_form"):
        user_input = st.text_input("用户名")
        pw_input = st.text_input("密码", type="password")
        submit = st.form_submit_button("登录")

        if submit:
            engine = get_engine()
            with engine.connect() as conn:
                # 验证身份
                query = text("SELECT role FROM users WHERE username = :u AND password = :p")
                res = conn.execute(query, {"u": user_input, "p": pw_input}).fetchone()

                if res:
                    st.session_state.logged_in = True
                    st.session_state.username = user_input
                    st.session_state.role = res[0]
                    st.rerun()
                else:
                    st.error("用户名或密码错误")


if not st.session_state.logged_in:
    login()
    st.stop()

# --- 3. 登录后的内容 ---

# 侧边栏：用户信息与退出
st.sidebar.title(f"👤 {st.session_state.username}")
st.sidebar.info(f"权限角色: {st.session_state.role}")
if st.sidebar.button("登出系统"):
    st.session_state.logged_in = False
    st.rerun()


# 数据获取函数
@st.cache_data(ttl=600)
def get_ships_data(role, username):
    engine = get_engine()
    with engine.connect() as conn:
        if role == 'admin':
            # 管理员可以看到 50 艘船的所有内容
            query = text("SELECT id, ship_name, manager_name FROM ships")
            return pd.read_sql_query(query, conn)
        else:
            # 普通员工只能看到属于自己的船
            query = text("SELECT id, ship_name, manager_name FROM ships WHERE manager_name = :u")
            return pd.read_sql_query(query, conn, params={"u": username})


ships_df = get_ships_data(st.session_state.role, st.session_state.username)

# --- 4. 核心页面逻辑 ---

# 页面导航（仅管理员可见管理选项）
tabs = ["数据填写"]
if st.session_state.role == 'admin':
    tabs.append("管理员控制台")
tabs.append("报表与会议材料")

current_tab = st.tabs(tabs)

# --- Tab 1: 数据填写 (所有角色可见) ---
with current_tab[0]:
    if ships_df.empty:
        st.warning("暂无分配给您的船舶。")
    else:
        selected_ship = st.selectbox("选择船舶", ships_df['ship_name'].tolist())
        ship_id = int(ships_df[ships_df['ship_name'] == selected_ship]['id'].iloc[0])

        st.divider()
        col1, col2 = st.columns(2)

        with col1:
            st.subheader("📊 历史记录")
            # 实时抓取该船最后一条记录
            with get_engine().connect() as conn:
                last_res = conn.execute(
                    text("SELECT this_week_issue FROM reports WHERE ship_id = :sid ORDER BY report_date DESC LIMIT 1"),
                    {"sid": ship_id}
                ).fetchone()
            st.info(last_res[0] if last_res else "暂无历史记录")

        with col2:
            st.subheader("📝 本周数据填写")
            this_issue = st.text_area("船舶问题", height=150)
            remark = st.text_input("备注")
            if st.button("提交填报"):
                if this_issue:
                    with get_engine().begin() as conn:
                        conn.execute(
                            text(
                                "INSERT INTO reports (ship_id, report_date, this_week_issue, remarks) VALUES (:sid, :dt, :iss, :rem)"),
                            {"sid": ship_id, "dt": datetime.now().date(), "iss": this_issue, "rem": remark}
                        )
                    st.success("提交成功！")
                    st.cache_data.clear()
                else:
                    st.warning("请填写内容")

# --- Tab 2: 管理员控制台 (仅自己/Admin可见) ---
if st.session_state.role == 'admin':
    with current_tab[1]:
        st.header("🛠️ 管理员数据控制中心")

        # 1. 批量上传 (Excel)
        st.subheader("1. 批量上传船舶清单")
        up_file = st.file_uploader("上传 Excel (列名: ship_name, manager_name)", type=["xlsx"])
        if up_file:
            if st.button("确认导入并覆盖旧数据"):
                df_new = pd.read_excel(up_file)
                with get_engine().begin() as conn:
                    conn.execute(text("TRUNCATE TABLE ships RESTART IDENTITY CASCADE"))
                    for _, row in df_new.iterrows():
                        conn.execute(
                            text("INSERT INTO ships (ship_name, manager_name) VALUES (:s, :m)"),
                            {"s": row['ship_name'], "m": row['manager_name']}
                        )
                st.success(f"成功导入 {len(df_new)} 艘船")
                st.cache_data.clear()

        st.divider()

        # 2. 数据删除与查看
        st.subheader("2. 数据库概览与清理")
        col_a, col_b = st.columns([2, 1])
        with col_a:
            all_reports = pd.read_sql_query("SELECT * FROM reports LIMIT 100", get_engine())
            st.write("最新 100 条填报记录：", all_reports)
        with col_b:
            st.warning("危险操作区")
            if st.button("⚠️ 清空所有填报记录"):
                with get_engine().begin() as conn:
                    conn.execute(text("DELETE FROM reports"))
                st.success("记录已全部清空")
                st.cache_data.clear()

# --- Tab 3: 报表与会议材料 (所有角色可见) ---
with current_tab[-1]:
    st.subheader("📂 导出汇总")
    if st.button("生成本周周报材料"):
        df_summary = export_utils.get_report_data()
        if not df_summary.empty:
            st.dataframe(df_summary)
            # 调用你之前的 PPT/Excel 生成函数
            ppt_file = export_utils.generate_ppt(df_summary, "Weekly_Meeting.pptx")
            with open(ppt_file, "rb") as f:
                st.download_button("📥 下载会议 PPT", f, file_name=ppt_file)
        else:
            st.info("本周尚无填报数据。")