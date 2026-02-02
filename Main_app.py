import streamlit as st
import pandas as pd
from datetime import datetime
import sqlalchemy
from sqlalchemy import text
import sqlite3
import export_utils  # 确保你的 export_utils.py 也在 GitHub 上

# 1. 页面基本配置
st.set_page_config(page_title="船舶问题云填报系统", layout="wide", page_icon="🚢")
st.title("🚢 船舶问题周度填报系统 (云端稳定版)")


# 2. 数据库连接函数
def get_db_connection():
    try:
        # 从 Streamlit Secrets 读取连接字符串
        db_url = st.secrets["postgres_url"]
        # 自动更正协议头（SQLAlchemy 要求使用 postgresql://）
        if db_url.startswith("postgres://"):
            db_url = db_url.replace("postgres://", "postgresql://", 1)

        engine = sqlalchemy.create_engine(db_url, pool_pre_ping=True)
        return engine.connect()
    except Exception as e:
        st.error(f"❌ 数据库连接失败: {e}")
        st.info("请检查 Streamlit Cloud 后台的 Secrets 配置是否正确。")
        return None


# 3. 自动初始化表结构 (防止 ProgrammingError)
def init_db_tables():
    conn = get_db_connection()
    if conn:
        try:
            with conn.begin():
                # 创建船舶基础信息表
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS ships (
                        id SERIAL PRIMARY KEY,
                        ship_name TEXT NOT NULL,
                        manager_name TEXT NOT NULL
                    );
                """))
                # 创建周报记录表
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS reports (
                        id SERIAL PRIMARY KEY,
                        ship_id INTEGER REFERENCES ships(id),
                        report_date DATE,
                        this_week_issue TEXT,
                        remarks TEXT
                    );
                """))
        except Exception as e:
            st.error(f"初始化表结构失败: {e}")
        finally:
            conn.close()


# 执行初始化
init_db_tables()

# 4. 侧边栏：身份选择
conn = get_db_connection()
if conn:
    try:
        managers_query = text("SELECT DISTINCT manager_name FROM ships")
        managers_df = pd.read_sql_query(managers_query, conn)

        if not managers_df.empty:
            manager_list = managers_df['manager_name'].tolist()
            current_user = st.sidebar.selectbox("🔑 请选择您的姓名", manager_list)
        else:
            st.sidebar.warning("⚡ 数据库中暂无管理人数据，请先使用底部的搬家工具导入。")
            current_user = None
    except Exception as e:
        st.sidebar.error("读取数据失败")
        current_user = None
    finally:
        conn.close()
else:
    st.stop()

# 5. 主填报界面
if current_user:
    st.header(f"欢迎，{current_user}。")

    conn = get_db_connection()
    ships_query = text("SELECT * FROM ships WHERE manager_name = :name")
    my_ships_df = pd.read_sql_query(ships_query, conn, params={"name": current_user})
    conn.close()

    if not my_ships_df.empty:
        selected_ship_name = st.selectbox("1. 选择要填报的船舶", my_ships_df['ship_name'].tolist())
        ship_id = int(my_ships_df[my_ships_df['ship_name'] == selected_ship_name]['id'].iloc[0])

        col1, col2 = st.columns(2)

        with col1:
            st.subheader("📊 历史记录回溯")
            conn = get_db_connection()
            last_q = text("SELECT this_week_issue FROM reports WHERE ship_id = :sid ORDER BY report_date DESC LIMIT 1")
            last_res = conn.execute(last_q, {"sid": ship_id}).fetchone()
            conn.close()

            last_issue_val = last_res[0] if last_res else "（该船暂无历史填报记录）"
            st.info(f"**该船上一周存在的问题：**\n\n {last_issue_val}")

        with col2:
            st.subheader("📝 本周数据填报")
            this_issue = st.text_area("2. 本周船舶问题", placeholder="请详细描述本周发现的问题...", height=150)
            remark = st.text_input("3. 备注 (选填)")

            if st.button("✅ 提交并同步至云端"):
                if this_issue:
                    conn = get_db_connection()
                    try:
                        with conn.begin():
                            ins_q = text(
                                "INSERT INTO reports (ship_id, report_date, this_week_issue, remarks) VALUES (:sid, :dt, :issue, :rem)")
                            conn.execute(ins_q, {
                                "sid": ship_id,
                                "dt": datetime.now().date(),
                                "issue": this_issue,
                                "rem": remark
                            })
                        st.success(f"数据已于 {datetime.now().strftime('%H:%M:%S')} 成功存入云端！")
                    except Exception as e:
                        st.error(f"提交失败: {e}")
                    finally:
                        conn.close()
                else:
                    st.warning("⚠️ 请输入本周问题后再提交。")

# 6. 导出模块
st.divider()
st.header("📂 报表与会议材料")
if st.button("🔍 准备本周汇总数据"):
    with st.spinner("正在抓取云端数据并生成文档..."):
        df_summary = export_utils.get_report_data()
        if not df_summary.empty:
            st.dataframe(df_summary)
            excel_file = export_utils.generate_excel(df_summary, "船舶周报汇总.xlsx")
            ppt_file = export_utils.generate_ppt(df_summary, "周报展示.pptx")

            c1, c2 = st.columns(2)
            with c1:
                with open(excel_file, "rb") as f:
                    st.download_button("📥 下载 Excel 表格", f, file_name=excel_file)
            with c2:
                with open(ppt_file, "rb") as f:
                    st.download_button("📥 下载 PPT 汇报幻灯片", f, file_name=ppt_file)
        else:
            st.info("💡 过去 7 天内暂无任何填报记录。")

# 7. 管理员搬家工具 (迁移完成后可自行删除此段)
st.divider()
with st.expander("🛠️ 开发者专用：本地数据迁移工具"):
    st.write("如果云端是空的，请上传你电脑上的 `ships.db` 文件进行初始化。")
    uploaded_file = st.file_uploader("上传 ships.db", type="db")
    if uploaded_file and st.button("🚀 开始云端搬家"):
        import tempfile

        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp.write(uploaded_file.getvalue())
            tmp_path = tmp.name

        try:
            local_conn = sqlite3.connect(tmp_path)
            s_df = pd.read_sql("SELECT * FROM ships", local_conn)
            r_df = pd.read_sql("SELECT * FROM reports", local_conn)
            local_conn.close()

            cloud_conn = get_db_connection()
            if cloud_conn:
                s_df.to_sql('ships', cloud_conn, if_exists='append', index=False)
                r_df.to_sql('reports', cloud_conn, if_exists='append', index=False)
                # 修复 ID 序列
                cloud_conn.execute(text("SELECT setval('ships_id_seq', (SELECT MAX(id) FROM ships))"))
                cloud_conn.execute(text("SELECT setval('reports_id_seq', (SELECT MAX(id) FROM reports))"))
                cloud_conn.commit()
                cloud_conn.close()
                st.balloons()
                st.success("🎉 数据迁移成功！请刷新页面查看。")
        except Exception as e:
            st.error(f"迁移失败: {e}")