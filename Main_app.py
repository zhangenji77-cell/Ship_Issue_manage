import streamlit as st
import pandas as pd
from datetime import datetime
import sqlalchemy
from sqlalchemy import text
import export_utils  # 确保 export_utils.py 在同级目录下

# 1. 页面基本配置
st.set_page_config(page_title="船舶问题云填报系统", layout="wide", page_icon="🚢")
st.title("🚢 船舶问题周度填报系统")


# 2. 数据库连接函数 (保持高效连接)
# 使用缓存装饰器，让引擎只创建一次
@st.cache_resource
def get_database_engine():
    db_url = st.secrets["postgres_url"]
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)

    # 这里的 engine 会被缓存在内存中
    return sqlalchemy.create_engine(
        db_url,
        poolclass=sqlalchemy.pool.NullPool,
        connect_args={"sslmode": "require"}
    )


def get_db_connection():
    try:
        engine = get_database_engine()
        return engine.connect()
    except Exception as e:
        st.error(f"❌ 连接失败: {e}")
        return None


# 3. 获取管理人列表 (侧边栏)
conn = get_db_connection()
if conn:
    try:
        managers_df = pd.read_sql_query(text("SELECT DISTINCT manager_name FROM ships"), conn)
        manager_list = managers_df['manager_name'].tolist()
        current_user = st.sidebar.selectbox("🔑 请选择您的姓名", manager_list)
    except Exception as e:
        st.sidebar.error("读取管理人数据失败")
        current_user = None
    finally:
        conn.close()
else:
    st.stop()

# 4. 主填报逻辑
if current_user:
    st.header(f"欢迎，{current_user}。")

    # 获取当前管理人负责的船舶
    conn = get_db_connection()
    my_ships_df = pd.read_sql_query(
        text("SELECT * FROM ships WHERE manager_name = :name"),
        conn,
        params={"name": current_user}
    )
    conn.close()

    if not my_ships_df.empty:
        selected_ship_name = st.selectbox("1. 选择要填报的船舶", my_ships_df['ship_name'].tolist())
        ship_id = int(my_ships_df[my_ships_df['ship_name'] == selected_ship_name]['id'].iloc[0])

        col1, col2 = st.columns(2)

        with col1:
            st.subheader("📊 历史记录回溯")
            conn = get_db_connection()
            last_res = conn.execute(
                text("SELECT this_week_issue FROM reports WHERE ship_id = :sid ORDER BY report_date DESC LIMIT 1"),
                {"sid": ship_id}
            ).fetchone()
            conn.close()

            last_issue_val = last_res[0] if last_res else "（该船暂无历史记录）"
            st.info(f"**该船上周记录的问题：**\n\n {last_issue_val}")

        with col2:
            st.subheader("📝 本周数据填报")
            this_issue = st.text_area("2. 本周船舶问题", placeholder="请详细描述...", height=150)
            remark = st.text_input("3. 备注 (选填)")

            if st.button("✅ 提交并同步至云端"):
                if this_issue:
                    conn = get_db_connection()
                    try:
                        with conn.begin():
                            conn.execute(
                                text(
                                    "INSERT INTO reports (ship_id, report_date, this_week_issue, remarks) VALUES (:sid, :dt, :issue, :rem)"),
                                {"sid": ship_id, "dt": datetime.now().date(), "issue": this_issue, "rem": remark}
                            )
                        st.success(f"提交成功！提交时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
                        st.balloons()
                    except Exception as e:
                        st.error(f"提交失败: {e}")
                    finally:
                        conn.close()
                else:
                    st.warning("⚠️ 请输入问题内容后再提交。")

# 5. 导出与报表模块
st.divider()
st.header("📂 报表与会议材料")
if st.button("🔍 生成本周汇总报告"):
    with st.spinner("正在整理云端数据..."):
        df_summary = export_utils.get_report_data()
        if not df_summary.empty:
            st.dataframe(df_summary)

            # 生成文件
            excel_file = export_utils.generate_excel(df_summary, "船舶汇总.xlsx")
            ppt_file = export_utils.generate_ppt(df_summary, "周报展示.pptx")

            c1, c2 = st.columns(2)
            with c1:
                with open(excel_file, "rb") as f:
                    st.download_button("📥 下载 Excel 表格", f, file_name=excel_file)
            with c2:
                with open(ppt_file, "rb") as f:
                    st.download_button("📥 下载 PPT 幻灯片", f, file_name=ppt_file)
        else:
            st.info("💡 数据库中暂无本周填报记录。")