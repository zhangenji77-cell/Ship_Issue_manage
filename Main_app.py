import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import sqlalchemy
from sqlalchemy import text
import export_utils

# --- 初始化草稿箱 ---
if 'drafts' not in st.session_state:
    st.session_state.drafts = {}

# --- Tab 1: 数据填写与历史查询 (优化版) ---
# --- 必须在“数据填写”逻辑之前定义这部分 ---

# 1. 根据角色定义有哪些选项卡
tabs_list = ["数据填写"]
if st.session_state.role == 'admin':
    tabs_list.append("管理员控制台")
tabs_list.append("报表与会议材料")

# 2. 正式创建选项卡组件 (这是报错的关键！)
current_tab = st.tabs(tabs_list)

# --- 之后才能开始使用 with current_tab[0] ---
with current_tab[0]:
    # 之前优化的“数据填写”代码放这里...
with current_tab[0]:
    if ships_df.empty:
        st.warning("暂无分配给您的船舶。")
    else:
        # 1. 船舶选择与草稿初始化
        selected_ship = st.selectbox("🚢 选择船舶", ships_df['ship_name'].tolist())
        ship_row = ships_df[ships_df['ship_name'] == selected_ship].iloc[0]
        ship_id = int(ship_row['id'])

        if ship_id not in st.session_state.drafts:
            st.session_state.drafts[ship_id] = ""

        st.divider()
        col1, col2 = st.columns([1, 1.2])

        # --- 优化1：历史记录板块 (加入日期查询与总记录) ---
        with col1:
            st.subheader("📊 历史记录回溯")

            # 日期范围选择器
            date_range = st.date_input(
                "查询时间段",
                value=[datetime.now() - timedelta(days=30), datetime.now()],
                key=f"date_range_{ship_id}"
            )

            if len(date_range) == 2:
                start_date, end_date = date_range
                with get_engine().connect() as conn:
                    query = text("""
                        SELECT report_date as "日期", this_week_issue as "船舶问题", remarks as "备注"
                        FROM reports 
                        WHERE ship_id = :sid AND report_date BETWEEN :start AND :end
                        ORDER BY report_date DESC
                    """)
                    history_df = pd.read_sql_query(query, conn, params={
                        "sid": ship_id, "start": start_date, "end": end_date
                    })

                if not history_df.empty:
                    st.write(f"📅 该时段共计 {len(history_df)} 条记录")
                    # 直接展示总记录列表，方便用户滚动查看每周问题
                    st.dataframe(history_df, use_container_width=True, hide_index=True)
                else:
                    st.info("💡 该时段内无历史填报记录。")

        # --- 优化2：船舶问题板块 (提交后重置) ---
        with col2:
            st.subheader(f"📝 本周填报 - {selected_ship}")

            # 绑定 session_state 实现自动清空
            issue_val = st.text_area(
                "本周船舶问题：",
                value=st.session_state.drafts[ship_id],
                height=350,
                key=f"ta_{ship_id}"
            )
            # 实时保存草稿
            st.session_state.drafts[ship_id] = issue_val

            remark_val = st.text_input("备注 (选填)", key=f"ri_{ship_id}")

            if st.button("🚀 提交并同步", use_container_width=True):
                if issue_val.strip():
                    with get_engine().begin() as conn:
                        conn.execute(
                            text(
                                "INSERT INTO reports (ship_id, report_date, this_week_issue, remarks) VALUES (:sid, :dt, :iss, :rem)"),
                            {"sid": ship_id, "dt": datetime.now().date(), "iss": issue_val, "rem": remark_val}
                        )
                    st.success(f"✅ {selected_ship} 提交成功！")

                    # --- 核心优化：成功提交后彻底重置该船的草稿 ---
                    st.session_state.drafts[ship_id] = ""
                    st.cache_data.clear()
                    st.rerun()  # 强制触发重新渲染，清空文本框内容
                else:
                    st.warning("⚠️ 内容不能为空")

# --- Tab 2: 管理员控制台 (优化版：勾选删除功能) ---
if st.session_state.role == 'admin':
    with current_tab[1]:
        st.header("🛠️ 数据维护中心")

        # --- 优化3：船舶问题信息的选择删除与全选 ---
        st.subheader("🗑️ 记录管理 (选择性删除)")

        # 获取所有待管理的记录
        with get_engine().connect() as conn:
            all_reps_query = text("""
                SELECT r.id, s.ship_name as "船名", r.report_date as "日期", r.this_week_issue as "问题内容"
                FROM reports r
                JOIN ships s ON r.ship_id = s.id
                ORDER BY r.report_date DESC
            """)
            manage_df = pd.read_sql_query(all_reps_query, conn)

        if not manage_df.empty:
            # 加入勾选列
            manage_df.insert(0, "选择", False)

            # 全选功能
            select_all = st.checkbox("全选所有记录")
            if select_all:
                manage_df["选择"] = True

            # 使用数据编辑器进行勾选操作
            edited_df = st.data_editor(
                manage_df,
                hide_index=True,
                column_config={"选择": st.column_config.CheckboxColumn(required=True)},
                disabled=["船名", "日期", "问题内容"],
                use_container_width=True
            )

            # 筛选出被选中的 ID
            selected_ids = edited_df[edited_df["选择"] == True]["id"].tolist()

            if selected_ids:
                if st.button(f"🗑️ 删除选中的 {len(selected_ids)} 条记录", type="primary"):
                    st.session_state.show_confirm = True  # 开启二次确认状态

            # --- 系统再次询问用户 (二次确认逻辑) ---
            if st.session_state.get('show_confirm', False):
                st.warning(f"⚠️ 确定要永久删除这 {len(selected_ids)} 条记录吗？此操作不可撤销。")
                c1, c2 = st.columns(2)
                with c1:
                    if st.button("❌ 取消", use_container_width=True):
                        st.session_state.show_confirm = False
                        st.rerun()
                with c2:
                    if st.button("🔥 确认删除", use_container_width=True):
                        with get_engine().begin() as conn:
                            conn.execute(
                                text("DELETE FROM reports WHERE id IN :ids"),
                                {"ids": tuple(selected_ids)}
                            )
                        st.success("选定记录已成功删除")
                        st.session_state.show_confirm = False
                        st.cache_data.clear()
                        st.rerun()
        else:
            st.info("当前数据库中无填报记录。")