"""Оплата Stars: подписка и слоты."""
from __future__ import annotations
import json, logging

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery, LabeledPrice, Message, PreCheckoutQuery

from config import settings
from database import crud

logger = logging.getLogger(__name__)
router = Router(name="payments")


@router.callback_query(F.data == "pay_stars")
async def cb_pay_stars(call: CallbackQuery, bot: Bot) -> None:
    if call.from_user is None:
        return
    payload = json.dumps({
        "type": "subscription", "user_id": call.from_user.id,
        "days": settings.SUBSCRIPTION_DAYS,
    })
    try:
        await bot.send_invoice(
            chat_id=call.from_user.id,
            title=f"Подписка — {settings.SUBSCRIPTION_DAYS} дней",
            description="Доступ ко всем функциям бота",
            payload=payload, provider_token="", currency="XTR",
            prices=[LabeledPrice(label="Подписка",
                                 amount=settings.SUBSCRIPTION_PRICE_STARS)],
        )
    except Exception:
        logger.exception("send_invoice subscription")
        await call.answer("Ошибка создания счёта", show_alert=True); return
    await call.answer()


@router.callback_query(F.data == "pay_extra_slot")
async def cb_pay_slot(call: CallbackQuery, bot: Bot) -> None:
    if call.from_user is None:
        return
    payload = json.dumps({"type": "slot", "user_id": call.from_user.id})
    try:
        await bot.send_invoice(
            chat_id=call.from_user.id,
            title="Дополнительный слот",
            description=f"+1 слот (макс {settings.MAX_COMMAND_SLOTS})",
            payload=payload, provider_token="", currency="XTR",
            prices=[LabeledPrice(label="Слот",
                                 amount=settings.EXTRA_SLOT_PRICE_STARS)],
        )
    except Exception:
        logger.exception("send_invoice slot")
        await call.answer("Ошибка создания счёта", show_alert=True); return
    await call.answer()


@router.pre_checkout_query()
async def on_pre_checkout(q: PreCheckoutQuery) -> None:
    await q.answer(ok=True)


@router.message(F.successful_payment)
async def on_successful_payment(msg: Message) -> None:
    if msg.from_user is None or msg.successful_payment is None:
        return
    sp = msg.successful_payment
    uid = msg.from_user.id
    try:
        data = json.loads(sp.invoice_payload)
    except json.JSONDecodeError:
        data = {}
    await crud.add_payment(
        user_id=uid, provider="stars", amount=sp.total_amount,
        currency=sp.currency, status="succeeded", payload=data,
    )
    kind = data.get("type", "")
    if kind == "subscription":
        days = int(data.get("days") or settings.SUBSCRIPTION_DAYS)
        until = await crud.extend_subscription(uid, days)
        await msg.answer(
            f"✅ Подписка продлена на <b>{days} дн.</b>\n"
            f"До: {until.strftime('%d.%m.%Y')}")
    elif kind == "slot":
        new = await crud.add_slots(uid, 1)
        await msg.answer(f"✅ Куплен 1 слот. Теперь: <b>{new}</b>.")
    else:
        await msg.answer("✅ Спасибо!")
    logger.info("Payment OK user=%s amount=%s type=%s", uid, sp.total_amount, kind)
