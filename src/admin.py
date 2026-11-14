from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import sqlite3
import time
from contextlib import closing
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from src.database import DB_PATH
from src.loyalty import now_utc, point_transactions, points_summary, timestamp, update_member_order

router = APIRouter(prefix="/api/admin", tags=["admin"])
COOKIE_NAME = "gmc_admin_session"
SESSION_TTL_SECONDS = 8 * 60 * 60
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
ADMIN_SESSION_SECRET = os.getenv("ADMIN_SESSION_SECRET", "")


class AdminCredentials(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=256)


class MenuItemPayload(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=120)
    category: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=1, max_length=500)
    price: int = Field(ge=0, le=1000000)
    badge: str = Field(min_length=1, max_length=40)
    image_url: str = Field(min_length=1, max_length=2048)
    alt_text: str = Field(min_length=1, max_length=240)
    is_available: bool = True


class OrderUpdatePayload(BaseModel):
    status: Literal["received", "preparing", "ready", "completed", "cancelled"] | None = None
    payment_status: Literal["unpaid", "paid", "refunded"] | None = None


class CompetitorPayload(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=160)
    category: str = Field(min_length=1, max_length=80)
    address: str = Field(min_length=1, max_length=240)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    rating: float | None = Field(default=None, ge=0, le=5)
    review_count: int | None = Field(default=None, ge=0)
    business_hours: str | None = Field(default=None, max_length=500)
    phone: str | None = Field(default=None, max_length=40)
    website_url: str | None = Field(default=None, max_length=2048)
    source_url: str = Field(min_length=1, max_length=2048)
    source_checked_at: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    notes: str = Field(default="", max_length=1000)
    is_active: bool = True
    prices: dict[str, int | None] = Field(default_factory=dict)


def _save_competitor_prices(
    connection: sqlite3.Connection, competitor_id: str, prices: dict[str, int | None]
) -> None:
    known = {row[0] for row in connection.execute("SELECT id FROM menu_items")}
    if any(menu_id not in known or (price is not None and price < 0) for menu_id, price in prices.items()):
        raise HTTPException(status_code=422, detail="競品價格對應的餐點不存在或價格不正確。")
    existing = {row[0] for row in connection.execute(
        "SELECT menu_item_id FROM competitor_prices WHERE competitor_id = ?", (competitor_id,)
    )}
    for menu_id in existing - {key for key, price in prices.items() if price is not None}:
        connection.execute(
            "DELETE FROM competitor_prices WHERE competitor_id = ? AND menu_item_id = ?",
            (competitor_id, menu_id),
        )
    connection.executemany(
        """INSERT INTO competitor_prices (competitor_id, menu_item_id, price) VALUES (?, ?, ?)
           ON CONFLICT(competitor_id, menu_item_id) DO UPDATE SET
               product_name = CASE WHEN price = excluded.price THEN product_name ELSE NULL END,
               price_source_url = CASE WHEN price = excluded.price THEN price_source_url ELSE NULL END,
               price_checked_at = CASE WHEN price = excluded.price THEN price_checked_at ELSE NULL END,
               price_notes = CASE WHEN price = excluded.price THEN price_notes ELSE NULL END,
               price = excluded.price""",
        [(competitor_id, menu_id, price) for menu_id, price in prices.items() if price is not None],
    )


def _sign_session(username: str, expires_at: int) -> str:
    payload = f"{username}|{expires_at}|{secrets.token_urlsafe(12)}".encode("utf-8")
    encoded = base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")
    signature = hmac.new(ADMIN_SESSION_SECRET.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{encoded}.{signature}"


def require_admin(request: Request) -> str:
    if not ADMIN_USERNAME or not ADMIN_PASSWORD or not ADMIN_SESSION_SECRET:
        raise HTTPException(status_code=503, detail="Admin credentials are not configured.")

    token = request.cookies.get(COOKIE_NAME, "")
    try:
        encoded, signature = token.rsplit(".", 1)
        expected = hmac.new(ADMIN_SESSION_SECRET.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError("Invalid signature")
        padded = encoded + "=" * (-len(encoded) % 4)
        username, expires_at, _ = base64.urlsafe_b64decode(padded).decode("utf-8").split("|", 2)
        if username != ADMIN_USERNAME or int(expires_at) < int(time.time()):
            raise ValueError("Expired session")
    except (ValueError, UnicodeDecodeError, TypeError):
        raise HTTPException(status_code=401, detail="Admin authentication required.") from None

    return username


@router.get("/session")
def get_session(request: Request) -> dict[str, object]:
    configured = bool(ADMIN_USERNAME and ADMIN_PASSWORD and ADMIN_SESSION_SECRET)
    if not configured:
        return {"configured": False, "authenticated": False}
    try:
        username = require_admin(request)
    except HTTPException as error:
        if error.status_code != 401:
            raise
        return {"configured": True, "authenticated": False}
    return {"configured": True, "authenticated": True, "username": username}


@router.post("/login")
def login(credentials: AdminCredentials, request: Request, response: Response) -> dict[str, str]:
    if not ADMIN_USERNAME or not ADMIN_PASSWORD or not ADMIN_SESSION_SECRET:
        raise HTTPException(status_code=503, detail="Admin credentials are not configured.")
    username_matches = secrets.compare_digest(credentials.username, ADMIN_USERNAME)
    password_matches = secrets.compare_digest(credentials.password, ADMIN_PASSWORD)
    if not username_matches or not password_matches:
        raise HTTPException(status_code=401, detail="帳號或密碼錯誤。")

    response.set_cookie(
        key=COOKIE_NAME,
        value=_sign_session(ADMIN_USERNAME, int(time.time()) + SESSION_TTL_SECONDS),
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="strict",
        path="/api/admin",
    )
    return {"username": ADMIN_USERNAME}


@router.post("/logout")
def logout(response: Response) -> dict[str, str]:
    response.delete_cookie(COOKIE_NAME, path="/api/admin", samesite="strict")
    return {"text": "OK"}


@router.get("/menu")
def get_admin_menu(_: str = Depends(require_admin)) -> dict[str, list[dict[str, object]]]:
    with closing(sqlite3.connect(DB_PATH)) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """
            SELECT id, name, category, description, price, badge,
                   image_url, alt_text, is_available
            FROM menu_items
            ORDER BY category, rowid
            """
        ).fetchall()
        price_rows = connection.execute(
            """SELECT p.menu_item_id, p.price, p.product_name, p.price_source_url,
                      p.price_checked_at, p.price_notes, c.name AS competitor_name
               FROM competitor_prices p JOIN competitors c ON c.id = p.competitor_id
               WHERE c.is_active = 1 ORDER BY c.name"""
        ).fetchall()
    comparisons: dict[str, list[dict[str, object]]] = {}
    for price in price_rows:
        comparison = dict(price)
        menu_id = str(comparison.pop("menu_item_id"))
        comparisons.setdefault(menu_id, []).append(comparison)
    items = []
    for row in rows:
        samples = comparisons.get(row["id"], [])
        total = sum(int(sample["price"]) for sample in samples)
        recommended = (2 * total + len(samples)) // (2 * len(samples)) if samples else None
        items.append({**dict(row), "price_comparisons": samples, "recommended_price": recommended})
    return {"items": items}


@router.post("/menu", status_code=201)
def create_menu_item(payload: MenuItemPayload, _: str = Depends(require_admin)) -> dict[str, object]:
    try:
        with closing(sqlite3.connect(DB_PATH)) as connection:
            with connection:
                connection.execute(
                    """
                    INSERT INTO menu_items (
                        id, name, category, description, price, badge,
                        image_url, alt_text, is_available
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        payload.id, payload.name.strip(), payload.category.strip(),
                        payload.description.strip(), payload.price, payload.badge.strip(),
                        payload.image_url.strip(), payload.alt_text.strip(), int(payload.is_available),
                    ),
                )
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="餐點 ID 已存在。") from None
    return {"id": payload.id}


@router.put("/menu/{menu_item_id}")
def update_menu_item(
    menu_item_id: str,
    payload: MenuItemPayload,
    _: str = Depends(require_admin),
) -> dict[str, str]:
    if menu_item_id != payload.id:
        raise HTTPException(status_code=422, detail="餐點 ID 不可在編輯時變更。")
    with closing(sqlite3.connect(DB_PATH)) as connection:
        with connection:
            cursor = connection.execute(
                """
                UPDATE menu_items
                SET name = ?, category = ?, description = ?, price = ?, badge = ?,
                    image_url = ?, alt_text = ?, is_available = ?
                WHERE id = ?
                """,
                (
                    payload.name.strip(), payload.category.strip(), payload.description.strip(),
                    payload.price, payload.badge.strip(), payload.image_url.strip(),
                    payload.alt_text.strip(), int(payload.is_available), menu_item_id,
                ),
            )
            if cursor.rowcount == 0:
                raise HTTPException(status_code=404, detail="找不到此餐點。")
    return {"id": menu_item_id}


@router.get("/orders")
def get_admin_orders(
    table_number: str | None = Query(default=None),
    status: str | None = Query(default=None),
    payment_status: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=200),
    _: str = Depends(require_admin),
) -> dict[str, list[dict[str, object]]]:
    allowed_statuses = {"received", "preparing", "ready", "completed", "cancelled"}
    allowed_payment_statuses = {"unpaid", "paid", "refunded"}
    allowed_table_numbers = {f"{number:02d}" for number in range(1, 13)}
    if table_number is not None and table_number not in allowed_table_numbers:
        raise HTTPException(status_code=422, detail="Invalid table number.")
    if status is not None and status not in allowed_statuses:
        raise HTTPException(status_code=422, detail="Invalid order status.")
    if payment_status is not None and payment_status not in allowed_payment_statuses:
        raise HTTPException(status_code=422, detail="Invalid payment status.")

    filters = []
    parameters: list[str | int] = []
    if table_number is not None:
        filters.append("table_number = ?")
        parameters.append(table_number)
    if status is not None:
        filters.append("status = ?")
        parameters.append(status)
    if payment_status is not None:
        filters.append("payment_status = ?")
        parameters.append(payment_status)
    query = "SELECT * FROM orders"
    if filters:
        query += " WHERE " + " AND ".join(filters)
    query += " ORDER BY created_at DESC LIMIT ?"
    parameters.append(limit)
    with closing(sqlite3.connect(DB_PATH)) as connection:
        connection.row_factory = sqlite3.Row
        orders = connection.execute(query, parameters).fetchall()
        result = []
        for order in orders:
            items = connection.execute(
                """
                SELECT menu_item_id, item_name AS name, unit_price, quantity, subtotal
                FROM order_items WHERE order_id = ? ORDER BY rowid
                """,
                (order["id"],),
            ).fetchall()
            result.append({**dict(order), "items": [dict(item) for item in items]})

    return {"orders": result}


@router.get("/members")
def get_admin_members(
    response: Response,
    query: str = Query(default="", max_length=80),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    _: str = Depends(require_admin),
) -> dict[str, object]:
    response.headers["Cache-Control"] = "no-store"
    search = query.strip()
    with closing(sqlite3.connect(DB_PATH)) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """SELECT m.id, m.phone, m.name, m.status, m.created_at,
                      COALESCE((SELECT SUM(l.remaining_points) FROM point_lots l
                                WHERE l.member_id = m.id AND l.expires_at > ?), 0) AS available_points
               FROM members m
               WHERE instr(m.phone, ?) > 0 OR instr(COALESCE(m.name, ''), ?) > 0
               ORDER BY m.created_at DESC, m.id DESC LIMIT ? OFFSET ?""",
            (timestamp(now_utc()), search, search, limit + 1, offset),
        ).fetchall()
    return {"members": [dict(row) for row in rows[:limit]], "has_more": len(rows) > limit}


@router.get("/members/{member_id}/transactions")
def get_admin_member_transactions(
    member_id: str,
    response: Response,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    _: str = Depends(require_admin),
) -> dict[str, object]:
    response.headers["Cache-Control"] = "no-store"
    with closing(sqlite3.connect(DB_PATH)) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("BEGIN IMMEDIATE")
        member = connection.execute(
            "SELECT id, phone, name, status, created_at FROM members WHERE id = ?", (member_id,)
        ).fetchone()
        if member is None:
            raise HTTPException(status_code=404, detail="找不到此會員。")
        summary = points_summary(connection, member_id, now_utc())
        transactions, has_more = point_transactions(connection, member_id, limit, offset)
        connection.commit()
    return {"member": {**dict(member), **summary}, "transactions": transactions, "has_more": has_more}


@router.patch("/orders/{order_id}")
def update_order(
    order_id: str,
    payload: OrderUpdatePayload,
    _: str = Depends(require_admin),
) -> dict[str, str]:
    updates = payload.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=422, detail="至少提供一個要更新的欄位。")

    assignments = ", ".join(f"{field} = ?" for field in updates)
    values = [*updates.values(), order_id]
    with closing(sqlite3.connect(DB_PATH)) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        with connection:
            connection.execute("BEGIN IMMEDIATE")
            order = connection.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
            if order is None:
                raise HTTPException(status_code=404, detail="找不到此訂單。")
            update_member_order(
                connection, order, updates.get("status", order["status"]),
                updates.get("payment_status", order["payment_status"]), now_utc(),
            )
            cursor = connection.execute(
                f"UPDATE orders SET {assignments} WHERE id = ?", values
            )
            if cursor.rowcount == 0:
                raise HTTPException(status_code=404, detail="找不到此訂單。")
    return {"id": order_id, **updates}


@router.get("/competitors")
def get_competitors(
    query: str | None = Query(default=None, max_length=160),
    _: str = Depends(require_admin),
) -> dict[str, list[dict[str, object]]]:
    with closing(sqlite3.connect(DB_PATH)) as connection:
        connection.row_factory = sqlite3.Row
        menu = [
            dict(row)
            for row in connection.execute("SELECT id, name FROM menu_items ORDER BY rowid")
        ]
        price_rows = connection.execute(
            "SELECT competitor_id, menu_item_id, price FROM competitor_prices"
        ).fetchall()
        if query and query.strip():
            search = f"%{query.strip()}%"
            rows = connection.execute(
                """
                SELECT * FROM competitors
                WHERE name LIKE ? OR address LIKE ? OR category LIKE ?
                ORDER BY category, name
                """,
                (search, search, search),
            ).fetchall()
        else:
            rows = connection.execute(
                "SELECT * FROM competitors ORDER BY is_active DESC, category, name"
            ).fetchall()
    prices: dict[str, dict[str, int]] = {}
    for row in price_rows:
        prices.setdefault(row["competitor_id"], {})[row["menu_item_id"]] = row["price"]
    return {
        "menu_items": menu,
        "competitors": [{**dict(row), "prices": prices.get(row["id"], {})} for row in rows],
    }


@router.post("/competitors", status_code=201)
def create_competitor(
    payload: CompetitorPayload,
    _: str = Depends(require_admin),
) -> dict[str, str]:
    try:
        with closing(sqlite3.connect(DB_PATH)) as connection:
            with connection:
                connection.execute(
                    """
                    INSERT INTO competitors (
                        id, name, category, address, latitude, longitude, rating,
                        review_count, business_hours, phone, website_url, source_url,
                        source_checked_at, notes, is_active
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        payload.id, payload.name.strip(), payload.category.strip(),
                        payload.address.strip(), payload.latitude, payload.longitude,
                        payload.rating, payload.review_count, payload.business_hours,
                        payload.phone, payload.website_url, payload.source_url,
                        payload.source_checked_at, payload.notes.strip(), int(payload.is_active),
                    ),
                )
                _save_competitor_prices(connection, payload.id, payload.prices)
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="競品 ID 已存在。") from None
    return {"id": payload.id}


@router.put("/competitors/{competitor_id}")
def update_competitor(
    competitor_id: str,
    payload: CompetitorPayload,
    _: str = Depends(require_admin),
) -> dict[str, str]:
    if competitor_id != payload.id:
        raise HTTPException(status_code=422, detail="競品 ID 不可在編輯時變更。")
    with closing(sqlite3.connect(DB_PATH)) as connection:
        with connection:
            cursor = connection.execute(
                """
                UPDATE competitors
                SET name = ?, category = ?, address = ?, latitude = ?, longitude = ?,
                    rating = ?, review_count = ?, business_hours = ?, phone = ?,
                    website_url = ?, source_url = ?, source_checked_at = ?, notes = ?,
                    is_active = ?
                WHERE id = ?
                """,
                (
                    payload.name.strip(), payload.category.strip(), payload.address.strip(),
                    payload.latitude, payload.longitude, payload.rating, payload.review_count,
                    payload.business_hours, payload.phone, payload.website_url, payload.source_url,
                    payload.source_checked_at, payload.notes.strip(), int(payload.is_active),
                    competitor_id,
                ),
            )
            if cursor.rowcount == 0:
                raise HTTPException(status_code=404, detail="找不到此競品資料。")
            _save_competitor_prices(connection, competitor_id, payload.prices)
    return {"id": competitor_id}
