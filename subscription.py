"""Проверка подписки/триала + обязательные каналы."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

from database import crud
from database.db import Database

logger = logging.getLogger(__name__)


@dataclass
class SubscriptionStatus:
    user_id: int
    has_access: bool
    is_trial: bool
    is_paid: bool
    is_expired: bool
    expires_at: Optional[datetime]
    days_left: int

    def to_text(self) -> str:
        if not self.has_access:
            return "Подписка истекла"
        kind = "Триал" if self.is_trial else "Подписка"
        date = self.expires_at.strftime("%d.%m.%Y") if self.expires_at else "—"
        return f"{kind}: {self.days_left} дн. (до {date})"


class SubscriptionService:
    async def get_status(self, user_id: int) -> SubscriptionStatus:
        user = await crud.get_user(user_id)
        if user is None:
            return SubscriptionStatus(
                user_id=user_id, has_access=False, is_trial=False,
                is_paid=False, is_expired=True, expires_at=None, days_left=0,
            )
        now = crud.utcnow()
        sub_dt = crud.parse_iso(user["subscription_until"])
        trial_dt = crud.parse_iso(user["trial_until"])

        is_paid = bool(sub_dt and sub_dt > now)
        is_trial = bool(trial_dt and trial_dt > now and not is_paid)
        expires_at = sub_dt if is_paid else (trial_dt if is_trial else None)
        is_expired = not (is_paid or is_trial)
        days_left = 0
        if expires_at:
            days_left = max(0, (expires_at - now).days)
        return SubscriptionStatus(
            user_id=user_id,
            has_access=is_paid or is_trial,
            is_trial=is_trial,
            is_paid=is_paid,
            is_expired=is_expired,
            expires_at=expires_at,
            days_left=days_left,
        )

    async def is_active(self, user_id: int) -> bool:
        status = await self.get_status(user_id)
        return status.has_access


subscription_service = SubscriptionService()


async def check_required_channels(bot: Bot, user_id: int) -> list[dict]:
    """Возвращает список активных обязательных каналов, где юзер НЕ подписан."""
    db = Database.conn()
    async with db.execute(
        "SELECT * FROM required_channels WHERE is_active=1"
    ) as cur:
        rows = list(await cur.fetchall())

    missing: list[dict] = []
    for row in rows:
        chat_id = row["chat_id"]
        try:
            member = await bot.get_chat_member(chat_id=chat_id, user_id=user_id)
        except TelegramAPIError as e:
            logger.warning("get_chat_member(%s, %s): %s", chat_id, user_id, e)
            continue
        if member.status in ("left", "kicked"):
            missing.append({
                "chat_id": chat_id,
                "title": row["title"] or chat_id,
                "invite_link": row["invite_link"],
            })
    return missing
