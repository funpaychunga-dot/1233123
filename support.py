"""Тикеты."""
from __future__ import annotations
import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from config import settings
from database import crud
from utils.helpers import user_display

logger = logging.getLogger(__name__)
router = Router(name="support")


class SupportStates(StatesGroup):
    waiting_problem = State()


@router.message(SupportStates.waiting_problem)
async def on_problem(msg: Message, state: FSMContext) -> None:
    if msg.from_user is None:
        return
    text = (msg.text or "").strip()
    if not text:
        await msg.answer("⚠ Пришлите описание проблемы.")
        return
    tid = await crud.create_ticket(msg.from_user.id, text[:4000])
    await state.clear()
    await msg.answer(f"✅ Тикет <b>#{tid}</b> создан.")
    for admin_id in settings.admin_ids:
        try:
            await msg.bot.send_message(
                chat_id=admin_id,
                text=(
                    f"🆘 <b>Тикет #{tid}</b>\n"
                    f"От: {user_display(msg.from_user)} (<code>{msg.from_user.id}</code>)\n\n"
                    f"{text[:1000]}\n\n"
                    f"→ Ответ: <code>/reply_{tid} текст</code>"),
            )
        except Exception:
            logger.warning("notify admin %s failed", admin_id)
