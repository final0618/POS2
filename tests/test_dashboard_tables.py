import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from src import main
from src.database import initialize_database


class FrozenDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 11, 6, 15, 0, 0, tzinfo=tz)


class DashboardTableTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "dashboard.db"
        initialize_database(self.db)
        self.db_patch = patch.object(main, "DB_PATH", self.db)
        self.time_patch = patch.object(main, "datetime", FrozenDateTime)
        self.db_patch.start()
        self.time_patch.start()
        self.client = TestClient(main.app)

    def tearDown(self):
        self.client.close()
        self.time_patch.stop()
        self.db_patch.stop()
        self.temp.cleanup()

    def test_monthly_counts_include_all_tables_exclude_cancelled_and_outside_period(self):
        orders = [
            ("a", "01", "received", "2026-10-31T16:00:00.000Z"),
            ("b", "01", "completed", "2026-11-06T06:00:00.000Z"),
            ("c", "02", "preparing", "2026-11-06T06:59:59.999Z"),
            ("d", "02", "cancelled", "2026-11-06T06:00:00.000Z"),
            ("e", "03", "received", "2026-10-31T15:59:59.999Z"),
            ("f", "04", "received", "2026-11-06T07:00:01.000Z"),
        ]
        with closing(sqlite3.connect(self.db)) as connection, connection:
            connection.executemany(
                "INSERT INTO orders (id, table_number, status, total_amount, created_at) VALUES (?, ?, ?, 100, ?)",
                orders,
            )
        response = self.client.get("/api/dashboard")
        self.assertEqual(response.status_code, 200)
        tables = response.json()["table_counts"]
        self.assertEqual([row["table_number"] for row in tables], [f"{i:02}" for i in range(1, 13)])
        self.assertEqual([row["order_count"] for row in tables], [2, 1] + [0] * 10)

    def test_empty_month_has_twelve_zero_counts(self):
        response = self.client.get("/api/dashboard")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["table_counts"]), 12)
        self.assertTrue(all(row["order_count"] == 0 for row in response.json()["table_counts"]))


if __name__ == "__main__":
    unittest.main()
