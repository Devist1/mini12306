import tkinter as tk
from tkinter import ttk, messagebox
import sqlite3

class Mini12306:
    def __init__(self, root, username, role):
        self.root = root
        self.root.title("Mini-12306 铁路售票系统")
        self.root.geometry("800x600")
        self.username = username
        self.role = role

        menubar = tk.Menu(root)
        menubar.add_command(label="车次查询", command=self.show_train)
        menubar.add_command(label="我的订单", command=self.show_order)
        if self.role == "admin":
            menubar.add_command(label="车次管理", command=self.manage_train)
        menubar.add_command(label="退出登录", command=root.quit)
        root.config(menu=menubar)

        tk.Label(root, text=f"欢迎 {self.username} 登录 Mini-12306", font=("黑体", 16)).pack(pady=20)

    def show_train(self):
        from train import TrainQuery
        TrainQuery(self.root, self.username)

    def show_order(self):
        from order import OrderManager
        OrderManager(self.root, self.username)

    def manage_train(self):
        from train import TrainQuery
        TrainQuery(self.root, self.username, admin=True)

def init_db():
    conn = sqlite3.connect("data.db")
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (username TEXT PRIMARY KEY, password TEXT, idcard TEXT, phone TEXT, role TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS trains
                 (train_no TEXT PRIMARY KEY, start TEXT, end TEXT, time TEXT, price REAL, tickets INTEGER)''')
    c.execute('''CREATE TABLE IF NOT EXISTS orders
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, train_no TEXT, seat TEXT, status TEXT)''')
    c.execute("INSERT OR IGNORE INTO users VALUES ('admin','123','111111','13800000000','admin')")
    c.execute("INSERT OR IGNORE INTO trains VALUES ('G100','武汉','北京','08:00',450,100)")
    c.execute("INSERT OR IGNORE INTO trains VALUES ('D200','上海','武汉','10:30',280,120)")
    conn.commit()
    conn.close()

if __name__ == "__main__":
    init_db()
    root = tk.Tk()
    from user import UserLogin
    UserLogin(root)
    root.mainloop()