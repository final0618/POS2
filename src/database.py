from __future__ import annotations

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "pos.db"

MENU_ITEMS = [
    (
        "sunny-plate",
        "美式陽光早午餐盤",
        "招牌早午餐",
        "太陽蛋、香煎培根、薯餅與奶油吐司，一盤開啟好早晨。",
        220,
        "人氣招牌",
        "https://images.unsplash.com/photo-1525351484163-7529414344d8?auto=format&fit=crop&w=900&q=82",
        "美式早餐盤，搭配煎蛋、吐司與蔬菜",
    ),
    (
        "pancake-stack",
        "楓糖厚鬆餅",
        "招牌早午餐",
        "現煎厚鬆餅淋上楓糖，搭配奶油與季節水果。",
        185,
        "現點現煎",
        "https://images.unsplash.com/photo-1528207776546-365bb710ee93?auto=format&fit=crop&w=900&q=82",
        "淋上楓糖漿的鬆餅與水果",
    ),
    (
        "avocado-toast",
        "酪梨太陽蛋吐司",
        "招牌早午餐",
        "酪梨抹醬、半熟蛋與酸種吐司，清爽又有飽足感。",
        195,
        "清爽推薦",
        "https://images.unsplash.com/photo-1525351484163-7529414344d8?auto=format&fit=crop&w=900&q=82&sat=-35",
        "酪梨吐司與半熟太陽蛋",
    ),
    (
        "club-sandwich",
        "經典俱樂部三明治",
        "漢堡與吐司",
        "炙烤雞胸、培根、生菜與番茄，層層堆疊的經典滋味。",
        210,
        "店長推薦",
        "https://images.unsplash.com/photo-1528735602780-2552fd46c7af?auto=format&fit=crop&w=900&q=82",
        "烤吐司三明治搭配新鮮生菜",
    ),
    (
        "cheese-burger",
        "起司培根早餐堡",
        "漢堡與吐司",
        "手打牛肉、切達起司、脆培根與滑嫩炒蛋。",
        230,
        "飽足首選",
        "https://images.unsplash.com/photo-1568901346375-23c9450c58cd?auto=format&fit=crop&w=900&q=82",
        "牛肉起司漢堡與生菜",
    ),
    (
        "iced-latte",
        "焦糖冰拿鐵",
        "咖啡與飲品",
        "濃縮咖啡與鮮乳融合，焦糖香氣剛剛好。",
        95,
        "每日現調",
        "https://images.unsplash.com/photo-1461023058943-07fcbe16d735?auto=format&fit=crop&w=900&q=82",
        "玻璃杯冰拿鐵咖啡",
    ),
    (
        "orange-juice",
        "鮮榨柳橙汁",
        "咖啡與飲品",
        "酸甜清新，為早晨補充滿滿元氣。",
        85,
        "無添加",
        "https://images.unsplash.com/photo-1600271886742-f049cd451bba?auto=format&fit=crop&w=900&q=82",
        "新鮮柳橙汁與柳橙切片",
    ),
    (
        "cold-brew",
        "經典冷萃咖啡",
        "咖啡與飲品",
        "低溫慢萃，口感圓潤順口，冰涼醒腦。",
        100,
        "慢萃 12 小時",
        "https://images.unsplash.com/photo-1517701604599-bb29b565090c?auto=format&fit=crop&w=900&q=82",
        "加冰的黑咖啡",
    ),
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS menu_items (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    description TEXT NOT NULL,
    price INTEGER NOT NULL CHECK (price >= 0),
    badge TEXT NOT NULL,
    image_url TEXT NOT NULL,
    alt_text TEXT NOT NULL,
    is_available INTEGER NOT NULL DEFAULT 1 CHECK (is_available IN (0, 1))
);

CREATE INDEX IF NOT EXISTS idx_menu_items_category
    ON menu_items(category);

CREATE TABLE IF NOT EXISTS orders (
    id TEXT PRIMARY KEY,
    table_number TEXT NOT NULL
        CHECK (table_number IN ('01', '02', '03', '04', '05', '06',
                                '07', '08', '09', '10', '11', '12')),
    status TEXT NOT NULL DEFAULT 'received'
        CHECK (status IN ('received', 'preparing', 'ready', 'completed', 'cancelled')),
    payment_status TEXT NOT NULL DEFAULT 'unpaid'
        CHECK (payment_status IN ('unpaid', 'paid', 'refunded')),
    total_amount INTEGER NOT NULL CHECK (total_amount >= 0),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS order_items (
    order_id TEXT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    menu_item_id TEXT NOT NULL REFERENCES menu_items(id) ON DELETE RESTRICT,
    item_name TEXT NOT NULL,
    unit_price INTEGER NOT NULL CHECK (unit_price >= 0),
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    subtotal INTEGER NOT NULL CHECK (subtotal = unit_price * quantity),
    PRIMARY KEY (order_id, menu_item_id)
);

CREATE TABLE IF NOT EXISTS inputs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    input_text TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
"""


def initialize_database(db_path: str | Path = DB_PATH) -> Path:
    database_path = Path(db_path)
    database_path.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(database_path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(SCHEMA)
        connection.executemany(
            """
            INSERT OR IGNORE INTO menu_items (
                id, name, category, description, price, badge, image_url, alt_text
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            MENU_ITEMS,
        )

    return database_path


if __name__ == "__main__":
    print(initialize_database())