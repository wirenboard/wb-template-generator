"""Контекст запроса — request_id через ContextVar для asyncio."""

import secrets
from contextvars import ContextVar

_request_id_var: ContextVar[str] = ContextVar("request_id", default="")


def generate_request_id() -> str:
    """Генерирует уникальный request_id — 8 символов hex."""
    return secrets.token_hex(4)


def get_request_id() -> str:
    """Возвращает request_id текущей asyncio-задачи."""
    return _request_id_var.get()


def set_request_id(request_id: str) -> None:
    """Устанавливает request_id для текущей asyncio-задачи."""
    _request_id_var.set(request_id)
