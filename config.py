"""Централизованные настройки. Все секреты — через .env."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8",
        extra="ignore", case_sensitive=False,
    )

    BOT_TOKEN: SecretStr
    BOT_USERNAME: str = "YourSaviorRobot"
    BOT_VERSION: str = "1.0.0"
    ADMIN_IDS: str = ""

    FERNET_KEY: SecretStr

    DB_PATH: str = "data/savior.db"
    COMMANDS_DIR: str = "commands"
    LOGS_DIR: str = "logs"

    SUBSCRIPTION_PRICE_STARS: int = 15
    SUBSCRIPTION_DAYS: int = 30
    TRIAL_DAYS: int = 5
    FREE_COMMAND_SLOTS: int = 5
    MAX_COMMAND_SLOTS: int = 25
    EXTRA_SLOT_PRICE_STARS: int = 2

    MAX_COMMAND_FILE_BYTES: int = 64 * 1024
    COMMAND_EXEC_TIMEOUT: int = 5
    COMMAND_MAX_HTTP: int = 10
    COMMAND_MAX_MESSAGES: int = 5
    COMMAND_CPU_LIMIT: int = 5
    COMMAND_MEM_LIMIT_BYTES: int = 26_214_400

    RATE_LIMIT_MSGS_PER_SEC: int = 5
    RATE_LIMIT_CMDS_PER_MIN: int = 10
    GLOBAL_CONCURRENT_LIMIT: int = 50
    QUEUE_MAX_SIZE: int = 100

    DOCS_URL: str = "https://telegram.org"  # <-- Исправлено!
    SANDBOX_PAYMENTS: bool = True

    @property
    def admin_ids(self) -> set[int]:
        return {int(x.strip()) for x in self.ADMIN_IDS.split(",") if x.strip().lstrip("-").isdigit()}

    @property
    def db_path(self) -> Path:
        return Path(self.DB_PATH)

    @property
    def commands_root(self) -> Path:
        return Path(self.COMMANDS_DIR)

    @property
    def logs_root(self) -> Path:
        return Path(self.LOGS_DIR)

    @property
    def media_cache_dir(self) -> Path:
        return self.logs_root / "media_cache"

    def ensure_dirs(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.commands_root.mkdir(parents=True, exist_ok=True)
        self.logs_root.mkdir(parents=True, exist_ok=True)
        self.media_cache_dir.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    s = Settings()  # type: ignore[call-arg]
    s.ensure_dirs()
    return s


settings = get_settings()
