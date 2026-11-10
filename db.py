"""Единая точка доступа к SQLite через aiosqlite."""
from __future__ import annotations

import logging
from typing import Optional

import aiosqlite

from config import settings
from database.models import SCHEMA

logger = logging.getLogger(__name__)


class Database:
    _conn: Optional[aiosqlite.Connection] = None

    @classmethod
    async def init(cls) -> None:
        settings.ensure_dirs()
        cls._conn = await aiosqlite.connect(settings.DB_PATH)
        cls._conn.row_factory = aiosqlite.Row
        await cls._conn.execute("PRAGMA journal_mode=WAL")
        await cls._conn.execute("PRAGMA synchronous=NORMAL")
        await cls._conn.execute("PRAGMA foreign_keys=ON")
        await cls._conn.executescript(SCHEMA)
        await cls._conn.commit()
        logger.info("DB initialized: %s", settings.DB_PATH)

    @classmethod
    async def close(cls) -> None:
        if cls._conn is not None:
            await cls._conn.close()
            cls._conn = None
            logger.info("DB closed")

    @classmethod
    def conn(cls) -> aiosqlite.Connection:
        if cls._conn is None:
            raise RuntimeError("Database не инициализирована. Вызовите Database.init()")
        return cls._conn
