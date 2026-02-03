import sqlite3

def init_database():
    # 1. 连接数据库 (如果不存在则自动创建 ships.db 文件)
    conn = sqlite3.connect('ships.db')
    cursor = conn.cursor()

    # 2. 创建“船舶表”：存储船名、谁管这艘船
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS ships (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ship_name TEXT NOT NULL,
        manager_name TEXT NOT NULL
    )
    ''')

    # 3. 创建“周报记录表”：存储每一周填写的具体问题
    # ship_id 是用来关联上面那张表的（知道这行问题是哪艘船的）
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS reports (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ship_id INTEGER,
        report_date DATE,
        this_week_issue TEXT,
        remarks TEXT,
        FOREIGN KEY (ship_id) REFERENCES ships (id)
    )
    ''')

    # 4. 预设一些基础数据 (模拟你们公司的实际情况)
    # 先检查表里有没有数据，没数据再添加，防止重复添加
    cursor.execute("SELECT COUNT(*) FROM ships")
    if cursor.fetchone()[0] == 0:
        initial_ships = [
            ('UNI SUPPLY 1', 'Robert'),
            ('SYNERGY', 'Robert'),
            ('ZOEY', 'Robert'),
            ('ZEVIROUS', 'Robert'),
            ('ZALE', 'Robert'),
            ('CHLOE', 'Robert'),
            ('Jazzel', 'Robert'),
            ('KATORIN 1', 'Wilson'),
            ('OCEAN FORTUNE 18', 'Wilson')
            ('ARINE', 'Wilson')
            ('NILAM', 'Wilson')


        ]
        cursor.executemany('INSERT INTO ships (ship_name, manager_name) VALUES (?, ?)', initial_ships)
        print("✅ 已成功添加初始船舶和管理人数据！")

    # 提交修改并关闭连接
    conn.commit()
    conn.close()
    print("🚀 数据库初始化成功！当前目录下已生成 ships.db 文件")

if __name__ == "__main__":
    init_database()