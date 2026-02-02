from pptx.dml.color import RGBColor
import pandas as pd
from pptx import Presentation
from pptx.util import Inches, Pt
import sqlite3
from datetime import datetime


def get_report_data():
    """从数据库抓取本周的所有数据，并关联上周数据"""
    conn = sqlite3.connect('ships.db')
    # 1. 先抓取本周提交的所有记录
    query = """
        SELECT r.id, s.ship_name, s.manager_name, r.report_date, r.this_week_issue, r.remarks, r.ship_id
        FROM reports r
        JOIN ships s ON r.ship_id = s.id
        WHERE r.report_date >= date('now', '-7 days')
    """
    this_week_df = pd.read_sql_query(query, conn)

    final_data = []
    for _, row in this_week_df.iterrows():
        # 2. 为每一条记录寻找它的“上一周”内容
        last_query = """
            SELECT this_week_issue FROM reports 
            WHERE ship_id = ? AND report_date < ? 
            ORDER BY report_date DESC LIMIT 1
        """
        last_res = conn.execute(last_query, (row['ship_id'], row['report_date'])).fetchone()
        last_issue = last_res[0] if last_res else "无历史记录"

        final_data.append({
            "日期": row['report_date'],
            "船名": row['ship_name'],
            "船舶管理人": row['manager_name'],
            "上一周问题": last_issue,
            "本周问题": row['this_week_issue'],
            "备注": row['remarks']
        })

    conn.close()
    return pd.DataFrame(final_data)


def generate_excel(df, filename):
    """生成 Excel 文档"""
    df.to_excel(filename, index=False)
    return filename



def generate_ppt(df, filename):
    prs = Presentation()

    for _, row in df.iterrows():
        slide_layout = prs.slide_layouts[1]
        slide = prs.slides.add_slide(slide_layout)
        slide.shapes.title.text = f"船舶周报：{row['船名']}"

        body_shape = slide.placeholders[1]
        tf = body_shape.text_frame
        tf.word_wrap = True

        # --- 汇报信息 ---
        p = tf.add_paragraph()
        p.text = f"📅 汇报日期：{row['日期']}   👤 管理人：{row['船舶管理人']}"
        p.font.size = Pt(18)

        # --- 上周问题 ---
        p = tf.add_paragraph()
        p.text = f"\n⬅️ 上一周问题回溯："
        p.font.bold = True

        p = tf.add_paragraph()
        p.text = row['上一周问题']
        p.font.size = Pt(16)

        # --- 本周问题 (修复报错的地方) ---
        p = tf.add_paragraph()
        p.text = f"\n🔔 本周船舶问题："
        p.font.bold = True

        p = tf.add_paragraph()
        p.text = row['本周问题']
        p.font.size = Pt(20)  # 让本周问题字号大一点
        # 这里是修复代码：设置成红色 (RGB: 255, 0, 0)
        p.font.color.rgb = RGBColor(255, 0, 0)

        # --- 备注 ---
        if row['备注']:
            p = tf.add_paragraph()
            p.text = f"\n📝 备注：{row['备注']}"
            p.font.size = Pt(14)

    prs.save(filename)
    return filename