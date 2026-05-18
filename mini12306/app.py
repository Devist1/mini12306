from flask import Flask, render_template, request, jsonify
import sqlite3

app = Flask(__name__)
DB_PATH = "data.db"

# 初始化数据库
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    # 用户表
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (username TEXT PRIMARY KEY, password TEXT, idcard TEXT, phone TEXT, role TEXT)''')
    # 车次表：新增 type 区分 高铁/动车/普速火车/飞机
    c.execute('''CREATE TABLE IF NOT EXISTS trains
                 (train_no TEXT PRIMARY KEY, start TEXT, end TEXT, time TEXT, price REAL, tickets INTEGER, type TEXT)''')
    # 订单表
    c.execute('''CREATE TABLE IF NOT EXISTS orders
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, train_no TEXT, seat TEXT, status TEXT)''')
    # 预设管理员账号
    c.execute("INSERT OR IGNORE INTO users VALUES ('admin','123','111111','13800000000','admin')")

    # ====================== 真实12306公开车次库 开始 ======================
    # 1. 北京南 ↔ 上海虹桥（京沪高铁，最经典线路）
    c.execute("INSERT OR IGNORE INTO trains VALUES ('G1','北京南','上海虹桥','08:00',553,120,'高铁')")
    c.execute("INSERT OR IGNORE INTO trains VALUES ('G3','北京南','上海虹桥','09:00',553,100,'高铁')")
    c.execute("INSERT OR IGNORE INTO trains VALUES ('D200','北京南','上海虹桥','10:30',340,80,'动车')")
    c.execute("INSERT OR IGNORE INTO trains VALUES ('Z19','北京','上海','19:00',177,50,'普速火车')")
    c.execute("INSERT OR IGNORE INTO trains VALUES ('MU5101','北京首都','上海浦东','09:00',720,30,'飞机')")

    # 2. 北京西 ↔ 广州南（京广高铁）
    c.execute("INSERT OR IGNORE INTO trains VALUES ('G69','北京西','广州南','07:30',862,100,'高铁')")
    c.execute("INSERT OR IGNORE INTO trains VALUES ('G81','北京西','广州南','10:00',862,90,'高铁')")
    c.execute("INSERT OR IGNORE INTO trains VALUES ('K599','北京西','广州','17:00',251,40,'普速火车')")

    # 3. 上海虹桥 ↔ 深圳北
    c.execute("INSERT OR IGNORE INTO trains VALUES ('G2781','上海虹桥','深圳北','08:20',608,90,'高铁')")
    c.execute("INSERT OR IGNORE INTO trains VALUES ('9C8871','上海虹桥','深圳宝安','11:00',480,25,'飞机')")

    # 4. 武汉 ↔ 北京西
    c.execute("INSERT OR IGNORE INTO trains VALUES ('G84','武汉','北京西','09:00',522,110,'高铁')")
    c.execute("INSERT OR IGNORE INTO trains VALUES ('G512','汉口','北京西','14:00',520,85,'高铁')")

    # 5. 杭州东 ↔ 广州南
    c.execute("INSERT OR IGNORE INTO trains VALUES ('G1303','杭州东','广州南','12:10',720,75,'高铁')")

    # 6. 成都东 ↔ 重庆西（成渝高铁）
    c.execute("INSERT OR IGNORE INTO trains VALUES ('G8501','成都东','重庆西','07:40',154,150,'高铁')")
    # ====================== 真实12306公开车次库 结束 ======================

    conn.commit()
    conn.close()

# 登录验证
@app.route("/check_login", methods=["POST"])
def check_login():
    username = request.form["username"]
    password = request.form["password"]
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT username,role FROM users WHERE username=? AND password=?", (username, password))
    res = cur.fetchone()
    conn.close()
    if res:
        return f"success|{res[0]}"
    return "fail"

# 注册接口
@app.route("/do_register", methods=["POST"])
def do_register():
    username = request.form["username"]
    password = request.form["password"]
    phone = request.form["phone"]

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT username FROM users WHERE username=?", (username,))
    if cur.fetchone():
        conn.close()
        return "账号已被占用"
    # 正确插入 users 表：username,password,idcard,phone,role
    cur.execute("INSERT INTO users VALUES (?,?,?,?,?)", (username, password, "", phone, "user"))
    conn.commit()
    conn.close()
    return "注册成功"

# 页面路由
@app.route("/")
def login_page():
    return render_template("login.html")

@app.route("/index")
def index_page():
    return render_template("index.html")

@app.route("/buy_page")
def buy_page():
    return render_template("buy.html")

@app.route("/order_page")
def order_page():
    return render_template("order.html")

# 业务接口
@app.route("/get_trains")
def get_trains():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT * FROM trains")
    res = cur.fetchall()
    conn.close()
    return jsonify(res)

# 按出发地、目的地筛选车次
@app.route("/search_trains")
def search_trains():
    start = request.args.get("start", "")
    end = request.args.get("end", "")
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT * FROM trains WHERE start=? AND end=?", (start, end))
    res = cur.fetchall()
    conn.close()
    return jsonify(res)
# 购票
@app.route("/buy", methods=["POST"])
def buy():
    username = request.form["username"]
    train_no = request.form["train_no"]
    seat = request.form["seat"]

    def check_seat(seat):
        num = ""
        char = ""
        for c in seat.upper():
            if c.isdigit(): num += c
            else: char += c
        if not num.isdigit() or len(char) != 1: return False
        row = int(num)
        return 1 <= row <= 17 and char in "ABCDF"

    if not check_seat(seat): return "座位号输入错误"

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT tickets FROM trains WHERE train_no=?", (train_no,))
    tickets = cur.fetchone()[0]
    if tickets <= 0:
        conn.close()
        return "余票不足"
    cur.execute("UPDATE trains SET tickets = tickets - 1 WHERE train_no=?", (train_no,))
    cur.execute("INSERT INTO orders (username,train_no,seat,status) VALUES (?,?,?,'已购票')",(username,train_no,seat))
    conn.commit()
    conn.close()
    return "购票成功"

# 查订单
@app.route("/orders/<username>")
def get_orders(username):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT id,train_no,seat,status FROM orders WHERE username=?", (username,))
    res = cur.fetchall()
    conn.close()
    return jsonify(res)

# 退票（修复订单ID问题）
@app.route("/refund", methods=["POST"])
def refund():
    oid = int(request.form["order_id"])
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT train_no FROM orders WHERE id=?", (oid,))
    tno = cur.fetchone()[0]
    cur.execute("UPDATE orders SET status='已退票' WHERE id=?", (oid,))
    cur.execute("UPDATE trains SET tickets = tickets + 1 WHERE train_no=?", (tno,))
    conn.commit()
    conn.close()
    return "退票成功"

if __name__ == "__main__":
    init_db()
    app.run(debug=True)