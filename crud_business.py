"""CRUD для business-таблиц (business_connections, mutes, clones, auto_replies)."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

import aiosqlite

from database import crud
from database.db import Database


# ---------- business_connections ----------
async def save_business_connection(
    conn_id: str, owner_id: int, is_enabled: bool,
) -> None:
    db = Database.conn()
    await db.execute(
        """INSERT INTO business_connections
           (business_connection_id, owner_user_id, is_enabled, updated_at)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(business_connection_id) DO UPDATE SET
             owner_user_id=excluded.owner_user_id,
             is_enabled=excluded.is_enabled,
             updated_at=excluded.updated_at""",
        (conn_id, owner_id, 1 if is_enabled else 0, crud.iso(crud.utcnow())),
    )
    await db.commit()


async def get_business_owner(conn_id: str) -> Optional[int]:
    db = Database.conn()
    async with db.execute(
        "SELECT owner_user_id, is_enabled FROM business_connections WHERE business_connection_id=?",
        (conn_id,),
    ) as cur:
        row = await cur.fetchone()
    if not row or not row["is_enabled"]:
        return None
    return int(row["owner_user_id"])


# ---------- mutes ----------
async def set_mute(chat_id: int, user_id: int, until: datetime) -> None:
    db = Database.conn()
    await db.execute(
        """INSERT INTO mutes(chat_id, user_id, until) VALUES (?, ?, ?)
           ON CONFLICT(chat_id, user_id) DO UPDATE SET until=excluded.until""",
        (chat_id, user_id, crud.iso(until)),
    )
    await db.commit()


async def clear_mute(chat_id: int, user_id: int) -> None:
    db = Database.conn()
    await db.execute(
        "DELETE FROM mutes WHERE chat_id=? AND user_id=?", (chat_id, user_id)
    )
    await db.commit()


async def is_muted(chat_id: int, user_id: int) -> bool:
    db = Database.conn()
    async with db.execute(
        "SELECT until FROM mutes WHERE chat_id=? AND user_id=?",
        (chat_id, user_id),
    ) as cur:
        row = await cur.fetchone()
    if not row:
        return False
    until_dt = crud.parse_iso(row["until"])
    if not until_dt or until_dt <= crud.utcnow():
        await clear_mute(chat_id, user_id)
        return False
    return True


async def get_muted_until(chat_id: int, user_id: int) -> Optional[datetime]:
    db = Database.conn()
    async with db.execute(
        "SELECT until FROM mutes WHERE chat_id=? AND user_id=?",
        (chat_id, user_id),
    ) as cur:
        row = await cur.fetchone()
    return crud.parse_iso(row["until"]) if row else None


# ---------- clones ----------
async def enable_clone(chat_id: int, owner_id: int) -> None:
    db = Database.conn()
    await db.execute(
        """INSERT INTO clones(chat_id, owner_user_id) VALUES (?, ?)
           ON CONFLICT(chat_id) DO UPDATE SET owner_user_id=excluded.owner_user_id""",
        (chat_id, owner_id),
    )
    await db.commit()


async def disable_clone(chat_id: int) -> None:
    db = Database.conn()
    await db.execute("DELETE FROM clones WHERE chat_id=?", (chat_id,))
    await db.commit()


async def get_clone_owner(chat_id: int) -> Optional[int]:
    db = Database.conn()
    async with db.execute(
        "SELECT owner_user_id FROM clones WHERE chat_id=?", (chat_id,)
    ) as cur:
        row = await cur.fetchone()
    return int(row["owner_user_id"]) if row else None


# ---------- auto_replies ----------
async def set_auto_reply(owner_id: int, text: str, is_active: bool = True) -> None:
    db = Database.conn()
    await db.execute(
        """INSERT INTO auto_replies(owner_user_id, text, is_active, updated_at)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(owner_user_id) DO UPDATE SET
             text=excluded.text,
             is_active=excluded.is_active,
             updated_at=excluded.updated_at""",
        (owner_id, text, 1 if is_active else 0, crud.iso(crud.utcnow())),
    )
    await db.commit()


async def disable_auto_reply(owner_id: int) -> None:
    db = Database.conn()
    await db.execute(
        "UPDATE auto_replies SET is_active=0, updated_at=? WHERE owner_user_id=?",
        (crud.iso(crud.utcnow()), owner_id),
    )
    await db.commit()


async def get_auto_reply(owner_id: int) -> Optional[aiosqlite.Row]:
    db = Database.conn()
    async with db.execute(
        "SELECT * FROM auto_replies WHERE owner_user_id=?", (owner_id,)
    ) as cur:
        return await cur.fetchone()
