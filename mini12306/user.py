import tkinter as tk
from tkinter import ttk, messagebox
import sqlite3

class UserLogin:
    def __init__(self, root):
        self.root = root
        self.root.title("Mini-12306 登录")
        self.root.geometry("400x300")

        tk.Label(root, text="账号", font=("黑体",12)).place(x=80,y=60)
        tk.Label(root, text="密码", font=("黑体",12)).place(x=80,y=110)
        self.user_entry = tk.Entry(root)
        self.pwd_entry = tk.Entry(root, show="*")
        self.user_entry.place(x=150,y=60)
        self.pwd_entry.place(x=150,y=110)

        tk.Button(root, text="登录", command=self.login, width=10).place(x=100,y=170)
        tk.Button(root, text="注册", command=self.register_win, width=10).place(x=220,y=170)

    def login(self):
        username = self.user_entry.get().strip()
        pwd = self.pwd_entry.get().strip()
        if not username or not pwd:
            messagebox.showerror("错误","账号密码不能为空")
            return

        conn = sqlite3.connect("data.db")
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE username=? AND password=?", (username,pwd))
        res = c.fetchone()
        conn.close()

        if res:
            self.root.destroy()
            new_root = tk.Tk()
            from main import Mini12306
            Mini12306(new_root, username, res[4])
        else:
            messagebox.showerror("错误","账号或密码错误")

    def register_win(self):
        win = tk.Toplevel()
        win.title("注册")
        win.geometry("400x350")

        tk.Label(win,text="账号").place(x=80,y=40)
        tk.Label(win,text="密码").place(x=80,y=80)
        tk.Label(win,text="身份证").place(x=80,y=120)
        tk.Label(win,text="手机号").place(x=80,y=160)

        u = tk.Entry(win)
        p = tk.Entry(win)
        idc = tk.Entry(win)
        ph = tk.Entry(win)
        u.place(x=160,y=40)
        p.place(x=160,y=80)
        idc.place(x=160,y=120)
        ph.place(x=160,y=160)

        def reg():
            username = u.get().strip()
            pwd = p.get().strip()
            idcard = idc.get().strip()
            phone = ph.get().strip()
            if not all([username,pwd,idcard,phone]):
                messagebox.showerror("错误","信息不能为空")
                return

            try:
                conn = sqlite3.connect("data.db")
                c = conn.cursor()
                c.execute("INSERT INTO users VALUES (?,?,?,?,?)",
                          (username,pwd,idcard,phone,"user"))
                conn.commit()
                conn.close()
                messagebox.showinfo("成功","注册成功")
                win.destroy()
            except:
                messagebox.showerror("错误","账号已存在")

        tk.Button(win,text="确认注册",command=reg,width=12).place(x=150,y=220)