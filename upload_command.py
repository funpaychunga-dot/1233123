"""FSM загрузки .py-плагинов + управление + триггеры."""
from __future__ import annotations
import io, json, logging
from pathlib import Path
from typing import Optional

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message,
)

from config import settings
from database import crud
from services.command_executor import CommandExecutor
from services.command_sandbox import validate_source

logger = logging.getLogger(__name__)
router = Router(name="upload_command")


@router.startup()
async def _executor_startup(bot: Bot) -> None:
    ex = CommandExecutor.init(bot)
    await ex.start()


@router.shutdown()
async def _executor_shutdown() -> None:
    await CommandExecutor.shutdown()


class UploadStates(StatesGroup):
    waiting_file = State()
    waiting_config_value = State()


def _cmd_buttons(name: str, is_active: bool) -> InlineKeyboardMarkup:
    toggle = "🔴 Деактивировать" if is_active else "🟢 Активировать"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=toggle, callback_data=f"cmd:activate:{name}"),
         InlineKeyboardButton(text="⚙ Настроить", callback_data=f"cmd:config:{name}")],
        [InlineKeyboardButton(text="🧪 Тест", callback_data=f"cmd:test:{name}"),
         InlineKeyboardButton(text="🗑 Удалить", callback_data=f"cmd:delete:{name}")],
    ])


async def _check_quota(user_id: int) -> tuple[bool, str]:
    user = await crud.get_user(user_id)
    if user is None: return False, "Профиль не найден"
    used = await crud.count_user_commands(user_id)
    if used >= int(user["slots"]):
        return False, (f"⚠ Достигнут лимит: {used}/{user['slots']} команд.\n"
                       f"Купите слот за {settings.EXTRA_SLOT_PRICE_STARS} ⭐.")
    return True, ""


async def _save_file(user_id: int, name: str, source: str) -> Path:
    cmd_dir = settings.commands_root / str(user_id)
    cmd_dir.mkdir(parents=True, exist_ok=True)
    path = cmd_dir / f"{name}.py"
    path.write_text(source, encoding="utf-8", newline="\n")
    return path


@router.message(F.text == "/upload")
async def cmd_upload(msg: Message, state: FSMContext) -> None:
    if msg.from_user is None: return
    ok, err = await _check_quota(msg.from_user.id)
    if not ok: await msg.answer(err); return
    await state.set_state(UploadStates.waiting_file)
    await msg.answer("📤 Пришлите <b>.py-файл</b> (≤ 64 КБ) с <code>async def handler(ctx)</code>.\nПодробнее — /docs")


@router.callback_query(F.data == "commands_add")
async def cb_add(call: CallbackQuery, state: FSMContext) -> None:
    if call.from_user is None: return
    ok, err = await _check_quota(call.from_user.id)
    if not ok: await call.answer(err, show_alert=True); return
    await state.set_state(UploadStates.waiting_file)
    await call.message.answer("📤 Пришлите <b>.py-файл</b> с <code>async def handler(ctx)</code> (≤ 64 КБ).")
    await call.answer()


@router.message(UploadStates.waiting_file, F.document)
async def on_file(msg: Message, state: FSMContext, bot: Bot) -> None:
    assert msg.from_user is not None and msg.document is not None
    if not (msg.document.file_name or "").lower().endswith(".py"):
        await msg.answer("⚠ Нужен файл <code>.py</code>."); return
    if msg.document.file_size and msg.document.file_size > settings.MAX_COMMAND_FILE_BYTES:
        await msg.answer(f"⚠ Файл больше {settings.MAX_COMMAND_FILE_BYTES // 1024} КБ."); return

    file = await bot.get_file(msg.document.file_id)
    buf = io.BytesIO()
    await bot.download_file(file.file_path, buf)
    try: source = buf.getvalue().decode("utf-8")
    except UnicodeDecodeError: await msg.answer("⚠ Файл должен быть UTF-8."); return

    filename = msg.document.file_name or "plugin.py"
    vr = validate_source(source, filename)
    if not vr.ok:
        errors = "\n".join(f"• {e}" for e in vr.errors)
        await msg.answer(f"❌ <b>Валидация не прошла:</b>\n{errors}"); return

    name = (vr.metadata.get("COMMAND_NAME") or Path(filename).stem).strip()
    if not name.isidentifier():
        await msg.answer("⚠ COMMAND_NAME должен быть валидным идентификатором Python."); return
    if await crud.get_user_command(msg.from_user.id, name) is not None:
        await msg.answer(f"⚠ Команда <code>{name}</code> уже существует."); return

    path = await _save_file(msg.from_user.id, name, source)
    try:
        await crud.add_user_command(
            user_id=msg.from_user.id, command_name=name, source_path=str(path),
            description=vr.metadata.get("COMMAND_DESCRIPTION"),
            version=vr.metadata.get("COMMAND_VERSION"),
            triggers=vr.metadata.get("COMMAND_TRIGGERS") or [],
            config=vr.metadata.get("COMMAND_CONFIG_SCHEMA") or {},
        )
    except Exception as e:
        path.unlink(missing_ok=True)
        logger.exception("save failed")
        await msg.answer(f"⚠ Ошибка сохранения: {e}"); return

    await state.clear()
    triggers = vr.metadata.get("COMMAND_TRIGGERS") or []
    await msg.answer(
        f"✅ <b>Команда {name} загружена</b>\nТриггеры: {', '.join(f'<code>{t}</code>' for t in triggers) or '—'}",
        reply_markup=_cmd_buttons(name, True))


@router.message(UploadStates.waiting_file)
async def on_file_wrong(msg: Message) -> None:
    await msg.answer("⚠ Ожидается .py-файл. /upload — заново.")


@router.callback_query(F.data.startswith("cmd:manage:"))
async def cb_manage(call: CallbackQuery) -> None:
    assert call.data is not None and call.from_user is not None
    name = call.data.split(":", 2)[2]
    row = await crud.get_user_command(call.from_user.id, name)
    if row is None: await call.answer("Не найдена", show_alert=True); return
    await call.message.edit_text(f"⚙ Управление командой <code>{name}</code>", reply_markup=_cmd_buttons(name, bool(row["is_active"])))
    await call.answer()


@router.callback_query(F.data.startswith("cmd:activate:"))
async def cb_activate(call: CallbackQuery) -> None:
    assert call.data is not None and call.from_user is not None
    name = call.data.split(":", 2)[2]
    row = await crud.get_user_command(call.from_user.id, name)
    if row is None: await call.answer("Не найдена", show_alert=True); return
    new = not bool(row["is_active"])
    await crud.set_command_active(call.from_user.id, name, new)
    await call.message.edit_reply_markup(reply_markup=_cmd_buttons(name, new))
    await call.answer("🟢" if new else "🔴")


@router.callback_query(F.data.startswith("cmd:delete:"))
async def cb_delete(call: CallbackQuery) -> None:
    assert call.data is not None and call.from_user is not None
    name = call.data.split(":", 2)[2]
    row = await crud.get_user_command(call.from_user.id, name)
    if row is None: await call.answer("Не найдена", show_alert=True); return
    await crud.delete_user_command(call.from_user.id, name)
    try: Path(row["source_path"]).unlink(missing_ok=True)
    except OSError: pass
    await call.message.edit_text(f"🗑 Команда <code>{name}</code> удалена.")
    await call.answer()


@router.callback_query(F.data.startswith("cmd:test:"))
async def cb_test(call: CallbackQuery) -> None:
    assert call.data is not None and call.from_user is not None
    name = call.data.split(":", 2)[2]
    row = await crud.get_user_command(call.from_user.id, name)
    if row is None: await call.answer("Не найдена", show_alert=True); return
    try: ex = CommandExecutor.get()
    except RuntimeError: await call.answer("Исполнитель не готов", show_alert=True); return
    config = json.loads(row["config_json"] or "{}")
    triggers = json.loads(row["triggers"] or "[]")
    trigger = triggers[0] if triggers else f"/{name}"
    await call.answer("🧪 Запускаю…")
    u = call.from_user
    result = await ex.execute(
        user_id=u.id, chat_id=u.id, command_name=name, source_path=Path(row["source_path"]),
        config=config, payload={"user": {"id": u.id, "first_name": u.first_name, "username": u.username},
                                "chat_id": u.id, "text": f"{trigger} test", "args": "test"})
    if result.get("ok"): await call.message.answer("✅ Тест выполнен.")
    else: await call.message.answer(f"❌ <code>{result.get('error')}</code>")


@router.callback_query(F.data.startswith("cmd:config:"))
async def cb_config(call: CallbackQuery, state: FSMContext) -> None:
    assert call.data is not None and call.from_user is not None
    name = call.data.split(":", 2)[2]
    row = await crud.get_user_command(call.from_user.id, name)
    if row is None: await call.answer("Не найдена", show_alert=True); return
    schema = json.loads(row["config_json"] or "{}")
    if not schema: await call.answer("Нет параметров", show_alert=True); return
    keys = list(schema.keys())
    await state.update_data(cfg_name=name, cfg_keys=keys, cfg_values=dict(schema), cfg_idx=0, cfg_user_id=call.from_user.id)
    await state.set_state(UploadStates.waiting_config_value)
    await call.message.answer(f"⚙ <b>{name}</b>\n<code>{keys[0]}</code> (сейчас: <code>{schema[keys[0]]}</code>)\nНовое значение или /skip:")
    await call.answer()


@router.message(UploadStates.waiting_config_value)
async def on_config_value(msg: Message, state: FSMContext) -> None:
    data = await state.get_data()
    keys = data.get("cfg_keys", [])
    values = data.get("cfg_values", {})
    idx = data.get("cfg_idx", 0)
    name = data.get("cfg_name", "")
    uid = data.get("cfg_user_id", 0)
    if not keys or not msg.from_user or msg.from_user.id != uid: return
    text = (msg.text or "").strip()
    if text and text != "/skip": values[keys[idx]] = text
    idx += 1
    if idx >= len(keys):
        await crud.update_command_config(uid, name, values)
        await state.clear()
        await msg.answer(f"✅ Настройки <b>{name}</b> сохранены."); return
    await state.update_data(cfg_idx=idx, cfg_values=values)
    await msg.answer(f"<code>{keys[idx]}</code> (сейчас: <code>{values.get(keys[idx], '')}</code>):")


async def _handle_plugin_trigger(msg: Message, bot: Bot, state: FSMContext) -> None:
    if await state.get_state(): return
    if not msg.text or not msg.from_user: return
    parts = msg.text.split(maxsplit=1)
    if not parts: return
    first_word = parts[0]
    args = parts[1] if len(parts) > 1 else ""
    matches = await crud.find_active_commands_by_trigger(first_word)
    if not matches: return
    try: ex = CommandExecutor.get()
    except RuntimeError: return
    for row in matches:
        if int(row["user_id"]) != msg.from_user.id: continue
        try: config = json.loads(row["config_json"] or "{}")
        except json.JSONDecodeError: config = {}
        u = msg.from_user
        result = await ex.execute(
            user_id=u.id, chat_id=msg.chat.id, command_name=row["command_name"],
            source_path=Path(row["source_path"]), config=config,
            payload={"user": {"id": u.id, "first_name": u.first_name, "username": u.username},
                     "chat_id": msg.chat.id, "text": msg.text, "args": args})
        if not result.get("ok") and result.get("error"): await msg.reply(f"⚠ {result['error']}")
        return


@router.message(F.text)
async def on_plugin_trigger(msg: Message, bot: Bot, state: FSMContext) -> None:
    await _handle_plugin_trigger(msg, bot, state)

@router.business_message(F.text)
async def on_business_plugin_trigger(msg: Message, bot: Bot, state: FSMContext) -> None:
    await _handle_plugin_trigger(msg, bot, state)


DOCS_TEXT = (
    "📘 <b>Документация по плагинам</b>\n\n"
    "Плагин — это <code>.py</code>-файл (≤ 64 КБ) с обязательной функцией:\n"
    "<pre>async def handler(ctx): ...</pre>\n\n"
    "<b>Метаданные (рекомендуются):</b>\n"
    "• <code>COMMAND_NAME</code> — имя команды\n"
    "• <code>COMMAND_TRIGGERS</code> — список триггеров, напр. <code>['/hello', '.привет']</code>\n"
    "• <code>COMMAND_CONFIG_SCHEMA</code> — {{ключ: значение_по_умолчанию}}\n"
    "• <code>COMMAND_DESCRIPTION</code>, <code>COMMAND_VERSION</code>\n\n"
    "<b>Что есть в ctx:</b>\n"
    "• <code>ctx.user</code> (id, first_name, username), <code>ctx.chat_id</code>\n"
    "• <code>ctx.message_text</code>, <code>ctx.args</code>, <code>ctx.config</code>\n"
    "• <code>await ctx.send_message(text)</code>, <code>send_photo</code>, <code>send_document</code>\n"
    "• <code>await ctx.http_get(url, headers, params)</code>, <code>http_post</code>\n"
    "• <code>await ctx.telegram.get_chat('@user')</code>\n"
    "• <code>await ctx.db_get(key)</code> / <code>db_set(key, value)</code>\n"
    "• <code>ctx.log(msg)</code>\n\n"
    "<b>Запрещено:</b> open, os, subprocess, socket, eval/exec, import telebot/aiogram/pyrogram,\n"
    "global/nonlocal, dunder-атрибуты, любые импорты вне whitelist.\n\n"
    "<b>Лимиты на вызов:</b> 5 сек CPU, ~25.6 МБ RAM, ≤10 HTTP, ≤5 сообщений, 10 вызовов/мин.\n\n"
    "📖 Полная документация: {docs_url}"
)


@router.callback_query(F.data == "commands_docs")
async def cb_docs(call: CallbackQuery) -> None:
    text = DOCS_TEXT.replace("{docs_url}", settings.DOCS_URL)
    url = settings.DOCS_URL if settings.DOCS_URL.startswith("http") else "https://telegram.org"
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📘 Открыть документацию", url=url)]])
    try: await call.message.edit_text(text, reply_markup=kb)
    except Exception: await call.message.answer(text, reply_markup=kb)
    await call.answer()


@router.message(F.text == "/docs")
async def cmd_docs(msg: Message) -> None:
    text = DOCS_TEXT.replace("{docs_url}", settings.DOCS_URL)
    url = settings.DOCS_URL if settings.DOCS_URL.startswith("http") else "https://telegram.org"
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📘 Открыть документацию", url=url)]])
    await msg.answer(text, reply_markup=kb)
