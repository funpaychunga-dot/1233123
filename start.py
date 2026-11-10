"""/start, меню, профиль, Команды, SubscriptionMiddleware."""
from __future__ import annotations
import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware, Bot, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message,
    PreCheckoutQuery, TelegramObject,
)

from config import settings
from database import crud
from services.subscription import subscription_service, check_required_channels
from ui.buttons import btn, main_menu_rows
from ui.texts import get_text

logger = logging.getLogger(__name__)
router = Router(name="start")


class SubscriptionMiddleware(BaseMiddleware):
    SKIP_CB = {"menu_profile", "menu_buy", "pay_stars", "pay_extra_slot"}
    SKIP_TX = {"/start", "/buy", "/profile"}

    async def __call__(
        self, handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject, data: dict[str, Any],
    ) -> Any:
        u = getattr(event, "from_user", None)
        if u is None or u.id in settings.admin_ids: return await handler(event, data)
        if isinstance(event, Message) and event.business_connection_id: return await handler(event, data)
        if isinstance(event, PreCheckoutQuery): return await handler(event, data)
        if isinstance(event, Message) and getattr(event, "successful_payment", None): return await handler(event, data)

        user = await crud.get_or_create_user(u.id, u.username, u.first_name, u.last_name)
        
        if user["is_banned"]:
            try:
                if isinstance(event, Message): await event.answer("🚫 Вы забанены в этом боте.")
                elif isinstance(event, CallbackQuery): await event.answer("🚫 Вы забанены в этом боте.", show_alert=True)
            except Exception: pass
            return

        if isinstance(event, CallbackQuery) and event.data == "check_subs": return await handler(event, data)

        missing = await check_required_channels(event.bot, u.id)
        if missing:
            text = "🛑 <b>Для использования бота подпишитесь на каналы:</b>\n\n"
            kb = []
            for ch in missing:
                text += f"• {ch['title']}\n"
                if ch["invite_link"]: kb.append([InlineKeyboardButton(text=ch["title"], url=ch["invite_link"])])
            kb.append([InlineKeyboardButton(text="✅ Проверить", callback_data="check_subs")])
            try:
                if isinstance(event, Message): await event.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
                elif isinstance(event, CallbackQuery):
                    await event.message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
                    await event.answer()
            except Exception: pass
            return

        if not await subscription_service.is_active(u.id):
            if isinstance(event, CallbackQuery) and event.data in self.SKIP_CB: return await handler(event, data)
            if isinstance(event, Message) and event.text in self.SKIP_TX: return await handler(event, data)
            text = await get_text("subscription.expired")
            kb = InlineKeyboardMarkup(inline_keyboard=[[await btn("pay_stars", callback_data="pay_stars")]])
            try:
                if isinstance(event, Message): await event.answer(text, reply_markup=kb)
                elif isinstance(event, CallbackQuery):
                    await event.message.answer(text, reply_markup=kb)
                    await event.answer()
            except Exception: pass
            return
        return await handler(event, data)


async def _show_main_menu(message: Message, state: FSMContext, user_id: int, first_name: str) -> None:
    await state.clear()
    user = await crud.get_or_create_user(user_id, None, first_name, None)
    st = await subscription_service.get_status(user_id)
    text = await get_text("start.welcome", user=first_name or "друг", days_left=st.days_left)
    is_admin = bool(user["is_admin"]) or user_id in settings.admin_ids
    kb = InlineKeyboardMarkup(inline_keyboard=await main_menu_rows(is_admin))
    try: await message.edit_text(text, reply_markup=kb)
    except Exception: await message.answer(text, reply_markup=kb)


@router.message(CommandStart())
async def cmd_start(msg: Message, state: FSMContext) -> None:
    if msg.from_user is None: return
    await _show_main_menu(msg, state, msg.from_user.id, msg.from_user.first_name)


@router.callback_query(F.data == "check_subs")
async def cb_check_subs(call: CallbackQuery, state: FSMContext) -> None:
    missing = await check_required_channels(call.bot, call.from_user.id)
    if missing: await call.answer("Вы всё ещё не подписаны на все каналы.", show_alert=True)
    else:
        await call.answer("✅ Подписка подтверждена!", show_alert=True)
        await _show_main_menu(call.message, state, call.from_user.id, call.from_user.first_name)


@router.message(Command("buy"))
async def cmd_buy(msg: Message) -> None: await _show_buy(msg, edit=False)

@router.message(Command("profile"))
async def cmd_profile(msg: Message) -> None: await _show_profile(msg, edit=False)

@router.callback_query(F.data == "menu_profile")
async def cb_profile(call: CallbackQuery) -> None:
    await _show_profile(call.message, edit=True)
    await call.answer()


async def _show_profile(message: Message, edit: bool) -> None:
    if message.chat is None: return
    uid = message.chat.id
    row = await crud.get_user(uid)
    if row is None: return
    st = await subscription_service.get_status(uid)
    used = await crud.count_user_commands(uid)
    text = await get_text("profile.title", user=row["first_name"] or "—", user_id=uid,
                          sub_status=st.to_text(), slots=f"{used}/{row['slots']}", max_slots=settings.MAX_COMMAND_SLOTS)
    kb = InlineKeyboardMarkup(inline_keyboard=[[await btn("menu_back", callback_data="menu_back")]])
    if edit:
        try: await message.edit_text(text, reply_markup=kb); return
        except Exception: pass
    await message.answer(text, reply_markup=kb)


@router.callback_query(F.data == "menu_commands")
async def cb_commands(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    text = await get_text("menu.commands")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [await btn("commands_my", callback_data="commands_my"), await btn("commands_builtin", callback_data="commands_builtin")],
        [await btn("commands_add", callback_data="commands_add"), await btn("commands_docs", callback_data="commands_docs")],
        [await btn("menu_back", callback_data="menu_back")],
    ])
    try: await call.message.edit_text(text, reply_markup=kb)
    except Exception: await call.message.answer(text, reply_markup=kb)
    await call.answer()


@router.callback_query(F.data == "commands_my")
async def cb_my(call: CallbackQuery) -> None:
    if call.from_user is None: return
    cmds = await crud.list_user_commands(call.from_user.id)
    if not cmds:
        text = "📂 У вас пока нет команд."
        kb = InlineKeyboardMarkup(inline_keyboard=[[await btn("menu_back", callback_data="menu_commands")]])
    else:
        text = "📂 <b>Ваши команды:</b>\n\nВыберите для управления:"
        rows = []
        for r in cmds:
            flag = "🟢" if r["is_active"] else "🔴"
            rows.append([InlineKeyboardButton(text=f"{flag} {r['command_name']}", callback_data=f"cmd:manage:{r['command_name']}")])
        rows.append([await btn("menu_back", callback_data="menu_commands")])
        kb = InlineKeyboardMarkup(inline_keyboard=rows)
    try: await call.message.edit_text(text, reply_markup=kb)
    except Exception: await call.message.answer(text, reply_markup=kb)
    await call.answer()


@router.callback_query(F.data == "commands_builtin")
async def cb_builtin(call: CallbackQuery) -> None:
    text = (
        "🔧 <b>Встроенные команды</b>\n\n"
        "<code>.мут [сек]</code> — reply: удалять сообщения автора\n"
        "<code>.размут</code> — reply: снять мут\n"
        "<code>.клон</code> / <code>.разклон</code> — дублирование в личку\n"
        "<code>.спам N текст</code> — N сообщений\n"
        "<code>.автоответ текст</code> — автоответ ({ник} = имя)\n"
        "<code>.автоответ off</code> — выключить"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[[await btn("menu_back", callback_data="menu_commands")]])
    try: await call.message.edit_text(text, reply_markup=kb)
    except Exception: await call.message.answer(text, reply_markup=kb)
    await call.answer()


@router.callback_query(F.data == "menu_buy")
async def cb_buy(call: CallbackQuery) -> None:
    await _show_buy(call.message, edit=True)
    await call.answer()


async def _show_buy(message: Message, edit: bool) -> None:
    text = await get_text("buy.title", price=settings.SUBSCRIPTION_PRICE_STARS, days=settings.SUBSCRIPTION_DAYS, extra_price=settings.EXTRA_SLOT_PRICE_STARS)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [await btn("pay_stars", callback_data="pay_stars")], [await btn("pay_extra_slot", callback_data="pay_extra_slot")],
        [await btn("menu_back", callback_data="menu_back")],
    ])
    if edit:
        try: await message.edit_text(text, reply_markup=kb); return
        except Exception: pass
    await message.answer(text, reply_markup=kb)


@router.callback_query(F.data == "menu_docs")
async def cb_docs(call: CallbackQuery) -> None:
    from handlers.upload_command import DOCS_TEXT
    text = DOCS_TEXT.replace("{docs_url}", settings.DOCS_URL)
    url = settings.DOCS_URL if settings.DOCS_URL.startswith("http") else "https://telegram.org"
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📘 Открыть документацию", url=url)], [await btn("menu_back", callback_data="menu_back")]])
    try: await call.message.edit_text(text, reply_markup=kb)
    except Exception: await call.message.answer(text, reply_markup=kb)
    await call.answer()


@router.callback_query(F.data == "menu_settings")
async def cb_settings(call: CallbackQuery) -> None:
    text = await get_text("settings.title") + "\n\n<i>Скоро появится.</i>"
    kb = InlineKeyboardMarkup(inline_keyboard=[[await btn("menu_back", callback_data="menu_back")]])
    try: await call.message.edit_text(text, reply_markup=kb)
    except Exception: await call.message.answer(text, reply_markup=kb)
    await call.answer()


@router.callback_query(F.data == "menu_support")
async def cb_support(call: CallbackQuery, state: FSMContext) -> None:
    from handlers.support import SupportStates
    text = await get_text("support.title")
    kb = InlineKeyboardMarkup(inline_keyboard=[[await btn("menu_back", callback_data="menu_back")]])
    try: await call.message.edit_text(text, reply_markup=kb)
    except Exception: await call.message.answer(text, reply_markup=kb)
    await state.set_state(SupportStates.waiting_problem)
    await call.answer()


@router.callback_query(F.data == "menu_promocodes")
async def cb_promos(call: CallbackQuery, state: FSMContext) -> None:
    from handlers.promocodes import PromoStates
    text = await get_text("promocodes.title")
    kb = InlineKeyboardMarkup(inline_keyboard=[[await btn("menu_back", callback_data="menu_back")]])
    try: await call.message.edit_text(text, reply_markup=kb)
    except Exception: await call.message.answer(text, reply_markup=kb)
    await state.set_state(PromoStates.waiting_code)
    await call.answer()


@router.callback_query(F.data == "menu_admin")
async def cb_admin(call: CallbackQuery) -> None:
    if call.from_user is None or call.from_user.id not in settings.admin_ids: await call.answer("Доступ запрещён", show_alert=True); return
    from handlers.admin import show_admin_menu
    await show_admin_menu(call.message, edit=True)
    await call.answer()


@router.callback_query(F.data == "menu_back")
async def cb_back(call: CallbackQuery, state: FSMContext) -> None:
    if call.from_user is None: return
    await _show_main_menu(call.message, state, call.from_user.id, call.from_user.first_name)
    await call.answer()
