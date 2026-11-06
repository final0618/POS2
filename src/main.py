from contextlib import asynccontextmanager, closing
from datetime import datetime, timedelta, timezone
import sqlite3
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from src.admin import router as admin_router
from src.database import DB_PATH, initialize_database

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
TAIPEI = ZoneInfo("Asia/Taipei")


class OrderItemRequest(BaseModel):
    menu_item_id: str = Field(min_length=1, max_length=80)
    quantity: int = Field(ge=1, le=99)


class OrderRequest(BaseModel):
    table_number: str = Field(pattern=r"^(0[1-9]|1[0-2])$")
    items: list[OrderItemRequest] = Field(min_length=1, max_length=50)


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize_database()
    yield


app = FastAPI(title="Good Morning Club API", lifespan=lifespan)
app.include_router(admin_router)


@app.get("/api/menu")
def get_menu() -> dict[str, list[dict[str, object]]]:
    with closing(sqlite3.connect(DB_PATH)) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        rows = connection.execute(
            """
            SELECT
                id,
                name,
                category,
                description,
                price,
                badge,
                image_url AS image,
                alt_text AS alt
            FROM menu_items
            WHERE is_available = 1
            ORDER BY rowid
            """
        ).fetchall()

    return {"items": [dict(row) for row in rows]}


@app.post("/api/orders", status_code=201)
def create_order(request: OrderRequest) -> dict[str, dict[str, object]]:
    quantities: dict[str, int] = {}
    for item in request.items:
        quantities[item.menu_item_id] = quantities.get(item.menu_item_id, 0) + item.quantity
        if quantities[item.menu_item_id] > 99:
            raise HTTPException(status_code=422, detail="Each item quantity must not exceed 99.")

    placeholders = ", ".join("?" for _ in quantities)
    order_id = uuid4().hex

    with closing(sqlite3.connect(DB_PATH)) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        with connection:
            menu_rows = connection.execute(
                f"""
                SELECT id, name, price
                FROM menu_items
                WHERE is_available = 1 AND id IN ({placeholders})
                """,
                tuple(quantities),
            ).fetchall()
            menu_by_id = {row["id"]: row for row in menu_rows}
            unavailable = set(quantities) - menu_by_id.keys()
            if unavailable:
                raise HTTPException(
                    status_code=422,
                    detail=f"Unavailable menu item(s): {', '.join(sorted(unavailable))}",
                )

            order_items = []
            total_amount = 0
            for menu_item_id, quantity in quantities.items():
                menu_item = menu_by_id[menu_item_id]
                unit_price = menu_item["price"]
                subtotal = unit_price * quantity
                total_amount += subtotal
                order_items.append(
                    {
                        "menu_item_id": menu_item_id,
                        "name": menu_item["name"],
                        "unit_price": unit_price,
                        "quantity": quantity,
                        "subtotal": subtotal,
                    }
                )

            connection.execute(
                "INSERT INTO orders (id, table_number, total_amount) VALUES (?, ?, ?)",
                (order_id, request.table_number, total_amount),
            )
            connection.executemany(
                """
                INSERT INTO order_items (
                    order_id, menu_item_id, item_name, unit_price, quantity, subtotal
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        order_id,
                        item["menu_item_id"],
                        item["name"],
                        item["unit_price"],
                        item["quantity"],
                        item["subtotal"],
                    )
                    for item in order_items
                ],
            )
            created_at = connection.execute(
                "SELECT created_at FROM orders WHERE id = ?", (order_id,)
            ).fetchone()["created_at"]

    return {
        "order": {
            "id": order_id,
            "table_number": request.table_number,
            "status": "received",
            "payment_status": "unpaid",
            "total_amount": total_amount,
            "created_at": created_at,
            "items": order_items,
        }
    }


def _database_timestamp(value: datetime) -> str:
    utc_value = value.astimezone(timezone.utc)
    return utc_value.strftime("%Y-%m-%dT%H:%M:%S.") + f"{utc_value.microsecond // 1000:03d}Z"


@app.get("/api/dashboard")
def get_dashboard() -> dict[str, object]:
    now = datetime.now(TAIPEI)
    period_end = now.replace(microsecond=0) + timedelta(seconds=1)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=today_start.weekday())
    month_start = today_start.replace(day=1)
    end_timestamp = _database_timestamp(period_end)
    month_timestamp = _database_timestamp(month_start)
    week_timestamp = _database_timestamp(week_start)
    today_timestamp = _database_timestamp(today_start)

    with closing(sqlite3.connect(DB_PATH)) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        sales = connection.execute(
            """
            SELECT
                COALESCE(SUM(CASE WHEN created_at >= ? THEN total_amount ELSE 0 END), 0) AS today,
                COALESCE(SUM(CASE WHEN created_at >= ? THEN total_amount ELSE 0 END), 0) AS week,
                COALESCE(SUM(total_amount), 0) AS month
            FROM orders
            WHERE status != 'cancelled' AND created_at >= ? AND created_at < ?
            """,
            (today_timestamp, week_timestamp, month_timestamp, end_timestamp),
        ).fetchone()
        top_products = connection.execute(
            """
            SELECT
                oi.menu_item_id,
                oi.item_name AS name,
                SUM(oi.quantity) AS quantity,
                SUM(oi.subtotal) AS revenue
            FROM order_items AS oi
            JOIN orders AS o ON o.id = oi.order_id
            WHERE o.status != 'cancelled'
                AND o.created_at >= ? AND o.created_at < ?
            GROUP BY oi.menu_item_id, oi.item_name
            ORDER BY quantity DESC, revenue DESC, name ASC
            LIMIT 10
            """,
            (month_timestamp, end_timestamp),
        ).fetchall()
        popular_times = connection.execute(
            """
            SELECT
                strftime('%H', created_at, '+8 hours') AS hour,
                CASE
                    WHEN CAST(strftime('%M', created_at, '+8 hours') AS INTEGER) < 30 THEN '00'
                    ELSE '30'
                END AS minute,
                COUNT(*) AS order_count
            FROM orders
            WHERE status != 'cancelled'
                AND created_at >= ? AND created_at < ?
            GROUP BY hour, minute
            ORDER BY order_count DESC, hour ASC, minute ASC
            LIMIT 8
            """,
            (month_timestamp, end_timestamp),
        ).fetchall()

    return {
        "generated_at": now.isoformat(timespec="seconds"),
        "timezone": "Asia/Taipei",
        "sales_definition": "非取消訂單總額，包含待付款訂單",
        "sales": {
            "today": sales["today"],
            "week": sales["week"],
            "month": sales["month"],
        },
        "top_products": [dict(row) for row in top_products],
        "popular_times": [
            {"time": f"{row['hour']}:{row['minute']}", "order_count": row["order_count"]}
            for row in popular_times
        ],
    }


app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")