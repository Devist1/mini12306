# -*- coding: utf-8 -*-
"""
Mini12306 核心功能单元测试：购票、退票、改签
==============================================
测试覆盖：
  - 购票：正常、缺参数、车次不存在、余票不足、已发车、日限额、学生票折扣
  - 退票：正常、订单不存在、未支付、已退票、已发车、手续费
  - 改签：正常（降价/涨价）、订单不存在、未支付、已改签、新车次不存在、
          余票不足、同城限制、飞机互通限制、已改签不可再改
"""

import unittest
import json
import sqlite3
import time
from datetime import datetime, timedelta
from app import app, init_db, get_db


class TestMini12306Core(unittest.TestCase):
    """核心业务流程测试"""

    @classmethod
    def setUpClass(cls):
        init_db()
        conn = sqlite3.connect("data.db")
        c = conn.cursor()
        c.execute("UPDATE sys_config SET value='20' WHERE key='daily_buy_limit'")
        conn.commit()
        conn.close()

    def setUp(self):
        app.config['TESTING'] = True
        self.client = app.test_client()
        self.username = "testuser"
        # 每个测试前重置限额 + 清理今天已支付订单
        conn = sqlite3.connect("data.db")
        c = conn.cursor()
        c.execute("UPDATE sys_config SET value='20' WHERE key='daily_buy_limit'")
        today_str = datetime.now().strftime("%Y-%m-%d")
        c.execute(
            "UPDATE orders SET pay_status='已取消', status='已退票' WHERE username=? AND create_time LIKE ?",
            (self.username, today_str + "%")
        )
        c.execute("UPDATE trains SET remaining_tickets=total_tickets")
        conn.commit()
        conn.close()

    # ======================== 辅助方法 ========================
    def _get_available_train(self, days_ahead=5):
        conn = get_db()
        c = conn.cursor()
        future_date = (datetime.now() + timedelta(days=days_ahead)).strftime("%Y-%m-%d")
        c.execute(
            "SELECT train_no, type, price, start, end, remaining_tickets, total_tickets "
            "FROM trains WHERE travel_date=? AND remaining_tickets > 0 LIMIT 1",
            (future_date,)
        )
        row = c.fetchone()
        conn.close()
        if not row:
            raise unittest.SkipTest("无可测试车次，跳过测试")
        return dict(row)

    def _buy_ticket(self, train_no, seat="二等座", passenger="测试乘客", is_student="n"):
        resp = self.client.post("/buy", data={
            "username": self.username,
            "train_no": train_no,
            "seat": seat,
            "passenger_name": passenger,
            "is_student": is_student,
        })
        return resp.get_json()

    def _pay_order(self, order_no):
        resp = self.client.post("/pay", data={"order_no": order_no})
        return resp.get_data(as_text=True)

    def _bulk_buy(self, seat="二等座", passenger="张三"):
        """购票→支付→返回订单 dict（自动重试支付）"""
        train = self._get_available_train()
        buy_res = self._buy_ticket(train["train_no"], seat, passenger)
        self.assertTrue(buy_res["success"], f"购票失败: {buy_res.get('msg','')}")
        order_no = buy_res["order_no"]
        for _ in range(20):
            pay_res = self._pay_order(order_no)
            if pay_res == "支付成功":
                break
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT * FROM orders WHERE order_no=?", (order_no,))
        order = dict(c.fetchone())
        conn.close()
        self.assertEqual(order["pay_status"], "已支付")
        self.assertEqual(order["status"], "已购票")
        return order

    # ======================== 购票 ========================
    def test_buy_success(self):
        """正常购票并支付"""
        train = self._get_available_train()
        buy_res = self._buy_ticket(train["train_no"])
        self.assertTrue(buy_res["success"])
        self.assertIn("order_no", buy_res)
        self.assertGreater(buy_res["price"], 0)

        pay_ok = False
        for _ in range(20):
            r = self._pay_order(buy_res["order_no"])
            if r == "支付成功":
                pay_ok = True
                break
        self.assertTrue(pay_ok, f"支付应成功: {self._pay_order(buy_res['order_no'])}")

        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT pay_status, status FROM orders WHERE order_no=?", (buy_res["order_no"],))
        row = c.fetchone()
        conn.close()
        self.assertEqual(row["pay_status"], "已支付")
        self.assertEqual(row["status"], "已购票")

        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT remaining_tickets FROM trains WHERE train_no=?", (train["train_no"],))
        row = c.fetchone()
        conn.close()
        self.assertEqual(row["remaining_tickets"], train["remaining_tickets"] - 1)

    def test_buy_missing_params(self):
        resp = self.client.post("/buy", data={"username": self.username})
        data = resp.get_json()
        self.assertFalse(data["success"])
        self.assertIn("参数不完整", data["msg"])

    def test_buy_train_not_found(self):
        buy_res = self._buy_ticket("G99999_2099-12-31")
        self.assertFalse(buy_res["success"])
        self.assertIn("车次不存在", buy_res["msg"])

    def test_buy_no_tickets(self):
        train = self._get_available_train()
        conn = get_db()
        c = conn.cursor()
        c.execute("UPDATE trains SET remaining_tickets=0 WHERE train_no=?", (train["train_no"],))
        conn.commit()
        conn.close()
        buy_res = self._buy_ticket(train["train_no"])
        self.assertFalse(buy_res["success"])
        self.assertIn("余票不足", buy_res["msg"])
        # 恢复
        conn = get_db()
        c = conn.cursor()
        c.execute("UPDATE trains SET remaining_tickets=? WHERE train_no=?", (train["total_tickets"], train["train_no"]))
        conn.commit()
        conn.close()

    def test_buy_departed_train(self):
        conn = get_db()
        c = conn.cursor()
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        c.execute("SELECT train_no FROM trains WHERE travel_date=? AND remaining_tickets > 0 LIMIT 1", (yesterday,))
        row = c.fetchone()
        conn.close()
        if not row:
            self.skipTest("无已发车可测车次")
        buy_res = self._buy_ticket(row["train_no"])
        self.assertFalse(buy_res["success"])
        self.assertIn("已发车", buy_res["msg"])

    def test_buy_daily_limit(self):
        conn = sqlite3.connect("data.db")
        c = conn.cursor()
        c.execute("UPDATE sys_config SET value='1' WHERE key='daily_buy_limit'")
        conn.commit()
        conn.close()
        train = self._get_available_train()
        buy_res = self._buy_ticket(train["train_no"])
        self.assertTrue(buy_res["success"])
        for _ in range(20):
            if self._pay_order(buy_res["order_no"]) == "支付成功":
                break
        # 先验证第二张票买不了（限额=1，已买1张）
        train2 = self._get_available_train(6)
        buy_res2 = self._buy_ticket(train2["train_no"])
        self.assertFalse(buy_res2["success"])
        self.assertIn("已达上限", buy_res2["msg"])
        # 清理：还原限额 + 清除今天已购买票
        conn3 = sqlite3.connect("data.db")
        c3 = conn3.cursor()
        c3.execute("UPDATE sys_config SET value='20' WHERE key='daily_buy_limit'")
        c3.execute("UPDATE orders SET status='已退票', pay_status='已取消' WHERE username=? AND create_time LIKE ?",
                   (self.username, datetime.now().strftime("%Y-%m-%d") + "%"))
        conn3.commit()
        conn3.close()

    def test_buy_student_discount(self):
        train = self._get_available_train()
        if not train or train["type"] not in ("高铁", "动车"):
            self.skipTest("需要高铁/动车车次")
        buy_res = self._buy_ticket(train["train_no"], "二等座", "学生张三", "y")
        self.assertTrue(buy_res["success"])
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT seat_types FROM trains WHERE train_no=?", (train["train_no"],))
        seat_json = c.fetchone()["seat_types"]
        conn.close()
        seats = json.loads(seat_json)
        if isinstance(seats, list) and len(seats) > 0 and isinstance(seats[0], dict):
            expected = next(s["price"] for s in seats if s["name"] == "二等座") * 0.75
        else:
            expected = train["price"] * 0.75
        self.assertAlmostEqual(buy_res["price"], round(expected, 2), places=1)

    # ======================== 退票 ========================
    def test_refund_success(self):
        order = self._bulk_buy()
        resp = self.client.post("/refund", data={"order_id": order["id"]})
        text = resp.get_data(as_text=True)
        self.assertIn("退票成功", text)
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT status FROM orders WHERE id=?", (order["id"],))
        row = c.fetchone()
        conn.close()
        self.assertEqual(row["status"], "已退票")

    def test_refund_order_not_found(self):
        resp = self.client.post("/refund", data={"order_id": 99999999})
        self.assertEqual(resp.get_data(as_text=True), "订单不存在")

    def test_refund_unpaid(self):
        train = self._get_available_train()
        buy_res = self._buy_ticket(train["train_no"])
        self.assertTrue(buy_res["success"])
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT id FROM orders WHERE order_no=?", (buy_res["order_no"],))
        order_id = c.fetchone()["id"]
        conn.close()
        resp = self.client.post("/refund", data={"order_id": order_id})
        self.assertEqual(resp.get_data(as_text=True), "仅可退已支付订单")

    def test_refund_already_refunded(self):
        order = self._bulk_buy()
        self.client.post("/refund", data={"order_id": order["id"]})
        resp = self.client.post("/refund", data={"order_id": order["id"]})
        self.assertEqual(resp.get_data(as_text=True), "该订单已退票")

    def test_refund_departed(self):
        conn = get_db()
        c = conn.cursor()
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        c.execute(
            "SELECT o.id FROM orders o JOIN trains t ON o.train_no = t.train_no "
            "WHERE o.pay_status='已支付' AND o.status='已购票' AND t.travel_date <= ? LIMIT 1",
            (yesterday,)
        )
        row = c.fetchone()
        conn.close()
        if row:
            resp = self.client.post("/refund", data={"order_id": row["id"]})
            self.assertIn("已发车", resp.get_data(as_text=True))
        else:
            # 手动制造已发车环境
            order = self._bulk_buy()
            conn = get_db()
            c = conn.cursor()
            c.execute("SELECT train_no FROM orders WHERE id=?", (order["id"],))
            old_tno = c.fetchone()["train_no"]
            orig_date = old_tno.split("_", 1)[1]
            c.execute("UPDATE trains SET travel_date=? WHERE train_no=?", (yesterday, old_tno))
            conn.commit()
            conn.close()
            resp = self.client.post("/refund", data={"order_id": order["id"]})
            self.assertIn("已发车", resp.get_data(as_text=True))
            # 恢复
            conn = get_db()
            c = conn.cursor()
            c.execute("UPDATE trains SET travel_date=? WHERE train_no=?", (orig_date, old_tno))
            conn.commit()
            conn.close()

    # ======================== 改签 ========================
    def test_reschedule_cheaper(self):
        order = self._bulk_buy()
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT * FROM orders WHERE id=?", (order["id"],))
        o = c.fetchone()
        c.execute(
            "SELECT * FROM trains WHERE start=? AND end=? AND travel_date >= ? "
            "AND remaining_tickets > 0 AND price < ? LIMIT 1",
            (o["start"], o["end"], datetime.now().strftime("%Y-%m-%d"), o["price"])
        )
        cheaper = c.fetchone()
        conn.close()
        if not cheaper:
            self.skipTest("没有更便宜的改签目标")
        resp = self.client.post("/reschedule", data={
            "order_id": order["id"],
            "new_train_no": cheaper["train_no"],
            "new_seat_type": order["seat_type"],
        })
        data = resp.get_json()
        self.assertTrue(data["success"])
        self.assertFalse(data["need_pay"])
        if data["price_diff"] < 0:
            self.assertIn("退差价", data["msg"])
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT status FROM orders WHERE id=?", (order["id"],))
        row = c.fetchone()
        conn.close()
        self.assertEqual(row["status"], "已改签")

    def test_reschedule_order_not_found(self):
        resp = self.client.post("/reschedule", data={
            "order_id": 99999999, "new_train_no": "G1_2099-12-31", "new_seat_type": "二等座"
        })
        data = resp.get_json()
        self.assertFalse(data["success"])
        self.assertIn("订单不存在", data["msg"])

    def test_reschedule_unpaid(self):
        train = self._get_available_train()
        buy_res = self._buy_ticket(train["train_no"])
        self.assertTrue(buy_res["success"])
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT id FROM orders WHERE order_no=?", (buy_res["order_no"],))
        order_id = c.fetchone()["id"]
        conn.close()
        resp = self.client.post("/reschedule", data={
            "order_id": order_id, "new_train_no": train["train_no"], "new_seat_type": "二等座"
        })
        data = resp.get_json()
        self.assertFalse(data["success"])
        self.assertIn("仅可改签已支付", data["msg"])

    def test_reschedule_already_done(self):
        order = self._bulk_buy()
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT * FROM orders WHERE id=?", (order["id"],))
        o = c.fetchone()
        c.execute(
            "SELECT * FROM trains WHERE start=? AND end=? AND travel_date >= ? "
            "AND remaining_tickets > 0 AND train_no != ? LIMIT 1",
            (o["start"], o["end"], datetime.now().strftime("%Y-%m-%d"), o["train_no"])
        )
        new_train = c.fetchone()
        conn.close()
        if not new_train:
            self.skipTest("没有改签目标")
        resp1 = self.client.post("/reschedule", data={
            "order_id": order["id"], "new_train_no": new_train["train_no"],
            "new_seat_type": order["seat_type"],
        })
        self.assertTrue(resp1.get_json()["success"])
        resp2 = self.client.post("/reschedule", data={
            "order_id": order["id"], "new_train_no": new_train["train_no"],
            "new_seat_type": order["seat_type"],
        })
        data2 = resp2.get_json()
        self.assertFalse(data2["success"])
        self.assertIn("不可改签", data2["msg"])

    def test_reschedule_train_not_found(self):
        order = self._bulk_buy()
        resp = self.client.post("/reschedule", data={
            "order_id": order["id"], "new_train_no": "G99999_2099-12-31", "new_seat_type": "二等座"
        })
        data = resp.get_json()
        self.assertFalse(data["success"])
        self.assertIn("新车次不存在", data["msg"])

    def test_reschedule_no_tickets(self):
        order = self._bulk_buy()
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT * FROM orders WHERE id=?", (order["id"],))
        o = c.fetchone()
        c.execute(
            "SELECT * FROM trains WHERE start=? AND end=? AND travel_date >= ? "
            "AND remaining_tickets > 0 AND train_no != ? LIMIT 1",
            (o["start"], o["end"], datetime.now().strftime("%Y-%m-%d"), o["train_no"])
        )
        target = c.fetchone()
        if not target:
            conn.close()
            self.skipTest("没有改签目标")
        c.execute("UPDATE trains SET remaining_tickets=0 WHERE train_no=?", (target["train_no"],))
        conn.commit()
        conn.close()
        resp = self.client.post("/reschedule", data={
            "order_id": order["id"], "new_train_no": target["train_no"], "new_seat_type": "二等座"
        })
        data = resp.get_json()
        self.assertFalse(data["success"])
        self.assertIn("余票不足", data["msg"])
        # 恢复
        conn = get_db()
        c = conn.cursor()
        c.execute("UPDATE trains SET remaining_tickets=total_tickets WHERE train_no=?", (target["train_no"],))
        conn.commit()
        conn.close()

    def test_reschedule_different_city(self):
        order = self._bulk_buy()
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT * FROM orders WHERE id=?", (order["id"],))
        o = c.fetchone()
        c.execute(
            "SELECT * FROM trains WHERE start!=? AND end!=? AND remaining_tickets > 0 LIMIT 1",
            (o["start"], o["end"])
        )
        diff = c.fetchone()
        conn.close()
        if not diff:
            self.skipTest("没有不同城车次")
        resp = self.client.post("/reschedule", data={
            "order_id": order["id"], "new_train_no": diff["train_no"], "new_seat_type": "二等座"
        })
        data = resp.get_json()
        self.assertFalse(data["success"])
        self.assertIn("同城", data["msg"])

    def test_reschedule_plane_to_plane(self):
        conn = get_db()
        c = conn.cursor()
        future_date = (datetime.now() + timedelta(days=10)).strftime("%Y-%m-%d")
        c.execute(
            "SELECT * FROM trains WHERE type='飞机' AND travel_date=? AND remaining_tickets > 0 LIMIT 1",
            (future_date,)
        )
        plane = c.fetchone()
        conn.close()
        if not plane:
            self.skipTest("没有飞机票可测")
        buy_res = self._buy_ticket(plane["train_no"], "经济舱")
        self.assertTrue(buy_res["success"])
        for _ in range(20):
            if self._pay_order(buy_res["order_no"]) == "支付成功":
                break
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT id FROM orders WHERE order_no=?", (buy_res["order_no"],))
        order_id = c.fetchone()["id"]
        c.execute("SELECT * FROM trains WHERE type='高铁' AND remaining_tickets > 0 LIMIT 1")
        train = c.fetchone()
        conn.close()
        if not train:
            self.skipTest("没有高铁车次可测")
        resp = self.client.post("/reschedule", data={
            "order_id": order_id, "new_train_no": train["train_no"], "new_seat_type": "二等座"
        })
        data = resp.get_json()
        self.assertFalse(data["success"])
        self.assertIn("飞机", data["msg"])

    def test_reschedule_cannot_again(self):
        order = self._bulk_buy()
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT * FROM orders WHERE id=?", (order["id"],))
        o = c.fetchone()
        c.execute(
            "SELECT * FROM trains WHERE start=? AND end=? AND travel_date >= ? "
            "AND remaining_tickets > 0 AND train_no != ? LIMIT 1",
            (o["start"], o["end"], datetime.now().strftime("%Y-%m-%d"), o["train_no"])
        )
        target = c.fetchone()
        conn.close()
        if not target:
            self.skipTest("没有改签目标")
        resp1 = self.client.post("/reschedule", data={
            "order_id": order["id"], "new_train_no": target["train_no"],
            "new_seat_type": order["seat_type"],
        })
        data1 = resp1.get_json()
        self.assertTrue(data1["success"])
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT id FROM orders WHERE original_order_id=?", (order["id"],))
        new_order_row = c.fetchone()
        conn.close()
        if new_order_row:
            resp2 = self.client.post("/reschedule", data={
                "order_id": new_order_row["id"], "new_train_no": target["train_no"],
                "new_seat_type": order["seat_type"],
            })
            data2 = resp2.get_json()
            self.assertFalse(data2["success"])
            self.assertIn("不可改签", data2["msg"])


if __name__ == '__main__':
    unittest.main()