from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

from src.loyalty_schema import migrate_loyalty

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "pos.db"

MENU_ITEMS = [
    (
        "sunny-plate", "美式陽光早午餐盤", "招牌早午餐",
        "太陽蛋、香煎培根、薯餅與奶油吐司，一盤開啟好早晨。", 220,
        "人氣招牌", "https://images.unsplash.com/photo-1525351484163-7529414344d8?auto=format&fit=crop&w=900&q=82",
        "美式早餐盤，搭配煎蛋、吐司與蔬菜",
    ),
    (
        "pancake-stack", "楓糖厚鬆餅", "招牌早午餐",
        "現煎厚鬆餅淋上楓糖，搭配奶油與季節水果。", 185,
        "現點現煎", "https://images.unsplash.com/photo-1528207776546-365bb710ee93?auto=format&fit=crop&w=900&q=82",
        "淋上楓糖漿的鬆餅與水果",
    ),
    (
        "avocado-toast", "酪梨太陽蛋吐司", "招牌早午餐",
        "酪梨抹醬、半熟蛋與酸種吐司，清爽又有飽足感。", 195,
        "清爽推薦", "https://images.unsplash.com/photo-1525351484163-7529414344d8?auto=format&fit=crop&w=900&q=82&sat=-35",
        "酪梨吐司與半熟太陽蛋",
    ),
    (
        "club-sandwich", "經典俱樂部三明治", "漢堡與吐司",
        "炙烤雞胸、培根、生菜與番茄，層層堆疊的經典滋味。", 210,
        "店長推薦", "https://images.unsplash.com/photo-1528735602780-2552fd46c7af?auto=format&fit=crop&w=900&q=82",
        "烤吐司三明治搭配新鮮生菜",
    ),
    (
        "cheese-burger", "起司培根早餐堡", "漢堡與吐司",
        "手打牛肉、切達起司、脆培根與滑嫩炒蛋。", 230,
        "飽足首選", "https://images.unsplash.com/photo-1568901346375-23c9450c58cd?auto=format&fit=crop&w=900&q=82",
        "牛肉起司漢堡與生菜",
    ),
    (
        "iced-latte", "焦糖冰拿鐵", "咖啡與飲品",
        "濃縮咖啡與鮮乳融合，焦糖香氣剛剛好。", 95,
        "每日現調", "https://images.unsplash.com/photo-1461023058943-07fcbe16d735?auto=format&fit=crop&w=900&q=82",
        "玻璃杯冰拿鐵咖啡",
    ),
    (
        "orange-juice", "鮮榨柳橙汁", "咖啡與飲品",
        "酸甜清新，為早晨補充滿滿元氣。", 85,
        "無添加", "https://images.unsplash.com/photo-1600271886742-f049cd451bba?auto=format&fit=crop&w=900&q=82",
        "新鮮柳橙汁與柳橙切片",
    ),
    (
        "cold-brew", "經典冷萃咖啡", "咖啡與飲品",
        "低溫慢萃，口感圓潤順口，冰涼醒腦。", 100,
        "慢萃 12 小時", "https://images.unsplash.com/photo-1517701604599-bb29b565090c?auto=format&fit=crop&w=900&q=82",
        "加冰的黑咖啡",
    ),
]

COMPETITORS = [
    (
        "maps-0x34693d8a861cd28d-0x21e2347928be2b0d",
        "大方早餐店",
        "早餐店",
        "青海路二段240-5號",
        24.1704139,
        120.6456991,
        4.3,
        223,
        "Google Maps 查詢顯示週六 05:00 開始營業",
        "https://www.google.com/maps/place/%E5%A4%A7%E6%96%B9%E6%97%A9%E9%A4%90%E5%BA%97/data=!4m7!3m6!1s0x34693d8a861cd28d:0x21e2347928be2b0d!8m2!3d24.1704139!4d120.6456991!16s%2Fg%2F11c18pwxsk!19sChIJjdIchoo9aTQRDSu-KHk04iE?hl=zh-TW",
    ),
    (
        "maps-0x34693d8a7db24a8b-0xe860637d146b932b",
        "春三朝午",
        "早午餐餐廳",
        "上石路179號",
        24.170511,
        120.6460165,
        4.5,
        4242,
        "Google Maps 查詢顯示營業中，17:30 打烊",
        "https://www.google.com/maps/place/%E6%98%A5%E4%B8%89%E6%9C%9D%E5%8D%88/data=!4m7!3m6!1s0x34693d8a7db24a8b:0xe860637d146b932b!8m2!3d24.170511!4d120.6460165!16s%2Fg%2F11c1lk4439!19sChIJi0qyfYo9aTQRK5NrFH1jYOg?hl=zh-TW",
    ),
    (
        "maps-0x34691620354e51e9-0xfe564d4fa2effa2c",
        "心饗晨坊 早午餐",
        "早餐店",
        "西屯路二段269-28號",
        24.1739093,
        120.6443584,
        4.1,
        557,
        "Google Maps 查詢顯示週六 06:30 開始營業",
        "https://www.google.com/maps/place/%E5%BF%83%E9%A5%97%E6%99%A8%E5%9D%8A+%E6%97%A9%E5%8D%88%E9%A4%90/data=!4m7!3m6!1s0x34691620354e51e9:0xfe564d4fa2effa2c!8m2!3d24.1739093!4d120.6443584!16s%2Fg%2F11cn0t6blz!19sChIJ6VFONSAWaTQRLPrvok9NVv4?hl=zh-TW",
    ),
    (
        "maps-0x3469175414a011cf-0xf747747f28d56fc8",
        "尚美早餐店",
        "早餐店",
        "至善路118號",
        24.1736466,
        120.6416,
        4.8,
        36,
        "Google Maps 查詢顯示週六 06:00 開始營業",
        "https://www.google.com/maps/place/%E5%B0%9A%E7%BE%8E%E6%97%A9%E9%A4%90%E5%BA%97/data=!4m7!3m6!1s0x3469175414a011cf:0xf747747f28d56fc8!8m2!3d24.1736466!4d120.6416!16s%2Fg%2F11fhz0lccl!19sChIJzxGgFFQXaTQRyG_VKH90R_c?hl=zh-TW",
    ),
    (
        "maps-0x34691737df10e107-0x53a9aeaf4dfc6f1c",
        "微早晨 We Brunch 手作早午餐",
        "早餐店",
        "櫻花路76號",
        24.1707839,
        120.6513587,
        4.0,
        492,
        "Google Maps 查詢顯示即將打烊 14:00，週六 06:30 開始營業",
        "https://www.google.com/maps/place/%E5%BE%AE%E6%97%A9%E6%99%A8+We+Brunch+%E6%89%8B%E4%BD%9C%E6%97%A9%E5%8D%88%E9%A4%90/data=!4m7!3m6!1s0x34691737df10e107:0x53a9aeaf4dfc6f1c!8m2!3d24.1707839!4d120.6513587!16s%2Fg%2F11mhp3f5sm!19sChIJB-EQ3zcXaTQRHG_8Ta-uqVM?hl=zh-TW",
    ),
    (
        "preserve-taichung-huizhong",
        "PRESERVE 台中惠中店",
        "蔬食早午餐",
        "惠中路二段39號",
        24.156092,
        120.641281,
        None,
        None,
        "來源文章列示平日09:00-21:00、假日08:00-21:00",
        "https://www.instagram.com/p/DUAcoIFk9aH/",
    ),
    (
        "local-sa-day-xitun",
        "三塊鬆餅 SA DAY",
        "早午餐餐廳",
        "漢城六街51號",
        None,
        None,
        4.8,
        324,
        "Google Maps 查詢顯示營業至16:00",
        "https://www.foodpanda.com.tw/restaurant/rsfd/sa-day-song-bing",
    ),
    (
        "local-bagel-expresso-park",
        "Bagel Expresso 貝果咖啡公園店",
        "早午餐咖啡",
        "河南路二段301巷72號",
        None,
        None,
        None,
        None,
        "來源文章列示平日07:30-16:00、假日07:30-17:00",
        "https://taiwan17go.com/bluecheese1812/",
    ),
]

COMPETITOR_PRICES = [
    (
        "preserve-taichung-huizhong", "sunny-plate", 355, "酪梨大早餐盤",
        "https://upssmile.com/270995/preserve-taichung", "2026-02-22",
        "完整酪梨早午餐盤，與本店早餐盤份量/配菜不同；另收10%服務費",
    ),
    (
        "local-sa-day-xitun", "sunny-plate", 400, "經典鄉村鬆餅套餐",
        "https://www.foodpanda.com.tw/restaurant/rsfd/sa-day-song-bing", "2026-11-06",
        "套餐含鬆餅、沙拉、配菜及紅茶，非單一早餐盤；Foodpanda 外送價",
    ),
    (
        "preserve-taichung-huizhong", "avocado-toast", 355, "酪梨大早餐盤",
        "https://upssmile.com/270995/preserve-taichung", "2026-02-22",
        "同類參考：含兩顆蛋、菇和沙拉，份量與本店吐司不同；另收10%服務費",
    ),
    (
        "local-sa-day-xitun", "pancake-stack", 160, "原味舒芙蕾鬆餅",
        "https://www.foodpanda.com.tw/restaurant/rsfd/sa-day-song-bing", "2026-11-06",
        "舒芙蕾鬆餅附蜂蜜和鮮奶油，與本店楓糖厚鬆餅配料不同；Foodpanda 外送價",
    ),
    (
        "local-bagel-expresso-park", "club-sandwich", 120, "自醃烤雞腿排貝果",
        "https://taiwan17go.com/bluecheese1812/", "2026-11-06",
        "雞腿排貝果單品，麵包及配料不同於俱樂部三明治；來源文章發布於2026-06-30",
    ),
    (
        "local-bagel-expresso-park", "cheese-burger", 350, "U.S.A.手打厚牛肉堡",
        "https://taiwan17go.com/bluecheese1812/", "2026-11-06",
        "厚牛肉早午餐漢堡，份量與配菜不同；來源文章發布於2026-06-30",
    ),
    (
        "local-bagel-expresso-park", "iced-latte", 105, "拿鐵",
        "https://taiwan17go.com/bluecheese1812/", "2026-11-06",
        "來源未標示冰/熱與容量；來源文章發布於2026-06-30",
    ),
    (
        "local-sa-day-xitun", "iced-latte", 150, "焦糖拿鐵",
        "https://www.foodpanda.com.tw/restaurant/rsfd/sa-day-song-bing", "2026-11-06",
        "來源未標示冰/熱與容量，與本店冰飲規格不同；Foodpanda 外送價",
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

CREATE TABLE IF NOT EXISTS competitors (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    address TEXT NOT NULL,
    latitude REAL,
    longitude REAL,
    rating REAL CHECK (rating IS NULL OR (rating >= 0 AND rating <= 5)),
    review_count INTEGER CHECK (review_count IS NULL OR review_count >= 0),
    business_hours TEXT,
    phone TEXT,
    website_url TEXT,
    source_url TEXT NOT NULL,
    source_checked_at TEXT NOT NULL,
    notes TEXT NOT NULL DEFAULT '',
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1))
);

CREATE TABLE IF NOT EXISTS competitor_prices (
    competitor_id TEXT NOT NULL REFERENCES competitors(id) ON DELETE CASCADE,
    menu_item_id TEXT NOT NULL REFERENCES menu_items(id) ON DELETE CASCADE,
    price INTEGER NOT NULL CHECK (price >= 0),
    product_name TEXT,
    price_source_url TEXT,
    price_checked_at TEXT,
    price_notes TEXT,
    PRIMARY KEY (competitor_id, menu_item_id)
);

CREATE INDEX IF NOT EXISTS idx_competitors_name
    ON competitors(name);
CREATE INDEX IF NOT EXISTS idx_competitors_category
    ON competitors(category);

"""


def initialize_database(db_path: str | Path = DB_PATH) -> Path:
    database_path = Path(db_path)
    database_path.parent.mkdir(parents=True, exist_ok=True)

    with closing(sqlite3.connect(database_path)) as connection, connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(SCHEMA)
        migrate_loyalty(connection)
        price_columns = {row[1] for row in connection.execute("PRAGMA table_info(competitor_prices)")}
        for column in ("product_name", "price_source_url", "price_checked_at", "price_notes"):
            if column not in price_columns:
                connection.execute(f"ALTER TABLE competitor_prices ADD COLUMN {column} TEXT")
        connection.executemany(
            """
            INSERT OR IGNORE INTO menu_items (
                id, name, category, description, price, badge, image_url, alt_text
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            MENU_ITEMS,
        )
        connection.executemany(
            """
            INSERT OR IGNORE INTO competitors (
                id, name, category, address, latitude, longitude, rating,
                review_count, business_hours, phone, website_url, source_url,
                source_checked_at, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    competitor_id, name.strip(), category.strip(), address.strip(), latitude, longitude,
                    rating, review_count, business_hours.strip(), None, None, source_url.strip(),
                    "2026-11-06",
                    "來源：Google 地圖搜尋「早餐店 上石路 台中市西屯區」。評分、評論數與營業資訊為查詢當時顯示，請以店家最新公告為準。",
                )
                for (
                    competitor_id, name, category, address, latitude, longitude,
                    rating, review_count, business_hours, source_url,
                ) in COMPETITORS
            ],
        )
        connection.executemany(
            """
            INSERT OR IGNORE INTO competitor_prices (
                competitor_id, menu_item_id, price, product_name,
                price_source_url, price_checked_at, price_notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            COMPETITOR_PRICES,
        )

    return database_path


if __name__ == "__main__":
    print(initialize_database())