import calendar
import sqlite3
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi import HTTPException

TAIPEI = ZoneInfo("Asia/Taipei")


def timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def expiry_date(value: datetime, months: int) -> datetime:
    local = value.astimezone(TAIPEI)
    month_index = local.year * 12 + local.month - 1 + months
    year, month = divmod(month_index, 12)
    month += 1
    day = min(local.day, calendar.monthrange(year, month)[1])
    return local.replace(year=year, month=month, day=day).astimezone(timezone.utc)


def active_rule(connection: sqlite3.Connection, now: str) -> sqlite3.Row:
    rule = connection.execute(
        "SELECT * FROM loyalty_rules WHERE effective_at <= ? ORDER BY effective_at DESC LIMIT 1",
        (now,),
    ).fetchone()
    if rule is None:
        raise HTTPException(status_code=503, detail="紅利規則尚未設定。")
    return rule


def add_transaction(
    connection: sqlite3.Connection, member_id: str, kind: str, delta: int,
    key: str, now: str, order_id: str | None = None,
    rule_id: str | None = None, related_id: str | None = None,
) -> str:
    transaction_id = uuid4().hex
    connection.execute(
        """INSERT INTO point_transactions
           (id, member_id, order_id, rule_id, kind, points_delta,
            related_transaction_id, idempotency_key, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (transaction_id, member_id, order_id, rule_id, kind, delta, related_id, key, now),
    )
    return transaction_id


def expire_points(connection: sqlite3.Connection, member_id: str, now: str) -> None:
    lots = connection.execute(
        """SELECT id, remaining_points, source_transaction_id FROM point_lots
           WHERE member_id = ? AND expires_at <= ? AND remaining_points > 0""",
        (member_id, now),
    ).fetchall()
    for lot in lots:
        add_transaction(
            connection, member_id, "expire", -lot["remaining_points"],
            f"expire:{lot['id']}", now, related_id=lot["source_transaction_id"],
        )
        connection.execute("UPDATE point_lots SET remaining_points = 0 WHERE id = ?", (lot["id"],))


def redeem_points(
    connection: sqlite3.Connection, member_id: str, order_id: str,
    points: int, total: int, now: str,
) -> tuple[int, str | None]:
    if not points:
        return 0, None
    rule = active_rule(connection, now)
    if points % rule["redeem_points"]:
        raise HTTPException(status_code=422, detail="折抵點數須為 100 點的倍數。")
    discount = points // rule["redeem_points"] * rule["redeem_amount"]
    if discount > total:
        raise HTTPException(status_code=422, detail="折抵金額不可超過訂單總額。")
    expire_points(connection, member_id, now)
    lots = connection.execute(
        """SELECT id, remaining_points FROM point_lots
           WHERE member_id = ? AND expires_at > ? AND remaining_points > 0
           ORDER BY expires_at, id""",
        (member_id, now),
    ).fetchall()
    if sum(lot["remaining_points"] for lot in lots) < points:
        raise HTTPException(status_code=422, detail="可用點數不足。")
    transaction_id = add_transaction(
        connection, member_id, "redeem", -points, f"redeem:{order_id}",
        now, order_id, rule["id"],
    )
    remaining = points
    for lot in lots:
        used = min(remaining, lot["remaining_points"])
        if not used:
            break
        connection.execute("UPDATE point_lots SET remaining_points = remaining_points - ? WHERE id = ?", (used, lot["id"]))
        connection.execute(
            "INSERT INTO point_redemption_allocations (transaction_id, lot_id, member_id, points) VALUES (?, ?, ?, ?)",
            (transaction_id, lot["id"], member_id, used),
        )
        remaining -= used
    return discount, transaction_id


def update_member_order(
    connection: sqlite3.Connection, order: sqlite3.Row, status: str, payment: str, now_value: datetime,
) -> None:
    member_id = order["member_id"]
    if member_id is None:
        return
    now = timestamp(now_value)
    if (order["status"] == "cancelled" and status != "cancelled") or (
        order["payment_status"] == "refunded" and payment != "refunded"
    ):
        raise HTTPException(status_code=409, detail="已取消或退款的會員訂單不可重新開啟。")
    if order["payment_status"] == "paid" and payment == "unpaid":
        raise HTTPException(status_code=409, detail="已付款訂單請使用退款狀態。")
    if status == "cancelled" or payment == "refunded":
        reverse_order_points(connection, order["id"], member_id, now)
        return
    was_eligible = order["status"] == "completed" and order["payment_status"] == "paid"
    eligible = status == "completed" and payment == "paid"
    if was_eligible and not eligible:
        raise HTTPException(status_code=409, detail="已完成付款的會員訂單請透過取消或退款處理。")
    if eligible and not was_eligible:
        rule = active_rule(connection, now)
        amount = order["payable_amount"]
        if amount is None:
            raise HTTPException(status_code=409, detail="訂單應付金額缺失，無法累點。")
        earned = amount // rule["earn_amount"] * rule["earn_points"]
        if earned:
            transaction_id = add_transaction(
                connection, member_id, "earn", earned, f"earn:{order['id']}",
                now, order["id"], rule["id"],
            )
            connection.execute(
                """INSERT INTO point_lots
                   (id, member_id, source_transaction_id, initial_points, remaining_points, expires_at, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (uuid4().hex, member_id, transaction_id, earned, earned,
                 timestamp(expiry_date(now_value, rule["expiry_months"])), now),
            )


def reverse_order_points(connection: sqlite3.Connection, order_id: str, member_id: str, now: str) -> None:
    transactions = connection.execute(
        """SELECT * FROM point_transactions WHERE order_id = ? AND member_id = ?
           AND kind IN ('earn', 'redeem')
           AND NOT EXISTS (SELECT 1 FROM point_transactions r
                           WHERE r.related_transaction_id = point_transactions.id AND r.kind = 'reversal')""",
        (order_id, member_id),
    ).fetchall()
    for transaction in transactions:
        if transaction["kind"] == "earn":
            lot = connection.execute(
                "SELECT * FROM point_lots WHERE source_transaction_id = ?", (transaction["id"],)
            ).fetchone()
            if lot is None or lot["expires_at"] <= now or lot["remaining_points"] != lot["initial_points"]:
                raise HTTPException(status_code=409, detail="累積點數已使用或到期，請聯絡店家處理。")
            connection.execute("UPDATE point_lots SET remaining_points = 0 WHERE id = ?", (lot["id"],))
        else:
            allocations = connection.execute(
                """SELECT a.points, l.id, l.expires_at, l.initial_points, l.remaining_points
                   FROM point_redemption_allocations a JOIN point_lots l ON l.id = a.lot_id
                   WHERE a.transaction_id = ?""",
                (transaction["id"],),
            ).fetchall()
            if sum(row["points"] for row in allocations) != -transaction["points_delta"]:
                raise HTTPException(status_code=409, detail="折抵紀錄不完整，請聯絡店家處理。")
            for allocation in allocations:
                if allocation["expires_at"] <= now or allocation["remaining_points"] + allocation["points"] > allocation["initial_points"]:
                    raise HTTPException(status_code=409, detail="折抵點數批次已到期或無法退還，請聯絡店家處理。")
                connection.execute(
                    "UPDATE point_lots SET remaining_points = remaining_points + ? WHERE id = ?",
                    (allocation["points"], allocation["id"]),
                )
        add_transaction(
            connection, member_id, "reversal", -transaction["points_delta"],
            f"reverse:{transaction['id']}", now, order_id, transaction["rule_id"], transaction["id"],
        )


def points_summary(connection: sqlite3.Connection, member_id: str, now_value: datetime) -> dict[str, object]:
    now = timestamp(now_value)
    expire_points(connection, member_id, now)
    balance = connection.execute(
        "SELECT COALESCE(SUM(remaining_points), 0) FROM point_lots WHERE member_id = ? AND expires_at > ?",
        (member_id, now),
    ).fetchone()[0]
    soon = timestamp(now_value + timedelta(days=30))
    expiring = connection.execute(
        """SELECT expires_at, SUM(remaining_points) AS points FROM point_lots
           WHERE member_id = ? AND expires_at > ? AND expires_at <= ? AND remaining_points > 0
           GROUP BY expires_at ORDER BY expires_at""",
        (member_id, now, soon),
    ).fetchall()
    return {"available_points": balance, "expiring": [dict(row) for row in expiring]}


def point_transactions(
    connection: sqlite3.Connection, member_id: str, limit: int, offset: int,
) -> tuple[list[dict[str, object]], bool]:
    rows = connection.execute(
        """SELECT id, order_id, kind, points_delta, created_at FROM point_transactions
           WHERE member_id = ? ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?""",
        (member_id, limit + 1, offset),
    ).fetchall()
    return [dict(row) for row in rows[:limit]], len(rows) > limit
