import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from src import admin
from src.database import initialize_database
from src.main import app


class MenuPriceAdviceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "test.db"
        initialize_database(self.db)
        with closing(sqlite3.connect(self.db)) as connection, connection:
            connection.execute("DELETE FROM competitor_prices")
        self.db_patch = patch.object(admin, "DB_PATH", self.db)
        self.db_patch.start()
        app.dependency_overrides[admin.require_admin] = lambda: "test"
        self.client = TestClient(app)
        with closing(sqlite3.connect(self.db)) as connection, connection:
            ids = [row[0] for row in connection.execute("SELECT id FROM competitors LIMIT 3")]
            self.ids = ids
            connection.execute(
                "INSERT INTO competitor_prices VALUES (?, ?, ?, ?, ?, ?, ?)",
                (ids[0], "avocado-toast", 100, "Toast A", "https://example.com/a", "2026-11-06", "similar"),
            )
            connection.execute(
                "INSERT INTO competitor_prices (competitor_id, menu_item_id, price) VALUES (?, ?, ?)",
                (ids[1], "avocado-toast", 101),
            )
            connection.execute(
                "INSERT INTO competitor_prices (competitor_id, menu_item_id, price) VALUES (?, ?, ?)",
                (ids[2], "avocado-toast", 1000),
            )
            connection.execute("UPDATE competitors SET is_active = 0 WHERE id = ?", (ids[2],))

    def tearDown(self):
        self.client.close()
        app.dependency_overrides.clear()
        self.db_patch.stop()
        self.temp.cleanup()

    def test_comparisons_and_rounding_ignore_inactive(self):
        response = self.client.get("/api/admin/menu")
        self.assertEqual(response.status_code, 200)
        items = {item["id"]: item for item in response.json()["items"]}
        avocado = items["avocado-toast"]
        self.assertEqual(avocado["recommended_price"], 101)
        self.assertEqual(len(avocado["price_comparisons"]), 2)
        self.assertIn("https://example.com/a", [p["price_source_url"] for p in avocado["price_comparisons"]])
        self.assertIsNone(items["cold-brew"]["recommended_price"])
        self.assertEqual(items["cold-brew"]["price_comparisons"], [])

    def test_seeded_prices_and_missing_items(self):
        seeded_db = Path(self.temp.name) / "seeded.db"
        initialize_database(seeded_db)
        with patch.object(admin, "DB_PATH", seeded_db):
            response = self.client.get("/api/admin/menu")
        self.assertEqual(response.status_code, 200)
        items = {item["id"]: item for item in response.json()["items"]}
        self.assertEqual(items["sunny-plate"]["recommended_price"], 378)
        self.assertEqual(items["iced-latte"]["recommended_price"], 128)
        for menu_id in ("orange-juice", "cold-brew"):
            self.assertIsNone(items[menu_id]["recommended_price"])
            self.assertEqual(items[menu_id]["price_comparisons"], [])

    def test_preserve_source_only_when_price_unchanged(self):
        competitor = next(c for c in self.client.get("/api/admin/competitors").json()["competitors"]
                          if c["id"] == self.ids[0])
        self.assertEqual(self.client.put(f"/api/admin/competitors/{self.ids[0]}", json=competitor).status_code, 200)
        with closing(sqlite3.connect(self.db)) as connection:
            source = connection.execute(
                "SELECT price_source_url FROM competitor_prices WHERE competitor_id = ?", (self.ids[0],)
            ).fetchone()[0]
        self.assertEqual(source, "https://example.com/a")
        competitor["prices"]["avocado-toast"] = 120
        self.assertEqual(self.client.put(f"/api/admin/competitors/{self.ids[0]}", json=competitor).status_code, 200)
        with closing(sqlite3.connect(self.db)) as connection:
            source = connection.execute(
                "SELECT price_source_url FROM competitor_prices WHERE competitor_id = ?", (self.ids[0],)
            ).fetchone()[0]
        self.assertIsNone(source)

    def test_existing_price_table_is_migrated_without_losing_prices(self):
        with closing(sqlite3.connect(self.db)) as connection, connection:
            connection.execute("ALTER TABLE competitor_prices RENAME TO old_prices")
            connection.execute(
                "CREATE TABLE competitor_prices (competitor_id TEXT, menu_item_id TEXT, "
                "price INTEGER, PRIMARY KEY (competitor_id, menu_item_id))"
            )
            connection.execute(
                "INSERT INTO competitor_prices SELECT competitor_id, menu_item_id, price FROM old_prices"
            )
            connection.execute("DROP TABLE old_prices")
        initialize_database(self.db)
        with closing(sqlite3.connect(self.db)) as connection:
            price = connection.execute(
                "SELECT price, price_source_url FROM competitor_prices WHERE competitor_id = ?",
                (self.ids[0],),
            ).fetchone()
        self.assertEqual(price, (100, None))


if __name__ == "__main__":
    unittest.main()
