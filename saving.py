"""Сохранение и пересылка удалённых / изменённых / исчезающих сообщений."""
from __future__ import annotations
import asyncio, logging
from collections import OrderedDict
from pathlib import Path
from typing import Any, Optional

from aiogram import Bot, Router
from aiogram.types import (
    BusinessConnection, BusinessMessagesDeleted, Message, FSInputFile
)

from config import settings
from database import crud, crud_business as cdb
from services.subscription import subscription_service
from ui.texts import get_text

logger = logging.getLogger(__name__)
router = Router(name="saving")


@router.startup()
async def _startup_saving() -> None:
    from database.migrations import apply_migrations
    await apply_migrations()


class MessageCache:
    def __init__(self, max_size: int = 5000) -> None:
        self._data: "OrderedDict[tuple[int, int], tuple[Message, Optional[Path]]]" = OrderedDict()
        self._max = max_size
        self._lock = asyncio.Lock()

    async def put(self, msg: Message, file_path: Optional[Path] = None) -> None:
        async with self._lock:
            key = (msg.chat.id, msg.message_id)
            old = self._data.get(key)
            if old and old[1] and old[1] != file_path:
                try: old[1].unlink(missing_ok=True)
                except Exception: pass
            self._data[key] = (msg, file_path)
            self._data.move_to_end(key)
            while len(self._data) > self._max:
                _, (_, f) = self._data.popitem(last=False)
                if f:
                    try: f.unlink(missing_ok=True)
                    except Exception: pass

    async def get(self, chat_id: int, message_id: int) -> Optional[tuple[Message, Optional[Path]]]:
        async with self._lock:
            item = self._data.get((chat_id, message_id))
            if item is not None:
                self._data.move_to_end((chat_id, message_id))
            return item

    async def pop(self, chat_id: int, message_id: int) -> Optional[tuple[Message, Optional[Path]]]:
        async with self._lock:
            return self._data.pop((chat_id, message_id), None)


cache = MessageCache()


def _nick(msg: Message) -> str:
    if msg.from_user and msg.from_user.first_name:
        return msg.from_user.first_name
    if msg.sender_chat and msg.sender_chat.title:
        return msg.sender_chat.title
    return "—"


def _username(msg: Message) -> str:
    if msg.from_user and msg.from_user.username:
        return msg.from_user.username
    return "—"


async def _download_media(bot: Bot, msg: Message) -> Optional[Path]:
    file_id = None
    ext = ""
    if msg.photo: file_id = msg.photo[-1].file_id; ext = ".jpg"
    elif msg.video: file_id = msg.video.file_id; ext = ".mp4"
    elif msg.audio: file_id = msg.audio.file_id; ext = ".mp3"
    elif msg.voice: file_id = msg.voice.file_id; ext = ".ogg"
    elif msg.video_note: file_id = msg.video_note.file_id; ext = ".mp4"
    elif msg.animation: file_id = msg.animation.file_id; ext = ".mp4"
    elif msg.sticker: file_id = msg.sticker.file_id; ext = ".webp"
    elif msg.document: file_id = msg.document.file_id; ext = ".file"

    if not file_id: return None

    try:
        file = await bot.get_file(file_id)
        local = settings.media_cache_dir / f"{msg.message_id}_{file.file_unique_id}{ext}"
        await bot.download_file(file.file_path, destination=str(local))
        return local
    except Exception as e:
        logger.warning("Не удалось скачать медиа %s: %s", file_id, e)
        return None


async def _send_by_kind(bot: Bot, chat_id: int, kind: str, source: Any, caption: Optional[str]) -> None:
    if isinstance(source, Path):
        source = FSInputFile(source)

    if kind == "photo": await bot.send_photo(chat_id=chat_id, photo=source, caption=caption)
    elif kind == "video": await bot.send_video(chat_id=chat_id, video=source, caption=caption)
    elif kind == "audio": await bot.send_audio(chat_id=chat_id, audio=source, caption=caption)
    elif kind == "voice": await bot.send_voice(chat_id=chat_id, voice=source, caption=caption)
    elif kind == "video_note": await bot.send_video_note(chat_id=chat_id, video_note=source)
    elif kind == "animation": await bot.send_animation(chat_id=chat_id, animation=source, caption=caption)
    elif kind == "sticker": await bot.send_sticker(chat_id=chat_id, sticker=source)
    elif kind == "document": await bot.send_document(chat_id=chat_id, document=source, caption=caption)
    else: raise ValueError(f"Неизвестный kind: {kind}")


async def _send_content(bot: Bot, chat_id: int, msg: Message, file_path: Optional[Path] = None) -> None:
    if msg.text:
        await bot.send_message(chat_id=chat_id, text=msg.text)
        return

    caption = msg.caption or None
    source = file_path if file_path else None

    if msg.photo: await _send_by_kind(bot, chat_id, "photo", source or msg.photo[-1].file_id, caption)
    elif msg.video: await _send_by_kind(bot, chat_id, "video", source or msg.video.file_id, caption)
    elif msg.audio: await _send_by_kind(bot, chat_id, "audio", source or msg.audio.file_id, caption)
    elif msg.voice: await _send_by_kind(bot, chat_id, "voice", source or msg.voice.file_id, caption)
    elif msg.video_note: await _send_by_kind(bot, chat_id, "video_note", source or msg.video_note.file_id, None)
    elif msg.animation: await _send_by_kind(bot, chat_id, "animation", source or msg.animation.file_id, caption)
    elif msg.sticker: await _send_by_kind(bot, chat_id, "sticker", source or msg.sticker.file_id, None)
    elif msg.document: await _send_by_kind(bot, chat_id, "document", source or msg.document.file_id, caption)
    elif msg.poll: await bot.send_message(chat_id=chat_id, text=f"📊 Опрос: {msg.poll.question}")
    elif caption: await bot.send_message(chat_id=chat_id, text=caption)
    else: await bot.send_message(chat_id=chat_id, text=f"⚠ Вложение (тип: {msg.content_type})")


async def _ensure_owner_user(owner_id: int, conn: Optional[BusinessConnection] = None) -> None:
    if await crud.get_user(owner_id) is not None: return
    if conn and conn.user:
        u = conn.user
        await crud.get_or_create_user(u.id, u.username, u.first_name, u.last_name)
    else:
        await crud.get_or_create_user(owner_id, None, None, None)


@router.business_connection()
async def on_business_connection(conn: BusinessConnection, bot: Bot) -> None:
    await cdb.save_business_connection(conn.id, conn.user.id, conn.is_enabled)
    await _ensure_owner_user(conn.user.id, conn)
    logger.info("Business connection id=%s owner=%s enabled=%s", conn.id, conn.user.id, conn.is_enabled)
    if conn.is_enabled:
        try:
            await bot.send_message(
                chat_id=conn.user.id,
                text=(
                    "✅ <b>Бот успешно подключён к вашему Business-аккаунту!</b>\n\n"
                    "Теперь я буду сохранять удалённые, изменённые и исчезающие сообщения.\n"
                    "Проверить работу можно командой <code>.мут</code> или <code>.клон</code>."
                ),
            )
        except Exception: pass


@router.business_message()
async def on_business_message(msg: Message, bot: Bot) -> None:
    if not msg.business_connection_id: return
    owner_id = await cdb.get_business_owner(msg.business_connection_id)
    if owner_id is None:
        try:
            conn = await bot.get_business_connection(msg.business_connection_id)
            owner_id = conn.user.id
            await cdb.save_business_connection(conn.id, owner_id, conn.is_enabled)
            await _ensure_owner_user(owner_id, conn)
        except Exception:
            return
    if not await subscription_service.is_active(owner_id): return
    if msg.from_user and msg.from_user.id == owner_id: return
    
    if msg.from_user and await cdb.is_muted(msg.chat.id, msg.from_user.id):
        try:
            await bot.delete_business_messages(
                business_connection_id=msg.business_connection_id,
                message_ids=[msg.message_id],
            )
        except Exception as e: logger.warning("delete_business_messages %s: %s", msg.message_id, e)
        return
        
    if msg.from_user:
        auto = await cdb.get_auto_reply(owner_id)
        if auto and auto["is_active"]:
            nick = msg.from_user.first_name or msg.from_user.username or "друг"
            try:
                await bot.send_message(
                    chat_id=msg.chat.id,
                    text=auto["text"].replace("{ник}", nick),
                    business_connection_id=msg.business_connection_id,
                )
            except Exception as e: logger.warning("auto-reply: %s", e)
                
    clone_owner = await cdb.get_clone_owner(msg.chat.id)
    if clone_owner:
        try:
            header = await get_text("notification.clone", ник=_nick(msg), username=_username(msg))
            file_path = await _download_media(bot, msg)
            await bot.send_message(chat_id=clone_owner, text=header)
            await _send_content(bot, clone_owner, msg, file_path)
            if file_path: file_path.unlink(missing_ok=True)
        except Exception: logger.exception("clone forward")

    file_path = await _download_media(bot, msg)
        
    if msg.effect_id or msg.has_media_spoiler:
        try:
            header = await get_text("notification.disappearing", ник=_nick(msg), username=_username(msg))
            if msg.text:
                text = f"{header}\n\n<blockquote>{msg.text}</blockquote>"
                await bot.send_message(chat_id=owner_id, text=text)
            else:
                await bot.send_message(chat_id=owner_id, text=header)
                await _send_content(bot, owner_id, msg, file_path)
                
            if file_path: file_path.unlink(missing_ok=True)
            await crud.save_saved_message(
                user_id=owner_id, chat_id=msg.chat.id, kind="disappearing",
                from_user_id=msg.from_user.id if msg.from_user else None,
                from_username=msg.from_user.username if msg.from_user else None,
                from_first_name=msg.from_user.first_name if msg.from_user else None,
                content=(msg.text or msg.caption or "")[:2000],
            )
        except Exception: logger.exception("disappearing forward")
        return

    await cache.put(msg, file_path)


@router.edited_business_message()
async def on_edited_business_message(msg: Message, bot: Bot) -> None:
    if not msg.business_connection_id: return
    owner_id = await cdb.get_business_owner(msg.business_connection_id)
    if owner_id is None: return
    if msg.from_user and msg.from_user.id == owner_id: return
    if not await subscription_service.is_active(owner_id): return
        
    old_item = await cache.get(msg.chat.id, msg.message_id)
    old_msg = old_item[0] if old_item else None
    old_file = old_item[1] if old_item else None
    
    file_path = await _download_media(bot, msg)
    await cache.put(msg, file_path)
    
    header = await get_text("notification.edited", ник=_nick(msg), username=_username(msg))
    
    if old_msg and old_msg.text and msg.text:
        text = f"{header}\n\n<blockquote>{old_msg.text}</blockquote>\n\n⇩⇩⇩\n\n<blockquote>{msg.text}</blockquote>"
        await bot.send_message(chat_id=owner_id, text=text)
    else:
        await bot.send_message(chat_id=owner_id, text=header)
        if old_msg:
            await _send_content(bot, owner_id, old_msg, old_file)
            if old_file: old_file.unlink(missing_ok=True)
        else:
            await bot.send_message(chat_id=owner_id, text="<blockquote>(старая версия не найдена)</blockquote>")
        await bot.send_message(chat_id=owner_id, text="⇩⇩⇩")
        await _send_content(bot, owner_id, msg, file_path)
    
    await crud.save_saved_message(
        user_id=owner_id, chat_id=msg.chat.id, kind="edited",
        from_user_id=msg.from_user.id if msg.from_user else None,
        from_username=msg.from_user.username if msg.from_user else None,
        from_first_name=msg.from_user.first_name if msg.from_user else None,
        content=(msg.text or msg.caption or "")[:2000],
    )


@router.deleted_business_messages()
async def on_deleted_business_messages(event: BusinessMessagesDeleted, bot: Bot) -> None:
    if not event.business_connection_id: return
    owner_id = await cdb.get_business_owner(event.business_connection_id)
    if owner_id is None: return
    if not await subscription_service.is_active(owner_id): return
    for message_id in event.message_ids:
        item = await cache.pop(event.chat.id, message_id)
        if item is None: continue
        cached, file_path = item
        if cached.from_user and cached.from_user.id == owner_id: continue
        try:
            header = await get_text("notification.deleted", ник=_nick(cached), username=_username(cached))
            
            # Если это текст, склеиваем в одно сообщение
            if cached.text:
                text = f"{header}\n\n<blockquote>{cached.text}</blockquote>"
                await bot.send_message(chat_id=owner_id, text=text)
            else:
                await bot.send_message(chat_id=owner_id, text=header)
                await _send_content(bot, owner_id, cached, file_path)
                
            if file_path: file_path.unlink(missing_ok=True)
            await crud.save_saved_message(
                user_id=owner_id, chat_id=event.chat.id, kind="deleted",
                from_user_id=cached.from_user.id if cached.from_user else None,
                from_username=cached.from_user.username if cached.from_user else None,
                from_first_name=cached.from_user.first_name if cached.from_user else None,
                content=(cached.text or cached.caption or "")[:2000],
            )
        except Exception: logger.exception("deleted forward %s", message_id)
