"""SQL-схема БД. Все даты — ISO-8601 UTC (TEXT)."""

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id                 INTEGER PRIMARY KEY,
    username           TEXT,
    first_name         TEXT,
    last_name          TEXT,
    subscription_until TEXT,
    trial_until        TEXT,
    trial_given        INTEGER NOT NULL DEFAULT 0,
    slots              INTEGER NOT NULL DEFAULT 5,
    is_admin           INTEGER NOT NULL DEFAULT 0,
    is_banned          INTEGER NOT NULL DEFAULT 0,
    created_at         TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at         TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS user_commands (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL,
    command_name TEXT NOT NULL,
    description  TEXT,
    version      TEXT,
    triggers     TEXT,
    source_path  TEXT NOT NULL,
    config_json  TEXT NOT NULL DEFAULT '{}',
    is_active    INTEGER NOT NULL DEFAULT 1,
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(user_id, command_name),
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_cmds_user ON user_commands(user_id);

CREATE TABLE IF NOT EXISTS command_kv (
    user_id      INTEGER NOT NULL,
    command_name TEXT NOT NULL,
    key          TEXT NOT NULL,
    value        TEXT,
    PRIMARY KEY(user_id, command_name, key)
);

CREATE TABLE IF NOT EXISTS saved_messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL,
    chat_id         INTEGER NOT NULL,
    kind            TEXT NOT NULL,
    from_user_id    INTEGER,
    from_username   TEXT,
    from_first_name TEXT,
    content         TEXT,
    media_path      TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_saved_user ON saved_messages(user_id);

CREATE TABLE IF NOT EXISTS payments (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL,
    provider     TEXT NOT NULL,
    amount       INTEGER NOT NULL,
    currency     TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'pending',
    payload_json TEXT,
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_payments_user ON payments(user_id);

CREATE TABLE IF NOT EXISTS tickets (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id        INTEGER NOT NULL,
    text           TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'open',
    admin_response TEXT,
    created_at     TEXT NOT NULL DEFAULT (datetime('now')),
    answered_at    TEXT
);
CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status);

CREATE TABLE IF NOT EXISTS promocodes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    code       TEXT NOT NULL UNIQUE,
    days       INTEGER NOT NULL,
    max_uses   INTEGER NOT NULL DEFAULT 0,
    used_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS promocode_uses (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    promocode_id INTEGER NOT NULL,
    user_id      INTEGER NOT NULL,
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(promocode_id, user_id),
    FOREIGN KEY(promocode_id) REFERENCES promocodes(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS rate_limits (
    user_id      INTEGER NOT NULL,
    action       TEXT NOT NULL,
    count        INTEGER NOT NULL DEFAULT 0,
    window_start TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY(user_id, action)
);

CREATE TABLE IF NOT EXISTS ui_buttons (
    button_key      TEXT PRIMARY KEY,
    label           TEXT,
    emoji           TEXT,
    custom_emoji_id TEXT,
    color           TEXT
);

CREATE TABLE IF NOT EXISTS ui_texts (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS metrics_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts         TEXT NOT NULL DEFAULT (datetime('now')),
    cpu        REAL,
    ram_used   REAL,
    disk_used  REAL,
    queue_len  INTEGER
);

CREATE TABLE IF NOT EXISTS required_channels (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id     TEXT NOT NULL,
    title       TEXT,
    invite_link TEXT,
    is_active   INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS audit_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER,
    action     TEXT NOT NULL,
    details    TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""
