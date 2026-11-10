"""Метрики хостинга через psutil + состояние БД и очереди."""
from __future__ import annotations

import os
import platform
import sys
import time
from pathlib import Path
from typing import Any

import psutil

from config import settings
from database.db import Database
from services.rate_limiter import rate_limiter
from utils.helpers import human_bytes

START_TIME = time.time()


async def collect_metrics() -> dict[str, Any]:
    # --- CPU ---
    cpu_percent = psutil.cpu_percent(interval=None)
    cpu_per_core = psutil.cpu_percent(percpu=True, interval=None)
    try:
        load1, load5, load15 = os.getloadavg()
    except (AttributeError, OSError):
        load1 = load5 = load15 = 0.0

    # --- RAM ---
    vm = psutil.virtual_memory()

    # --- Disk (по разделу с БД) ---
    db_path = Path(settings.DB_PATH).resolve()
    du = psutil.disk_usage(str(db_path.parent))

    # --- Net ---
    net = psutil.net_io_counters()

    # --- Process ---
    proc = psutil.Process(os.getpid())
    with proc.oneshot():
        proc_ram = proc.memory_info().rss
        proc_cpu = proc.cpu_percent(interval=None)
        proc_threads = proc.num_threads()
        proc_uptime = time.time() - proc.create_time()

    # --- System ---
    sys_uptime = time.time() - psutil.boot_time()

    # --- DB ---
    db_size = db_path.stat().st_size if db_path.exists() else 0
    db_stats = await _db_stats()

    # --- Queue / rate limiter ---
    rl_stats = rate_limiter.stats()

    # --- Versions ---
    import aiogram  # noqa: PLC0415
    versions = {
        "python": sys.version.split()[0],
        "aiogram": getattr(aiogram, "__version__", "?"),
        "bot": settings.BOT_VERSION,
        "platform": f"{platform.system()} {platform.release()}",
    }

    return {
        "ts": time.time(),
        "cpu": {
            "percent": cpu_percent,
            "per_core": cpu_per_core,
            "load_avg": (load1, load5, load15),
            "cores": psutil.cpu_count(logical=True),
        },
        "ram": {
            "total": vm.total,
            "used": vm.used,
            "free": vm.available,
            "percent": vm.percent,
        },
        "disk": {
            "total": du.total,
            "used": du.used,
            "free": du.free,
            "percent": du.percent,
            "mount": str(db_path.parent),
        },
        "network": {
            "bytes_sent": net.bytes_sent,
            "bytes_recv": net.bytes_recv,
        },
        "process": {
            "ram_rss": proc_ram,
            "cpu_percent": proc_cpu,
            "threads": proc_threads,
            "uptime_sec": proc_uptime,
        },
        "system": {
            "uptime_sec": sys_uptime,
        },
        "db": {
            "size": db_size,
            "tables": db_stats,
        },
        "queue": rl_stats,
        "versions": versions,
    }


async def _db_stats() -> dict[str, int]:
    out: dict[str, int] = {}
    try:
        db = Database.conn()
        async with db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ) as cur:
            tables = [r[0] for r in await cur.fetchall() if not r[0].startswith("sqlite_")]
        for t in tables:
            try:
                async with db.execute(f"SELECT COUNT(*) FROM {t}") as cur:
                    row = await cur.fetchone()
                out[t] = int(row[0]) if row else 0
            except Exception:
                out[t] = -1
    except Exception:
        pass
    return out


def check_thresholds(m: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    if m["ram"]["percent"] > 85:
        warnings.append(f"ОЗУ {m['ram']['percent']:.0f}% (>85%)")
    if m["cpu"]["percent"] > 90:
        warnings.append(f"CPU {m['cpu']['percent']:.0f}% (>90%)")
    if m["disk"]["percent"] > 90:
        warnings.append(f"Диск {m['disk']['percent']:.0f}% (>90%)")
    if m["queue"]["queue_len"] > settings.QUEUE_MAX_SIZE * 0.8:
        warnings.append(f"Очередь {m['queue']['queue_len']} (>80%)")
    return warnings


def _fmt_dur(seconds: float) -> str:
    s = int(seconds)
    d, s = divmod(s, 86400)
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    parts: list[str] = []
    if d:
        parts.append(f"{d}д")
    if h:
        parts.append(f"{h}ч")
    if m:
        parts.append(f"{m}м")
    parts.append(f"{s}с")
    return " ".join(parts)


def format_metrics(m: dict[str, Any]) -> str:
    ram = m["ram"]; disk = m["disk"]; cpu = m["cpu"]
    net = m["network"]; pr = m["process"]; sy = m["system"]
    db = m["db"]; q = m["queue"]; ver = m["versions"]
    la = cpu["load_avg"]
    lines = [
        "<b>🖥 Состояние хостинга</b>",
        f"ОЗУ: {human_bytes(ram['used'])} / {human_bytes(ram['total'])} ({ram['percent']:.0f}%)",
        f"CPU: {cpu['percent']:.1f}% • ядер {cpu['cores']} • LA {la[0]:.2f}/{la[1]:.2f}/{la[2]:.2f}",
        f"Диск ({disk['mount']}): {human_bytes(disk['used'])} / {human_bytes(disk['total'])} ({disk['percent']:.0f}%)",
        f"Процесс: RSS {human_bytes(pr['ram_rss'])}, потоков {pr['threads']}, uptime {_fmt_dur(pr['uptime_sec'])}",
        f"Система: uptime {_fmt_dur(sy['uptime_sec'])}",
        f"Сеть: ↑{human_bytes(net['bytes_sent'])} ↓{human_bytes(net['bytes_recv'])}",
        f"БД: {human_bytes(db['size'])} • таблиц {len(db['tables'])}",
        f"Очередь: {q['queue_len']} • RTT {q['avg_rtt_ms']} мс • ошибок 5м: {q['errors_last_5min']}",
        f"Версии: py {ver['python']}, aiogram {ver['aiogram']}, bot {ver['bot']}",
    ]
    return "\n".join(lines)
