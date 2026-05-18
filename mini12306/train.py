import tkinter as tk
from tkinter import ttk, messagebox
import sqlite3

class TrainQuery:
    def __init__(self, parent, username, admin=False):
        self.win = tk.Toplevel(parent)
        self.win.title("车次查询")
        self.win.geometry("750x500")
        self.username = username
        self.admin = admin

        tk.Label(self.win, text="出发地").place(x=30,y=20)
        tk.Label(self.win, text="目的地").place(x=200,y=20)
        self.start = tk.Entry(self.win)
        self.end = tk.Entry(self.win)
        self.start.place(x=90,y=20)
        self.end.place(x=260,y=20)
        tk.Button(self.win,text="查询",command=self.query).place(x=380,y=15)

        self.tree = ttk.Treeview(self.win, columns=("车次","出发","到达","时间","票价","余票"), show="headings")
        for col in self.tree["columns"]:
            self.tree.heading(col, text=col)
            self.tree.column(col, width=110)
        self.tree.place(x=20,y=70,width=700,height=300)

        tk.Button(self.win,text="购票",command=self.buy).place(x=320,y=390)

        if admin:
            tk.Button(self.win,text="新增车次",command=self.add_train).place(x=150,y=390)
            tk.Button(self.win,text="删除车次",command=self.del_train).place(x=480,y=390)

        self.query()

    def query(self):
        s = self.start.get().strip()
        e = self.end.get().strip()
        conn = sqlite3.connect("data.db")
        c = conn.cursor()
        if s and e:
            c.execute("SELECT * FROM trains WHERE start=? AND end=?", (s,e))
        else:
            c.execute("SELECT * FROM trains")
        rows = c.fetchall()
        conn.close()

        for i in self.tree.get_children():
            self.tree.delete(i)
        for row in rows:
            self.tree.insert("", "end", values=row)

    def buy(self):
        item = self.tree.selection()
        if not item:
            messagebox.showwarning("提示","请选择车次")
            return
        train_no = self.tree.item(item,"values")[0]
        from order import buy_ticket
        buy_ticket(self.win, self.username, train_no)

    def add_train(self):
        win = tk.Toplevel(self.win)
        win.title("新增车次")
        entries = []
        for i, t in enumerate(["车次","出发","到达","时间","票价","余票"]):
            tk.Label(win,text=t).grid(row=i,column=0)
            e = tk.Entry(win)
            e.grid(row=i,column=1)
            entries.append(e)

        def save():
            data = [e.get() for e in entries]
            if not all(data):
                messagebox.showerror("错误","不能为空")
                return
            try:
                conn = sqlite3.connect("data.db")
                c = conn.cursor()
                c.execute("INSERT INTO trains VALUES (?,?,?,?,?,?)",
                          (data[0],data[1],data[2],data[3],float(data[4]),int(data[5])))
                conn.commit()
                conn.close()
                messagebox.showinfo("成功","添加成功")
                self.query()
                win.destroy()
            except:
                messagebox.showerror("错误","添加失败")
        tk.Button(win,text="保存",command=save).grid(row=6,column=1)

    def del_train(self):
        item = self.tree.selection()
        if not item:
            messagebox.showwarning("提示","请选择车次")
            return
        train_no = self.tree.item(item,"values")[0]
        conn = sqlite3.connect("data.db")
        c = conn.cursor()
        c.execute("DELETE FROM trains WHERE train_no=?", (train_no,))
        conn.commit()
        conn.close()
        self.query()
        messagebox.showinfo("成功","删除成功")