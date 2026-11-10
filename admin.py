"""Админ-панель."""
from __future__ import annotations
import asyncio, logging
from typing import Optional

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message,
)

from config import settings
from database import crud
from database.db import Database
from services import monitoring
from ui.buttons import DEFAULT_BUTTONS, btn
from ui.texts import DEFAULT_TEXTS

logger = logging.getLogger(__name__)
router = Router(name="admin")


def _is_admin(uid: Optional[int]) -> bool:
    return uid is not None and uid in settings.admin_ids


class AdminStates(StatesGroup):
    ticket_reply = State()
    promo_code = State()
    promo_days = State()
    promo_max = State()
    broadcast_text = State()
    broadcast_confirm = State()
    ui_btn_label = State()
    ui_btn_emoji = State()
    ui_text_value = State()
    channel_add = State()
    user_ban_id = State()
    user_action = State()


async def show_admin_menu(message: Message, edit: bool = False) -> None:
    text = f"👑 <b>Админ-панель</b>\n\nВерсия: {settings.BOT_VERSION}"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [await btn("admin_stats", callback_data="adm:stats"), await btn("admin_hosting", callback_data="adm:hosting")],
        [await btn("admin_tickets", callback_data="adm:tickets"), await btn("admin_promos", callback_data="adm:promos")],
        [await btn("admin_broadcast", callback_data="adm:broadcast")],
        [await btn("admin_ui", callback_data="adm:ui"), await btn("admin_channels", callback_data="adm:channels")],
        [await btn("admin_users", callback_data="adm:users")],
        [await btn("menu_back", callback_data="menu_back")],
    ])
    if edit:
        try: await message.edit_text(text, reply_markup=kb); return
        except Exception: pass
    await message.answer(text, reply_markup=kb)


@router.message(F.text.regexp(r"^/admin(?:\s|$)"))
async def cmd_admin(msg: Message) -> None:
    if not _is_admin(msg.from_user.id if msg.from_user else None): return
    await show_admin_menu(msg)


@router.callback_query(F.data == "adm:stats")
async def cb_stats(call: CallbackQuery) -> None:
    if not _is_admin(call.from_user.id if call.from_user else None): await call.answer("Доступ запрещён", show_alert=True); return
    s = await crud.stats_overview()
    text = (f"📊 <b>Статистика</b>\n\nВсего: <b>{s['users_total']}</b>\nЗабанено: {s['users_banned']}\n"
            f"Активных подписок: <b>{s['active_subs']}</b>\nНа триале: {s['on_trial']}\nПлативших: {s['paid_users']}\n"
            f"Тикетов: {s['open_tickets']}\nКоманд: {s['commands_total']}")
    kb = InlineKeyboardMarkup(inline_keyboard=[[await btn("admin_back", callback_data="adm:menu")]])
    try: await call.message.edit_text(text, reply_markup=kb)
    except Exception: await call.message.answer(text, reply_markup=kb)
    await call.answer()


@router.callback_query(F.data == "adm:hosting")
async def cb_hosting(call: CallbackQuery) -> None:
    if not _is_admin(call.from_user.id if call.from_user else None): await call.answer("Доступ запрещён", show_alert=True); return
    try:
        m = await monitoring.collect_metrics()
        text = monitoring.format_metrics(m)
        w = monitoring.check_thresholds(m)
        if w: text += "\n\n⚠ <b>Внимание:</b>\n" + "\n".join("• " + x for x in w)
    except Exception as e: text = f"⚠ {e}"
    kb = InlineKeyboardMarkup(inline_keyboard=[[await btn("admin_refresh", callback_data="adm:hosting")], [await btn("admin_back", callback_data="adm:menu")]])
    try: await call.message.edit_text(text, reply_markup=kb)
    except Exception: await call.message.answer(text, reply_markup=kb)
    await call.answer()


@router.callback_query(F.data == "adm:menu")
async def cb_menu(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    if not _is_admin(call.from_user.id if call.from_user else None): return
    await show_admin_menu(call.message, edit=True)
    await call.answer()


@router.callback_query(F.data == "adm:tickets")
async def cb_tickets(call: CallbackQuery) -> None:
    if not _is_admin(call.from_user.id if call.from_user else None): await call.answer("Доступ запрещён", show_alert=True); return
    tickets = await crud.list_open_tickets(20)
    if not tickets:
        text = "📨 Открытых тикетов нет."
        kb = InlineKeyboardMarkup(inline_keyboard=[[await btn("admin_back", callback_data="adm:menu")]])
    else:
        text = "📨 <b>Открытые тикеты</b>\n\n"
        rows: list[list[InlineKeyboardButton]] = []
        for t in tickets:
            text += f"#{t['id']} • user <code>{t['user_id']}</code>\n"
            rows.append([InlineKeyboardButton(text=f"↩ #{t['id']}", callback_data=f"adm:ticket:{t['id']}")])
        rows.append([await btn("admin_back", callback_data="adm:menu")])
        kb = InlineKeyboardMarkup(inline_keyboard=rows)
    try: await call.message.edit_text(text, reply_markup=kb)
    except Exception: await call.message.answer(text, reply_markup=kb)
    await call.answer()


@router.callback_query(F.data.startswith("adm:ticket:"))
async def cb_ticket(call: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(call.from_user.id if call.from_user else None): return
    tid = int(call.data.split(":")[2])
    t = await crud.get_ticket(tid)
    if t is None: await call.answer("Не найден", show_alert=True); return
    await call.message.answer(f"📨 <b>Тикет #{tid}</b>\nОт: <code>{t['user_id']}</code>\n\n{t['text']}\n\nПришлите ответ:")
    await state.update_data(ticket_id=tid)
    await state.set_state(AdminStates.ticket_reply)
    await call.answer()


@router.message(AdminStates.ticket_reply)
async def on_ticket_reply(msg: Message, state: FSMContext, bot: Bot) -> None:
    if not _is_admin(msg.from_user.id if msg.from_user else None): return
    data = await state.get_data()
    tid = data.get("ticket_id")
    if not tid: await state.clear(); return
    t = await crud.get_ticket(tid)
    if t is None: await state.clear(); return
    await crud.answer_ticket(tid, msg.text or "")
    try: await bot.send_message(chat_id=t["user_id"], text=f"📬 <b>Ответ поддержки #{tid}:</b>\n\n{msg.text}")
    except Exception: logger.warning("cannot reply to %s", t["user_id"])
    await msg.answer("✅ Отправлено.")
    await state.clear()


@router.message(F.text.regexp(r"^/reply_(\d+)\s+(.+)"))
async def cmd_reply(msg: Message, bot: Bot) -> None:
    if not _is_admin(msg.from_user.id if msg.from_user else None): return
    assert msg.text is not None
    parts = msg.text.split(maxsplit=1)
    tid = int(parts[0].replace("/reply_", ""))
    resp = parts[1] if len(parts) > 1 else ""
    if not resp: await msg.answer("⚠ Пусто."); return
    t = await crud.get_ticket(tid)
    if t is None: await msg.answer("Не найден."); return
    await crud.answer_ticket(tid, resp)
    try: await bot.send_message(chat_id=t["user_id"], text=f"📬 <b>Ответ #{tid}:</b>\n\n{resp}")
    except Exception: pass
    await msg.answer("✅ Отправлено.")


@router.callback_query(F.data == "adm:promos")
async def cb_promos(call: CallbackQuery) -> None:
    if not _is_admin(call.from_user.id if call.from_user else None): await call.answer("Доступ запрещён", show_alert=True); return
    db = Database.conn()
    async with db.execute("SELECT * FROM promocodes ORDER BY id DESC LIMIT 20") as cur:
        rows = await cur.fetchall()
    text = "🎟 <b>Промокоды</b>\n\n"
    if not rows: text += "Пока нет."
    else:
        for r in rows: text += f"<code>{r['code']}</code> • +{r['days']}д • {r['used_count']}/{r['max_uses'] or '∞'}\n"
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="➕ Создать", callback_data="adm:promo_new")], [await btn("admin_back", callback_data="adm:menu")]])
    try: await call.message.edit_text(text, reply_markup=kb)
    except Exception: await call.message.answer(text, reply_markup=kb)
    await call.answer()


@router.callback_query(F.data == "adm:promo_new")
async def cb_promo_new(call: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(call.from_user.id if call.from_user else None): return
    await call.message.answer("Введите код промокода:")
    await state.set_state(AdminStates.promo_code)
    await call.answer()


@router.message(AdminStates.promo_code)
async def on_promo_code(msg: Message, state: FSMContext) -> None:
    if not _is_admin(msg.from_user.id if msg.from_user else None): return
    code = (msg.text or "").strip().upper()
    if not code: return
    await state.update_data(promo_code=code)
    await msg.answer("Сколько дней даёт?")
    await state.set_state(AdminStates.promo_days)


@router.message(AdminStates.promo_days)
async def on_promo_days(msg: Message, state: FSMContext) -> None:
    try:
        d = int((msg.text or "").strip())
        if d < 1 or d > 3650: raise ValueError
    except ValueError: await msg.answer("⚠ 1..3650"); return
    await state.update_data(promo_days=d)
    await msg.answer("Макс использований (0 = ∞):")
    await state.set_state(AdminStates.promo_max)


@router.message(AdminStates.promo_max)
async def on_promo_max(msg: Message, state: FSMContext) -> None:
    try:
        m = int((msg.text or "").strip())
        if m < 0 or m > 1_000_000: raise ValueError
    except ValueError: await msg.answer("⚠ >= 0"); return
    data = await state.get_data()
    try: await crud.create_promocode(data["promo_code"], data["promo_days"], m)
    except Exception as e: await msg.answer(f"⚠ {e}"); await state.clear(); return
    await msg.answer(f"✅ <code>{data['promo_code']}</code> создан (+{data['promo_days']}д, макс {m or '∞'})")
    await state.clear()


@router.callback_query(F.data == "adm:broadcast")
async def cb_broadcast(call: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(call.from_user.id if call.from_user else None): await call.answer("Доступ запрещён", show_alert=True); return
    await call.message.answer("📢 Текст рассылки (HTML):")
    await state.set_state(AdminStates.broadcast_text)
    await call.answer()


@router.message(AdminStates.broadcast_text)
async def on_bc_text(msg: Message, state: FSMContext) -> None:
    if not _is_admin(msg.from_user.id if msg.from_user else None): return
    await state.update_data(bc_text=msg.html_text or msg.text or "")
    await msg.answer(f"<b>Превью:</b>\n\n{msg.html_text or msg.text}\n\nОтправить?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Да", callback_data="adm:bc_yes")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="adm:menu")]]))
    await state.set_state(AdminStates.broadcast_confirm)


@router.callback_query(F.data == "adm:bc_yes")
async def cb_bc_yes(call: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    if not _is_admin(call.from_user.id if call.from_user else None): return
    data = await state.get_data()
    text = data.get("bc_text", "")
    await state.clear()
    if not text: await call.answer("Пусто", show_alert=True); return
    db = Database.conn()
    async with db.execute("SELECT id FROM users WHERE is_banned=0") as cur:
        uids = [r[0] for r in await cur.fetchall()]
    ok = fail = 0
    for uid in uids:
        try: await bot.send_message(chat_id=uid, text=text); ok += 1; await asyncio.sleep(0.05)
        except Exception: fail += 1
    await call.message.answer(f"✅ Доставлено: {ok}, ошибок: {fail}")
    await call.answer()


@router.callback_query(F.data == "adm:ui")
async def cb_ui(call: CallbackQuery) -> None:
    if not _is_admin(call.from_user.id if call.from_user else None): await call.answer("Доступ запрещён", show_alert=True); return
    text = "🎨 <b>Редактор интерфейса</b>\n\n<i>В кнопках Telegram нельзя использовать премиум-эмодзи. Только обычные.</i>"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔘 Кнопки", callback_data="adm:ui_btns")],
        [InlineKeyboardButton(text="📝 Тексты", callback_data="adm:ui_texts")],
        [await btn("admin_back", callback_data="adm:menu")]])
    try: await call.message.edit_text(text, reply_markup=kb)
    except Exception: await call.message.answer(text, reply_markup=kb)
    await call.answer()


@router.callback_query(F.data == "adm:ui_btns")
async def cb_ui_btns(call: CallbackQuery) -> None:
    if not _is_admin(call.from_user.id if call.from_user else None): return
    rows: list[list[InlineKeyboardButton]] = []
    for key in list(DEFAULT_BUTTONS.keys())[:40]:
        r = await crud.ui_button_get(key)
        label = (r["label"] if r and r["label"] else DEFAULT_BUTTONS[key]["label"])
        emoji = (r["emoji"] if r and r["emoji"] else DEFAULT_BUTTONS[key]["emoji"])
        rows.append([InlineKeyboardButton(text=f"{emoji} {label}", callback_data=f"adm:ui_btn:{key}")])
    rows.append([await btn("admin_back", callback_data="adm:ui")])
    try: await call.message.edit_text("🔘 <b>Кнопки</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    except Exception: await call.message.answer("🔘 <b>Кнопки</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await call.answer()


@router.callback_query(F.data.startswith("adm:ui_btn:"))
async def cb_ui_btn(call: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(call.from_user.id if call.from_user else None): return
    key = call.data.split(":", 2)[2]
    r = await crud.ui_button_get(key)
    cur = r["label"] if r and r["label"] else DEFAULT_BUTTONS[key]["label"]
    await state.update_data(ui_btn_key=key)
    await call.message.answer(f"🔘 <code>{key}</code>\nСейчас: {cur}\n\nНовый текст (label) или /skip:")
    await state.set_state(AdminStates.ui_btn_label)
    await call.answer()


@router.message(AdminStates.ui_btn_label)
async def on_ui_label(msg: Message, state: FSMContext) -> None:
    if not _is_admin(msg.from_user.id if msg.from_user else None): return
    data = await state.get_data()
    t = (msg.text or "").strip()
    if t and t != "/skip": await crud.ui_button_upsert(data["ui_btn_key"], label=t)
    await msg.answer("Пришлите новый <b>обычный</b> эмодзи для кнопки (или /skip):")
    await state.set_state(AdminStates.ui_btn_emoji)


@router.message(AdminStates.ui_btn_emoji)
async def on_ui_emoji(msg: Message, state: FSMContext) -> None:
    if not _is_admin(msg.from_user.id if msg.from_user else None): return
    data = await state.get_data()
    t = (msg.text or "").strip()
    
    if t and t != "/skip":
        # Берем только первые 4 символа (на случай сложных составных эмодзи)
        if len(t) > 4: await msg.answer("⚠ Отправьте один эмодзи (или /skip)."); return
        await crud.ui_button_upsert(data["ui_btn_key"], emoji=t)
        
    await msg.answer(f"✅ Кнопка <code>{data['ui_btn_key']}</code> обновлена.")
    await state.clear()


@router.callback_query(F.data == "adm:ui_texts")
async def cb_ui_texts(call: CallbackQuery) -> None:
    if not _is_admin(call.from_user.id if call.from_user else None): return
    rows: list[list[InlineKeyboardButton]] = []
    for key in list(DEFAULT_TEXTS.keys())[:40]:
        rows.append([InlineKeyboardButton(text=key, callback_data=f"adm:ui_text:{key}")])
    rows.append([await btn("admin_back", callback_data="adm:ui")])
    try: await call.message.edit_text("📝 <b>Тексты</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    except Exception: await call.message.answer("📝 <b>Тексты</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await call.answer()


@router.callback_query(F.data.startswith("adm:ui_text:"))
async def cb_ui_text(call: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(call.from_user.id if call.from_user else None): return
    key = call.data.split(":", 2)[2]
    v = await crud.ui_text_get(key)
    cur = v if v is not None else DEFAULT_TEXTS.get(key, "—")
    await state.update_data(ui_text_key=key)
    await call.message.answer(f"📝 <code>{key}</code>\n\n<b>Сейчас:</b>\n{cur}\n\nНовый текст или /skip:")
    await state.set_state(AdminStates.ui_text_value)
    await call.answer()


@router.message(AdminStates.ui_text_value)
async def on_ui_text(msg: Message, state: FSMContext) -> None:
    if not _is_admin(msg.from_user.id if msg.from_user else None): return
    data = await state.get_data()
    t = msg.html_text or msg.text or ""
    if t.strip() and t.strip() != "/skip":
        await crud.ui_text_set(data["ui_text_key"], t)
        await msg.answer(f"✅ <code>{data['ui_text_key']}</code> обновлён.")
    else: await msg.answer("Пропущено.")
    await state.clear()


@router.callback_query(F.data == "adm:channels")
async def cb_channels(call: CallbackQuery) -> None:
    if not _is_admin(call.from_user.id if call.from_user else None): return
    db = Database.conn()
    async with db.execute("SELECT * FROM required_channels ORDER BY id") as cur:
        rows = await cur.fetchall()
    text = "🔗 <b>Обязательные каналы</b>\n\n"
    if not rows: text += "Пока нет."
    else:
        for r in rows: text += f"{'🟢' if r['is_active'] else '🔴'} <code>{r['chat_id']}</code> — {r['title'] or '—'}\n"
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="➕ Добавить", callback_data="adm:channel_add")], [await btn("admin_back", callback_data="adm:menu")]])
    try: await call.message.edit_text(text, reply_markup=kb)
    except Exception: await call.message.answer(text, reply_markup=kb)
    await call.answer()


@router.callback_query(F.data == "adm:channel_add")
async def cb_ch_add(call: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(call.from_user.id if call.from_user else None): return
    await call.message.answer("Введите @username или -100xxx:")
    await state.set_state(AdminStates.channel_add)
    await call.answer()


@router.message(AdminStates.channel_add)
async def on_ch_add(msg: Message, bot: Bot, state: FSMContext) -> None:
    if not _is_admin(msg.from_user.id if msg.from_user else None): return
    target = (msg.text or "").strip()
    if not target: return
    try:
        chat = await bot.get_chat(target)
        link = chat.invite_link or (f"https://t.me/{chat.username}" if chat.username else "")
        db = Database.conn()
        await db.execute("INSERT INTO required_channels(chat_id, title, invite_link, is_active) VALUES (?, ?, ?, 1)", (str(chat.id), chat.title or "—", link))
        await db.commit()
        await msg.answer(f"✅ <b>{chat.title}</b> добавлен.")
    except Exception as e: await msg.answer(f"⚠ {e}")
    await state.clear()


@router.callback_query(F.data == "adm:users")
async def cb_users(call: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(call.from_user.id if call.from_user else None): return
    await call.message.answer("Введите ID пользователя:")
    await state.set_state(AdminStates.user_ban_id)
    await call.answer()


@router.message(AdminStates.user_ban_id)
async def on_user_id(msg: Message, state: FSMContext) -> None:
    if not _is_admin(msg.from_user.id if msg.from_user else None): return
    try: uid = int((msg.text or "").strip())
    except ValueError: await msg.answer("⚠ Нужно число."); return
    u = await crud.get_user(uid)
    if u is None: await msg.answer("Не найден."); await state.clear(); return
    await state.update_data(target_uid=uid)
    banned = bool(u["is_banned"])
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=("✅ Разбанить" if banned else "🚫 Забанить"), callback_data="adm:user_toggle_ban")],
        [await btn("admin_back", callback_data="adm:menu")]])
    await msg.answer(f"👤 <code>{uid}</code>\nСтатус: {'забанен' if banned else 'активен'}", reply_markup=kb)
    await state.set_state(AdminStates.user_action)


@router.callback_query(F.data == "adm:user_toggle_ban")
async def cb_toggle_ban(call: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    if not _is_admin(call.from_user.id if call.from_user else None): return
    data = await state.get_data()
    uid = data.get("target_uid")
    if not uid: await call.answer("Нет пользователя", show_alert=True); return
    u = await crud.get_user(uid)
    if u is None: return
    new = not bool(u["is_banned"])
    await crud.set_user_banned(uid, new)
    try: await bot.send_message(uid, "🚫 Вы были забанены." if new else "✅ Вы были разбанены.")
    except Exception: pass
    await call.message.answer("✅ Забанен." if new else "✅ Разбанен.")
    await state.clear()
    await call.answer()


_bg_task: asyncio.Task | None = None

@router.startup()
async def _start_bg(bot: Bot) -> None:
    global _bg_task
    if _bg_task is not None: return
    async def _loop() -> None:
        await asyncio.sleep(60)
        while True:
            try:
                m = await monitoring.collect_metrics()
                w = monitoring.check_thresholds(m)
                if w:
                    txt = "⚠ <b>Метрики</b>\n" + "\n".join("• " + x for x in w)
                    for aid in settings.admin_ids:
                        try: await bot.send_message(chat_id=aid, text=txt)
                        except Exception: pass
            except Exception: logger.exception("bg loop")
            await asyncio.sleep(300)
    _bg_task = asyncio.create_task(_loop())

@router.shutdown()
async def _stop_bg() -> None:
    global _bg_task
    if _bg_task is not None: _bg_task.cancel(); _bg_task = None
