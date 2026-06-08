# -*- coding: utf-8 -*-
"""
============================================================================
 Mini12306 铁路售票系统 - Web版 v2.2
 功能概述：用户端：注册/登录/重置密码/查询车票/购票/支付/退票/改签/订单/乘车人
           管理端：车次增删改/用户管理/系统配置/日志查看
 技术栈：Flask + SQLite + Jinja2模板
 部署配置：host="0.0.0.0" 允许外部访问，threaded=True多线程并发
============================================================================
"""

from flask import Flask, render_template, request, jsonify, session, redirect, url_for
import sqlite3, re, time, random, hashlib, json, threading, traceback, os, socket
from datetime import datetime, timedelta

# ======================== 应用初始化 ========================
app = Flask(__name__)
app.secret_key = "mini12306_secret_key_2024"      # 会话加密密钥
DB_PATH = "data.db"                               # SQLite 数据库路径

# ======================== 同城车站映射（31个城市 → 105个车站） ========================
SAME_CITY = {
    "北京": ["北京", "北京南", "北京西", "北京北", "北京朝阳", "北京丰台", "北京首都", "北京大兴"],
    "上海": ["上海", "上海虹桥", "上海南", "上海西", "上海浦东"],
    "广州": ["广州", "广州南", "广州东", "广州白云"],
    "深圳": ["深圳", "深圳北", "深圳宝安"],
    "武汉": ["武汉", "武昌", "汉口", "武汉东", "武汉天河"],
    "成都": ["成都", "成都东", "成都南", "成都双流", "成都天府"],
    "重庆": ["重庆", "重庆北", "重庆西", "重庆江北"],
    "杭州": ["杭州", "杭州东", "杭州南", "杭州西", "杭州萧山"],
    "西安": ["西安", "西安北", "西安咸阳"],
    "南京": ["南京", "南京南", "南京禄口"],
    "郑州": ["郑州", "郑州东"],
    "长沙": ["长沙", "长沙南"],
    "天津": ["天津", "天津南", "天津西", "天津滨海"],
    "济南": ["济南", "济南西", "济南东"],
    "青岛": ["青岛", "青岛北", "青岛流亭"],
    "沈阳": ["沈阳", "沈阳北", "沈阳南"],
    "大连": ["大连", "大连北", "大连周水子"],
    "哈尔滨": ["哈尔滨", "哈尔滨西", "哈尔滨东"],
    "福州": ["福州", "福州南"],
    "厦门": ["厦门", "厦门北"],
    "合肥": ["合肥", "合肥南"],
    "昆明": ["昆明", "昆明南", "昆明长水"],
    "贵阳": ["贵阳", "贵阳北", "贵阳东"],
    "南昌": ["南昌", "南昌西"],
    "兰州": ["兰州", "兰州西"],
    "石家庄": ["石家庄", "石家庄北"],
    "太原": ["太原", "太原南"],
    "南宁": ["南宁", "南宁东"],
    "海口": ["海口", "海口美兰"],
    "三亚": ["三亚", "三亚凤凰"],
    "香港": ["香港西九龙", "香港九龙"],
}

def get_same_city_stations(station):
    """根据输入返回车站列表：城市名展开所有车站，具体车站精确匹配"""
    if station in SAME_CITY:
        return SAME_CITY[station]
    for group in SAME_CITY.values():
        if station in group:
            return [station]
    return [station]

# ======================== 席别折扣系数 ========================
SEAT_DISCOUNTS = {
    "二等座": 1.0, "一等座": 1.2, "商务座": 2.5,
    "硬座": 1.0, "硬卧": 1.5, "软卧": 2.0,
    "经济舱": 1.0, "商务舱": 2.0,
}

# ======================== 数据库操作 ========================
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db():
    conn = sqlite3.connect(DB_PATH); c = conn.cursor(); c.execute("PRAGMA foreign_keys = ON")
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL, password TEXT NOT NULL,
        idcard TEXT UNIQUE NOT NULL, phone TEXT UNIQUE NOT NULL, role TEXT DEFAULT 'user',
        login_attempts INTEGER DEFAULT 0, locked_until TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS trains (
        id INTEGER PRIMARY KEY AUTOINCREMENT, train_no TEXT UNIQUE NOT NULL, start TEXT NOT NULL, end TEXT NOT NULL,
        depart_time TEXT NOT NULL, arrive_time TEXT NOT NULL, price REAL NOT NULL, seat_types TEXT NOT NULL,
        total_tickets INTEGER NOT NULL, remaining_tickets INTEGER NOT NULL, type TEXT NOT NULL, travel_date TEXT NOT NULL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT, order_no TEXT UNIQUE NOT NULL, username TEXT NOT NULL,
        passenger_name TEXT NOT NULL, train_no TEXT NOT NULL, start TEXT, end TEXT, depart_time TEXT, arrive_time TEXT,
        seat_type TEXT NOT NULL, price REAL NOT NULL, status TEXT DEFAULT '待支付', pay_status TEXT DEFAULT '未支付',
        is_student TEXT DEFAULT 'n', create_time TEXT, pay_time TEXT, original_order_id INTEGER)''')
    c.execute('''CREATE TABLE IF NOT EXISTS passengers (
        id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL, passenger_name TEXT NOT NULL,
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
    user_pwd = hashlib.sha256("User1234".encode()).hexdigest()
    c.execute("INSERT OR IGNORE INTO users (username,password,idcard,phone,role) VALUES (?,?,?,?,?)",
              ("admin", admin_pwd, "110101199001010001", "13800000000", "admin"))
    c.execute("INSERT OR IGNORE INTO users (username,password,idcard,phone,role) VALUES (?,?,?,?,?)",
              ("testuser", user_pwd, "320106199508152234", "13912345678", "user"))
    today = datetime.now().date()
    json_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "trains.json")
    if os.path.exists(json_path):
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        days = data.get("days", 30)
        test_trains_raw = data.get("trains", [])
        print(f"  [INFO] 从 trains.json 加载了 {len(test_trains_raw)} 条基准车次")
    else:
        days = 30; test_trains_raw = []
        print("  [WARN] 未找到 trains.json，车次数据为空")
    for train in test_trains_raw:
        for i in range(days):
            d = today + timedelta(days=i); ds = d.strftime("%Y-%m-%d")
            tno = train["train_no"] + "_" + ds
            c.execute("INSERT OR IGNORE INTO trains (train_no,start,end,depart_time,arrive_time,price,seat_types,total_tickets,remaining_tickets,type,travel_date) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                      (tno, train["start"], train["end"], train["depart_time"], train["arrive_time"],
                       train["price"], json.dumps(train["seat_types"]), train["total_tickets"],
                       train["total_tickets"], train["type"], ds))
    c.execute("INSERT OR IGNORE INTO passengers (username,passenger_name,idcard,phone) VALUES (?,?,?,?)",
              ("testuser", "张三", "320106199508152234", "13912345678"))
    c.execute("INSERT OR IGNORE INTO passengers (username,passenger_name,idcard,phone) VALUES (?,?,?,?)",
              ("testuser", "李四", "110101199502150019", "13600001111"))
    conn.commit(); conn.close()

# ======================== 工具函数 ========================
def write_log(username, action, detail=""):
    conn = get_db(); c = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ip = request.remote_addr if request else ""
    c.execute("INSERT INTO sys_logs (username,action,detail,ip,create_time) VALUES (?,?,?,?,?)",
              (username, action, detail, ip, now))
    conn.commit(); conn.close()

def validate_idcard(idcard):
    if len(idcard) != 18: return False
    if not re.match(r'^[1-9]\d{5}(19|20)\d{2}(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])\d{3}[\dXx]$', idcard):
        return False
    w = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2]
    cc = "10X98765432"
    return cc[sum(int(idcard[i]) * w[i] for i in range(17)) % 11] == idcard[17].upper()

def validate_phone(phone):
    return bool(re.match(r'^1[3-9]\d{9}$', phone))

def validate_password(pw):
    if len(pw) < 8: return False, "密码长度不能少于8位"
    if not re.search(r'[A-Z]', pw): return False, "密码必须包含大写字母"
    if not re.search(r'[a-z]', pw): return False, "密码必须包含小写字母"
    if not re.search(r'\d', pw): return False, "密码必须包含数字"
    return True, ""

def check_unpaid_orders():
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT value FROM sys_config WHERE key='pay_timeout'")
    row = c.fetchone()
    if not row: conn.close(); return
    timeout = int(row["value"]); now = datetime.now()
    c.execute("SELECT * FROM orders WHERE pay_status='未支付'")
    for order in c.fetchall():
        try:
            ct = datetime.strptime(order["create_time"], "%Y-%m-%d %H:%M:%S")
            if (now - ct).total_seconds() > timeout:
                c.execute("UPDATE orders SET pay_status='已取消', status='已退票' WHERE id=?", (order["id"],))
                c.execute("UPDATE trains SET remaining_tickets = remaining_tickets + 1 WHERE train_no=?", (order["train_no"],))
                write_log(order["username"], "订单超时取消", f"订单号:{order['order_no']}")
        except: pass
    conn.commit(); conn.close()

def auto_cancel_worker():
    while True:
        time.sleep(60)
        try: check_unpaid_orders()
        except: pass

threading.Thread(target=auto_cancel_worker, daemon=True).start()

# ======================== 页面路由 ========================
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

# ======================== 用户认证 ========================
@app.route("/check_login", methods=["POST"])
def check_login():
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "").strip()
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT * FROM users WHERE username=?", (username,))
    user = c.fetchone()
    if not user: conn.close(); return "fail|账号不存在"
    if user["locked_until"]:
        try:
            lock_time = datetime.strptime(user["locked_until"], "%Y-%m-%d %H:%M:%S")
            if datetime.now() < lock_time:
                remain = int((lock_time - datetime.now()).total_seconds())
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
    conn.commit(); write_log(username, "用户登录", f"角色:{user['role']}"); conn.close()
    session["username"] = username; session["role"] = user["role"]
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
    c.execute("INSERT INTO users (username,password,idcard,phone,role) VALUES (?,?,?,?,?)",
              (username, hashed, idcard, phone, "user"))
    conn.commit(); conn.close()
    write_log(username, "用户注册", f"手机:{phone}")
    return "注册成功"

@app.route("/do_reset_password", methods=["POST"])
def do_reset_password():
    username = request.form.get("username", "").strip()
    phone = request.form.get("phone", "").strip()
    idcard = request.form.get("idcard", "").strip()
    new_pw = request.form.get("new_password", "").strip()
    conn = get_db(); c = conn.cursor()
    if not c.execute("SELECT * FROM users WHERE username=? AND phone=? AND idcard=?", (username, phone, idcard)).fetchone():
        conn.close(); return "验证失败：信息不匹配"
    valid, msg = validate_password(new_pw)
    if not valid: conn.close(); return msg
    hashed = hashlib.sha256(new_pw.encode()).hexdigest()
    c.execute("UPDATE users SET password=?, login_attempts=0, locked_until=NULL WHERE username=?", (hashed, username))
    conn.commit(); conn.close()
    write_log(username, "重置密码", "通过手机号验证")
    return "密码重置成功，请重新登录"

# ======================== 车站信息 ========================
@app.route("/get_stations")
def get_stations():
    cities = []; all_stations = set()
    for city, stations in SAME_CITY.items():
        cities.append({"city": city, "stations": stations})
        for s in stations: all_stations.add(s)
    return jsonify({"cities": cities, "all_stations": sorted(list(all_stations))})

# ======================== 车次查询 ========================
@app.route("/get_trains")
def get_trains():
    conn = get_db(); c = conn.cursor()
    today = datetime.now().strftime("%Y-%m-%d")
    start = request.args.get("start", ""); end = request.args.get("end", "")
    date = request.args.get("date", today); train_no = request.args.get("train_no", "")
    train_type = request.args.get("type", "")
    exact_start = request.args.get("exact_start", "") == "1"
    exact_end = request.args.get("exact_end", "") == "1"
    where = ["travel_date >= ?"]; params = [today]
    if start:
        stations = [start] if exact_start else get_same_city_stations(start)
        where.append(f"start IN ({','.join(['?'] * len(stations))})"); params.extend(stations)
    if end:
        stations = [end] if exact_end else get_same_city_stations(end)
        where.append(f"end IN ({','.join(['?'] * len(stations))})"); params.extend(stations)
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
    week = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"]
    dates = []
    for i in range(15):
        d = today + timedelta(days=i)
        dates.append({"value": d.strftime("%Y-%m-%d"), "label": f"{d.month}月{d.day}日 {week[d.weekday()]}"})
    return jsonify(dates)

# ======================== 购票 ========================
# 修复3：早于当前时间的车票无法购买（在余票检查后增加发车时间检查）
@app.route("/buy", methods=["POST"])
def buy():
    try:
        username = request.form.get("username", "").strip()
        train_no = request.form.get("train_no", "").strip()
        seat_type = request.form.get("seat", "").strip()
        is_student = request.form.get("is_student", "n").strip()
        passenger_name = request.form.get("passenger_name", "").strip()
        if not all([username, train_no, seat_type, passenger_name]):
            return jsonify({"success": False, "msg": "参数不完整"})
        conn = get_db(); c = conn.cursor()
        c.execute("SELECT value FROM sys_config WHERE key='daily_buy_limit'")
        daily_limit = int(c.fetchone()["value"])
        today_str = datetime.now().strftime("%Y-%m-%d")
        c.execute("SELECT COUNT(*) as cnt FROM orders WHERE username=? AND create_time LIKE ? AND pay_status='已支付' AND status NOT IN ('已退票','已改签')",
                  (username, f"{today_str}%"))
        if c.fetchone()["cnt"] >= daily_limit:
            conn.close(); return jsonify({"success": False, "msg": f"今日购票已达上限（{daily_limit}张）"})
        c.execute("SELECT * FROM trains WHERE train_no=?", (train_no,))
        train = c.fetchone()
        if not train: conn.close(); return jsonify({"success": False, "msg": "车次不存在"})
        if train["remaining_tickets"] <= 0:
            conn.close(); return jsonify({"success": False, "msg": "余票不足"})

        # 【修复3】检查发车时间是否已过，已发车的车次无法购买
        try:
            depart_dt = datetime.strptime(train["travel_date"] + " " + train["depart_time"], "%Y-%m-%d %H:%M")
            if depart_dt <= datetime.now():
                conn.close(); return jsonify({"success": False, "msg": "该车次已发车，无法购买"})
        except: pass

        price = train["price"]; train_type = train["type"]
        try:
            seat_data = json.loads(train["seat_types"])
            if isinstance(seat_data, list) and len(seat_data) > 0 and isinstance(seat_data[0], dict):
                for s in seat_data:
                    if s.get("name") == seat_type: price = s["price"]; break
            else:
                price = price * SEAT_DISCOUNTS.get(seat_type, 1.0)
        except:
            price = price * SEAT_DISCOUNTS.get(seat_type, 1.0)
        if is_student == "y":
            if train_type in ("高铁", "动车") and seat_type == "二等座": price *= 0.75
            elif train_type == "普速火车" and seat_type == "硬座": price *= 0.5
        order_no = "M" + datetime.now().strftime("%Y%m%d%H%M%S") + str(random.randint(1000, 9999))
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        c.execute('''INSERT INTO orders (order_no,username,passenger_name,train_no,start,end,depart_time,arrive_time,
                     seat_type,price,status,pay_status,is_student,create_time)
                     VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                  (order_no, username, passenger_name, train_no, train["start"], train["end"],
                   train["depart_time"], train["arrive_time"], seat_type, round(price, 2),
                   "待支付", "未支付", is_student, now))
        conn.commit(); conn.close()
        write_log(username, "创建订单", f"订单号:{order_no}")
        return jsonify({"success": True, "order_no": order_no, "price": round(price, 2)})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "msg": f"系统错误: {str(e)}"})

# ======================== 支付 ========================
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

# ======================== 订单管理 ========================
@app.route("/orders/<username>")
def get_user_orders(username):
    conn = get_db(); c = conn.cursor()
    if request.args.get("active") == "1":
        c.execute("SELECT * FROM orders WHERE username=? AND pay_status='已支付' AND status NOT IN ('已退票','已改签') ORDER BY id DESC", (username,))
    else:
        c.execute("SELECT * FROM orders WHERE username=? ORDER BY id DESC", (username,))
    rows = c.fetchall(); result = []
    for r in rows:
        d = dict(r)
        if d.get("original_order_id"):
            c2 = conn.cursor()
            c2.execute("SELECT train_no, seat_type FROM orders WHERE id=?", (d["original_order_id"],))
            orig = c2.fetchone()
            if orig: d["original_train_no"] = orig["train_no"]; d["original_seat_type"] = orig["seat_type"]
        result.append(d)
    conn.close(); return jsonify(result)

@app.route("/all_orders")
def get_all_orders():
    if session.get("role") != "admin": return jsonify([])
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT * FROM orders ORDER BY id DESC"); rows = c.fetchall(); conn.close()
    return jsonify([dict(r) for r in rows])

@app.route("/cancel_order", methods=["POST"])
def cancel_order():
    order_id = request.form.get("order_id", "")
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT * FROM orders WHERE id=?", (order_id,)); order = c.fetchone()
    if not order: conn.close(); return "订单不存在"
    if order["pay_status"] != "未支付": conn.close(); return "仅可取消未支付订单"
    c.execute("UPDATE orders SET pay_status='已取消', status='已退票' WHERE id=?", (order_id,)); conn.commit(); conn.close()
    write_log(order["username"], "取消订单", f"订单号:{order['order_no']}")
    return "取消成功"

# ======================== 退票 ========================
@app.route("/refund", methods=["POST"])
def refund():
    order_id = request.form.get("order_id", "")
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT * FROM orders WHERE id=?", (order_id,)); order = c.fetchone()
    if not order: conn.close(); return "订单不存在"
    if order["pay_status"] != "已支付": conn.close(); return "仅可退已支付订单"
    if order["status"] == "已退票": conn.close(); return "该订单已退票"
    c.execute("SELECT * FROM trains WHERE train_no=?", (order["train_no"],)); train = c.fetchone()
    refund_amount = order["price"]
    if train:
        depart_dt = datetime.strptime(train["travel_date"] + " " + train["depart_time"], "%Y-%m-%d %H:%M")
        now = datetime.now(); diff_hours = (depart_dt - now).total_seconds() / 3600
        if diff_hours < 0: conn.close(); return "已发车，无法退票"
        fee_rate = 0
        if diff_hours < 24:
            c.execute("SELECT value FROM sys_config WHERE key='refund_fee_24h'"); fee_rate = float(c.fetchone()["value"])
        elif diff_hours < 48:
            c.execute("SELECT value FROM sys_config WHERE key='refund_fee_48h'"); fee_rate = float(c.fetchone()["value"])
        refund_amount = order["price"] * (1 - fee_rate)
    c.execute("UPDATE orders SET status='已退票' WHERE id=?", (order_id,))
    c.execute("UPDATE trains SET remaining_tickets = remaining_tickets + 1 WHERE train_no=?", (order["train_no"],))
    conn.commit(); conn.close()
    write_log(order["username"], "退票", f"订单号:{order['order_no']}, 退款:¥{round(refund_amount, 2)}")
    return f"退票成功，退款 ¥{round(refund_amount, 2)}"

# ======================== 改签 ========================
@app.route("/reschedule_info/<int:order_id>")
def reschedule_info(order_id):
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT * FROM orders WHERE id=?", (order_id,)); order = c.fetchone()
    if not order: conn.close(); return jsonify({"error": "订单不存在"}), 404
    c.execute("SELECT * FROM trains WHERE train_no=?", (order["train_no"],)); old_train = c.fetchone()
    old_start_stations = get_same_city_stations(old_train["start"]) if old_train else []
    old_end_stations = get_same_city_stations(old_train["end"]) if old_train else []
    today = datetime.now().strftime("%Y-%m-%d")
    ps = ",".join(["?"] * len(old_start_stations)); pe = ",".join(["?"] * len(old_end_stations))
    c.execute(f"""SELECT * FROM trains WHERE start IN ({ps}) AND end IN ({pe})
                  AND travel_date >= ? AND remaining_tickets > 0 ORDER BY travel_date, depart_time""",
              old_start_stations + old_end_stations + [today])
    trains = [dict(r) for r in c.fetchall()]; conn.close()
    return jsonify({"order": dict(order), "old_train": dict(old_train) if old_train else None,
                    "available_trains": trains, "same_city_start": old_start_stations, "same_city_end": old_end_stations})

@app.route("/reschedule", methods=["POST"])
def reschedule():
    """
    执行改签
    【修复1】已改签过的车票不能再次改签
    【修复1】飞机只能改飞机，火车不能改飞机
    """
    order_id = request.form.get("order_id", ""); new_train_no = request.form.get("new_train_no", "")
    new_seat_type = request.form.get("new_seat_type", "")
    conn = get_db(); c = conn.cursor()

    # 原订单校验
    c.execute("SELECT * FROM orders WHERE id=?", (order_id,)); order = c.fetchone()
    if not order: conn.close(); return jsonify({"success": False, "msg": "订单不存在"})
    if order["pay_status"] != "已支付": conn.close(); return jsonify({"success": False, "msg": "仅可改签已支付订单"})
    if order["status"] in ("已退票", "已改签", "改签待支付"):
        conn.close(); return jsonify({"success": False, "msg": "订单状态不可改签"})

    # 【修复1-A】已改签过的订单（有original_order_id字段）不能再改签
    if order["original_order_id"]:
        conn.close(); return jsonify({"success": False, "msg": "该车票已改签过，不可再次改签"})

    # 新车次校验
    c.execute("SELECT * FROM trains WHERE train_no=?", (new_train_no,)); new_train = c.fetchone()
    if not new_train: conn.close(); return jsonify({"success": False, "msg": "新车次不存在"})
    if new_train["remaining_tickets"] <= 0:
        conn.close(); return jsonify({"success": False, "msg": "新车次余票不足"})

    # 获取原车次信息
    c.execute("SELECT * FROM trains WHERE train_no=?", (order["train_no"],)); old_train = c.fetchone()

    # 【修复1-B】飞机与其他交通工具不互通：飞机只能改飞机，其他只能改其他
    old_is_plane = (old_train["type"] == "飞机")
    new_is_plane = (new_train["type"] == "飞机")
    if old_is_plane != new_is_plane:
        conn.close(); return jsonify({"success": False, "msg": "飞机只能改签飞机，火车/高铁/动车不能改签飞机"})

    # 同城校验
    old_start_group = get_same_city_stations(old_train["start"])
    old_end_group = get_same_city_stations(old_train["end"])
    if new_train["start"] not in old_start_group or new_train["end"] not in old_end_group:
        conn.close(); return jsonify({"success": False, "msg": "仅可改签同城车站或相同发到站的车次"})

    seat_type = new_seat_type if new_seat_type else order["seat_type"]
    new_price = new_train["price"] * SEAT_DISCOUNTS.get(seat_type, 1.0)
    if order["is_student"] == "y":
        if new_train["type"] in ("高铁", "动车") and seat_type == "二等座": new_price *= 0.75
        elif new_train["type"] == "普速火车" and seat_type == "硬座": new_price *= 0.5
    new_price = round(new_price, 2); old_price = order["price"]
    price_diff = round(new_price - old_price, 2)

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rno = "R" + datetime.now().strftime("%Y%m%d%H%M%S") + str(random.randint(1000, 9999))

    # 释放原车票
    c.execute("UPDATE orders SET status='已改签' WHERE id=?", (order_id,))
    c.execute("UPDATE trains SET remaining_tickets = remaining_tickets + 1 WHERE train_no=?", (order["train_no"],))

    if price_diff > 0:
        c.execute("UPDATE trains SET remaining_tickets = remaining_tickets - 1 WHERE train_no=?", (new_train_no,))
        c.execute('''INSERT INTO orders (order_no,username,passenger_name,train_no,start,end,depart_time,arrive_time,
                     seat_type,price,status,pay_status,is_student,create_time,original_order_id)
                     VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                  (rno, order["username"], order["passenger_name"], new_train_no,
                   new_train["start"], new_train["end"], new_train["depart_time"], new_train["arrive_time"],
                   seat_type, new_price, "改签待支付", "未支付", order["is_student"], now, order_id))
        conn.commit(); conn.close()
        write_log(order["username"], "改签申请", f"原订单:{order['order_no']} -> {new_train_no}, 需补差价:¥{price_diff}")
        return jsonify({"success": True, "need_pay": True, "price_diff": price_diff,
                        "order_no": rno, "new_price": new_price, "old_price": old_price})

    c.execute("UPDATE trains SET remaining_tickets = remaining_tickets - 1 WHERE train_no=?", (new_train_no,))
    c.execute('''INSERT INTO orders (order_no,username,passenger_name,train_no,start,end,depart_time,arrive_time,
                 seat_type,price,status,pay_status,is_student,create_time,pay_time,original_order_id)
                 VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
              (rno, order["username"], order["passenger_name"], new_train_no,
               new_train["start"], new_train["end"], new_train["depart_time"], new_train["arrive_time"],
               seat_type, new_price, "已改签", "已支付", order["is_student"], now, now, order_id))
    conn.commit(); conn.close()
    msg = f"改签成功，退差价 ¥{abs(price_diff)}" if price_diff < 0 else "改签成功"
    write_log(order["username"], "改签成功", f"原订单:{order['order_no']} -> {new_train_no}, 差价:¥{price_diff}")
    return jsonify({"success": True, "need_pay": False, "price_diff": price_diff, "msg": msg,
                    "order_no": rno, "new_price": new_price, "old_price": old_price})

# 【修复2】改签差价支付接口
@app.route("/pay_reschedule", methods=["POST"])
def pay_reschedule():
    """支付改签差价"""
    order_no = request.form.get("order_no", "").strip()
    if not order_no: return "缺少订单号"
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT * FROM orders WHERE order_no=?", (order_no,)); order = c.fetchone()
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

# ======================== 乘车人、个人中心、管理员 ========================
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
        conn.close(); return "该乘车人已存在"
    c.execute("INSERT INTO passengers (username,passenger_name,idcard,phone) VALUES (?,?,?,?)",
              (username, passenger_name, idcard, phone))
    conn.commit(); conn.close()
    return "添加成功"

@app.route("/del_passenger", methods=["POST"])
def del_passenger():
    pid = request.form.get("id", "")
    conn = get_db(); c = conn.cursor()
    c.execute("DELETE FROM passengers WHERE id=?", (pid,)); conn.commit(); conn.close()
    return "删除成功"

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
    old_pw = request.form.get("old_password", "").strip()
    new_pw = request.form.get("new_password", "").strip()
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT password FROM users WHERE username=?", (username,)); user = c.fetchone()
    if not user: conn.close(); return "用户不存在"
    if hashlib.sha256(old_pw.encode()).hexdigest() != user["password"]:
        conn.close(); return "原密码错误"
    valid, msg = validate_password(new_pw)
    if not valid: conn.close(); return msg
    c.execute("UPDATE users SET password=? WHERE username=?", (hashlib.sha256(new_pw.encode()).hexdigest(), username))
    conn.commit(); conn.close()
    write_log(username, "修改密码")
    return "密码修改成功"

@app.route("/admin/add_train", methods=["POST"])
def admin_add_train():
    if session.get("role") != "admin": return "无权限"
    d = request.form
    for f in ["train_no", "start", "end", "depart_time", "arrive_time", "type", "travel_date"]:
        if not d.get(f): return f"缺少字段: {f}"
    tno = d["train_no"] + "_" + d["travel_date"]
    sd = d.get("seat_details", "")
    if sd:
        sds = json.loads(sd); sj = json.dumps(sds)
        total = sum(s["tickets"] for s in sds); price = min(s["price"] for s in sds)
    else:
        sj = d.get("seat_types", '["二等座","一等座","商务座"]')
        price = float(d.get("price", 0)); total = int(d.get("total_tickets", 0))
    conn = get_db(); c = conn.cursor()
    try:
        c.execute('''INSERT INTO trains (train_no,start,end,depart_time,arrive_time,price,seat_types,total_tickets,remaining_tickets,type,travel_date)
                     VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
                  (tno, d["start"], d["end"], d["depart_time"], d["arrive_time"],
                   price, sj, total, total, d["type"], d["travel_date"]))
        conn.commit(); conn.close()
        write_log(session.get("username"), "新增车次", f"车次:{tno}")
        return "添加成功"
    except Exception as e: conn.close(); return f"添加失败: {str(e)}"

@app.route("/admin/update_train", methods=["POST"])
def admin_update_train():
    if session.get("role") != "admin": return "无权限"
    tn = request.form.get("train_no", ""); f = request.form.get("field", ""); v = request.form.get("value", "")
    if f not in ["price", "remaining_tickets", "total_tickets", "depart_time", "arrive_time"]:
        return "不允许修改的字段"
    conn = get_db(); c = conn.cursor()
    c.execute(f"UPDATE trains SET {f}=? WHERE train_no=?",
              (float(v) if any(x in f for x in ["price", "tickets"]) else v, tn))
    conn.commit(); conn.close()
    write_log(session.get("username"), "修改车次", f"车次:{tn}, {f}={v}")
    return "修改成功"

@app.route("/admin/del_train", methods=["POST"])
def admin_del_train():
    if session.get("role") != "admin": return "无权限"
    tn = request.form.get("train_no", "")
    conn = get_db(); c = conn.cursor()
    c.execute("DELETE FROM trains WHERE train_no=?", (tn,)); conn.commit(); conn.close()
    write_log(session.get("username"), "删除车次", f"车次:{tn}")
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
    username = request.form.get("username", ""); action = request.form.get("action", "")
    conn = get_db(); c = conn.cursor()
    if action == "disable":
        c.execute("UPDATE users SET locked_until='2999-12-31 23:59:59' WHERE username=?", (username,))
    else:
        c.execute("UPDATE users SET locked_until=NULL, login_attempts=0 WHERE username=?", (username,))
    conn.commit(); conn.close()
    write_log(session.get("username"), f"{'禁用' if action == 'disable' else '启用'}用户", f"用户名:{username}")
    return "操作成功"

@app.route("/admin/config")
def admin_get_config():
    if session.get("role") != "admin": return jsonify({})
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT * FROM sys_config"); rows = c.fetchall(); conn.close()
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
    total = c.fetchone()["cnt"]; conn.close()
    return jsonify({"active": active, "total": total})

@app.route("/admin/logs")
def admin_get_logs():
    if session.get("role") != "admin": return jsonify([])
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT * FROM sys_logs ORDER BY id DESC LIMIT 200")
    rows = c.fetchall(); conn.close()
    return jsonify([dict(r) for r in rows])

# ======================== 应用启动（允许外部访问） ========================
if __name__ == "__main__":
    init_db()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
    except:
        local_ip = "127.0.0.1"
    print("=" * 60)
    print("  Mini12306 铁路售票系统 v2.2")
    print(f"  本机访问:   http://127.0.0.1:5000")
    print(f"  局域网访问: http://{local_ip}:5000")
    print("  管理员: admin / Admin123  |  测试用户: testuser / User1234")
    print("=" * 60)
    # host="0.0.0.0" → 绑定所有网络接口，允许局域网内其他设备通过IP访问
    # threaded=True → 多线程模式，支持并发请求
    app.run(host="0.0.0.0", port=5000, threaded=True)