import streamlit as st
import pandas as pd
from datetime import datetime
import sqlalchemy
from sqlalchemy import text
import export_utils

# --- 1. 页面基本配置 ---
st.set_page_config(
    page_title="船舶问题云填报系统",
    layout="wide",
    page_icon="🚢",
    initial_sidebar_state="expanded"
)

st.title("🚢 船舶问题周度填报系统")
st.caption("当前节点：Singapore (ap-southeast-1) | 环境：极速缓存模式")


# --- 2. 数据库引擎缓存 (保持连接，避免重复握手) ---
@st.cache_resource
def get_engine():
    try:
        db_url = st.secrets["postgres_url"]
        if db_url.startswith("postgres://"):
            db_url = db_url.replace("postgres://", "postgresql://", 1)

        return sqlalchemy.create_engine(
            db_url,
            poolclass=sqlalchemy.pool.NullPool,  # 禁用本地池，完全交给 Supabase 池管理
            connect_args={
                "sslmode": "require",
                "connect_timeout": 5
            }
        )
    except Exception as e:
        st.error(f"引擎创建失败: {e}")
        return None


# --- 3. 数据层：极速缓存逻辑 ---
@st.cache_data(ttl=600)  # 缓存10分钟，10分钟内刷新网页秒开
def fetch_initial_data():
    """一次性抓取所有管理人和船舶基础数据，减少网络往返次数"""
    engine = get_engine()
    if not engine: return pd.DataFrame()

    with engine.connect() as conn:
        # 一次性关联查询
        query = text("SELECT id, ship_name, manager_name FROM ships ORDER BY manager_name, ship_name")
        return pd.read_sql_query(query, conn)


def fetch_last_report(ship_id):
    """实时抓取指定船舶的上一条记录（不缓存，确保即时可见）"""
    engine = get_engine()
    with engine.connect() as conn:
        query = text("""
            SELECT this_week_issue FROM reports 
            WHERE ship_id = :sid 
            ORDER BY report_date DESC LIMIT 1
        """)
        res = conn.execute(query, {"sid": ship_id}).fetchone()
        return res[0] if res else "（该船暂无历史记录）"


# --- 4. 业务逻辑主体 ---

# 4.1 加载基础数据（由于有 cache_data，这里极快）
all_ships_df = fetch_initial_data()

if all_ships_df.empty:
    st.warning("⚠️ 数据库连接正常但未发现数据，请检查 ships 表。")
    st.stop()

# 4.2 侧边栏：选择管理人
manager_list = sorted(all_ships_df['manager_name'].unique().tolist())
current_user = st.sidebar.selectbox("🔑 请选择您的姓名", ["--- 请选择 ---"] + manager_list)

if current_user != "--- 请选择 ---":
    st.header(f"欢迎，{current_user}。")

    # 4.3 选择船舶（纯内存过滤，0延迟）
    my_ships = all_ships_df[all_ships_df['manager_name'] == current_user]
    selected_ship_name = st.selectbox("1. 选择要填报的船舶", my_ships['ship_name'].tolist())
    ship_id = int(my_ships[my_ships['ship_name'] == selected_ship_name]['id'].iloc[0])

    st.divider()

    col1, col2 = st.columns([1, 1.2])

    with col1:
        st.subheader("📊 历史记录回溯")
        # 仅针对选中的船进行一次精准查询
        last_issue = fetch_last_report(ship_id)
        st.info(f"**该船上周记录的问题：**\n\n {last_issue}")

    with col2:
        st.subheader("📝 本周数据填报")
        this_issue = st.text_area("2. 本周船舶问题", placeholder="请详细描述本周发现的问题...", height=150)
        remark = st.text_input("3. 备注 (选填)")

        if st.button("✅ 提交并同步至云端", use_container_width=True):
            if this_issue:
                with st.spinner("正在同步至新加坡数据库..."):
                    engine = get_engine()
                    try:
                        with engine.begin() as conn:
                            conn.execute(
                                text(
                                    "INSERT INTO reports (ship_id, report_date, this_week_issue, remarks) VALUES (:sid, :dt, :issue, :rem)"),
                                {"sid": ship_id, "dt": datetime.now().date(), "issue": this_issue, "rem": remark}
                            )
                        st.success("提交成功！数据已实时同步。")
                        st.balloons()
                        # 重要：提交后清除数据缓存，确保下次刷新能看到新记录
                        st.cache_data.clear()
                    except Exception as e:
                        st.error(f"提交失败: {e}")
            else:
                st.warning("⚠️ 请输入问题内容后再提交。")

# --- 5. 报表生成模块 ---
st.divider()
st.header("📂 报表与会议材料")
if st.button("🔍 生成本周汇总报告", type="secondary"):
    with st.spinner("正在整理云端汇总数据..."):
        df_summary = export_utils.get_report_data()
        if not df_summary.empty:
            st.dataframe(df_summary, use_container_width=True)

            # 生成临时文件并提供下载
            excel_file = export_utils.generate_excel(df_summary, "船舶汇总.xlsx")
            ppt_file = export_utils.generate_ppt(df_summary, "周报展示.pptx")

            c1, c2 = st.columns(2)
            with c1:
                with open(excel_file, "rb") as f:
                    st.download_button("📥 下载 Excel 表格", f, file_name=excel_file, use_container_width=True)
            with c2:
                with open(ppt_file, "rb") as f:
                    st.download_button("📥 下载 PPT 幻灯片", f, file_name=ppt_file, use_container_width=True)
        else:
            st.info("💡 数据库中暂无本周填报记录。")