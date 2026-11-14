import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from src import admin, main, members
from src.database import initialize_database
from src.loyalty import expiry_date


class MemberLoyaltyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "test.db"
        initialize_database(self.db)
        self.patches = [patch.object(module, "DB_PATH", self.db) for module in (main, admin, members)]
        for item in self.patches:
            item.start()
        main.app.dependency_overrides[admin.require_admin] = lambda: "admin"
        self.client = TestClient(main.app)

    def tearDown(self):
        self.client.close()
        main.app.dependency_overrides.pop(admin.require_admin, None)
        for item in self.patches:
            item.stop()
        self.temp.cleanup()

    def register_and_login(self, phone="0912345678"):
        data = {"phone": phone, "password": "test-password-123"}
        self.assertEqual(self.client.post("/api/members/register", json=data).status_code, 201)
        self.assertEqual(self.client.post("/api/members/login", json=data).status_code, 200)

    def order(self, points=0, client=None):
        return (client or self.client).post(
            "/api/orders",
            json={"table_number": "01", "items": [{"menu_item_id": "sunny-plate", "quantity": 1}],
                  "points_redeemed": points},
        )

    def complete(self, order_id):
        for payload in ({"payment_status": "paid"}, {"status": "completed"}):
            response = self.client.patch(f"/api/admin/orders/{order_id}", json=payload)
            self.assertEqual(response.status_code, 200, response.text)

    def balance(self):
        response = self.client.get("/api/members/me/points")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["available_points"]

    def test_guest_order_migration_and_member_auth(self):
        guest = self.order()
        self.assertEqual(guest.status_code, 201)
        self.assertEqual(guest.json()["order"]["payable_amount"], 220)
        self.assertEqual(self.client.get("/api/members/me/points").status_code, 401)
        initialize_database(self.db)
        with closing(sqlite3.connect(self.db)) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT member_id FROM orders").fetchone()[0], None)
        self.register_and_login()
        response = self.order()
        self.assertEqual(response.status_code, 201)
        with closing(sqlite3.connect(self.db)) as connection:
            self.assertIsNotNone(connection.execute("SELECT member_id FROM orders WHERE id = ?", (response.json()["order"]["id"],)).fetchone()[0])
        self.assertEqual(self.client.post("/api/members/logout").status_code, 200)
        self.assertEqual(self.client.get("/api/members/me/points").status_code, 401)
        self.assertEqual(self.order().status_code, 201)

    def test_earning_redemption_and_reversal(self):
        self.register_and_login()
        first = None
        for _ in range(5):
            order_id = self.order().json()["order"]["id"]
            first = first or order_id
            self.complete(order_id)
        self.assertEqual(self.balance(), 110)
        self.client.patch(f"/api/admin/orders/{first}", json={"status": "completed", "payment_status": "paid"})
        self.assertEqual(self.balance(), 110)
        redeemed = self.order(100).json()["order"]
        self.assertEqual((redeemed["points_discount_amount"], redeemed["payable_amount"]), (1, 219))
        self.assertEqual(self.balance(), 10)
        self.assertEqual(self.client.patch(f"/api/admin/orders/{first}", json={"payment_status": "refunded"}).status_code, 409)
        self.assertEqual(self.client.patch(f"/api/admin/orders/{redeemed['id']}", json={"status": "cancelled"}).status_code, 200)
        self.assertEqual(self.balance(), 110)
        self.assertEqual(self.client.patch(f"/api/admin/orders/{first}", json={"payment_status": "refunded"}).status_code, 200)
        self.assertEqual(self.balance(), 88)
        self.assertEqual(self.client.patch(f"/api/admin/orders/{first}", json={"payment_status": "paid"}).status_code, 409)

    def test_refund_restores_original_expiry_and_rejects_expired_lots(self):
        self.register_and_login()
        for _ in range(5):
            self.complete(self.order().json()["order"]["id"])
        redeemed = self.order(100).json()["order"]
        with closing(sqlite3.connect(self.db)) as connection, connection:
            connection.execute(
                """UPDATE point_lots SET expires_at = '2000-01-01T00:00:00.000Z'
                   WHERE id IN (SELECT lot_id FROM point_redemption_allocations)"""
            )
        self.assertEqual(self.client.patch(f"/api/admin/orders/{redeemed['id']}", json={"status": "cancelled"}).status_code, 409)
        with closing(sqlite3.connect(self.db)) as connection:
            self.assertEqual(connection.execute("SELECT status FROM orders WHERE id = ?", (redeemed["id"],)).fetchone()[0], "received")

    def test_isolation_validation_and_origin(self):
        self.register_and_login()
        self.complete(self.order().json()["order"]["id"])
        self.assertEqual(self.balance(), 22)
        self.assertEqual(self.order(100).status_code, 422)
        self.assertEqual(self.order(1).status_code, 422)
        forged = self.client.post("/api/orders", json={"table_number": "01", "items": [{"menu_item_id": "sunny-plate", "quantity": 1}], "member_id": "other"})
        self.assertEqual(forged.status_code, 422)
        self.assertEqual(self.client.post("/api/members/logout", headers={"Origin": "https://evil.example"}).status_code, 403)
        self.client.post("/api/members/logout")
        self.register_and_login("0912345679")
        self.assertEqual(self.balance(), 0)
        self.assertEqual(self.client.get("/api/members/me/points/transactions").json()["transactions"], [])
        self.assertEqual(self.order(100).status_code, 422)

    def test_completed_before_payment_and_zero_total_redemption(self):
        self.register_and_login()
        first = self.order().json()["order"]["id"]
        self.assertEqual(self.client.patch(f"/api/admin/orders/{first}", json={"status": "completed"}).status_code, 200)
        self.assertEqual(self.balance(), 0)
        self.assertEqual(self.client.patch(f"/api/admin/orders/{first}", json={"payment_status": "paid"}).status_code, 200)
        self.assertEqual(self.balance(), 22)
        with closing(sqlite3.connect(self.db)) as connection, connection:
            member_id = connection.execute("SELECT id FROM members").fetchone()[0]
            connection.execute(
                """INSERT INTO point_transactions (id, member_id, kind, points_delta, idempotency_key, created_at)
                   VALUES ('fixture-transaction', ?, 'adjustment', 22000, 'fixture', '2020-01-01T00:00:00.000Z')""",
                (member_id,),
            )
            connection.execute(
                """INSERT INTO point_lots (id, member_id, source_transaction_id, initial_points, remaining_points, expires_at, created_at)
                   VALUES ('fixture-lot', ?, 'fixture-transaction', 22000, 22000, '2099-01-01T00:00:00.000Z', '2020-01-01T00:00:00.000Z')""",
                (member_id,),
            )
        order = self.order(22000).json()["order"]
        self.assertEqual(order["payable_amount"], 0)
        self.complete(order["id"])
        self.assertEqual(self.balance(), 22)

    def test_duplicate_phone_and_expired_session(self):
        self.register_and_login()
        self.assertEqual(
            self.client.post("/api/members/register", json={"phone": "0912-345-678", "password": "other-password"}).status_code,
            409,
        )
        with closing(sqlite3.connect(self.db)) as connection, connection:
            connection.execute("UPDATE member_sessions SET expires_at = '2000-01-01T00:00:00.000Z'")
        self.assertEqual(self.client.get("/api/members/me/points").status_code, 401)
        self.assertEqual(self.order().status_code, 401)
        self.assertEqual(self.client.post("/api/members/logout").status_code, 200)
        self.assertEqual(self.order().status_code, 201)

    def test_expiry_and_calendar_month_end(self):
        self.assertEqual(expiry_date(datetime(2024, 2, 29, 0, 0, tzinfo=timezone.utc), 12), datetime(2025, 2, 28, 0, 0, tzinfo=timezone.utc))
        self.register_and_login()
        self.complete(self.order().json()["order"]["id"])
        with closing(sqlite3.connect(self.db)) as connection, connection:
            connection.execute("UPDATE point_lots SET expires_at = '2000-01-01T00:00:00.000Z'")
        self.assertEqual(self.balance(), 0)
        self.assertEqual(self.balance(), 0)
        transactions = self.client.get("/api/members/me/points/transactions").json()["transactions"]
        self.assertEqual(sum(row["kind"] == "expire" for row in transactions), 1)

    def test_concurrent_redemptions_cannot_spend_same_points(self):
        self.register_and_login()
        for _ in range(5):
            self.complete(self.order().json()["order"]["id"])
        cookie = self.client.cookies.get(members.COOKIE_NAME)
        def place(_):
            client = TestClient(main.app)
            try:
                client.cookies.set(members.COOKIE_NAME, cookie)
                return self.order(100, client).status_code
            finally:
                client.close()
        with ThreadPoolExecutor(max_workers=2) as executor:
            statuses = sorted(executor.map(place, range(2)))
        self.assertEqual(statuses, [201, 422])
        self.assertEqual(self.balance(), 10)

    def test_login_throttle(self):
        self.register_and_login()
        self.client.post("/api/members/logout")
        for _ in range(5):
            response = self.client.post("/api/members/login", json={"phone": "0912345678", "password": "wrong-password"})
            self.assertEqual(response.status_code, 401)
        self.assertEqual(self.client.post("/api/members/login", json={"phone": "0912345678", "password": "test-password-123"}).status_code, 429)


if __name__ == "__main__":
    unittest.main()
