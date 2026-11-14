import hashlib
import hmac
import re
import secrets
import sqlite3
import time
from contextlib import closing
from datetime import timedelta
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from src.database import DB_PATH
from src.loyalty import now_utc, point_transactions, points_summary, timestamp

router = APIRouter(prefix="/api/members", tags=["members"])
COOKIE_NAME = "gmc_member_session"
SESSION_SECONDS = 7 * 24 * 60 * 60
SALT_BYTES = 16
LOGIN_WINDOW = 15 * 60
LOGIN_LIMIT = 5
DUMMY_PASSWORD_HASH = f"scrypt$16384$8$1${'00' * SALT_BYTES}${'00' * 32}"


class Credentials(BaseModel):
    phone: str = Field(min_length=1, max_length=30)
    password: str = Field(min_length=10, max_length=128)


def check_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if origin:
        parsed = urlsplit(origin)
        if parsed.scheme != request.url.scheme or parsed.netloc.lower() != request.url.netloc.lower():
            raise HTTPException(status_code=403, detail="不允許跨來源操作。")


def normalize_phone(value: str) -> str:
    phone = re.sub(r"[\s-]", "", value)
    if not re.fullmatch(r"09[0-9]{8}", phone):
        raise HTTPException(status_code=422, detail="請輸入有效的台灣手機號碼。")
    return phone


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(SALT_BYTES)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=16384, r=8, p=1, dklen=32)
    return f"scrypt$16384$8$1${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    parts = stored.split("$")
    if len(parts) != 6 or parts[:4] != ["scrypt", "16384", "8", "1"]:
        raise RuntimeError("Unsupported password hash format")
    salt, expected = bytes.fromhex(parts[4]), bytes.fromhex(parts[5])
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=16384, r=8, p=1, dklen=32)
    return hmac.compare_digest(digest, expected)


def connect() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def member_from_session(connection: sqlite3.Connection, request: Request) -> sqlite3.Row | None:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    row = connection.execute(
        """SELECT m.id, m.phone, m.name FROM members m
           JOIN member_sessions s ON s.member_id = m.id
           WHERE s.token_hash = ? AND s.revoked_at IS NULL AND s.expires_at > ?
           AND m.status = 'active'""",
        (digest, timestamp(now_utc())),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=401, detail="會員登入已失效，請重新登入。")
    return row


def require_member(connection: sqlite3.Connection, request: Request) -> sqlite3.Row:
    member = member_from_session(connection, request)
    if member is None:
        raise HTTPException(status_code=401, detail="請先登入會員。")
    return member


@router.post("/register", status_code=201)
def register(payload: Credentials, request: Request) -> dict[str, str]:
    check_origin(request)
    phone = normalize_phone(payload.phone)
    password_hash = hash_password(payload.password)
    now = timestamp(now_utc())
    with closing(connect()) as connection:
        try:
            with connection:
                connection.execute(
                    "INSERT INTO members (id, phone, password_hash, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                    (uuid4().hex, phone, password_hash, now, now),
                )
        except sqlite3.IntegrityError as error:
            if connection.execute("SELECT 1 FROM members WHERE phone = ?", (phone,)).fetchone():
                raise HTTPException(status_code=409, detail="無法註冊，請確認資料或聯絡店家。") from error
            raise
    return {"message": "註冊完成，請登入。"}


@router.post("/login")
def login(payload: Credentials, request: Request, response: Response) -> dict[str, str]:
    check_origin(request)
    phone = normalize_phone(payload.phone)
    current = int(time.time())
    ip = request.client.host if request.client else "unknown"
    keys = [f"phone:{hashlib.sha256(phone.encode()).hexdigest()}", f"ip:{hashlib.sha256(ip.encode()).hexdigest()}"]
    with closing(connect()) as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("DELETE FROM member_login_attempts WHERE attempted_at <= ?", (current - LOGIN_WINDOW,))
        for key in keys:
            count = connection.execute(
                "SELECT COUNT(*) FROM member_login_attempts WHERE key = ?", (key,)
            ).fetchone()[0]
            if count >= LOGIN_LIMIT:
                connection.commit()
                raise HTTPException(status_code=429, detail="登入嘗試過多，請稍後再試。")
        member = connection.execute("SELECT * FROM members WHERE phone = ?", (phone,)).fetchone()
        password_valid = verify_password(payload.password, member["password_hash"] if member else DUMMY_PASSWORD_HASH)
        if member is None or member["status"] != "active" or not password_valid:
            connection.executemany(
                "INSERT INTO member_login_attempts (key, attempted_at) VALUES (?, ?)",
                [(key, current) for key in keys],
            )
            connection.commit()
            raise HTTPException(status_code=401, detail="手機號碼或密碼錯誤。")
        connection.execute("DELETE FROM member_login_attempts WHERE key = ?", (keys[0],))
        token = secrets.token_urlsafe(32)
        now = now_utc()
        connection.execute(
            "INSERT INTO member_sessions (id, member_id, token_hash, expires_at, created_at) VALUES (?, ?, ?, ?, ?)",
            (uuid4().hex, member["id"], hashlib.sha256(token.encode()).hexdigest(),
             timestamp(now + timedelta(seconds=SESSION_SECONDS)), timestamp(now)),
        )
        connection.commit()
    response.set_cookie(
        COOKIE_NAME, token, max_age=SESSION_SECONDS, httponly=True,
        secure=request.url.scheme == "https", samesite="strict", path="/",
    )
    return {"message": "登入成功。"}


@router.post("/logout")
def logout(request: Request, response: Response) -> dict[str, str]:
    check_origin(request)
    token = request.cookies.get(COOKIE_NAME)
    if token:
        with closing(connect()) as connection, connection:
            connection.execute(
                "UPDATE member_sessions SET revoked_at = ? WHERE token_hash = ? AND revoked_at IS NULL",
                (timestamp(now_utc()), hashlib.sha256(token.encode()).hexdigest()),
            )
    response.delete_cookie(COOKIE_NAME, path="/", samesite="strict")
    return {"message": "已登出。"}


@router.get("/session")
def session(request: Request) -> dict[str, object]:
    with closing(connect()) as connection:
        member = member_from_session(connection, request)
    return {"authenticated": member is not None, "phone": member["phone"][-4:] if member else None}


@router.get("/me/points")
def get_points(request: Request) -> dict[str, object]:
    with closing(connect()) as connection:
        connection.execute("BEGIN IMMEDIATE")
        member = require_member(connection, request)
        result = points_summary(connection, member["id"], now_utc())
        connection.commit()
        return result


@router.get("/me/points/transactions")
def get_transactions(
    request: Request, limit: int = Query(default=20, ge=1, le=100), offset: int = Query(default=0, ge=0),
) -> dict[str, object]:
    with closing(connect()) as connection:
        connection.execute("BEGIN IMMEDIATE")
        member = require_member(connection, request)
        points_summary(connection, member["id"], now_utc())
        transactions, has_more = point_transactions(connection, member["id"], limit, offset)
        connection.commit()
    return {"transactions": transactions, "has_more": has_more}
