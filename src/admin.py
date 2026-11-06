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
    return {"items": [dict(row) for row in rows]}


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
    status: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=200),
    _: str = Depends(require_admin),
) -> dict[str, list[dict[str, object]]]:
    allowed_statuses = {"received", "preparing", "ready", "completed", "cancelled"}
    if status is not None and status not in allowed_statuses:
        raise HTTPException(status_code=422, detail="Invalid order status.")

    with closing(sqlite3.connect(DB_PATH)) as connection:
        connection.row_factory = sqlite3.Row
        if status is None:
            orders = connection.execute(
                "SELECT * FROM orders ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        else:
            orders = connection.execute(
                "SELECT * FROM orders WHERE status = ? ORDER BY created_at DESC LIMIT ?",
                (status, limit),
            ).fetchall()
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
        with connection:
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
    return {"competitors": [dict(row) for row in rows]}


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
    return {"id": competitor_id}
