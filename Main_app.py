import streamlit as st
import pandas as pd
from datetime import datetime
import sqlalchemy
from sqlalchemy import text  # 用于处理云端 SQL 语句
import export_utils  # 引用你的导出工具

# 1. 页面基本设置
st.set_page_config(page_title="船舶问题云填报系统", layout="wide")
st.title("🚢 船舶问题周度填报系统 (云端版)")


# 2. 【关键】云数据库连接函数
def get_db_connection():
    # 部署到 Streamlit Cloud 后，在这里填入 Secrets 中的连接地址
    try:
        db_url = st.secrets["postgres_url"]
        engine = sqlalchemy.create_engine(db_url)
        return engine.connect()
    except Exception as e:
        st.error("数据库连接失败，请检查 Secrets 配置。")
        return None


def get_last_week_issue(ship_id):
    """核心逻辑：从云端数据库抓取上周问题"""
    conn = get_db_connection()
    if conn:
        # PostgreSQL 的语法与 SQLite 略有不同，这里使用通用写法
        query = text("SELECT this_week_issue FROM reports WHERE ship_id = :sid ORDER BY report_date DESC LIMIT 1")
        res = conn.execute(query, {"sid": ship_id}).fetchone()
        conn.close()
        return res[0] if res else "（初次填报，暂无历史记录）"
    return "连接失败"


# 3. 侧边栏：获取管理人名单
conn = get_db_connection()
if conn:
    managers_df = pd.read_sql_query(text("SELECT DISTINCT manager_name FROM ships"), conn)
    conn.close()
    current_user = st.sidebar.selectbox("🔑 请选择您的姓名", managers_df['manager_name'].tolist())
else:
    st.stop()  # 连接失败则停止运行

# 4. 主界面：填报逻辑
st.header(f"欢迎，{current_user}。")

conn = get_db_connection()
my_ships_df = pd.read_sql_query(text("SELECT * FROM ships WHERE manager_name = :name"), conn,
                                params={"name": current_user})
conn.close()

if not my_ships_df.empty:
    selected_ship_name = st.selectbox("1. 选择船舶", my_ships_df['ship_name'].tolist())
    ship_id = int(my_ships_df[my_ships_df['ship_name'] == selected_ship_name]['id'].iloc[0])

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("📊 历史记录回溯")
        last_issue = get_last_week_issue(ship_id)
        st.info(f"**该船上一周存在的问题：**\n\n {last_issue}")

    with col2:
        st.subheader("📝 本周数据填报")
        this_issue = st.text_area("2. 本周船舶问题", placeholder="请输入...", height=150)
        remark = st.text_input("3. 备注 (选填)")

        if st.button("✅ 提交并存入云端"):
            if this_issue:
                conn = get_db_connection()
                today = datetime.now().strftime('%Y-%m-%d')
                ins_query = text(
                    "INSERT INTO reports (ship_id, report_date, this_week_issue, remarks) VALUES (:sid, :dt, :issue, :rem)")
                conn.execute(ins_query, {"sid": ship_id, "dt": today, "issue": this_issue, "rem": remark})
                conn.commit()
                conn.close()
                st.success("数据已永久同步至云端数据库！")
            else:
                st.warning("请填写内容。")

# 5. 底部：导出功能
st.divider()
st.header("📊 会议材料生成")
if st.button("🔄 准备汇总数据"):
    summary_df = export_utils.get_report_data()  # 注意：export_utils 也需要同步修改为 SQLAlchemy 模式
    if not summary_df.empty:
        st.dataframe(summary_df)
        excel_file = export_utils.generate_excel(summary_df, "汇总.xlsx")
        ppt_file = export_utils.generate_ppt(summary_df, "展示.pptx")

        c1, c2 = st.columns(2)
        with c1:
            with open(excel_file, "rb") as f:
                st.download_button("📥 下载 Excel", f, file_name=excel_file)
        with c2:
            with open(ppt_file, "rb") as f:
                st.download_button("📥 下载 PPT", f, file_name=ppt_file)