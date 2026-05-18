import tkinter as tk
from tkinter import messagebox
import sqlite3

def check_seat(seat):
    if len(seat) < 2:
        return None
    num = ""
    char = ""
    for c in seat:
        if c.isdigit():
            num += c
        else:
            char += c.upper()
    if not num.isdigit() or len(char)!=1:
        return None
    row = int(num)
    if not (1<=row<=17) or char not in "ABCDF":
        return None
    if char in "AF":
        return "窗口"
    elif char in "CD":
        return "过道"
    elif char == "B":
        return "中间"

def buy_ticket(parent, username, train_no):
    win = tk.Toplevel(parent)
    win.title("购票")
    win.geometry("350x250")

    tk.Label(win, text="座位号（如 12F）", font=("黑体",12)).pack(pady=10)
    seat_entry = tk.Entry(win)
    seat_entry.pack(pady=5)
    result_label = tk.Label(win, text="", fg="blue")
    result_label.pack(pady=5)

    def check():
        seat = seat_entry.get().strip()
        res = check_seat(seat)
        if not res:
            result_label.config(text="输入错误")
        else:
            result_label.config(text=f"座位类型：{res}")

    def confirm():
        seat = seat_entry.get().strip()
        if not check_seat(seat):
            messagebox.showerror("错误","座位号不合法")
            return
        conn = sqlite3.connect("data.db")
        c = conn.cursor()
        c.execute("SELECT tickets FROM trains WHERE train_no=?", (train_no,))
        tickets = c.fetchone()[0]
        if tickets <=0:
            messagebox.showerror("错误","无票")
            conn.close()
            return
        c.execute("UPDATE trains SET tickets = tickets -1 WHERE train_no=?", (train_no,))
        c.execute("INSERT INTO orders (username,train_no,seat,status) VALUES (?,?,?,'已购票')",
                  (username,train_no,seat))
        conn.commit()
        conn.close()
        messagebox.showinfo("成功","购票成功")
        win.destroy()

    tk.Button(win, text="校验座位", command=check).pack(pady=5)
    tk.Button(win, text="确认购票", command=confirm).pack(pady=5)

class OrderManager:
    def __init__(self, parent, username):
        self.win = tk.Toplevel(parent)
        self.win.title("我的订单")
        self.win.geometry("650x400")
        self.username = username

        self.tree = tk.ttk.Treeview(self.win, columns=("ID","车次","座位","状态"), show="headings")
        for col in self.tree["columns"]:
            self.tree.heading(col, text=col)
            self.tree.column(col, width=150)
        self.tree.pack(pady=20, fill=tk.X)

        tk.Button(self.win, text="刷新", command=self.show_orders).pack(side=tk.LEFT, padx=30)
        tk.Button(self.win, text="退票", command=self.refund).pack(side=tk.LEFT, padx=30)
        tk.Button(self.win, text="改签", command=self.change).pack(side=tk.LEFT, padx=30)
        self.show_orders()

    def show_orders(self):
        for i in self.tree.get_children():
            self.tree.delete(i)
        conn = sqlite3.connect("data.db")
        c = conn.cursor()
        c.execute("SELECT id,train_no,seat,status FROM orders WHERE username=?", (self.username,))
        for row in c.fetchall():
            self.tree.insert("", "end", values=row)
        conn.close()

    def refund(self):
        item = self.tree.selection()
        if not item:
            messagebox.showwarning("提示","请选择订单")
            return
        oid, tno, _, status = self.tree.item(item,"values")
        if status == "已退票":
            messagebox.showwarning("提示","已退过票")
            return

        conn = sqlite3.connect("data.db")
        c = conn.cursor()
        c.execute("UPDATE orders SET status='已退票' WHERE id=?", (oid,))
        c.execute("UPDATE trains SET tickets = tickets +1 WHERE train_no=?", (tno,))
        conn.commit()
        conn.close()
        self.show_orders()
        messagebox.showinfo("成功","退票成功")

    def change(self):
        item = self.tree.selection()
        if not item:
            messagebox.showwarning("提示","请选择订单")
            return
        oid, tno, seat, status = self.tree.item(item,"values")
        if status != "已购票":
            messagebox.showwarning("提示","无法改签")
            return
        messagebox.showinfo("提示","改签：先退票，再重新购票即可")