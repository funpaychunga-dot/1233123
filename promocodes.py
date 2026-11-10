"""Промокоды."""
from __future__ import annotations
import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from database import crud

logger = logging.getLogger(__name__)
router = Router(name="promocodes")


class PromoStates(StatesGroup):
    waiting_code = State()


@router.message(PromoStates.waiting_code)
async def on_code(msg: Message, state: FSMContext) -> None:
    if msg.from_user is None:
        return
    code = (msg.text or "").strip()
    if not code:
        return
    ok, text, days = await crud.redeem_promocode(code, msg.from_user.id)
    await state.clear()
    if ok and days:
        until = await crud.extend_subscription(msg.from_user.id, days)
        await msg.answer(
            f"✅ Промокод активирован: <b>+{days} дн.</b>\n"
            f"До: {until.strftime('%d.%m.%Y')}")
    else:
        await msg.answer(f"❌ {text}")
