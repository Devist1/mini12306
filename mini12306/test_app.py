import unittest
from app import app

class TestMini12306(unittest.TestCase):
    # 每个测试方法执行前初始化
    def setUp(self):
        app.config['TESTING'] = True
        self.client = app.test_client()

    # 测试登录页（对应 @app.route("/")）
    def test_login_page(self):
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200)

    # 测试注册页（对应 @app.route("/register")）
    def test_register_page(self):
        res = self.client.get("/register")
        self.assertEqual(res.status_code, 200)

    # 测试首页（对应 @app.route("/index")）
    def test_index_page(self):
        res = self.client.get("/index")
        self.assertEqual(res.status_code, 200)

    # 测试购票页（对应 @app.route("/buy_page")）
    def test_buy_page(self):
        res = self.client.get("/buy_page")
        self.assertEqual(res.status_code, 200)

    # 测试订单页（对应 @app.route("/order_page")）
    def test_order_page(self):
        res = self.client.get("/order_page")
        self.assertEqual(res.status_code, 200)

    # 测试个人中心页（对应 @app.route("/personal_page")）
    def test_personal_page(self):
        res = self.client.get("/personal_page")
        self.assertEqual(res.status_code, 200)

    # 测试管理员页（对应 @app.route("/admin_page")）
    def test_admin_page(self):
        res = self.client.get("/admin_page")
        self.assertEqual(res.status_code, 200)

    # 测试支付页（对应 @app.route("/pay_page")）
    def test_pay_page(self):
        res = self.client.get("/pay_page")
        self.assertEqual(res.status_code, 200)

    # 测试改签页（对应 @app.route("/reschedule_page")）
    def test_reschedule_page(self):
        res = self.client.get("/reschedule_page")
        self.assertEqual(res.status_code, 200)

    # 测试重置密码页（对应 @app.route("/reset_password")）
    def test_reset_password_page(self):
        res = self.client.get("/reset_password")
        self.assertEqual(res.status_code, 200)

if __name__ == '__main__':
    unittest.main()