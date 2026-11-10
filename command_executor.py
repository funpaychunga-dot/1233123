"""Оркестратор плагинов: HTTP-bridge + multiprocessing(spawn) + лимиты."""
from __future__ import annotations

import asyncio
import json
import logging
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import multiprocessing as mp
from aiohttp import web

from config import settings
from database import crud
from services.command_worker import run_worker

logger = logging.getLogger(__name__)


@dataclass
class _Session:
    user_id: int
    command_name: str
    chat_id: int
    http_count: int = 0
    msg_count: int = 0
    finish_event: Optional[asyncio.Event] = None
    result: Optional[dict] = None


class CommandExecutor:
    """Singleton. Инициализируется в router.startup() (см. upload_command.py)."""

    _instance: Optional["CommandExecutor"] = None

    def __init__(self, bot: Any) -> None:
        self.bot = bot
        self._sessions: dict[str, _Session] = {}
        self._token = secrets.token_hex(32)
        self._port = 0
        self._runner: Optional[web.AppRunner] = None
        self._global_sem = asyncio.Semaphore(10)

    @classmethod
    def get(cls) -> "CommandExecutor":
        if cls._instance is None:
            raise RuntimeError("CommandExecutor не инициализирован (startup не вызван)")
        return cls._instance

    @classmethod
    def init(cls, bot: Any) -> "CommandExecutor":
        if cls._instance is None:
            cls._instance = cls(bot)
        return cls._instance

    @classmethod
    async def shutdown(cls) -> None:
        if cls._instance is not None:
            await cls._instance.stop()
            cls._instance = None

    # ---- HTTP-сервер ----
    async def start(self) -> None:
        app = web.Application()
        app.router.add_post("/api/exec", self._handle_exec)
        app.router.add_post("/api/finish", self._handle_finish)
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "127.0.0.1", 0)
        await site.start()
        self._port = site._server.sockets[0].getsockname()[1]
        logger.info("CommandExecutor HTTP on 127.0.0.1:%d", self._port)

    async def stop(self) -> None:
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None
            logger.info("CommandExecutor stopped")

    def _check_auth(self, request: web.Request) -> Optional[web.Response]:
        if request.headers.get("X-Sandbox-Token") != self._token:
            return web.json_response({"error": "auth"}, status=401)
        return None

    async def _handle_exec(self, request: web.Request) -> web.Response:
        err = self._check_auth(request)
        if err:
            return err
        data = await request.json()
        sess = self._sessions.get(data.get("session_id", ""))
        if sess is None:
            return web.json_response({"error": "unknown session"}, status=404)
        result = await self._dispatch(sess, data.get("action", ""), data.get("params") or {})
        return web.json_response(result)

    async def _handle_finish(self, request: web.Request) -> web.Response:
        err = self._check_auth(request)
        if err:
            return err
        data = await request.json()
        sess = self._sessions.get(data.get("session_id", ""))
        if sess is not None and sess.finish_event is not None:
            sess.result = {"ok": bool(data.get("ok")), "error": data.get("error", "")}
            sess.finish_event.set()
        return web.json_response({"ok": True})

    # ---- Диспетчер действий ----
    async def _dispatch(self, sess: _Session, action: str, params: dict) -> dict:
        try:
            if action == "send_message":
                if sess.msg_count >= settings.COMMAND_MAX_MESSAGES:
                    return {"error": f"лимит сообщений исчерпан ({settings.COMMAND_MAX_MESSAGES})"}
                sess.msg_count += 1
                msg = await self.bot.send_message(chat_id=sess.chat_id, text=params["text"])
                return {"ok": True, "message_id": msg.message_id}

            if action == "send_photo":
                if sess.msg_count >= settings.COMMAND_MAX_MESSAGES:
                    return {"error": "лимит сообщений исчерпан"}
                sess.msg_count += 1
                msg = await self.bot.send_photo(
                    chat_id=sess.chat_id, photo=params["file"],
                    caption=params.get("caption") or None,
                )
                return {"ok": True, "message_id": msg.message_id}

            if action == "send_document":
                if sess.msg_count >= settings.COMMAND_MAX_MESSAGES:
                    return {"error": "лимит сообщений исчерпан"}
                sess.msg_count += 1
                msg = await self.bot.send_document(
                    chat_id=sess.chat_id, document=params["file"],
                    caption=params.get("caption") or None,
                )
                return {"ok": True, "message_id": msg.message_id}

            if action in ("http_get", "http_post"):
                if sess.http_count >= settings.COMMAND_MAX_HTTP:
                    return {"error": f"лимит HTTP исчерпан ({settings.COMMAND_MAX_HTTP})"}
                sess.http_count += 1
                return await self._do_http(action, params)

            if action == "get_chat":
                chat = await self.bot.get_chat(params["target"])
                return {"ok": True, "result": {
                    "id": chat.id,
                    "type": str(chat.type),
                    "title": getattr(chat, "title", None),
                    "first_name": getattr(chat, "first_name", None),
                    "last_name": getattr(chat, "last_name", None),
                    "username": getattr(chat, "username", None),
                    "bio": getattr(chat, "bio", None),
                }}

            if action == "db_get":
                v = await crud.kv_get(sess.user_id, sess.command_name, str(params["key"]))
                return {"ok": True, "value": v}

            if action == "db_set":
                await crud.kv_set(
                    sess.user_id, sess.command_name,
                    str(params["key"]), str(params["value"]),
                )
                return {"ok": True}

            if action == "log":
                logger.info("[plugin %s/%s] %s",
                            sess.user_id, sess.command_name, params.get("msg", ""))
                return {"ok": True}

            return {"error": f"unknown action: {action}"}
        except Exception as e:  # noqa: BLE001
            logger.exception("dispatch error action=%s", action)
            return {"error": f"{type(e).__name__}: {e}"}

    async def _do_http(self, action: str, params: dict) -> dict:
        import aiohttp
        timeout = aiohttp.ClientTimeout(total=4)
        async with aiohttp.ClientSession(timeout=timeout) as s:
            if action == "http_get":
                ctx_mgr = s.get(
                    params["url"],
                    headers=params.get("headers") or {},
                    params=params.get("params") or {},
                )
            else:
                ctx_mgr = s.post(
                    params["url"],
                    json=params.get("json"),
                    headers=params.get("headers") or {},
                )
            async with ctx_mgr as r:
                text = await r.text()
                return {"ok": True, "status": r.status, "text": text[:10000]}

    # ---- Публичный API ----
    async def execute(
        self,
        *,
        user_id: int,
        chat_id: int,
        command_name: str,
        source_path: Path,
        config: dict,
        payload: dict,
    ) -> dict:
        async with self._global_sem:
            return await self._execute_locked(
                user_id=user_id, chat_id=chat_id,
                command_name=command_name, source_path=source_path,
                config=config, payload=payload,
            )

    async def _execute_locked(
        self, *, user_id: int, chat_id: int, command_name: str,
        source_path: Path, config: dict, payload: dict,
    ) -> dict:
        try:
            source = source_path.read_text(encoding="utf-8")
        except OSError as e:
            return {"ok": False, "error": f"Не удалось прочитать файл: {e}"}

        session_id = secrets.token_hex(16)
        sess = _Session(
            user_id=user_id, command_name=command_name, chat_id=chat_id,
        )
        sess.finish_event = asyncio.Event()
        self._sessions[session_id] = sess

        limits = {
            "cpu": settings.COMMAND_CPU_LIMIT,
            "mem": settings.COMMAND_MEM_LIMIT_BYTES,
        }

        try:
            ctx_mp = mp.get_context("spawn")
            proc = ctx_mp.Process(
                target=run_worker,
                args=(
                    source, str(source_path), config,
                    self._port, self._token, session_id, limits, payload,
                ),
                daemon=True,
            )
            proc.start()

            try:
                await asyncio.wait_for(
                    sess.finish_event.wait(),
                    timeout=settings.COMMAND_EXEC_TIMEOUT,
                )
            except asyncio.TimeoutError:
                self._kill_process(proc)
                return {"ok": False, "error": f"timeout {settings.COMMAND_EXEC_TIMEOUT}с"}

            await asyncio.to_thread(proc.join, 2)
            if proc.is_alive():
                self._kill_process(proc)

            return sess.result or {"ok": False, "error": f"exitcode={proc.exitcode}"}
        finally:
            self._sessions.pop(session_id, None)

    @staticmethod
    def _kill_process(proc: mp.Process) -> None:
        try:
            proc.terminate()
        except Exception:
            pass
        try:
            proc.join(timeout=1)
        except Exception:
            pass
        if proc.is_alive():
            try:
                proc.kill()
            except Exception:
                pass
