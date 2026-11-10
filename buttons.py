"""Реестр кнопок + кастомизация из БД."""
from __future__ import annotations
from typing import Optional
from aiogram.types import InlineKeyboardButton
from database import crud

DEFAULT_BUTTONS: dict[str, dict[str, str]] = {
    "menu_profile": {"label": "Профиль", "emoji": "👤"},
    "menu_commands": {"label": "Команды", "emoji": "📜"},
    "menu_buy": {"label": "Купить", "emoji": "💳"},
    "menu_docs": {"label": "Документация", "emoji": "📘"},
    "menu_promocodes": {"label": "Промокоды", "emoji": "🎟"},
    "menu_settings": {"label": "Настройки", "emoji": "⚙"},
    "menu_support": {"label": "Поддержка", "emoji": "🆘"},
    "menu_admin": {"label": "Админ-панель", "emoji": "👑"},
    "menu_back": {"label": "Назад", "emoji": "⬅"},
    "commands_my": {"label": "Мои команды", "emoji": "📂"},
    "commands_builtin": {"label": "Встроенные", "emoji": "🔧"},
    "commands_add": {"label": "Добавить", "emoji": "➕"},
    "commands_docs": {"label": "Документация", "emoji": "📘"},
    "pay_stars": {"label": "Оплатить 15 ⭐", "emoji": "💳"},
    "pay_extra_slot": {"label": "Купить слот (2 ⭐)", "emoji": "➕"},
    "support_new": {"label": "Создать тикет", "emoji": "🆕"},
    "admin_stats": {"label": "Статистика", "emoji": "📊"},
    "admin_hosting": {"label": "Хостинг", "emoji": "🖥"},
    "admin_refresh": {"label": "Обновить", "emoji": "🔄"},
    "admin_tickets": {"label": "Тикеты", "emoji": "📨"},
    "admin_promos": {"label": "Промокоды", "emoji": "🎟"},
    "admin_broadcast": {"label": "Рассылка", "emoji": "📢"},
    "admin_ui": {"label": "Интерфейс", "emoji": "🎨"},
    "admin_channels": {"label": "Каналы", "emoji": "🔗"},
    "admin_users": {"label": "Пользователи", "emoji": "👥"},
    "admin_back": {"label": "Назад", "emoji": "⬅"},
}


async def _resolve(key: str) -> tuple[str, str]:
    default = DEFAULT_BUTTONS.get(key, {"label": key, "emoji": ""})
    row = await crud.ui_button_get(key)
    label = (row["label"] if row and row["label"] else default["label"])
    emoji = (row["emoji"] if row and row["emoji"] else default["emoji"])
    return label, emoji


async def btn(key: str, *, callback_data: Optional[str] = None, url: Optional[str] = None) -> InlineKeyboardButton:
    label, emoji = await _resolve(key)
    
    # В кнопках Telegram НЕ поддерживает HTML-теги, только обычный текст
    text = f"{emoji} {label}".strip()
    
    if url:
        return InlineKeyboardButton(text=text, url=url)
    return InlineKeyboardButton(text=text, callback_data=callback_data or key)


async def btn_plain(text: str, *, callback_data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=callback_data)

async def btn_url(text: str, url: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, url=url)

async def main_menu_rows(is_admin: bool) -> list[list[InlineKeyboardButton]]:
    rows = [
        [await btn("menu_profile"), await btn("menu_commands")],
        [await btn("menu_buy"), await btn("menu_docs")],
        [await btn("menu_promocodes"), await btn("menu_settings")],
        [await btn("menu_support")],
    ]
    if is_admin: rows.append([await btn("menu_admin")])
    return rows
