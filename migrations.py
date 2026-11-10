"""Идемпотентные миграции для таблиц Части 3 (business/mutes/clones/auto_replies)."""
from __future__ import annotations

import asyncio
import logging

from database.db import Database

logger = logging.getLogger(__name__)

_LOCK = asyncio.Lock()
_APPLIED = False

PART3_SCHEMA = """
CREATE TABLE IF NOT EXISTS business_connections (
    business_connection_id TEXT PRIMARY KEY,
    owner_user_id         INTEGER NOT NULL,
    is_enabled            INTEGER NOT NULL DEFAULT 1,
    updated_at            TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS mutes (
    chat_id    INTEGER NOT NULL,
    user_id    INTEGER NOT NULL,
    until      TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY(chat_id, user_id)
);

CREATE TABLE IF NOT EXISTS clones (
    chat_id       INTEGER PRIMARY KEY,
    owner_user_id INTEGER NOT NULL,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS auto_replies (
    owner_user_id INTEGER PRIMARY KEY,
    text          TEXT NOT NULL,
    is_active     INTEGER NOT NULL DEFAULT 1,
    updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


async def apply_migrations() -> None:
    global _APPLIED
    if _APPLIED:
        return
    async with _LOCK:
        if _APPLIED:
            return
        db = Database.conn()
        await db.executescript(PART3_SCHEMA)
        await db.commit()
        _APPLIED = True
        logger.info("Part3 migrations applied")
