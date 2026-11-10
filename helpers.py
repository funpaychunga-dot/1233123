"""Мелкие хелперы, используемые в разных частях."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from aiogram.types import User as TgUser


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def fmt_dt(dt: Optional[datetime]) -> str:
    if not dt:
        return "—"
    return dt.astimezone().strftime("%d.%m.%Y %H:%M")


def user_display(u: TgUser) -> str:
    if u.first_name and u.username:
        return f"{u.first_name} (@{u.username})"
    if u.first_name:
        return u.first_name
    if u.username:
        return f"@{u.username}"
    return str(u.id)


def human_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def mask_secret(s: str, keep: int = 4) -> str:
    if not s:
        return "—"
    if len(s) <= keep * 2:
        return "*" * len(s)
    return s[:keep] + "…" + s[-keep:]
