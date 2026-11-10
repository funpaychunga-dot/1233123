"""Встроенные команды (работают в Business и в обычных чатах)."""
from __future__ import annotations
import asyncio, logging
from datetime import timedelta
from typing import Optional

from aiogram import Bot, F, Router
from aiogram.types import Message

from database import crud, crud_business as cdb
from services.subscription import subscription_service
from ui.texts import get_text

logger = logging.getLogger(__name__)
router = Router(name="commands")

SPAM_MAX = 10
SPAM_DELAY = 0.5
_spam_tasks: dict[int, asyncio.Task] = {}


async def _get_owner(bot: Bot, msg: Message) -> Optional[int]:
    if msg.business_connection_id:
        return await cdb.get_business_owner(msg.business_connection_id)
    if msg.from_user:
        return msg.from_user.id
    return None


async def _is_admin_or_owner(bot: Bot, msg: Message, owner_id: Optional[int]) -> bool:
    if owner_id is None: return False
    if msg.from_user and msg.from_user.id == owner_id:
        return True
    if msg.chat.type in ("group", "supergroup") and msg.from_user:
        try:
            member = await bot.get_chat_member(msg.chat.id, msg.from_user.id)
            if member.status in ("administrator", "creator"):
                return True
        except Exception:
            pass
    return False


async def _check_sub(msg: Message, bot: Bot, owner: Optional[int]) -> bool:
    if owner is None:
        return False
    if await subscription_service.is_active(owner):
        return True
    try:
        await bot.send_message(
            chat_id=msg.chat.id,
            text=await get_text("subscription.expired"),
            business_connection_id=msg.business_connection_id)
    except Exception:
        pass
    return False


async def cmd_mute(msg: Message, bot: Bot) -> None:
    logger.info("CMD .мут от %s", msg.from_user.id if msg.from_user else "?")
    o = await _get_owner(bot, msg)
    if o is None or not await _is_admin_or_owner(bot, msg, o):
        return
    if not await _check_sub(msg, bot, o):
        return
    
    parts = msg.text.split(maxsplit=1)
    arg = parts[1] if len(parts) > 1 else ""
    try:
        s = int(arg.split()[0]) if arg else 60
        s = max(5, min(s, 86400))
    except (ValueError, IndexError):
        await msg.reply("⚠ Используйте: .мут [секунды] в ответ на сообщение."); return
        
    tgt = msg.reply_to_message.from_user if msg.reply_to_message else None
    if tgt is None:
        await msg.reply(await get_text("mute.need_reply")); return
    if tgt.id == o:
        await msg.reply(await get_text("mute.cant_self")); return
    await cdb.set_mute(msg.chat.id, tgt.id, crud.utcnow() + timedelta(seconds=s))
    await msg.reply(await get_text("mute.set", seconds=s))


async def cmd_unmute(msg: Message, bot: Bot) -> None:
    logger.info("CMD .размут от %s", msg.from_user.id if msg.from_user else "?")
    o = await _get_owner(bot, msg)
    if o is None or not await _is_admin_or_owner(bot, msg, o):
        return
    if not await _check_sub(msg, bot, o):
        return
    tgt = msg.reply_to_message.from_user if msg.reply_to_message else None
    if tgt is None:
        await msg.reply(await get_text("mute.need_reply")); return
    await cdb.clear_mute(msg.chat.id, tgt.id)
    await msg.reply(await get_text("mute.cleared"))


async def cmd_clone(msg: Message, bot: Bot) -> None:
    logger.info("CMD .клон от %s", msg.from_user.id if msg.from_user else "?")
    o = await _get_owner(bot, msg)
    if o is None or not await _is_admin_or_owner(bot, msg, o):
        await msg.reply(await get_text("clone.not_business")); return
    if not await _check_sub(msg, bot, o):
        return
    await cdb.enable_clone(msg.chat.id, o)
    await msg.reply(await get_text("clone.enabled"))


async def cmd_unclone(msg: Message, bot: Bot) -> None:
    logger.info("CMD .разклон от %s", msg.from_user.id if msg.from_user else "?")
    o = await _get_owner(bot, msg)
    if o is None or not await _is_admin_or_owner(bot, msg, o):
        return
    if not await _check_sub(msg, bot, o):
        return
    await cdb.disable_clone(msg.chat.id)
    await msg.reply(await get_text("clone.disabled"))


async def cmd_spam(msg: Message, bot: Bot) -> None:
    logger.info("CMD .спам от %s: %s", msg.from_user.id if msg.from_user else "?", msg.text)
    if not msg.text: return
    parts = msg.text.split(maxsplit=2)
    if len(parts) < 3:
        await msg.reply(await get_text("spam.invalid")); return
    try:
        count = int(parts[1])
    except ValueError:
        await msg.reply(await get_text("spam.invalid")); return
    
    text = parts[2]
    if count < 1 or count > SPAM_MAX:
        await msg.reply(await get_text("spam.too_many", max=SPAM_MAX)); return
        
    if msg.from_user:
        prev = _spam_tasks.get(msg.from_user.id)
        if prev and not prev.done():
            prev.cancel()
            
    kw: dict = {}
    if msg.business_connection_id:
        kw["business_connection_id"] = msg.business_connection_id
        
    async def _job() -> None:
        try:
            for _ in range(count):
                await bot.send_message(chat_id=msg.chat.id, text=text, **kw)
                await asyncio.sleep(SPAM_DELAY)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.warning("spam: %s", e)
        finally:
            if msg.from_user:
                _spam_tasks.pop(msg.from_user.id, None)
                
    if msg.from_user:
        _spam_tasks[msg.from_user.id] = asyncio.create_task(_job())


async def cmd_auto_reply(msg: Message, bot: Bot) -> None:
    logger.info("CMD .автоответ от %s", msg.from_user.id if msg.from_user else "?")
    o = await _get_owner(bot, msg)
    if o is None or not await _is_admin_or_owner(bot, msg, o):
        return
    if not await _check_sub(msg, bot, o):
        return
        
    parts = msg.text.split(maxsplit=1)
    arg = parts[1].strip() if len(parts) > 1 else ""
    
    if not arg:
        cur = await cdb.get_auto_reply(o)
        if cur and cur["is_active"]:
            await msg.reply(await get_text("auto_reply.current", text=cur["text"]))
        else:
            await msg.reply(await get_text("auto_reply.empty"))
        return
        
    if arg.lower() == "off":
        await cdb.disable_auto_reply(o)
        await msg.reply(await get_text("auto_reply.disabled")); return
        
    await cdb.set_auto_reply(o, arg, True)
    prev = arg[:150] + ("…" if len(arg) > 150 else "")
    await msg.reply(await get_text("auto_reply.set", text_preview=prev))


# Регистрация для обычных сообщений (в личке, группах)
router.message(F.text.regexp(r"^\.мут(?:\s|$)"))(cmd_mute)
router.message(F.text.regexp(r"^\.размут(?:\s|$)"))(cmd_unmute)
router.message(F.text.regexp(r"^\.клон(?:\s|$)"))(cmd_clone)
router.message(F.text.regexp(r"^\.разклон(?:\s|$)"))(cmd_unclone)
router.message(F.text.regexp(r"^\.спам(?:\s|$)"))(cmd_spam)
router.message(F.text.regexp(r"^\.автоответ(?:\s|$)"))(cmd_auto_reply)

# Регистрация для Business-сообщений
router.business_message(F.text.regexp(r"^\.мут(?:\s|$)"))(cmd_mute)
router.business_message(F.text.regexp(r"^\.размут(?:\s|$)"))(cmd_unmute)
router.business_message(F.text.regexp(r"^\.клон(?:\s|$)"))(cmd_clone)
router.business_message(F.text.regexp(r"^\.разклон(?:\s|$)"))(cmd_unclone)
router.business_message(F.text.regexp(r"^\.спам(?:\s|$)"))(cmd_spam)
router.business_message(F.text.regexp(r"^\.автоответ(?:\s|$)"))(cmd_auto_reply)
