# -*- coding: utf-8 -*-
"""
Mini12306 铁路售票系统 - Web版 v2.1
全面功能：注册、登录、车次管理、购票、支付、退票、改签、订单、管理员、个人中心
"""

from flask import Flask, render_template, request, jsonify, session, redirect, url_for
import sqlite3, re, time, random, hashlib, json, threading, traceback, os
from datetime import datetime, timedelta

app = Flask(__name__)
app.secret_key = "mini12306_secret_key_2024"
DB_PATH = "data.db"

# 同城车站映射
SAME_CITY = {
    "北京": ["北京", "北京南", "北京西", "北京首都"],
    "上海": ["上海", "上海虹桥", "上海浦东"],
    "广州": ["广州", "广州南"],
    "深圳": ["深圳北", "深圳宝安"],
    "武汉": ["武汉", "汉口"],
    "成都": ["成都东"],
    "重庆": ["重庆西"],
    "杭州": ["杭州东"],
    "西安": ["西安北"],
    "南京": ["南京南"],
    "郑州": ["郑州东"],
    "长沙": ["长沙南"],
    "天津": ["天津南", "天津西"],
    "济南": ["济南西"],
    "青岛": ["青岛"],
    "沈阳": ["沈阳北"],
    "大连": ["大连北"],
    "哈尔滨": ["哈尔滨西"],
    "福州": ["福州", "福州南"],
    "厦门": ["厦门", "厦门北"],
    "合肥": ["合肥南"],
    "昆明": ["昆明南"],
    "贵阳": ["贵阳北"],
    "南昌": ["南昌西"],
    "兰州": ["兰州西"],
    "石家庄": ["石家庄"],
    "太原": ["太原南"],
    "南宁": ["南宁东"],
}
def get_same_city_stations(station):
    """返回与给定车站同城的所有车站列表"""
    for key, group in SAME_CITY.items():
        if station == key or station in group:
            return group
    # 也被其他城组作为别名的情况
    for key, group in SAME_CITY.items():
        if station in group:
            return group
    return [station]

# 席别折扣系数
SEAT_DISCOUNTS = {"二等座":1.0,"一等座":1.2,"商务座":2.5,"硬座":1.0,"硬卧":1.5,"软卧":2.0,"经济舱":1.0,"商务舱":2.0}

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("PRAGMA foreign_keys = ON")

    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL, password TEXT NOT NULL,
        idcard TEXT UNIQUE NOT NULL, phone TEXT UNIQUE NOT NULL,
        role TEXT DEFAULT 'user', login_attempts INTEGER DEFAULT 0, locked_until TEXT)''')

    c.execute('''CREATE TABLE IF NOT EXISTS trains (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        train_no TEXT UNIQUE NOT NULL, start TEXT NOT NULL, end TEXT NOT NULL,
        depart_time TEXT NOT NULL, arrive_time TEXT NOT NULL,
        price REAL NOT NULL, seat_types TEXT NOT NULL,
        total_tickets INTEGER NOT NULL, remaining_tickets INTEGER NOT NULL,
        type TEXT NOT NULL, travel_date TEXT NOT NULL)''')

    c.execute('''CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_no TEXT UNIQUE NOT NULL, username TEXT NOT NULL,
        passenger_name TEXT NOT NULL, train_no TEXT NOT NULL,
        start TEXT, end TEXT, depart_time TEXT, arrive_time TEXT,
        seat_type TEXT NOT NULL, price REAL NOT NULL,
        status TEXT DEFAULT '待支付', pay_status TEXT DEFAULT '未支付',
        is_student TEXT DEFAULT 'n', create_time TEXT, pay_time TEXT,
        original_order_id INTEGER)''')

    c.execute('''CREATE TABLE IF NOT EXISTS passengers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL, passenger_name TEXT NOT NULL,
        idcard TEXT NOT NULL, phone TEXT)''')

    c.execute('''CREATE TABLE IF NOT EXISTS sys_config (
        id INTEGER PRIMARY KEY AUTOINCREMENT, key TEXT UNIQUE NOT NULL, value TEXT NOT NULL)''')

    c.execute('''CREATE TABLE IF NOT EXISTS sys_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, action TEXT NOT NULL,
        detail TEXT, ip TEXT, create_time TEXT)''')

    defaults = {"refund_fee_24h": "0.10", "refund_fee_48h": "0.05", "pay_timeout": "600", "daily_buy_limit": "5"}
    for k, v in defaults.items():
        c.execute("INSERT OR IGNORE INTO sys_config (key, value) VALUES (?, ?)", (k, v))

    admin_pwd = hashlib.sha256("Admin123".encode()).hexdigest()
    c.execute("INSERT OR IGNORE INTO users (username, password, idcard, phone, role) VALUES (?,?,?,?,?)",
              ("admin", admin_pwd, "110101199001010001", "13800000000", "admin"))
    user_pwd = hashlib.sha256("User1234".encode()).hexdigest()
    c.execute("INSERT OR IGNORE INTO users (username, password, idcard, phone, role) VALUES (?,?,?,?,?)",
              ("testuser", user_pwd, "320106199508152234", "13912345678", "user"))

    # 从 JSON 文件加载车次数据
    today = datetime.now().date()
    json_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "trains.json")
    if os.path.exists(json_path):
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        days = data.get("days", 30)
        test_trains_raw = data.get("trains", [])
        print(f"  [INFO] 从 trains.json 加载了 {len(test_trains_raw)} 条基准车次")
    else:
        days = 30
        test_trains_raw = [
            {"train_no":"G1","start":"北京南","end":"上海虹桥","depart_time":"08:00","arrive_time":"12:30","price":553,"seat_types":["二等座","一等座","商务座"],"total_tickets":120,"type":"高铁"},
            {"train_no":"G3","start":"北京南","end":"上海虹桥","depart_time":"09:00","arrive_time":"13:30","price":553,"seat_types":["二等座","一等座","商务座"],"total_tickets":100,"type":"高铁"},
            {"train_no":"D200","start":"北京南","end":"上海虹桥","depart_time":"10:30","arrive_time":"15:00","price":340,"seat_types":["二等座","一等座"],"total_tickets":80,"type":"动车"},
            {"train_no":"Z19","start":"北京","end":"上海","depart_time":"19:00","arrive_time":"07:30","price":177,"seat_types":["硬座","硬卧","软卧"],"total_tickets":50,"type":"普速火车"},
            {"train_no":"MU5101","start":"北京首都","end":"上海浦东","depart_time":"09:00","arrive_time":"11:00","price":720,"seat_types":["经济舱","商务舱"],"total_tickets":30,"type":"飞机"},
            {"train_no":"G69","start":"北京西","end":"广州南","depart_time":"07:30","arrive_time":"15:00","price":862,"seat_types":["二等座","一等座","商务座"],"total_tickets":100,"type":"高铁"},
            {"train_no":"G81","start":"北京西","end":"广州南","depart_time":"10:00","arrive_time":"17:30","price":862,"seat_types":["二等座","一等座","商务座"],"total_tickets":90,"type":"高铁"},
            {"train_no":"G84","start":"武汉","end":"北京西","depart_time":"09:00","arrive_time":"13:00","price":522,"seat_types":["二等座","一等座","商务座"],"total_tickets":110,"type":"高铁"},
            {"train_no":"G512","start":"汉口","end":"北京西","depart_time":"14:00","arrive_time":"18:00","price":520,"seat_types":["二等座","一等座","商务座"],"total_tickets":85,"type":"高铁"},
            {"train_no":"G8501","start":"成都东","end":"重庆西","depart_time":"07:40","arrive_time":"09:10","price":154,"seat_types":["二等座","一等座","商务座"],"total_tickets":150,"type":"高铁"},
        ]
        print(f"  [WARN] 未找到 trains.json，使用默认 {len(test_trains_raw)} 条车次")
    for train in test_trains_raw:
        for i in range(days):
            d = today + timedelta(days=i)
            ds = d.strftime("%Y-%m-%d")
            tno = train["train_no"] + "_" + ds
            c.execute("INSERT OR IGNORE INTO trains (train_no,start,end,depart_time,arrive_time,price,seat_types,total_tickets,remaining_tickets,type,travel_date) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                      (tno, train["start"], train["end"], train["depart_time"], train["arrive_time"], train["price"], json.dumps(train["seat_types"]), train["total_tickets"], train["total_tickets"], train["type"], ds))

    c.execute("INSERT OR IGNORE INTO passengers (username, passenger_name, idcard, phone) VALUES (?,?,?,?)",
              ("testuser", "张三", "320106199508152234", "13912345678"))
    c.execute("INSERT OR IGNORE INTO passengers (username, passenger_name, idcard, phone) VALUES (?,?,?,?)",
              ("testuser", "李四", "110101199502150019", "13600001111"))
    conn.commit()
    conn.close()

# ---- 工具函数 ----
def write_log(username, action, detail=""):
    conn = get_db()
    c = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ip = request.remote_addr if request else ""
    c.execute("INSERT INTO sys_logs (username,action,detail,ip,create_time) VALUES (?,?,?,?,?)",
              (username, action, detail, ip, now))
    conn.commit()
    conn.close()

def validate_idcard(idcard):
    if len(idcard) != 18: return False
    if not re.match(r'^[1-9]\d{5}(19|20)\d{2}(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])\d{3}[\dXx]$', idcard): return False
    weight = [7,9,10,5,8,4,2,1,6,3,7,9,10,5,8,4,2]
    check_codes = "10X98765432"
    s = sum(int(idcard[i]) * weight[i] for i in range(17))
    return check_codes[s % 11] == idcard[17].upper()

def validate_phone(phone):
    return bool(re.match(r'^1[3-9]\d{9}$', phone))

def validate_password(password):
    if len(password) < 8: return False, "密码长度不能少于8位"
    if not re.search(r'[A-Z]', password): return False, "密码必须包含大写字母"
    if not re.search(r'[a-z]', password): return False, "密码必须包含小写字母"
    if not re.search(r'\d', password): return False, "密码必须包含数字"
    return True, ""

def check_unpaid_orders():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT value FROM sys_config WHERE key='pay_timeout'")
    row = c.fetchone()
    if not row: conn.close(); return
    timeout = int(row["value"])
    now = datetime.now()
    c.execute("SELECT * FROM orders WHERE pay_status='未支付'")
    for order in c.fetchall():
        try:
            create_time = datetime.strptime(order["create_time"], "%Y-%m-%d %H:%M:%S")
            if (now - create_time).total_seconds() > timeout:
                c.execute("UPDATE orders SET pay_status='已取消', status='已退票' WHERE id=?", (order["id"],))
                c.execute("UPDATE trains SET remaining_tickets = remaining_tickets + 1 WHERE train_no=?", (order["train_no"],))
                write_log(order["username"], "订单超时取消", f"订单号:{order['order_no']}")
        except: pass
    conn.commit()
    conn.close()

def auto_cancel_worker():
    while True:
        time.sleep(60)
        try: check_unpaid_orders()
        except: pass

bg_thread = threading.Thread(target=auto_cancel_worker, daemon=True)
bg_thread.start()

# ---- 页面路由 ----
@app.route("/")
def login_page(): return render_template("login.html")
@app.route("/register")
def register_page(): return render_template("register.html")
@app.route("/index")
def index_page(): return render_template("index.html")
@app.route("/buy_page")
def buy_page(): return render_template("buy.html")
@app.route("/order_page")
def order_page(): return render_template("order.html")
@app.route("/personal_page")
def personal_page(): return render_template("personal.html")
@app.route("/admin_page")
def admin_page(): return render_template("admin.html")
@app.route("/pay_page")
def pay_page(): return render_template("pay.html")
@app.route("/reschedule_page")
def reschedule_page(): return render_template("reschedule.html")
@app.route("/reset_password")
def reset_password_page(): return render_template("reset_password.html")

# ---- 认证 ----
@app.route("/check_login", methods=["POST"])
def check_login():
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "").strip()
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE username=?", (username,))
    user = c.fetchone()
    if not user: conn.close(); return "fail|账号不存在"
    if user["locked_until"]:
        try:
            locked = datetime.strptime(user["locked_until"], "%Y-%m-%d %H:%M:%S")
            if datetime.now() < locked:
                remain = int((locked - datetime.now()).total_seconds())
                conn.close(); return f"fail|账号已锁定，请{remain}秒后再试"
        except: pass
    hashed = hashlib.sha256(password.encode()).hexdigest()
    if hashed != user["password"]:
        attempts = user["login_attempts"] + 1
        if attempts >= 3:
            lock_time = (datetime.now() + timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")
            c.execute("UPDATE users SET login_attempts=?, locked_until=? WHERE username=?", (attempts, lock_time, username))
            write_log(username, "账号锁定", "密码连续输错3次，锁定5分钟")
        else:
            c.execute("UPDATE users SET login_attempts=? WHERE username=?", (attempts, username))
        conn.commit(); conn.close()
        return f"fail|密码错误，还剩{3 - attempts}次机会"
    c.execute("UPDATE users SET login_attempts=0, locked_until=NULL WHERE username=?", (username,))
    conn.commit()
    write_log(username, "用户登录", f"角色:{user['role']}")
    conn.close()
    session["username"] = username
    session["role"] = user["role"]
    return f"success|{username}|{user['role']}"

@app.route("/logout")
def logout():
    username = session.get("username", "")
    write_log(username, "用户登出")
    session.clear()
    return redirect("/")

@app.route("/do_register", methods=["POST"])
def do_register():
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "").strip()
    idcard = request.form.get("idcard", "").strip()
    phone = request.form.get("phone", "").strip()
    if not all([username, password, idcard, phone]): return "所有字段均为必填"
    valid, msg = validate_password(password)
    if not valid: return msg
    if not validate_idcard(idcard): return "身份证号码格式不正确"
    if not validate_phone(phone): return "手机号格式不正确"
    conn = get_db(); c = conn.cursor()
    if c.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone(): conn.close(); return "用户名已被占用"
    if c.execute("SELECT id FROM users WHERE idcard=?", (idcard,)).fetchone(): conn.close(); return "该身份证号已注册"
    if c.execute("SELECT id FROM users WHERE phone=?", (phone,)).fetchone(): conn.close(); return "该手机号已注册"
    hashed = hashlib.sha256(password.encode()).hexdigest()
    c.execute("INSERT INTO users (username,password,idcard,phone,role) VALUES (?,?,?,?,?)", (username, hashed, idcard, phone, "user"))
    conn.commit(); conn.close()
    write_log(username, "用户注册", f"手机:{phone}")
    return "注册成功"

@app.route("/do_reset_password", methods=["POST"])
def do_reset_password():
    username = request.form.get("username", "").strip()
    phone = request.form.get("phone", "").strip()
    idcard = request.form.get("idcard", "").strip()
    new_password = request.form.get("new_password", "").strip()
    conn = get_db(); c = conn.cursor()
    if not c.execute("SELECT * FROM users WHERE username=? AND phone=? AND idcard=?", (username, phone, idcard)).fetchone():
        conn.close(); return "验证失败：信息不匹配"
    valid, msg = validate_password(new_password)
    if not valid: conn.close(); return msg
    hashed = hashlib.sha256(new_password.encode()).hexdigest()
    c.execute("UPDATE users SET password=?, login_attempts=0, locked_until=NULL WHERE username=?", (hashed, username))
    conn.commit(); conn.close()
    write_log(username, "重置密码", "通过手机号验证")
    return "密码重置成功，请重新登录"

# ---- 车次查询 ----
@app.route("/get_trains")
def get_trains():
    conn = get_db(); c = conn.cursor()
    today = datetime.now().strftime("%Y-%m-%d")
    start = request.args.get("start", "")
    end = request.args.get("end", "")
    date = request.args.get("date", today)
    train_no = request.args.get("train_no", "")
    train_type = request.args.get("type", "")
    where = ["travel_date >= ?"]
    params = [today]
    if start:
        start_group = get_same_city_stations(start)
        placeholders = ",".join(["?"] * len(start_group))
        where.append(f"start IN ({placeholders})")
        params.extend(start_group)
    if end:
        end_group = get_same_city_stations(end)
        placeholders = ",".join(["?"] * len(end_group))
        where.append(f"end IN ({placeholders})")
        params.extend(end_group)
    if date: where.append("travel_date=?"); params.append(date)
    if train_no: where.append("train_no LIKE ?"); params.append(f"%{train_no}%")
    if train_type: where.append("type=?"); params.append(train_type)
    c.execute("SELECT * FROM trains WHERE " + " AND ".join(where) + " ORDER BY travel_date, depart_time LIMIT 500", params)
    rows = c.fetchall(); conn.close()
    return jsonify([dict(r) for r in rows])

@app.route("/search_trains")
def search_trains(): return get_trains()

@app.route("/train_info")
def get_train_info():
    train_no = request.args.get("train_no", "")
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT * FROM trains WHERE train_no=?", (train_no,))
    train = c.fetchone(); conn.close()
    if train: return jsonify(dict(train))
    return jsonify({"error": "车次不存在"}), 404

@app.route("/get_dates")
def get_dates():
    today = datetime.now().date()
    week = ["周日","周一","周二","周三","周四","周五","周六"]
    dates = []
    for i in range(15):
        d = today + timedelta(days=i)
        dates.append({"value": d.strftime("%Y-%m-%d"), "label": f"{d.month}月{d.day}日 {week[d.weekday()]}"})
    return jsonify(dates)

# ---- 购票 (关键：所有返回都是JSON) ----
@app.route("/buy", methods=["POST"])
def buy():
    try:
        username = request.form.get("username", "").strip()
        train_no = request.form.get("train_no", "").strip()
        seat_type = request.form.get("seat", "").strip()
        is_student = request.form.get("is_student", "n").strip()
        passenger_name = request.form.get("passenger_name", "").strip()

        if not all([username, train_no, seat_type, passenger_name]):
            return jsonify({"success": False, "msg": "参数不完整（车次、乘车人、席别不能为空）"})

        conn = get_db(); c = conn.cursor()

        c.execute("SELECT value FROM sys_config WHERE key='daily_buy_limit'")
        daily_limit = int(c.fetchone()["value"])
        today = datetime.now().strftime("%Y-%m-%d")
        c.execute("SELECT COUNT(*) as cnt FROM orders WHERE username=? AND create_time LIKE ? AND pay_status='已支付' AND status NOT IN ('已退票','已改签')",
                  (username, f"{today}%"))
        cur_cnt = c.fetchone()["cnt"]
        if cur_cnt >= daily_limit:
            conn.close()
            return jsonify({"success": False, "msg": f"今日购票已达上限（{daily_limit}张），你当前已有{cur_cnt}张有效票，无法继续购买"})

        c.execute("SELECT * FROM trains WHERE train_no=?", (train_no,))
        train = c.fetchone()
        if not train:
            conn.close()
            return jsonify({"success": False, "msg": "车次不存在"})

        if train["remaining_tickets"] <= 0:
            conn.close()
            return jsonify({"success": False, "msg": "余票不足"})

        price = train["price"]
        train_type = train["type"]
        # 尝试从 seat_types JSON 中读取该席别的实际票价
        try:
            seats = json.loads(train["seat_types"])
            if isinstance(seats, list) and len(seats) > 0 and isinstance(seats[0], dict):
                # 新格式 [{name,price,tickets},...]
                found = False
                for s in seats:
                    if s.get("name") == seat_type:
                        price = s["price"]
                        found = True
                        break
                if not found:
                    price = price * SEAT_DISCOUNTS.get(seat_type, 1.0)
            else:
                # 旧格式 ["二等座","一等座",...]
                price = price * SEAT_DISCOUNTS.get(seat_type, 1.0)
        except:
            price = price * SEAT_DISCOUNTS.get(seat_type, 1.0)
        if is_student == "y":
            if (train_type in ("高铁","动车")) and seat_type == "二等座": price *= 0.75
            elif train_type == "普速火车" and seat_type == "硬座": price *= 0.5

        order_no = "M" + datetime.now().strftime("%Y%m%d%H%M%S") + str(random.randint(1000,9999))
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        c.execute('''INSERT INTO orders (order_no,username,passenger_name,train_no,start,end,depart_time,arrive_time,
                     seat_type,price,status,pay_status,is_student,create_time)
                     VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                  (order_no, username, passenger_name, train_no, train["start"], train["end"],
                   train["depart_time"], train["arrive_time"], seat_type, round(price, 2),
                   "待支付", "未支付", is_student, now))
        conn.commit(); conn.close()
        write_log(username, "创建订单", f"订单号:{order_no}, 车次:{train_no}")
        return jsonify({"success": True, "order_no": order_no, "price": round(price, 2)})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "msg": f"系统错误: {str(e)}"})

# ---- 支付 ----
@app.route("/pay", methods=["POST"])
def pay():
    order_no = request.form.get("order_no", "").strip()
    if not order_no: return "缺少订单号"
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT * FROM orders WHERE order_no=?", (order_no,))
    order = c.fetchone()
    if not order: conn.close(); return "订单不存在"
    if order["pay_status"] != "未支付": conn.close(); return "订单状态异常"
    rand = random.random()
    if rand < 0.80:
        c.execute("UPDATE trains SET remaining_tickets = remaining_tickets - 1 WHERE train_no=? AND remaining_tickets > 0", (order["train_no"],))
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        c.execute("UPDATE orders SET pay_status='已支付', status='已购票', pay_time=? WHERE order_no=?", (now, order_no))
        conn.commit(); conn.close()
        write_log(order["username"], "支付成功", f"订单号:{order_no}")
        return "支付成功"
    elif rand < 0.95: conn.close(); return "支付失败"
    else: conn.close(); return "支付超时"

# ---- 订单 ----
@app.route("/orders/<username>")
def get_user_orders(username):
    conn = get_db(); c = conn.cursor()
    active_only = request.args.get("active") == "1"
    if active_only:
        c.execute("SELECT * FROM orders WHERE username=? AND pay_status='已支付' AND status NOT IN ('已退票','已改签') ORDER BY id DESC", (username,))
    else:
        c.execute("SELECT * FROM orders WHERE username=? ORDER BY id DESC", (username,))
    rows = c.fetchall()
    # 查改签订单的原车次信息
    result = []
    for r in rows:
        d = dict(r)
        if d.get("original_order_id"):
            c2 = conn.cursor()
            c2.execute("SELECT train_no,seat_type FROM orders WHERE id=?", (d["original_order_id"],))
            orig = c2.fetchone()
            if orig:
                d["original_train_no"] = orig["train_no"]
                d["original_seat_type"] = orig["seat_type"]
        result.append(d)
    conn.close()
    return jsonify(result)

@app.route("/all_orders")
def get_all_orders():
    if session.get("role") != "admin": return jsonify([])
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT * FROM orders ORDER BY id DESC")
    rows = c.fetchall(); conn.close()
    return jsonify([dict(r) for r in rows])

@app.route("/cancel_order", methods=["POST"])
def cancel_order():
    order_id = request.form.get("order_id", "")
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT * FROM orders WHERE id=?", (order_id,))
    order = c.fetchone()
    if not order: conn.close(); return "订单不存在"
    if order["pay_status"] != "未支付": conn.close(); return "仅可取消未支付订单"
    c.execute("UPDATE orders SET pay_status='已取消', status='已退票' WHERE id=?", (order_id,))
    conn.commit(); conn.close()
    write_log(order["username"], "取消订单", f"订单号:{order['order_no']}")
    return "取消成功"

# ---- 退票 ----
@app.route("/refund", methods=["POST"])
def refund():
    order_id = request.form.get("order_id", "")
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT * FROM orders WHERE id=?", (order_id,))
    order = c.fetchone()
    if not order: conn.close(); return "订单不存在"
    if order["pay_status"] != "已支付": conn.close(); return "仅可退已支付订单"
    if order["status"] == "已退票": conn.close(); return "该订单已退票"
    c.execute("SELECT * FROM trains WHERE train_no=?", (order["train_no"],))
    train = c.fetchone()
    refund_amount = order["price"]
    if train:
        depart_dt = datetime.strptime(train["travel_date"] + " " + train["depart_time"], "%Y-%m-%d %H:%M")
        now = datetime.now()
        diff_hours = (depart_dt - now).total_seconds() / 3600
        if diff_hours < 0: conn.close(); return "已发车，无法退票"
        fee_rate = 0
        if diff_hours < 24:
            c.execute("SELECT value FROM sys_config WHERE key='refund_fee_24h'")
            fee_rate = float(c.fetchone()["value"])
        elif diff_hours < 48:
            c.execute("SELECT value FROM sys_config WHERE key='refund_fee_48h'")
            fee_rate = float(c.fetchone()["value"])
        refund_amount = order["price"] * (1 - fee_rate)
    c.execute("UPDATE orders SET status='已退票' WHERE id=?", (order_id,))
    c.execute("UPDATE trains SET remaining_tickets = remaining_tickets + 1 WHERE train_no=?", (order["train_no"],))
    conn.commit(); conn.close()
    write_log(order["username"], "退票", f"订单号:{order['order_no']}, 退款:¥{round(refund_amount,2)}")
    return f"退票成功，退款 ¥{round(refund_amount, 2)}"

# ---- 改签 ----
@app.route("/reschedule_info/<int:order_id>")
def reschedule_info(order_id):
    """获取改签页面所需的订单与可选车次信息"""
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT * FROM orders WHERE id=?", (order_id,))
    order = c.fetchone()
    if not order: conn.close(); return jsonify({"error": "订单不存在"}), 404

    c.execute("SELECT * FROM trains WHERE train_no=?", (order["train_no"],))
    old_train = c.fetchone()

    old_start_stations = get_same_city_stations(old_train["start"]) if old_train else []
    old_end_stations = get_same_city_stations(old_train["end"]) if old_train else []

    # 查找同路线或同城车站的可选车次
    today = datetime.now().strftime("%Y-%m-%d")
    placeholders_start = ",".join(["?"] * len(old_start_stations))
    placeholders_end = ",".join(["?"] * len(old_end_stations))

    c.execute(f"""SELECT * FROM trains WHERE start IN ({placeholders_start}) AND end IN ({placeholders_end})
                  AND travel_date >= ? AND remaining_tickets > 0 ORDER BY travel_date, depart_time""",
              old_start_stations + old_end_stations + [today])
    trains = [dict(r) for r in c.fetchall()]
    conn.close()

    result = {
        "order": dict(order),
        "old_train": dict(old_train) if old_train else None,
        "available_trains": trains,
        "same_city_start": old_start_stations,
        "same_city_end": old_end_stations,
    }
    return jsonify(result)

@app.route("/reschedule", methods=["POST"])
def reschedule():
    order_id = request.form.get("order_id", "")
    new_train_no = request.form.get("new_train_no", "")
    new_seat_type = request.form.get("new_seat_type", "")

    conn = get_db(); c = conn.cursor()

    c.execute("SELECT * FROM orders WHERE id=?", (order_id,))
    order = c.fetchone()
    if not order: conn.close(); return jsonify({"success": False, "msg": "订单不存在"})
    if order["pay_status"] != "已支付": conn.close(); return jsonify({"success": False, "msg": "仅可改签已支付订单"})
    if order["status"] in ("已退票", "已改签", "改签待支付"):
        conn.close(); return jsonify({"success": False, "msg": "订单状态不可改签"})

    c.execute("SELECT * FROM trains WHERE train_no=?", (new_train_no,))
    new_train = c.fetchone()
    if not new_train: conn.close(); return jsonify({"success": False, "msg": "新车次不存在"})

    c.execute("SELECT * FROM trains WHERE train_no=?", (order["train_no"],))
    old_train = c.fetchone()

    # 验证发到站：同城或完全相同
    old_start_group = get_same_city_stations(old_train["start"])
    old_end_group = get_same_city_stations(old_train["end"])
    if new_train["start"] not in old_start_group or new_train["end"] not in old_end_group:
        conn.close(); return jsonify({"success": False, "msg": "仅可改签同城车站或相同发到站的车次"})

    if new_train["remaining_tickets"] <= 0:
        conn.close(); return jsonify({"success": False, "msg": "新车次余票不足"})

    # 使用新席别（如果未指定则保留原席别）
    seat_type = new_seat_type if new_seat_type else order["seat_type"]

    # 计算新票价
    new_price = new_train["price"] * SEAT_DISCOUNTS.get(seat_type, 1.0)
    # 学生票折扣
    if order["is_student"] == "y":
        if (new_train["type"] in ("高铁","动车")) and seat_type == "二等座":
            new_price *= 0.75
        elif new_train["type"] == "普速火车" and seat_type == "硬座":
            new_price *= 0.5

    new_price = round(new_price, 2)
    old_price = order["price"]
    price_diff = round(new_price - old_price, 2)

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    order_no = "R" + datetime.now().strftime("%Y%m%d%H%M%S") + str(random.randint(1000, 9999))

    # 原订单标记为已改签，释放原车次余票
    c.execute("UPDATE orders SET status='已改签' WHERE id=?", (order_id,))
    c.execute("UPDATE trains SET remaining_tickets = remaining_tickets + 1 WHERE train_no=?", (order["train_no"],))

    if price_diff > 0:
        # 需要补差价：创建待支付改签订单
        c.execute("UPDATE trains SET remaining_tickets = remaining_tickets - 1 WHERE train_no=?", (new_train_no,))
        c.execute('''INSERT INTO orders (order_no,username,passenger_name,train_no,start,end,depart_time,arrive_time,
                     seat_type,price,status,pay_status,is_student,create_time,original_order_id)
                     VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                  (order_no, order["username"], order["passenger_name"], new_train_no,
                   new_train["start"], new_train["end"], new_train["depart_time"], new_train["arrive_time"],
                   seat_type, new_price, "改签待支付", "未支付", order["is_student"], now, order_id))
        conn.commit(); conn.close()
        write_log(order["username"], "改签申请", f"原订单:{order['order_no']} -> {new_train_no}, 需补差价:¥{price_diff}")
        return jsonify({
            "success": True, "need_pay": True, "price_diff": price_diff,
            "order_no": order_no, "new_price": new_price, "old_price": old_price
        })

    # 便宜或同价：直接改签成功，退差价（如有）
    c.execute("UPDATE trains SET remaining_tickets = remaining_tickets - 1 WHERE train_no=?", (new_train_no,))
    c.execute('''INSERT INTO orders (order_no,username,passenger_name,train_no,start,end,depart_time,arrive_time,
                 seat_type,price,status,pay_status,is_student,create_time,pay_time,original_order_id)
                 VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
              (order_no, order["username"], order["passenger_name"], new_train_no,
               new_train["start"], new_train["end"], new_train["depart_time"], new_train["arrive_time"],
               seat_type, new_price, "已改签", "已支付", order["is_student"], now, now, order_id))
    conn.commit(); conn.close()

    msg = f"改签成功，退差价 ¥{abs(price_diff)}" if price_diff < 0 else "改签成功"
    write_log(order["username"], "改签成功", f"原订单:{order['order_no']} -> {new_train_no}, 差价:¥{price_diff}")
    return jsonify({
        "success": True, "need_pay": False, "price_diff": price_diff,
        "msg": msg, "order_no": order_no, "new_price": new_price, "old_price": old_price
    })

@app.route("/pay_reschedule", methods=["POST"])
def pay_reschedule():
    """支付改签差价"""
    order_no = request.form.get("order_no", "").strip()
    if not order_no: return "缺少订单号"
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT * FROM orders WHERE order_no=?", (order_no,))
    order = c.fetchone()
    if not order: conn.close(); return "改签订单不存在"
    if order["pay_status"] != "未支付": conn.close(); return "订单状态异常"
    if order["status"] != "改签待支付": conn.close(); return "非改签订单"

    rand = random.random()
    if rand < 0.80:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        c.execute("UPDATE orders SET pay_status='已支付', status='已改签', pay_time=? WHERE order_no=?", (now, order_no))
        conn.commit(); conn.close()
        write_log(order["username"], "改签支付成功", f"订单号:{order_no}")
        return "支付成功，改签完成"
    elif rand < 0.95: conn.close(); return "支付失败"
    else: conn.close(); return "支付超时"

# ---- 乘车人 ----
@app.route("/passengers/<username>")
def get_passengers(username):
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT * FROM passengers WHERE username=?", (username,))
    rows = c.fetchall(); conn.close()
    return jsonify([dict(r) for r in rows])

@app.route("/add_passenger", methods=["POST"])
def add_passenger():
    username = request.form.get("username", "").strip()
    passenger_name = request.form.get("passenger_name", "").strip()
    idcard = request.form.get("idcard", "").strip()
    phone = request.form.get("phone", "").strip()
    if not all([username, passenger_name, idcard]): return "姓名和身份证号必填"
    if not validate_idcard(idcard): return "身份证号格式不正确"
    conn = get_db(); c = conn.cursor()
    if c.execute("SELECT id FROM passengers WHERE username=? AND idcard=?", (username, idcard)).fetchone():
        conn.close(); return "该乘车人已存在（同一身份证号不可重复添加）"
    c.execute("INSERT INTO passengers (username,passenger_name,idcard,phone) VALUES (?,?,?,?)",
              (username, passenger_name, idcard, phone))
    conn.commit(); conn.close()
    return "添加成功"

@app.route("/del_passenger", methods=["POST"])
def del_passenger():
    pid = request.form.get("id", "")
    conn = get_db(); c = conn.cursor()
    c.execute("DELETE FROM passengers WHERE id=?", (pid,))
    conn.commit(); conn.close()
    return "删除成功"

# ---- 个人中心 ----
@app.route("/get_profile")
def get_profile():
    username = session.get("username", "") or request.args.get("username", "")
    if not username: return jsonify({})
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT username, idcard, phone, role FROM users WHERE username=?", (username,))
    user = c.fetchone(); conn.close()
    return jsonify(dict(user)) if user else jsonify({})

@app.route("/change_password", methods=["POST"])
def change_password():
    username = request.form.get("username", "").strip()
    old_password = request.form.get("old_password", "").strip()
    new_password = request.form.get("new_password", "").strip()
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT password FROM users WHERE username=?", (username,))
    user = c.fetchone()
    if not user: conn.close(); return "用户不存在"
    if hashlib.sha256(old_password.encode()).hexdigest() != user["password"]: conn.close(); return "原密码错误"
    valid, msg = validate_password(new_password)
    if not valid: conn.close(); return msg
    c.execute("UPDATE users SET password=? WHERE username=?", (hashlib.sha256(new_password.encode()).hexdigest(), username))
    conn.commit(); conn.close()
    write_log(username, "修改密码")
    return "密码修改成功"

# ---- 管理员 ----
@app.route("/admin/add_train", methods=["POST"])
def admin_add_train():
    if session.get("role") != "admin": return "无权限"
    data = request.form
    required = ["train_no","start","end","depart_time","arrive_time","type","travel_date"]
    for f in required:
        if not data.get(f): return f"缺少字段: {f}"
    train_no = data["train_no"] + "_" + data["travel_date"]
    # 新格式：seat_details 为 JSON 数组 [{name,price,tickets},...]
    seat_details_str = data.get("seat_details", "")
    if seat_details_str:
        seat_details = json.loads(seat_details_str)
        seat_types_json = json.dumps(seat_details)
        total = sum(s["tickets"] for s in seat_details)
        price = min(s["price"] for s in seat_details)
    else:
        # 兼容旧格式
        seat_types_json = data.get("seat_types", '["二等座","一等座","商务座"]')
        price = float(data.get("price", 0))
        total = int(data.get("total_tickets", 0))
    conn = get_db(); c = conn.cursor()
    try:
        c.execute('''INSERT INTO trains (train_no,start,end,depart_time,arrive_time,price,seat_types,total_tickets,remaining_tickets,type,travel_date)
                     VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
                  (train_no, data["start"], data["end"], data["depart_time"], data["arrive_time"],
                   price, seat_types_json, total, total, data["type"], data["travel_date"]))
        conn.commit(); conn.close()
        write_log(session.get("username"), "新增车次", f"车次:{train_no}")
        return "添加成功"
    except Exception as e: conn.close(); return f"添加失败: {str(e)}"

@app.route("/admin/update_train", methods=["POST"])
def admin_update_train():
    if session.get("role") != "admin": return "无权限"
    train_no = request.form.get("train_no", "")
    field = request.form.get("field", "")
    value = request.form.get("value", "")
    allowed = ["price","remaining_tickets","total_tickets","depart_time","arrive_time"]
    if field not in allowed: return "不允许修改的字段"
    conn = get_db(); c = conn.cursor()
    c.execute(f"UPDATE trains SET {field}=? WHERE train_no=?", (float(value) if any(x in field for x in ["price","tickets"]) else value, train_no))
    conn.commit(); conn.close()
    write_log(session.get("username"), "修改车次", f"车次:{train_no}, {field}={value}")
    return "修改成功"

@app.route("/admin/del_train", methods=["POST"])
def admin_del_train():
    if session.get("role") != "admin": return "无权限"
    train_no = request.form.get("train_no", "")
    conn = get_db(); c = conn.cursor()
    c.execute("DELETE FROM trains WHERE train_no=?", (train_no,))
    conn.commit(); conn.close()
    write_log(session.get("username"), "删除车次", f"车次:{train_no}")
    return "删除成功"

@app.route("/admin/users")
def admin_get_users():
    if session.get("role") != "admin": return jsonify([])
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT id,username,idcard,phone,role,login_attempts,locked_until FROM users")
    rows = c.fetchall(); conn.close()
    return jsonify([dict(r) for r in rows])

@app.route("/admin/toggle_user", methods=["POST"])
def admin_toggle_user():
    if session.get("role") != "admin": return "无权限"
    username = request.form.get("username", "")
    action = request.form.get("action", "")
    conn = get_db(); c = conn.cursor()
    if action == "disable":
        c.execute("UPDATE users SET locked_until='2999-12-31 23:59:59' WHERE username=?", (username,))
    else:
        c.execute("UPDATE users SET locked_until=NULL, login_attempts=0 WHERE username=?", (username,))
    conn.commit(); conn.close()
    write_log(session.get("username"), f"{'禁用' if action=='disable' else '启用'}用户", f"用户名:{username}")
    return "操作成功"

@app.route("/admin/config")
def admin_get_config():
    if session.get("role") != "admin": return jsonify({})
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT * FROM sys_config")
    rows = c.fetchall(); conn.close()
    return jsonify([dict(r) for r in rows])

@app.route("/admin/update_config", methods=["POST"])
def admin_update_config():
    if session.get("role") != "admin": return "无权限"
    key = request.form.get("key", ""); value = request.form.get("value", "")
    conn = get_db(); c = conn.cursor()
    c.execute("UPDATE sys_config SET value=? WHERE key=?", (value, key))
    conn.commit(); conn.close()
    write_log(session.get("username"), "修改系统配置", f"{key}={value}")
    return "保存成功"

@app.route("/order_count/<username>")
def order_count(username):
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT COUNT(*) as cnt FROM orders WHERE username=? AND pay_status='已支付' AND status NOT IN ('已退票','已改签')", (username,))
    active = c.fetchone()["cnt"]
    c.execute("SELECT COUNT(*) as cnt FROM orders WHERE username=? AND pay_status='已支付'", (username,))
    total = c.fetchone()["cnt"]
    conn.close()
    return jsonify({"active": active, "total": total})

@app.route("/admin/logs")
def admin_get_logs():
    if session.get("role") != "admin": return jsonify([])
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT * FROM sys_logs ORDER BY id DESC LIMIT 200")
    rows = c.fetchall(); conn.close()
    return jsonify([dict(r) for r in rows])

# ---- 启动 ----
if __name__ == "__main__":
    init_db()
    print("=" * 60)
    print("  Mini12306 铁路售票系统 v2.1")
    print("  管理员: admin / Admin123")
    print("  测试用户: testuser / User1234")
    print("=" * 60)
    app.run(debug=True, host="0.0.0.0", port=5000)