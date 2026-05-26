from flask import Flask, render_template, request, jsonify
import sqlite3

app = Flask(__name__)
DB_PATH = "data.db"

# 初始化数据库
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # 用户表（保持不变）
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (username TEXT PRIMARY KEY, password TEXT, idcard TEXT, phone TEXT, role TEXT)''')

    # 车次表：新增 type 区分 高铁/动车/普速火车/飞机
    c.execute('''CREATE TABLE IF NOT EXISTS trains
                 (train_no TEXT PRIMARY KEY, start TEXT, end TEXT, time TEXT, price REAL, tickets INTEGER, type TEXT)''')

    # 订单表（关键修复：增加 price 和 is_student 字段）
    c.execute('''CREATE TABLE IF NOT EXISTS orders
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  username TEXT,
                  train_no TEXT,
                  seat TEXT,
                  status TEXT,
                  price REAL,
                  is_student TEXT)''')

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

@app.route("/register")
def register_page():
    return render_template("register.html")

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

# 购票（支持学生票 + 自动按车型计算折扣，席别模式）
@app.route("/buy", methods=["POST"])
def buy():
    username = request.form["username"]
    train_no = request.form["train_no"]
    seat = request.form["seat"]
    is_student = request.form.get("is_student", "n")

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT tickets, price, type FROM trains WHERE train_no=?", (train_no,))
    tickets, price, train_type = cur.fetchone()

    if tickets <= 0:
        conn.close()
        return "余票不足"

    final_price = price
    # 严格遵循12306学生票规则：仅二等座、硬座打折
    if is_student == "y":
        if (train_type in ("高铁", "动车")) and seat == "二等座":
            final_price = price * 0.75
        elif train_type == "普速火车" and seat == "硬座":
            final_price = price * 0.5

    # 更新余票 + 插入订单
    cur.execute("UPDATE trains SET tickets = tickets - 1 WHERE train_no=?", (train_no,))
    cur.execute(
        "INSERT INTO orders (username,train_no,seat,status,price,is_student) VALUES (?,?,?,'已购票',?,?)",
        (username, train_no, seat, final_price, is_student)
    )
    conn.commit()
    conn.close()
    return f"购票成功！{'学生票' if is_student=='y' else '成人票'}，{seat}票价：{final_price:.2f}元"

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

@app.route("/train_info")
def get_train_info():
    train_no = request.args.get("train_no")
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT start, end, time FROM trains WHERE train_no=?", (train_no,))
    train = cur.fetchone()
    conn.close()
    if train:
        return jsonify({
            "start": train[0],
            "end": train[1],
            "time": train[2]
        })
    else:
        return jsonify({"error": "车次不存在"}), 404

# 查询当前用户所有订单
@app.route("/orders/<username>")
def get_user_orders(username):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    # 查询订单全字段：id, train_no, seat, status, price, is_student
    cur.execute("""
        SELECT id, train_no, seat, status, price, is_student
        FROM orders
        WHERE username = ?
    """, (username,))
    order_list = cur.fetchall()
    conn.close()
    return jsonify(order_list)

if __name__ == "__main__":
    init_db()
    app.run(debug=True)