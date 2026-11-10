"""Работа в дочернем процессе: rlimits, exec плагина, запуск handler(ctx)."""
from __future__ import annotations

import asyncio
import http.client
import json
import sys
import types
from typing import Any


def _apply_rlimits(cpu: int, mem: int) -> None:
    try:
        import resource  # noqa: PLC0415
    except ImportError:
        return  # Windows — без RLIMIT, работает только wait_for
    try:
        resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu + 1))
        resource.setrlimit(resource.RLIMIT_AS, (mem, mem))
    except (ValueError, OSError):
        pass


def _notify_finish(port: int, token: str, session_id: str, ok: bool, error: str = "") -> None:
    try:
        body = json.dumps(
            {"session_id": session_id, "ok": ok, "error": error[:2000]},
            ensure_ascii=False,
        ).encode("utf-8")
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
        try:
            conn.request("POST", "/api/finish", body, {
                "Content-Type": "application/json",
                "X-Sandbox-Token": token,
            })
            conn.getresponse().read()
        finally:
            conn.close()
    except Exception:
        pass


def _load_plugin(source: str, filename: str, safe_globals: dict) -> types.ModuleType:
    module = types.ModuleType("sandbox_plugin")
    module.__dict__["__file__"] = filename
    module.__dict__["__name__"] = "sandbox_plugin"
    env = dict(safe_globals)
    env.update({
        "__file__": filename,
        "__name__": "sandbox_plugin",
    })
    code = compile(source, filename, "exec")
    exec(code, env)
    for k, v in env.items():
        if k.startswith("__"):
            continue
        setattr(module, k, v)
    return module


def run_worker(
    source: str,
    filename: str,
    config: dict,
    port: int,
    token: str,
    session_id: str,
    limits: dict,
    payload: dict,
) -> None:
    """Точка входа дочернего процесса (запускается через mp.Process)."""
    _apply_rlimits(limits["cpu"], limits["mem"])

    try:
        # Defense in depth: перепроверяем уже внутри sandbox
        from services.command_sandbox import validate_source, build_safe_globals

        vr = validate_source(source, filename)
        if not vr.ok:
            _notify_finish(port, token, session_id, False, "; ".join(vr.errors))
            sys.exit(2)

        safe_globals = build_safe_globals()
        module = _load_plugin(source, filename, safe_globals)

        handler = getattr(module, "handler", None)
        if handler is None or not asyncio.iscoroutinefunction(handler):
            _notify_finish(port, token, session_id, False, "handler(ctx) не async")
            sys.exit(3)

        from services.command_context import SandboxContext

        ctx = SandboxContext(port, token, session_id, config, limits)
        ctx.user = _User_from(payload.get("user") or {})
        ctx.chat_id = int(payload.get("chat_id") or 0)
        ctx.message_text = payload.get("text") or ""
        ctx.args = payload.get("args") or ""

        asyncio.run(handler(ctx))
        _notify_finish(port, token, session_id, True)
        sys.exit(0)
    except SystemExit:
        raise
    except BaseException as e:
        _notify_finish(port, token, session_id, False, f"{type(e).__name__}: {e}")
        sys.exit(1)


def _User_from(data: dict):  # noqa: N802
    from services.command_context import _User  # noqa: PLC0415
    return _User(data)
