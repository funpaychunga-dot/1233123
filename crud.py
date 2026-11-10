"""CRUD-операции. Все возвращают aiosqlite.Row / list[Row]."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import aiosqlite

from config import settings
from database.db import Database


# ---------- helpers ----------
def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def parse_iso(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


# ---------- USERS ----------
async def get_user(user_id: int) -> Optional[aiosqlite.Row]:
    db = Database.conn()
    async with db.execute("SELECT * FROM users WHERE id = ?", (user_id,)) as cur:
        return await cur.fetchone()


async def get_or_create_user(
    user_id: int,
    username: Optional[str],
    first_name: Optional[str],
    last_name: Optional[str],
) -> aiosqlite.Row:
    db = Database.conn()
    row = await get_user(user_id)
    now = iso(utcnow())

    if row is None:
        trial_until = iso(utcnow() + timedelta(days=settings.TRIAL_DAYS))
        is_admin = 1 if user_id in settings.admin_ids else 0
        await db.execute(
            """INSERT INTO users
               (id, username, first_name, last_name, trial_until, trial_given,
                slots, is_admin, updated_at)
               VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?)""",
            (user_id, username, first_name, last_name, trial_until,
             settings.FREE_COMMAND_SLOTS, is_admin, now),
        )
        await db.commit()
        created = await get_user(user_id)
        assert created is not None
        return created

    await db.execute(
        """UPDATE users SET username=?, first_name=?, last_name=?, updated_at=?
           WHERE id=?""",
        (username, first_name, last_name, now, user_id),
    )
    await db.commit()
    updated = await get_user(user_id)
    assert updated is not None
    return updated


async def set_user_admin(user_id: int, is_admin: bool) -> None:
    db = Database.conn()
    await db.execute("UPDATE users SET is_admin=? WHERE id=?", (1 if is_admin else 0, user_id))
    await db.commit()


async def set_user_banned(user_id: int, is_banned: bool) -> None:
    db = Database.conn()
    await db.execute("UPDATE users SET is_banned=? WHERE id=?", (1 if is_banned else 0, user_id))
    await db.commit()


async def set_subscription(user_id: int, until: datetime) -> None:
    db = Database.conn()
    await db.execute(
        "UPDATE users SET subscription_until=?, updated_at=? WHERE id=?",
        (iso(until), iso(utcnow()), user_id),
    )
    await db.commit()


async def extend_subscription(user_id: int, days: int) -> datetime:
    user = await get_user(user_id)
    assert user is not None
    base = utcnow()
    cur = parse_iso(user["subscription_until"])
    if cur and cur > base:
        base = cur
    new_until = base + timedelta(days=days)
    await set_subscription(user_id, new_until)
    return new_until


async def add_slots(user_id: int, amount: int) -> int:
    user = await get_user(user_id)
    assert user is not None
    new_slots = min(int(user["slots"]) + amount, settings.MAX_COMMAND_SLOTS)
    db = Database.conn()
    await db.execute("UPDATE users SET slots=? WHERE id=?", (new_slots, user_id))
    await db.commit()
    return new_slots


async def count_all_users() -> int:
    db = Database.conn()
    async with db.execute("SELECT COUNT(*) AS c FROM users") as cur:
        row = await cur.fetchone()
    return int(row["c"]) if row else 0


# ---------- USER COMMANDS ----------
async def list_user_commands(user_id: int) -> list[aiosqlite.Row]:
    db = Database.conn()
    async with db.execute(
        "SELECT * FROM user_commands WHERE user_id=? ORDER BY id", (user_id,)
    ) as cur:
        return list(await cur.fetchall())


async def get_user_command(user_id: int, command_name: str) -> Optional[aiosqlite.Row]:
    db = Database.conn()
    async with db.execute(
        "SELECT * FROM user_commands WHERE user_id=? AND command_name=?",
        (user_id, command_name),
    ) as cur:
        return await cur.fetchone()


async def count_user_commands(user_id: int) -> int:
    db = Database.conn()
    async with db.execute(
        "SELECT COUNT(*) AS c FROM user_commands WHERE user_id=?", (user_id,)
    ) as cur:
        row = await cur.fetchone()
    return int(row["c"]) if row else 0


async def add_user_command(
    user_id: int,
    command_name: str,
    source_path: str,
    description: Optional[str] = None,
    version: Optional[str] = None,
    triggers: Optional[list[str]] = None,
    config: Optional[dict[str, Any]] = None,
) -> int:
    db = Database.conn()
    cur = await db.execute(
        """INSERT INTO user_commands
           (user_id, command_name, description, version, triggers,
            source_path, config_json, is_active)
           VALUES (?, ?, ?, ?, ?, ?, ?, 1)""",
        (
            user_id,
            command_name,
            description,
            version,
            json.dumps(triggers or [], ensure_ascii=False),
            source_path,
            json.dumps(config or {}, ensure_ascii=False),
        ),
    )
    await db.commit()
    return int(cur.lastrowid)


async def set_command_active(user_id: int, command_name: str, active: bool) -> None:
    db = Database.conn()
    await db.execute(
        "UPDATE user_commands SET is_active=? WHERE user_id=? AND command_name=?",
        (1 if active else 0, user_id, command_name),
    )
    await db.commit()


async def update_command_config(user_id: int, command_name: str, config: dict[str, Any]) -> None:
    db = Database.conn()
    await db.execute(
        "UPDATE user_commands SET config_json=? WHERE user_id=? AND command_name=?",
        (json.dumps(config, ensure_ascii=False), user_id, command_name),
    )
    await db.commit()


async def delete_user_command(user_id: int, command_name: str) -> None:
    db = Database.conn()
    await db.execute(
        "DELETE FROM user_commands WHERE user_id=? AND command_name=?",
        (user_id, command_name),
    )
    await db.execute(
        "DELETE FROM command_kv WHERE user_id=? AND command_name=?",
        (user_id, command_name),
    )
    await db.commit()


async def find_active_commands_by_trigger(trigger: str) -> list[aiosqlite.Row]:
    db = Database.conn()
    async with db.execute("SELECT * FROM user_commands WHERE is_active=1") as cur:
        rows = await cur.fetchall()
    matches: list[aiosqlite.Row] = []
    for r in rows:
        try:
            triggers = json.loads(r["triggers"] or "[]")
        except json.JSONDecodeError:
            triggers = []
        if trigger in triggers:
            matches.append(r)
    return matches


# ---------- COMMAND KV ----------
async def kv_get(user_id: int, command_name: str, key: str) -> Optional[str]:
    db = Database.conn()
    async with db.execute(
        "SELECT value FROM command_kv WHERE user_id=? AND command_name=? AND key=?",
        (user_id, command_name, key),
    ) as cur:
        row = await cur.fetchone()
    return row["value"] if row else None


async def kv_set(user_id: int, command_name: str, key: str, value: str) -> None:
    db = Database.conn()
    await db.execute(
        """INSERT INTO command_kv(user_id, command_name, key, value)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(user_id, command_name, key) DO UPDATE SET value=excluded.value""",
        (user_id, command_name, key, value),
    )
    await db.commit()


# ---------- SAVED MESSAGES ----------
async def save_saved_message(
    user_id: int,
    chat_id: int,
    kind: str,
    from_user_id: Optional[int],
    from_username: Optional[str],
    from_first_name: Optional[str],
    content: Optional[str] = None,
    media_path: Optional[str] = None,
) -> int:
    db = Database.conn()
    cur = await db.execute(
        """INSERT INTO saved_messages
           (user_id, chat_id, kind, from_user_id, from_username, from_first_name,
            content, media_path)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (user_id, chat_id, kind, from_user_id, from_username, from_first_name,
         content, media_path),
    )
    await db.commit()
    return int(cur.lastrowid)


# ---------- PAYMENTS ----------
async def add_payment(
    user_id: int, provider: str, amount: int, currency: str,
    status: str, payload: Optional[dict[str, Any]] = None,
) -> int:
    db = Database.conn()
    cur = await db.execute(
        """INSERT INTO payments(user_id, provider, amount, currency, status, payload_json)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (user_id, provider, amount, currency, status,
         json.dumps(payload or {}, ensure_ascii=False)),
    )
    await db.commit()
    return int(cur.lastrowid)


async def update_payment_status(payment_id: int, status: str) -> None:
    db = Database.conn()
    await db.execute("UPDATE payments SET status=? WHERE id=?", (status, payment_id))
    await db.commit()


async def list_user_payments(user_id: int, limit: int = 20) -> list[aiosqlite.Row]:
    db = Database.conn()
    async with db.execute(
        "SELECT * FROM payments WHERE user_id=? ORDER BY id DESC LIMIT ?",
        (user_id, limit),
    ) as cur:
        return list(await cur.fetchall())


# ---------- TICKETS ----------
async def create_ticket(user_id: int, text: str) -> int:
    db = Database.conn()
    cur = await db.execute(
        "INSERT INTO tickets(user_id, text) VALUES (?, ?)", (user_id, text)
    )
    await db.commit()
    return int(cur.lastrowid)


async def get_ticket(ticket_id: int) -> Optional[aiosqlite.Row]:
    db = Database.conn()
    async with db.execute("SELECT * FROM tickets WHERE id=?", (ticket_id,)) as cur:
        return await cur.fetchone()


async def answer_ticket(ticket_id: int, response: str) -> None:
    db = Database.conn()
    await db.execute(
        "UPDATE tickets SET status='answered', admin_response=?, answered_at=? WHERE id=?",
        (response, iso(utcnow()), ticket_id),
    )
    await db.commit()


async def list_open_tickets(limit: int = 50) -> list[aiosqlite.Row]:
    db = Database.conn()
    async with db.execute(
        "SELECT * FROM tickets WHERE status='open' ORDER BY id DESC LIMIT ?", (limit,)
    ) as cur:
        return list(await cur.fetchall())


# ---------- PROMOCODES ----------
async def create_promocode(code: str, days: int, max_uses: int = 0) -> int:
    db = Database.conn()
    cur = await db.execute(
        "INSERT INTO promocodes(code, days, max_uses) VALUES (?, ?, ?)",
        (code.upper(), days, max_uses),
    )
    await db.commit()
    return int(cur.lastrowid)


async def get_promocode(code: str) -> Optional[aiosqlite.Row]:
    db = Database.conn()
    async with db.execute(
        "SELECT * FROM promocodes WHERE code=?", (code.upper(),)
    ) as cur:
        return await cur.fetchone()


async def redeem_promocode(code: str, user_id: int) -> tuple[bool, str, Optional[int]]:
    db = Database.conn()
    promo = await get_promocode(code)
    if not promo:
        return False, "Промокод не найден", None
    if promo["max_uses"] and promo["used_count"] >= promo["max_uses"]:
        return False, "Промокод исчерпан", None
    try:
        await db.execute(
            "INSERT INTO promocode_uses(promocode_id, user_id) VALUES (?, ?)",
            (promo["id"], user_id),
        )
    except aiosqlite.IntegrityError:
        return False, "Вы уже использовали этот промокод", None
    await db.execute(
        "UPDATE promocodes SET used_count = used_count + 1 WHERE id=?", (promo["id"],)
    )
    await db.commit()
    return True, "OK", int(promo["days"])


# ---------- RATE LIMITS (persist) ----------
async def rl_get(user_id: int, action: str) -> Optional[aiosqlite.Row]:
    db = Database.conn()
    async with db.execute(
        "SELECT * FROM rate_limits WHERE user_id=? AND action=?", (user_id, action)
    ) as cur:
        return await cur.fetchone()


async def rl_bump(user_id: int, action: str, window_seconds: int) -> int:
    row = await rl_get(user_id, action)
    now = utcnow()
    db = Database.conn()
    if not row:
        await db.execute(
            "INSERT INTO rate_limits(user_id, action, count, window_start) VALUES (?, ?, 1, ?)",
            (user_id, action, iso(now)),
        )
        await db.commit()
        return 1
    ws = parse_iso(row["window_start"]) or now
    if (now - ws).total_seconds() >= window_seconds:
        await db.execute(
            "UPDATE rate_limits SET count=1, window_start=? WHERE user_id=? AND action=?",
            (iso(now), user_id, action),
        )
        await db.commit()
        return 1
    new_count = int(row["count"]) + 1
    await db.execute(
        "UPDATE rate_limits SET count=? WHERE user_id=? AND action=?",
        (new_count, user_id, action),
    )
    await db.commit()
    return new_count


# ---------- UI / texts ----------
async def ui_button_get(button_key: str) -> Optional[aiosqlite.Row]:
    db = Database.conn()
    async with db.execute(
        "SELECT * FROM ui_buttons WHERE button_key=?", (button_key,)
    ) as cur:
        return await cur.fetchone()


async def ui_button_upsert(
    button_key: str, label: Optional[str] = None,
    emoji: Optional[str] = None, custom_emoji_id: Optional[str] = None,
    color: Optional[str] = None,
) -> None:
    db = Database.conn()
    await db.execute(
        """INSERT INTO ui_buttons(button_key, label, emoji, custom_emoji_id, color)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(button_key) DO UPDATE SET
             label=COALESCE(excluded.label, ui_buttons.label),
             emoji=COALESCE(excluded.emoji, ui_buttons.emoji),
             custom_emoji_id=COALESCE(excluded.custom_emoji_id, ui_buttons.custom_emoji_id),
             color=COALESCE(excluded.color, ui_buttons.color)""",
        (button_key, label, emoji, custom_emoji_id, color),
    )
    await db.commit()


async def ui_text_get(key: str) -> Optional[str]:
    db = Database.conn()
    async with db.execute("SELECT value FROM ui_texts WHERE key=?", (key,)) as cur:
        row = await cur.fetchone()
    return row["value"] if row else None


async def ui_text_set(key: str, value: str) -> None:
    db = Database.conn()
    await db.execute(
        """INSERT INTO ui_texts(key, value) VALUES (?, ?)
           ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
        (key, value),
    )
    await db.commit()


# ---------- METRICS ----------
async def log_metrics(cpu: float, ram_used: float, disk_used: float, queue_len: int) -> None:
    db = Database.conn()
    await db.execute(
        "INSERT INTO metrics_log(cpu, ram_used, disk_used, queue_len) VALUES (?, ?, ?, ?)",
        (cpu, ram_used, disk_used, queue_len),
    )
    await db.commit()


# ---------- AUDIT ----------
async def audit(user_id: Optional[int], action: str, details: Optional[str] = None) -> None:
    db = Database.conn()
    await db.execute(
        "INSERT INTO audit_log(user_id, action, details) VALUES (?, ?, ?)",
        (user_id, action, details),
    )
    await db.commit()


# ---------- STATS ----------
async def stats_overview() -> dict[str, int]:
    db = Database.conn()
    now = iso(utcnow())
    out: dict[str, int] = {}

    async def count(sql: str, *args: Any) -> int:
        async with db.execute(sql, args) as cur:
            row = await cur.fetchone()
        return int(row[0]) if row else 0

    out["users_total"] = await count("SELECT COUNT(*) FROM users")
    out["users_banned"] = await count("SELECT COUNT(*) FROM users WHERE is_banned=1")
    out["active_subs"] = await count(
        "SELECT COUNT(*) FROM users WHERE subscription_until IS NOT NULL AND subscription_until > ?",
        now,
    )
    out["on_trial"] = await count(
        "SELECT COUNT(*) FROM users WHERE trial_until > ? AND (subscription_until IS NULL OR subscription_until <= ?)",
        now, now,
    )
    out["paid_users"] = await count(
        "SELECT COUNT(DISTINCT user_id) FROM payments WHERE status='succeeded'"
    )
    out["open_tickets"] = await count("SELECT COUNT(*) FROM tickets WHERE status='open'")
    out["commands_total"] = await count("SELECT COUNT(*) FROM user_commands")
    return out
