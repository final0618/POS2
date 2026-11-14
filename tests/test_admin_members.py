import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from src import admin, main
from src.database import initialize_database


class AdminMembersTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "members.db"
        initialize_database(self.db)
        self.patches = [
            patch.object(admin, "DB_PATH", self.db),
            patch.object(admin, "ADMIN_USERNAME", "staff"),
            patch.object(admin, "ADMIN_PASSWORD", "test-password"),
            patch.object(admin, "ADMIN_SESSION_SECRET", "test-secret"),
        ]
        for item in self.patches:
            item.start()
        self.client = TestClient(main.app)
        with closing(sqlite3.connect(self.db)) as connection, connection:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.executemany(
                "INSERT INTO members(id, phone, password_hash, name, status, created_at, updated_at) VALUES (?, ?, 'private-hash', ?, ?, ?, ?)",
                [
                    ("a", "0911111111", "Alice", "active", "2026-01-01T00:00:00.000Z", "2026-01-01T00:00:00.000Z"),
                    ("b", "0922222222", "Bob", "disabled", "2026-02-01T00:00:00.000Z", "2026-02-01T00:00:00.000Z"),
                ],
            )
            connection.executemany(
                """INSERT INTO point_transactions(id, member_id, kind, points_delta, idempotency_key, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                [
                    ("a-earn", "a", "earn", 130, "a-earn", "2026-01-02T00:00:00.000Z"),
                    ("a-redeem", "a", "redeem", -50, "a-redeem", "2026-01-03T00:00:00.000Z"),
                    ("a-expired", "a", "earn", 20, "a-expired", "2026-01-04T00:00:00.000Z"),
                    ("b-earn", "b", "earn", 10, "b-earn", "2026-02-02T00:00:00.000Z"),
                ],
            )
            connection.executemany(
                """INSERT INTO point_lots(id, member_id, source_transaction_id, initial_points, remaining_points, expires_at, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                [
                    ("a-lot", "a", "a-earn", 130, 80, "2099-01-01T00:00:00.000Z", "2026-01-02T00:00:00.000Z"),
                    ("expired-lot", "a", "a-expired", 20, 20, "2001-01-01T00:00:00.000Z", "2026-01-04T00:00:00.000Z"),
                    ("b-lot", "b", "b-earn", 10, 10, "2099-01-01T00:00:00.000Z", "2026-02-02T00:00:00.000Z"),
                ],
            )

    def tearDown(self):
        self.client.close()
        for item in self.patches:
            item.stop()
        self.temp.cleanup()

    def login(self):
        response = self.client.post("/api/admin/login", json={"username": "staff", "password": "test-password"})
        self.assertEqual(response.status_code, 200)

    def test_requires_admin_authentication(self):
        self.assertEqual(self.client.get("/api/admin/members").status_code, 401)
        self.assertEqual(self.client.get("/api/admin/members/a/transactions").status_code, 401)
        self.login()
        self.assertEqual(self.client.get("/api/admin/members").status_code, 200)
        self.client.post("/api/admin/logout")
        self.assertEqual(self.client.get("/api/admin/members").status_code, 401)

    def test_member_search_pagination_and_private_fields(self):
        self.login()
        response = self.client.get("/api/admin/members", params={"limit": 1})
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertTrue(response.json()["has_more"])
        self.assertEqual(response.json()["members"][0]["id"], "b")
        second = self.client.get("/api/admin/members", params={"limit": 1, "offset": 1}).json()
        self.assertEqual(second["members"][0]["available_points"], 80)
        self.assertNotIn("password_hash", second["members"][0])
        self.assertFalse(second["has_more"])
        self.assertEqual(self.client.get("/api/admin/members", params={"query": "1111"}).json()["members"][0]["id"], "a")
        self.assertEqual(self.client.get("/api/admin/members", params={"query": "Alice"}).json()["members"][0]["id"], "a")
        self.assertEqual(self.client.get("/api/admin/members", params={"query": "%"}).json()["members"], [])

    def test_history_is_member_scoped_and_expires_points(self):
        self.login()
        response = self.client.get("/api/admin/members/a/transactions", params={"limit": 2})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["cache-control"], "no-store")
        data = response.json()
        self.assertEqual(data["member"]["available_points"], 80)
        self.assertNotIn("password_hash", data["member"])
        self.assertTrue(data["has_more"])
        self.assertEqual(data["transactions"][0]["kind"], "expire")
        second = self.client.get("/api/admin/members/a/transactions", params={"limit": 10, "offset": 2}).json()
        ids = [row["id"] for row in data["transactions"] + second["transactions"]]
        self.assertIn("a-redeem", ids)
        self.assertNotIn("b-earn", ids)
        self.assertFalse(second["has_more"])
        self.assertEqual(self.client.get("/api/admin/members/missing/transactions").status_code, 404)


if __name__ == "__main__":
    unittest.main()
