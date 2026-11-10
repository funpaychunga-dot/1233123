"""Антифлуд + очередь + семафор. Мягкая деградация без бана."""
from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from contextlib import asynccontextmanager
from typing import AsyncIterator

from config import settings

logger = logging.getLogger(__name__)


class RateLimiter:
    """Мягкая деградация: не баним, а тормозим и ставим в очередь."""

    def __init__(self) -> None:
        self.msg_window = 1.0
        self.cmd_window = 60.0
        self.max_msgs = settings.RATE_LIMIT_MSGS_PER_SEC
        self.max_cmds = settings.RATE_LIMIT_CMDS_PER_MIN
        self.sem = asyncio.Semaphore(settings.GLOBAL_CONCURRENT_LIMIT)
        self.queue_size = 0
        self.max_queue = settings.QUEUE_MAX_SIZE
        self._user_msg: dict[int, deque[float]] = {}
        self._user_cmd: dict[int, deque[float]] = {}
        self._paused_until: dict[int, float] = {}
        self._rtt_samples: deque[float] = deque(maxlen=200)
        self._errors: deque[float] = deque(maxlen=2000)

    # --- утилиты ---
    @staticmethod
    def _now() -> float:
        return time.monotonic()

    @staticmethod
    def _prune(dq: deque[float], window: float) -> None:
        cutoff = time.monotonic() - window
        while dq and dq[0] < cutoff:
            dq.popleft()

    # --- пауза после флуда ---
    def is_paused(self, user_id: int) -> tuple[bool, int]:
        now = self._now()
        until = self._paused_until.get(user_id, 0.0)
        if until > now:
            return True, int(until - now) + 1
        if until and until <= now:
            self._paused_until.pop(user_id, None)
        return False, 0

    # --- проверки частоты ---
    def check_message(self, user_id: int) -> tuple[bool, str]:
        paused, secs = self.is_paused(user_id)
        if paused:
            return False, f"Не так быстро, подождите {secs} сек."
        dq = self._user_msg.setdefault(user_id, deque(maxlen=self.max_msgs * 4))
        self._prune(dq, self.msg_window)
        if len(dq) >= self.max_msgs:
            self._paused_until[user_id] = self._now() + 5.0
            logger.warning("Rate limit (msgs) user_id=%s — пауза 5с", user_id)
            return False, "Не так быстро, подождите 5 секунд."
        dq.append(self._now())
        return True, ""

    def check_command(self, user_id: int) -> tuple[bool, str]:
        dq = self._user_cmd.setdefault(user_id, deque(maxlen=self.max_cmds * 4))
        self._prune(dq, self.cmd_window)
        if len(dq) >= self.max_cmds:
            logger.warning("Rate limit (cmds) user_id=%s", user_id)
            return False, "Слишком много команд за минуту, попробуйте позже."
        dq.append(self._now())
        return True, ""

    # --- очередь + семафор ---
    @asynccontextmanager
    async def gate(self) -> AsyncIterator[bool]:
        """
        Использование:
            async with rate_limiter.gate() as ok:
                if not ok:
                    await msg.answer("Сервис перегружен, попробуйте через минуту.")
                    return
                ... бизнес-логика ...
        """
        if self.queue_size >= self.max_queue:
            logger.warning("Очередь переполнена (size=%s)", self.queue_size)
            yield False
            return
        self.queue_size += 1
        try:
            await self.sem.acquire()
        except asyncio.CancelledError:
            self.queue_size -= 1
            raise
        try:
            yield True
        finally:
            self.sem.release()
            self.queue_size -= 1

    # --- метрики для monitoring ---
    def record_rtt(self, ms: float) -> None:
        self._rtt_samples.append(ms)

    def record_error(self) -> None:
        self._errors.append(self._now())

    def stats(self) -> dict:
        now = self._now()
        cutoff_5m = now - 300.0
        cutoff_1m = now - 60.0
        avg = (sum(self._rtt_samples) / len(self._rtt_samples)) if self._rtt_samples else 0.0
        return {
            "queue_len": self.queue_size,
            "avg_rtt_ms": round(avg, 2),
            "errors_last_5min": sum(1 for t in self._errors if t >= cutoff_5m),
            "errors_last_1min": sum(1 for t in self._errors if t >= cutoff_1m),
            "active_users_msg": len(self._user_msg),
            "active_users_cmd": len(self._user_cmd),
        }


rate_limiter = RateLimiter()
