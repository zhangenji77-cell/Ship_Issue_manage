import pandas as pd
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
import sqlalchemy
from sqlalchemy import text
import streamlit as st
from datetime import datetime


# 1. 数据库连接函数 (同步 Main_app.py 的终极修复逻辑)
def get_conn():
    try:
        db_url = st.secrets["postgres_url"]
        if db_url.startswith("postgres://"):
            db_url = db_url.replace("postgres://", "postgresql://", 1)

        # 必须加入 NullPool 和 connect_args 才能在 Supabase 连接池模式下稳定运行
        engine = sqlalchemy.create_engine(
            db_url,
            poolclass=sqlalchemy.pool.NullPool,
            connect_args={
                "sslmode": "require",
                "connect_timeout": 10
            }
        )
        return engine.connect()
    except Exception as e:
        st.error(f"导出工具连接数据库失败: {e}")
        return None


# 2. 核心数据抓取：本周问题 + 自动关联上周问题
def get_report_data():
    conn = get_conn()
    if not conn:
        return pd.DataFrame()

    try:
        # 使用窗口函数 LAG 一次性查出“当前记录”和“该船的上一条记录”
        optimized_query = text("""
            WITH RawData AS (
                SELECT 
                    s.ship_name, 
                    s.manager_name, 
                    r.report_date, 
                    r.this_week_issue, 
                    r.remarks,
                    LAG(r.this_week_issue) OVER (PARTITION BY r.ship_id ORDER BY r.report_date) as last_week_issue
                FROM reports r
                JOIN ships s ON r.ship_id = s.id
            )
            SELECT * FROM RawData 
            WHERE report_date >= CURRENT_DATE - INTERVAL '7 days'
            ORDER BY report_date DESC
        """)

        df = pd.read_sql_query(optimized_query, conn)

        # 简单重命名一下列名以匹配你的导出逻辑
        df.columns = ["船名", "船舶管理人", "日期", "本周问题", "备注", "上一周问题"]
        # 处理空值
        df["上一周问题"] = df["上一周问题"].fillna("无历史记录")

        return df
    except Exception as e:
        st.error(f"提取报表数据出错: {e}")
        return pd.DataFrame()
    finally:
        conn.close()

# 3. 生成 Excel
def generate_excel(df, filename):
    # 确保 openpyxl 已安装
    df.to_excel(filename, index=False, engine='openpyxl')
    return filename


# 4. 生成 PPT (保持你优秀的排版逻辑)
def generate_ppt(df, filename):
    prs = Presentation()

    if df.empty:
        slide = prs.slides.add_slide(prs.slide_layouts[6])
        left = top = width = height = Inches(1)
        txBox = slide.shapes.add_textbox(left, top, width, height)
        txBox.text = "本周暂无填报数据"
        prs.save(filename)
        return filename

    for _, row in df.iterrows():
        slide_layout = prs.slide_layouts[1]
        slide = prs.slides.add_slide(slide_layout)

        # 标题：船名
        slide.shapes.title.text = f"🚢 {row['船名']} 会议汇报"

        # 内容正文
        body_shape = slide.placeholders[1]
        tf = body_shape.text_frame
        tf.word_wrap = True

        # 第一行：基础信息
        p = tf.paragraphs[0]
        p.text = f"汇报人：{row['船舶管理人']} | 日期：{row['日期']}"
        p.font.size = Pt(18)

        # 第二行：上周回顾
        p = tf.add_paragraph()
        p.text = "\n[上周问题回溯]"
        p.font.bold = True
        p.font.size = Pt(16)

        p = tf.add_paragraph()
        p.text = str(row['上一周问题'])
        p.font.size = Pt(14)
        p.font.color.rgb = RGBColor(100, 100, 100)

        # 第三行：本周重点 (醒目红色)
        p = tf.add_paragraph()
        p.text = "\n[本周存在问题]"
        p.font.bold = True
        p.font.size = Pt(18)

        p = tf.add_paragraph()
        p.text = str(row['本周问题'])
        p.font.size = Pt(20)
        p.font.bold = True
        p.font.color.rgb = RGBColor(255, 0, 0)

        if row['备注']:
            p = tf.add_paragraph()
            p.text = f"\n备注：{row['备注']}"
            p.font.size = Pt(14)
            p.font.italic = True

    prs.save(filename)
    return filename