import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from src import admin, main
from src.database import initialize_database


class AdminOrderFilterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "orders.db"
        initialize_database(self.db)
        self.db_patch = patch.object(admin, "DB_PATH", self.db)
        self.db_patch.start()
        main.app.dependency_overrides[admin.require_admin] = lambda: "test-admin"
        self.client = TestClient(main.app)
        with closing(sqlite3.connect(self.db)) as connection, connection:
            connection.executemany(
                """
                INSERT INTO orders (id, table_number, status, payment_status, total_amount, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    ("order-a", "03", "completed", "paid", 615, "2026-11-12T10:00:00.000Z"),
                    ("order-b", "03", "completed", "unpaid", 300, "2026-11-12T09:00:00.000Z"),
                    ("order-c", "04", "completed", "paid", 450, "2026-11-12T08:00:00.000Z"),
                    ("order-d", "03", "cancelled", "refunded", 200, "2026-11-12T07:00:00.000Z"),
                ],
            )

    def tearDown(self):
        self.client.close()
        main.app.dependency_overrides.pop(admin.require_admin, None)
        self.db_patch.stop()
        self.temp.cleanup()

    def test_table_status_and_payment_filters_can_be_combined(self):
        response = self.client.get(
            "/api/admin/orders",
            params={"table_number": "03", "status": "completed", "payment_status": "paid"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual([order["id"] for order in response.json()["orders"]], ["order-a"])

    def test_each_filter_can_be_used_independently(self):
        filters_and_expected = [
            ({"table_number": "04"}, ["order-c"]),
            ({"status": "cancelled"}, ["order-d"]),
            ({"payment_status": "unpaid"}, ["order-b"]),
        ]
        for filters, expected_ids in filters_and_expected:
            with self.subTest(filters=filters):
                response = self.client.get("/api/admin/orders", params=filters)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    [order["id"] for order in response.json()["orders"]],
                    expected_ids,
                )

    def test_invalid_filter_values_are_rejected(self):
        for filters in [
            {"table_number": "13"},
            {"status": "unknown"},
            {"payment_status": "pending"},
        ]:
            with self.subTest(filters=filters):
                response = self.client.get("/api/admin/orders", params=filters)
                self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
