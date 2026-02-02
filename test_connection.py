import psycopg2
import sys

# --- 请修改这里 ---
# 1. 你的项目 ID (确保没抄错)
PROJECT_ID = "hzlswivmpwshautfxryj"

# 2. 你刚刚重置后的新密码
PASSWORD = "15524106618jx"

# 3. 尝试两种连接模式
print(f"🔍 开始 Supabase 连接诊断 (项目ID: {PROJECT_ID})...\n")


def test_connect(mode_name, host, port, user, dbname="postgres"):
    print(f"正在尝试 [{mode_name}]...")
    print(f"  - 目标: {host}:{port}")
    print(f"  - 用户: {user}")

    try:
        conn = psycopg2.connect(
            host=host,
            port=port,
            user=user,
            password=PASSWORD,
            dbname=dbname,
            connect_timeout=10
        )
        print("  ✅ 连接成功！")
        cur = conn.cursor()
        cur.execute("SELECT version();")
        v = cur.fetchone()
        print(f"  ✅ 数据库版本: {v[0][:15]}...")
        conn.close()
        return True
    except Exception as e:
        print(f"  ❌ 失败: {e}")
        return False


# 测试 A: 连接池模式 (最常用)
# 用户名必须是: postgres.项目ID
success_a = test_connect(
    "连接池模式 (IPv4)",
    "aws-0-ap-southeast-1.pooler.supabase.com",
    6543,
    f"postgres.{PROJECT_ID}"
)

print("-" * 30)

# 测试 B: 直接模式 (可能因 IPv6 失败，但值得一试)
success_b = test_connect(
    "直接连接模式",
    f"db.{PROJECT_ID}.supabase.co",
    5432,
    "postgres"
)

if not success_a and not success_b:
    print("\n⚠️ 诊断结果：两种方式都失败。")
    print("请确认：1.Supabase后台项目状态是否为绿色Active？")
    print("       2.刚刚是否成功重置了密码？")