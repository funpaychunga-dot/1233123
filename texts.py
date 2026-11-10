"""Тексты из БД (ui_texts) с fallback на дефолты."""
from __future__ import annotations

from database import crud

DEFAULT_TEXTS: dict[str, str] = {
    "start.welcome": (
        "👋 Привет, <b>{user}</b>!\n\n"
        "Я — Спаситель сообщений. Подключите меня к своему Telegram Business,\n"
        "и я перешлю вам копии удалённых, изменённых и исчезающих сообщений.\n\n"
        "🎁 Пробный период: <b>{days_left} дн.</b>"
    ),
    "profile.title": (
        "👤 <b>Профиль</b>\n\n"
        "Имя: {user}\n"
        "ID: <code>{user_id}</code>\n"
        "Статус: {sub_status}\n"
        "Слотов команд: {slots} / {max_slots}"
    ),
    "menu.commands": "📜 <b>Раздел «Команды»</b>\n\nВыберите действие:",
    "buy.title": (
        "💳 <b>Оплата подписки</b>\n\n"
        "Подписка: <b>{price} ⭐ / {days} дн.</b>\n"
        "Один слот личной команды: <b>{extra_price} ⭐</b>"
    ),
    "promocodes.title": "🎟 <b>Промокоды</b>\n\nВведите код в ответ на это сообщение:",
    "settings.title": "⚙ <b>Настройки</b>",
    "support.title": "🆘 <b>Поддержка</b>\n\nОпишите проблему в ответ на это сообщение, и мы ответим.",
    "admin.title": "👑 <b>Админ-панель</b>",
    
    # --- Уведомления (добавлен курсив <i> для заголовков) ---
    "notification.deleted":       "🤙 <i>Спас удаление от {ник} (@{username})</i>",
    "notification.edited":        "🤙 <i>Спас изменение от {ник} (@{username})</i>",
    "notification.disappearing":  "🤙 <i>Спас сообщение (только для одноразовых) от {ник} (@{username})</i>",
    "notification.clone":         "👥 <i>Сообщение от {ник} (@{username})</i>",
    
    "subscription.expired": (
        "⏰ <b>Подписка истекла</b>\n\n"
        "Оплатите 15 ⭐ для продления на 30 дней — и я продолжу работать."
    ),
    "subscription.trial_left":  "🎁 Осталось {days_left} дн. пробного периода",
    "subscription.paid_left":   "✅ Подписка: осталось {days_left} дн.",
    
    "mute.set":            "🔇 Замьючен на {seconds} сек.",
    "mute.cleared":        "🔊 Размьючен.",
    "mute.need_reply":     "⚠ Ответьте на сообщение автора, чтобы замьютить его.",
    "mute.cant_self":      "⚠ Нельзя замьютить самого себя.",
    
    "clone.enabled":       "👥 Клон включён. Сообщения будут дублироваться в личку.",
    "clone.disabled":      "🚫 Клон выключен.",
    "clone.not_business":  "ℹ Команда доступна только в Business-чате владельца.",
    
    "spam.invalid":        "⚠ Формат: <code>.спам 3 текст сообщения</code>",
    "spam.too_many":       "⚠ Не больше {max} сообщений за раз.",
    
    "auto_reply.set":      "✅ Авто-ответ установлен:\n{text_preview}",
    "auto_reply.disabled": "🚫 Авто-ответ выключен.",
    "auto_reply.current":  "📝 Текущий авто-ответ:\n{text}\n\nОтключить: <code>.автоответ off</code>",
    "auto_reply.empty":    "ℹ У вас нет активного авто-ответа.\nУстановить: <code>.автоответ Привет, {ник}!</code>",
    
    "err.unknown":         "⚠ Что-то пошло не так. Попробуйте позже.",
    "err.too_fast":        "Не так быстро, подождите 5 секунд.",
    "err.subscription":    "⏰ <b>Подписка истекла</b> — оплатите 15 ⭐ для продолжения работы.",
}

async def get_text(key: str, **kwargs: object) -> str:
    row_value = await crud.ui_text_get(key)
    template = row_value if row_value is not None else DEFAULT_TEXTS.get(key, f"[{key}]")
    try:
        return template.format(**kwargs)
    except KeyError as e:
        return template + f"\n\n⚠ Плейсхолдер {e} не передан"
    except Exception:
        return template

async def set_text(key: str, value: str) -> None:
    await crud.ui_text_set(key, value)
