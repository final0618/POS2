from contextlib import asynccontextmanager, closing
import sqlite3
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from src.database import DB_PATH, initialize_database

WEB_DIR = Path(__file__).resolve().parent.parent / "web"


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


app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")