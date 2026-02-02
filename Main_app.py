import streamlit as st
import pandas as pd
from datetime import datetime
import sqlalchemy
from sqlalchemy import text
import export_utils

# --- 1. 页面配置 ---
st.set_page_config(page_title="船舶问题云填报系统", layout="wide", page_icon="🚢")
st.title("🚢 船舶问题周度填报系统")


# --- 2. 数据库引擎缓存 (保持连接池) ---
@st.cache_resource
def get_engine():
    db_url = st.secrets["postgres_url"]
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)
    return sqlalchemy.create_engine(
        db_url,
        poolclass=sqlalchemy.pool.NullPool,
        connect_args={"sslmode": "require", "connect_timeout": 5}
    )


# --- 3. 数据查询缓存 (核心提速点) ---
# ttl=300 表示数据在内存中存5分钟，5分钟内刷新网页都是秒开
@st.cache_data(ttl=300)
def fetch_managers():
    engine = get_engine()
    with engine.connect() as conn:
        df = pd.read_sql_query(text("SELECT DISTINCT manager_name FROM ships"), conn)
        return df['manager_name'].tolist()


@st.cache_data(ttl=300)
def fetch_my_ships(manager_name):
    engine = get_engine()
    with engine.connect() as conn:
        return pd.read_sql_query(
            text("SELECT id, ship_name FROM ships WHERE manager_name = :name"),
            conn, params={"name": manager_name}
        )


# --- 4. 界面逻辑 ---
# 快速获取管理人列表
manager_list = fetch_managers()

if not manager_list:
    st.error("数据库中没有发现管理人信息。")
    st.stop()

current_user = st.sidebar.selectbox("🔑 请选择您的姓名", manager_list)

if current_user:
    st.header(f"欢迎，{current_user}。")

    # 快速获取该管理人的船
    my_ships_df = fetch_my_ships(current_user)

    if not my_ships_df.empty:
        selected_ship_name = st.selectbox("1. 选择要填报的船舶", my_ships_df['ship_name'].tolist())
        ship_id = int(my_ships_df[my_ships_df['ship_name'] == selected_ship_name]['id'].iloc[0])

        col1, col2 = st.columns(2)

        with col1:
            st.subheader("📊 历史记录回溯")
            # 这里的查询不建议长时间缓存，因为刚提交的新数据需要即时看到
            engine = get_engine()
            with engine.connect() as conn:
                last_res = conn.execute(
                    text("SELECT this_week_issue FROM reports WHERE ship_id = :sid ORDER BY report_date DESC LIMIT 1"),
                    {"sid": ship_id}
                ).fetchone()

            last_issue_val = last_res[0] if last_res else "（该船暂无历史记录）"
            st.info(f"**该船上周记录的问题：**\n\n {last_issue_val}")

        with col2:
            st.subheader("📝 本周数据填报")
            this_issue = st.text_area("2. 本周船舶问题", placeholder="请详细描述...", height=150)
            remark = st.text_input("3. 备注 (选填)")

            if st.button("✅ 提交并同步至云端"):
                if this_issue:
                    engine = get_engine()
                    try:
                        with engine.begin() as conn:
                            conn.execute(
                                text(
                                    "INSERT INTO reports (ship_id, report_date, this_week_issue, remarks) VALUES (:sid, :dt, :issue, :rem)"),
                                {"sid": ship_id, "dt": datetime.now().date(), "issue": this_issue, "rem": remark}
                            )
                        st.success("提交成功！")
                        st.balloons()
                        # 提交后清除缓存，确保下次刷新能看到最新数据
                        st.cache_data.clear()
                    except Exception as e:
                        st.error(f"提交失败: {e}")
                else:
                    st.warning("⚠️ 请输入问题内容后再提交。")

# --- 5. 导出模块 ---
st.divider()
st.header("📂 报表与会议材料")
if st.button("🔍 生成本周汇总报告"):
    with st.spinner("正在整理云端数据..."):
        # 已经在 export_utils 中优化了 SQL
        df_summary = export_utils.get_report_data()
        if not df_summary.empty:
            st.dataframe(df_summary)
            excel_file = export_utils.generate_excel(df_summary, "船舶汇总.xlsx")
            ppt_file = export_utils.generate_ppt(df_summary, "周报展示.pptx")

            c1, c2 = st.columns(2)
            with c1:
                with open(excel_file, "rb") as f:
                    st.download_button("📥 下载 Excel 表格", f, file_name=excel_file)
            with c2:
                with open(ppt_file, "rb") as f:
                    st.download_button("📥 下载 PPT 幻灯片", f, file_name=ppt_file)