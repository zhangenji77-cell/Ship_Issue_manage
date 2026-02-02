import streamlit as st
import pandas as pd
from datetime import datetime
import sqlalchemy
from sqlalchemy import text
import export_utils


# --- 1. 引擎缓存：避免重复创建连接池 ---
@st.cache_resource
def get_engine():
    db_url = st.secrets["postgres_url"]
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)
    return sqlalchemy.create_engine(
        db_url,
        poolclass=sqlalchemy.pool.NullPool,  # 连接池交给云端
        connect_args={"sslmode": "require", "connect_timeout": 5}
    )


# --- 2. 数据缓存：让下拉菜单秒开 ---
@st.cache_data(ttl=600)  # 缓存10分钟
def get_all_init_data():
    engine = get_engine()
    with engine.connect() as conn:
        # 一次性查出所有人及其对应的船，减少往返次数
        df = pd.read_sql_query(text("SELECT id, ship_name, manager_name FROM ships"), conn)
        return df


# --- 3. 界面逻辑 ---
st.set_page_config(page_title="船舶填报系统", layout="wide")
st.title("🚢 船舶问题周度填报系统")

# 启动时直接从缓存拿数据
all_data_df = get_all_init_data()

# 侧边栏：选择管理人
manager_list = all_data_df['manager_name'].unique().tolist()
current_user = st.sidebar.selectbox("🔑 请选择您的姓名", ["请选择"] + manager_list)

if current_user != "请选择":
    # 过滤出该管理人的船舶（纯内存操作，0延迟）
    my_ships = all_data_df[all_data_df['manager_name'] == current_user]

    selected_ship_name = st.selectbox("1. 选择要填报的船舶", my_ships['ship_name'].tolist())
    ship_id = int(my_ships[my_ships['ship_name'] == selected_ship_name]['id'].iloc[0])

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("📊 历史记录回溯")
        # 这里的查询因为是动态的，不建议长期缓存
        engine = get_engine()
        with engine.connect() as conn:
            last_res = conn.execute(
                text("SELECT this_week_issue FROM reports WHERE ship_id = :sid ORDER BY report_date DESC LIMIT 1"),
                {"sid": ship_id}
            ).fetchone()

        last_issue_val = last_res[0] if last_res else "（暂无历史记录）"
        st.info(f"**该船上周记录：**\n\n {last_issue_val}")

    with col2:
        st.subheader("📝 本周数据填报")
        this_issue = st.text_area("2. 本周船舶问题", height=150)
        if st.button("✅ 提交并同步"):
            if this_issue:
                engine = get_engine()
                with engine.begin() as conn:
                    conn.execute(
                        text("INSERT INTO reports (ship_id, report_date, this_week_issue) VALUES (:sid, :dt, :issue)"),
                        {"sid": ship_id, "dt": datetime.now().date(), "issue": this_issue}
                    )
                st.success("提交成功！")
                st.balloons()
            else:
                st.warning("内容不能为空")

st.divider()
# 导出按钮保持原样，但记得使用我上次发你的优化版 export_utils