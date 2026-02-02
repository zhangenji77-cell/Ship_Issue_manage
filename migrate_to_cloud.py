import sqlite3
import sqlalchemy
from sqlalchemy import text
import pandas as pd
import urllib.parse

# ================= 配置区 (请只修改密码) =================
# 1. 你的项目 ID
PROJECT_ID = "hzlswivmpwshautfxryj"

# 2. 你的密码 (确保和 Supabase 网页上重置的一模一样)
PASSWORD = "15524106618jx"

# 3. 你的本地数据库文件
LOCAL_DB = 'ships.db'


# =======================================================

def migrate():
    # 强制构造 IPv4 连接池地址
    # 用户名格式: postgres.项目ID
    user = f"postgres.{PROJECT_ID}"
    encoded_pwd = urllib.parse.quote_plus(PASSWORD)
    host = "aws-0-ap-southeast-1.pooler.supabase.com"
    port = "6543"

    # 拼接最终链接
    cloud_url = f"postgresql://{user}:{encoded_pwd}@{host}:{port}/postgres"

    print(f"🚀 正在连接云端 (IPv4模式)...")
    print(f"   目标: {host}:{port}")
    print(f"   用户: {user}")

    try:
        # 1. 连接云端
        engine = sqlalchemy.create_engine(cloud_url)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        print("✅ 云端连接成功！(终于通了)")

        # 2. 连接本地
        local_conn = sqlite3.connect(LOCAL_DB)
        print("✅ 本地数据库已读取")

        # 3. 开始搬运
        for table in ['ships', 'reports']:
            print(f"📦 正在搬运表: {table} ...")
            try:
                df = pd.read_sql_query(f"SELECT * FROM {table}", local_conn)
                if not df.empty:
                    df.to_sql(table, engine, if_exists='append', index=False)
                    print(f"   成功写入 {len(df)} 条数据")
                else:
                    print(f"   表 {table} 是空的，跳过")
            except Exception as e:
                print(f"   ⚠️ 搬运 {table} 时遇到小问题 (可能是表已存在): {e}")

        # 4. 修复 ID
        with engine.begin() as conn:
            conn.execute(text("SELECT setval('ships_id_seq', (SELECT MAX(id) FROM ships))"))
            conn.execute(text("SELECT setval('reports_id_seq', (SELECT MAX(id) FROM reports))"))
        print("✅ 数据序列已修复")
        print("\n🎉🎉🎉 恭喜！数据搬家彻底完成！")

    except Exception as e:
        print("\n❌ 连接依然失败。")
        print(f"错误信息: {e}")
        print("------------------------------------------------")
        print("请再次检查：")
        print("1. Supabase 网页上项目状态必须是绿色 Active (不是 Paused)")
        print("2. 密码是否拼写正确？")


if __name__ == "__main__":
    migrate()