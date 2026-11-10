# Спаситель сообщений - @YourSaviorRobot

Telegram-бот, который через **Telegram Business** пересылает владельцу копии
**удалённых / изменённых / исчезающих** сообщений. Плюс `.py`-плагины,
подписка за звёзды, триал и админ-панель.

## Возможности

- Спасение сообщений: удаления, редактирования, disappearing-контент
- Встроенные команды: .мут, .размут, .клон, .разклон, .спам, .автоответ
- Личные плагины: настоящие .py с `async def handler(ctx)`, AST-валидация,
  multiprocessing + RLIMIT_CPU/AS, лимиты
- Оплата звёздами: 15 ⭐ / 30 дней, доп. слоты 2 ⭐
- Триал 5 дней автоматически при первом /start
- Промокоды, тикеты, админ-панель
- Мониторинг psutil: RAM/CPU/диск/сеть/процессы/очередь
- Кастомизация UI: эмодзи, подписи кнопок, все тексты из БД
- Антифлуд с мягкой деградацией

## Установка

    python -m venv .venv
    .venv\Scripts\activate       (Windows)
    source .venv/bin/activate    (Linux/Mac)
    pip install -r requirements.txt
    cp .env.example .env

Отредактируйте `.env`:

- `BOT_TOKEN` - от @BotFather
- `ADMIN_IDS` - ваш Telegram ID
- `FERNET_KEY` - сгенерируйте:
  `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`

## Запуск

    python main.py

## Подключение Business

**С Premium:** Настройки - Telegram Business - Чат-боты - @YourSaviorRobot - Подключить

**Без Premium:** Настройки - Изменить профиль - Автоматизация чатов - Подключить - @YourSaviorRobot

## Плагины

Пришлите боту `.py`-файл (не более 64 КБ) через `/upload`:

    COMMAND_NAME = "hello"
    COMMAND_TRIGGERS = ["/hello", ".привет"]

    async def handler(ctx):
        await ctx.send_message(f"Привет, {ctx.user.first_name}!")

В `ctx` доступно:
- `ctx.user`, `ctx.chat_id`, `ctx.message_text`, `ctx.args`, `ctx.config`
- `await ctx.send_message(text)`, `send_photo`, `send_document`
- `await ctx.http_get(url)`, `http_post(url, json)`
- `await ctx.telegram.get_chat("@username")`
- `await ctx.db_get(key)` / `db_set(key, value)`
- `ctx.log(msg)`

**Запрещено:** open, os, subprocess, socket, eval/exec, global/nonlocal,
dunder-атрибуты, импорты вне whitelist.

**Лимиты:** 5 сек CPU, 25.6 МБ RAM, 10 HTTP, 5 сообщений, 10 вызовов/мин.

## Docker

    docker build -t savior_bot .
    docker run -d --name savior --env-file .env \
      -v "$(pwd)/data:/app/data" \
      -v "$(pwd)/commands:/app/commands" \
      -v "$(pwd)/logs:/app/logs" \
      savior_bot

## Структура

    main.py            - запуск + middleware
    config.py          - настройки из .env
    handlers/          - start, saving, commands, upload_command,
                         payments, support, promocodes, admin
    services/          - crypto, rate_limiter, subscription, monitoring,
                         command_sandbox, command_context, command_worker,
                         command_executor, payments/
    database/          - db, models, crud, crud_business, migrations
    ui/                - buttons, texts
    commands/user_id/  - исходники плагинов
    data/, logs/

## Траблшутинг

- `Fernet key` error: перегенерируйте FERNET_KEY (на чистой БД)
- `Business connection` не приходит: нужен Premium ИЛИ автоматизация чатов
- RLIMIT_* не работают: это нормально на Windows; используйте Docker на Linux
- `send_invoice PROVIDER_ACCOUNT_INVALID`: подключите Stars в @BotFather - Payments
- Логи: `logs/bot.log` (INFO+), `logs/errors.log` (только ERROR)

## Лицензия

MIT
