"""ctx для плагинов. Выполняется ВНУТРИ subprocess, только stdlib.

Все 'опасные' действия (send_message, http_get, ...) транслируются
в HTTP-запросы к родительскому процессу (CommandExecutor), который
применяет политики и говорит с ботом.
"""
from __future__ import annotations

import asyncio
import http.client
import json
import threading
from typing import Any, Optional


class _User:
    """Лёгкий снимок пользователя."""
    __slots__ = ("id", "first_name", "username")

    def __init__(self, data: dict) -> None:
        self.id: Optional[int] = data.get("id")
        self.first_name: Optional[str] = data.get("first_name")
        self.username: Optional[str] = data.get("username")


class _TelegramNamespace:
    def __init__(self, parent: "SandboxContext") -> None:
        self._parent = parent

    async def get_chat(self, target: str) -> dict:
        return await self._parent._call("get_chat", {"target": target})


class SandboxContext:
    """Публичный контракт для плагинов."""

    def __init__(
        self,
        port: int,
        token: str,
        session_id: str,
        config: dict,
        limits: dict,
    ) -> None:
        self._port = port
        self._token = token
        self._session_id = session_id
        self._limits = limits
        # заполняется worker'ом до вызова handler():
        self.user = _User({})
        self.chat_id: int = 0
        self.message_text: str = ""
        self.args: str = ""
        self.config: dict = config or {}
        self.telegram = _TelegramNamespace(self)

    # ---- внутреннее ----
    def _sync_call(self, action: str, params: dict) -> Any:
        body = json.dumps(
            {"session_id": self._session_id, "action": action, "params": params},
            ensure_ascii=False,
        ).encode("utf-8")
        conn = http.client.HTTPConnection("127.0.0.1", self._port, timeout=10)
        try:
            conn.request("POST", "/api/exec", body, {
                "Content-Type": "application/json",
                "X-Sandbox-Token": self._token,
            })
            resp = conn.getresponse()
            data = json.loads(resp.read().decode("utf-8"))
        finally:
            conn.close()
        if "error" in data:
            raise RuntimeError(data["error"])
        return data.get("result", data)

    async def _call(self, action: str, params: dict) -> Any:
        return await asyncio.to_thread(self._sync_call, action, params)

    # ---- API ----
    async def send_message(self, text: str, **_kwargs: Any) -> Any:
        return await self._call("send_message", {"text": str(text)[:4000]})

    async def send_photo(self, file: Any, caption: Optional[str] = None) -> Any:
        return await self._call("send_photo", {"file": str(file), "caption": caption or ""})

    async def send_document(self, file: Any, caption: Optional[str] = None) -> Any:
        return await self._call("send_document", {"file": str(file), "caption": caption or ""})

    async def http_get(
        self, url: str,
        headers: Optional[dict] = None, params: Optional[dict] = None,
    ) -> dict:
        return await self._call("http_get", {"url": url, "headers": headers, "params": params})

    async def http_post(
        self, url: str,
        json: Optional[dict] = None, headers: Optional[dict] = None,
    ) -> dict:
        return await self._call("http_post", {"url": url, "json": json, "headers": headers})

    async def db_get(self, key: str) -> Optional[str]:
        r = await self._call("db_get", {"key": str(key)})
        return r.get("value") if isinstance(r, dict) else r

    async def db_set(self, key: str, value: Any) -> bool:
        await self._call("db_set", {"key": str(key), "value": str(value)})
        return True

    def log(self, msg: Any) -> None:
        """Fire-and-forget (в отдельном потоке, чтобы не блокировать handler)."""
        text = str(msg)[:500]
        threading.Thread(
            target=self._sync_call,
            args=("log", {"msg": text}),
            daemon=True,
        ).start()
