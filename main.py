"""Точка входа. Middleware + порядок роутеров."""
from __future__ import annotations
import asyncio, importlib, logging, logging.handlers, sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from config import settings
from database.db import Database
from services.crypto import Crypto


MODULES_TO_LOAD: list[str] = [
    "handlers.start",
    "handlers.commands",     # <-- ВАЖНО: команды ДО saving
    "handlers.saving",
    "handlers.payments",
    "handlers.support",
    "handlers.promocodes",
    "handlers.admin",
    "handlers.upload_command",
]


def setup_logging() -> logging.Logger:
    settings.ensure_dirs()
    ld = settings.logs_root
    root = logging.getLogger(); root.setLevel(logging.INFO)
    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(name)-30s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S")
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.INFO); console.setFormatter(fmt); root.addHandler(console)

    file_console = logging.handlers.RotatingFileHandler(
        ld / "console.log", maxBytes=5*1024*1024, backupCount=5, encoding="utf-8")
    file_console.setLevel(logging.INFO); file_console.setFormatter(fmt); root.addHandler(file_console)

    fa = logging.handlers.RotatingFileHandler(
        ld / "bot.log", maxBytes=5*1024*1024, backupCount=5, encoding="utf-8")
    fa.setLevel(logging.INFO); fa.setFormatter(fmt); root.addHandler(fa)

    fe = logging.handlers.RotatingFileHandler(
        ld / "errors.log", maxBytes=5*1024*1024, backupCount=5, encoding="utf-8")
    fe.setLevel(logging.ERROR); fe.setFormatter(fmt); root.addHandler(fe)

    logging.getLogger("aiogram.event").setLevel(logging.WARNING)
    return logging.getLogger("savior")


async def load_modules(dp: Dispatcher, logger: logging.Logger) -> list[str]:
    loaded: list[str] = []
    for path in MODULES_TO_LOAD:
        try:
            mod = importlib.import_module(path)
        except ModuleNotFoundError as e:
            logger.warning("Модуль %s отсутствует: %s", path, e); continue
        except Exception as e:
            logger.exception("Ошибка импорта %s: %s", path, e); continue
        r = getattr(mod, "router", None)
        if r is None:
            logger.warning("В %s нет router", path); continue
        try:
            dp.include_router(r)
            loaded.append(path)
            logger.info("Роутер: %s", path)
        except Exception as e:
            logger.exception("Роутер %s: %s", path, e)
    return loaded


async def main() -> None:
    logger = setup_logging()
    logger.info("=== @%s v%s ===", settings.BOT_USERNAME, settings.BOT_VERSION)
    await Database.init()
    try:
        Crypto.init(); logger.info("Fernet OK")
    except Exception as e:
        logger.error("Crypto: %s", e)
    bot = Bot(
        token=settings.BOT_TOKEN.get_secret_value(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())

    try:
        from handlers.start import SubscriptionMiddleware
        dp.message.outer_middleware(SubscriptionMiddleware())
        dp.callback_query.outer_middleware(SubscriptionMiddleware())
        logger.info("SubscriptionMiddleware подключён")
    except Exception as e:
        logger.warning("Middleware: %s", e)

    loaded = await load_modules(dp, logger)
    logger.info("Загружено: %d / %d", len(loaded), len(MODULES_TO_LOAD))

    from aiogram.types import ErrorEvent

    @dp.error()
    async def _err(event: ErrorEvent):
        logger.exception("Ошибка: %s", event.exception)
        try:
            from services.rate_limiter import rate_limiter
            rate_limiter.record_error()
        except Exception:
            pass
        for aid in settings.admin_ids:
            try:
                await bot.send_message(
                    aid,
                    f"⚠ <b>Ошибка</b>\n<code>{type(event.exception).__name__}: "
                    f"{event.exception}</code>")
            except Exception:
                pass
        return True

    try:
        await bot.delete_webhook(drop_pending_updates=False)
        await dp.start_polling(
            bot,
            allowed_updates=[
                "message", "callback_query", "pre_checkout_query",
                "business_connection", "business_message",
                "edited_business_message", "deleted_business_messages"
            ]
        )
    finally:
        await Database.close()
        await bot.session.close()
        logger.info("Остановлен")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("\nВыход.")
