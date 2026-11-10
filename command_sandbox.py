"""AST-валидация .py-плагинов + restricted globals для exec."""
from __future__ import annotations

import ast
import builtins
from dataclasses import dataclass, field
from typing import Any


# ---- импорты ----
ALLOWED_IMPORTS: set[str] = {
    "math", "re", "json", "datetime", "random", "string",
    "hashlib", "base64", "html", "textwrap", "collections",
    "itertools", "functools", "typing", "dataclasses", "enum",
}

FORBIDDEN_IMPORTS: set[str] = {
    "os", "sys", "subprocess", "socket", "ctypes", "pathlib",
    "shutil", "tempfile", "pickle", "marshal", "shelve",
    "threading", "multiprocessing", "signal", "asyncio",
    "importlib", "__builtin__", "builtins", "gc", "inspect",
    "requests", "urllib", "http", "ftplib", "smtplib",
    "telebot", "aiogram", "pyrogram", "telethon", "python_telegram_bot",
}

# ---- запрещённые функции ----
FORBIDDEN_CALLS: set[str] = {
    "open", "eval", "exec", "compile", "__import__",
    "getattr", "setattr", "delattr",
    "globals", "locals", "vars", "dir",
    "input", "breakpoint", "help", "exit", "quit",
}

# ---- зарезервированные триггеры ----
RESERVED_TRIGGERS: set[str] = {
    ".мут", ".размут", ".клон", ".разклон", ".спам",
}


@dataclass
class ValidationResult:
    ok: bool
    errors: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


# ---- AST visitor ----
class _SandboxVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.errors: list[str] = []

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            top = alias.name.split(".")[0]
            if top in FORBIDDEN_IMPORTS:
                self.errors.append(f"Запрещённый импорт: {alias.name}")
            elif top not in ALLOWED_IMPORTS:
                self.errors.append(f"Импорт вне белого списка: {alias.name}")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module:
            top = node.module.split(".")[0]
            if top in FORBIDDEN_IMPORTS:
                self.errors.append(f"Запрещённый импорт: from {node.module}")
            elif top not in ALLOWED_IMPORTS:
                self.errors.append(f"Импорт вне белого списка: from {node.module}")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name) and node.func.id in FORBIDDEN_CALLS:
            self.errors.append(f"Запрещённый вызов: {node.func.id}()")
        if isinstance(node.func, ast.Attribute) and node.func.attr in FORBIDDEN_CALLS:
            self.errors.append(f"Запрещённый вызов: .{node.func.attr}()")
        self.generic_visit(node)

    def visit_Global(self, node: ast.Global) -> None:
        self.errors.append("Запрещена конструкция: global")
        self.generic_visit(node)

    def visit_Nonlocal(self, node: ast.Nonlocal) -> None:
        self.errors.append("Запрещена конструкция: nonlocal")
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr.startswith("__") and node.attr.endswith("__"):
            self.errors.append(f"Запрещён доступ к dunder-атрибуту: {node.attr}")
        self.generic_visit(node)


def _extract_metadata(tree: ast.Module) -> dict[str, Any]:
    meta: dict[str, Any] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id.startswith("COMMAND_"):
                    try:
                        meta[target.id] = ast.literal_eval(node.value)
                    except (ValueError, SyntaxError):
                        pass
    return meta


def _find_handler(tree: ast.Module) -> tuple[bool, str]:
    for node in tree.body:
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "handler":
            args = node.args.args
            if len(args) != 1:
                return False, "handler(ctx) должен принимать ровно один аргумент"
            return True, ""
        if isinstance(node, ast.FunctionDef) and node.name == "handler":
            return False, "handler должен быть async def (не def)"
    return False, "Не найден async def handler(ctx)"


def validate_source(source: str, filename: str = "<plugin>") -> ValidationResult:
    """Валидирует исходник. Возвращает ValidationResult."""
    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError as e:
        return ValidationResult(ok=False, errors=[f"Синтаксис: {e.msg} (строка {e.lineno})"])

    visitor = _SandboxVisitor()
    visitor.visit(tree)
    if visitor.errors:
        return ValidationResult(ok=False, errors=visitor.errors)

    ok, err = _find_handler(tree)
    if not ok:
        return ValidationResult(ok=False, errors=[err])

    meta = _extract_metadata(tree)

    triggers = meta.get("COMMAND_TRIGGERS", [])
    if isinstance(triggers, list):
        for t in triggers:
            if not isinstance(t, str):
                return ValidationResult(ok=False, errors=["COMMAND_TRIGGERS должен быть списком строк"])
            if t in RESERVED_TRIGGERS:
                return ValidationResult(ok=False, errors=[f"Триггер {t} зарезервирован"])

    return ValidationResult(ok=True, metadata=meta)


# ---- restricted globals для exec() ----
_SAFE_BUILTINS = {
    "print", "len", "range", "str", "int", "float", "bool", "list",
    "dict", "tuple", "set", "frozenset", "bytes", "bytearray", "type",
    "isinstance", "issubclass", "repr", "hash", "sorted", "reversed",
    "enumerate", "zip", "map", "filter", "any", "all", "min", "max",
    "sum", "abs", "round", "chr", "ord", "hex", "oct", "bin", "format",
    "id", "callable", "__build_class__", "object", "super",
    "Exception", "ValueError", "TypeError", "RuntimeError", "KeyError",
    "IndexError", "AttributeError", "StopIteration", "StopAsyncIteration",
    "ZeroDivisionError", "NameError", "ArithmeticError", "LookupError",
    "BaseException", "NotImplemented", "True", "False", "None", "Ellipsis",
}


def _safe_import(name: str, *args: Any, **kwargs: Any) -> Any:
    top = name.split(".")[0]
    if top not in ALLOWED_IMPORTS:
        raise ImportError(f"Модуль {name} запрещён в плагинах")
    return builtins.__import__(name, *args, **kwargs)


def build_safe_globals() -> dict[str, Any]:
    g: dict[str, Any] = {"__builtins__": {}}
    for name in _SAFE_BUILTINS:
        if hasattr(builtins, name):
            g["__builtins__"][name] = getattr(builtins, name)
    g["__builtins__"]["__import__"] = _safe_import
    return g
