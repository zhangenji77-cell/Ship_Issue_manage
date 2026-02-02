import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime

# 1. 页面基本设置
st.set_page_config(page_title="船舶问题填报系统", layout="wide")
st.title("🚢 船舶问题周度填报系统")


# 2. 数据库连接函数
# 修改后 (适配云端)：
import sqlalchemy

def get_db_connection():
    # 这里的地址将来会放在 Streamlit 的 Secrets（隐私设置）里
    db_url = st.secrets["postgres_url"]
    engine = sqlalchemy.create_engine(db_url)
    return engine.connect()

def get_last_week_issue(ship_id):
    """【核心逻辑】从数据库中查找该船最后一次提交的问题记录"""
    conn = get_db_connection()
    # 按照日期倒序排列，取第1条记录，即为该船的“上周”问题
    query = "SELECT this_week_issue FROM reports WHERE ship_id = ? ORDER BY report_date DESC LIMIT 1"
    res = conn.execute(query, (ship_id,)).fetchone()
    conn.close()
    return res[0] if res else "（初次填报，暂无历史记录）"


# 3. 侧边栏：模拟登录
st.sidebar.header("🔑 用户登录")
# 先从数据库获取所有管理人名单
conn = get_db_connection()
managers_df = pd.read_sql_query("SELECT DISTINCT manager_name FROM ships", conn)
conn.close()

current_user = st.sidebar.selectbox("请选择您的姓名", managers_df['manager_name'].tolist())

# 4. 主界面：填报逻辑
st.header(f"欢迎，{current_user}。请完成本周填报：")

conn = get_db_connection()
# 获取当前登录人负责的船舶列表
my_ships_df = pd.read_sql_query("SELECT * FROM ships WHERE manager_name = ?", conn, params=(current_user,))
conn.close()

if not my_ships_df.empty:
    selected_ship_name = st.selectbox("1. 选择船舶", my_ships_df['ship_name'].tolist())

    # 获取选中船只的数据库 ID
    ship_id = int(my_ships_df[my_ships_df['ship_name'] == selected_ship_name]['id'].iloc[0])

    # 使用两列布局
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("📊 历史记录回溯")
        # 自动获取上周问题并显示（灰色信息框）
        last_issue = get_last_week_issue(ship_id)
        st.info(f"**该船上一周存在的问题：**\n\n {last_issue}")

    with col2:
        st.subheader("📝 本周数据填报")
        this_issue = st.text_area("2. 本周船舶问题", placeholder="请详细描述本周发现的问题...", height=150)
        remark = st.text_input("3. 备注 (选填)")

        if st.button("✅ 提交并存入数据库"):
            if this_issue:
                conn = get_db_connection()
                today = datetime.now().strftime('%Y-%m-%d')
                conn.execute(
                    "INSERT INTO reports (ship_id, report_date, this_week_issue, remarks) VALUES (?, ?, ?, ?)",
                    (ship_id, today, this_issue, remark)
                )
                conn.commit()
                conn.close()
                st.success(f"提交成功！{selected_ship_name} 的本周数据已存档。")
            else:
                st.warning("请填写本周问题后再提交。")
else:
    st.error("您名下暂无负责的船舶，请联系系统管理员。")

# 5. 底部：数据实时预览
st.divider()
st.subheader("🔍 最近 5 条提交记录预览")
conn = get_db_connection()
recent_df = pd.read_sql_query("""
    SELECT s.ship_name as 船名, r.report_date as 提交日期, r.this_week_issue as 问题内容 
    FROM reports r JOIN ships s ON r.ship_id = s.id 
    ORDER BY r.report_date DESC LIMIT 5
""", conn)
st.table(recent_df)
conn.close()
# --- 导入我们刚才写的工具函数 ---
import export_utils

st.divider()
st.header("📊 会议材料一键生成 (管理员功能)")

if st.button("🔄 准备本周汇总数据"):
    summary_df = export_utils.get_report_data()

    if not summary_df.empty:
        st.write("本周待汇总数据预览：", summary_df)

        # 生成 Excel 文件
        excel_file = "船舶问题汇总.xlsx"
        export_utils.generate_excel(summary_df, excel_file)

        # 生成 PPT 文件
        ppt_file = "船舶会议展示.pptx"
        export_utils.generate_ppt(summary_df, ppt_file)

        # 提供下载按钮
        col_dl1, col_dl2 = st.columns(2)
        with col_dl1:
            with open(excel_file, "rb") as f:
                st.download_button("📥 下载 Excel 汇总表", f, file_name=excel_file)

        with col_dl2:
            with open(ppt_file, "rb") as f:
                st.download_button("📥 下载 会议展示 PPT", f, file_name=ppt_file)
    else:
        st.warning("本周暂无填报数据，无法生成文档。")