"""Классификатор ошибок LLM API.

Определяет категорию и серьёзность исключения от openai SDK или от httpx для
маршрутизации в уведомления (Telegram), метрики и текст отказа пользователю.

Используется в llm_service и main для детектирования проблем с серверным
LLM (истёк ключ, кончилась квота, недоступен сервис провайдера и т. п.).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import httpx
import openai


class ErrorCategory(str, Enum):
    """Категория сбоя обращения к LLM API."""

    QUOTA_EXCEEDED = "quota_exceeded"   # закончились средства / превышена квота биллинга
    AUTH = "auth"                       # 401 — невалидный API-ключ
    PERMISSION = "permission"           # 403 — отозван доступ (без quota-маркеров)
    NOT_FOUND = "not_found"             # 404 — модель не найдена
    BAD_REQUEST = "bad_request"         # 400/422 — провайдер не принял файл или запрос
    RATE_LIMIT = "rate_limit"           # 429 без quota-маркеров — стандартный лимит RPM/TPM
    TIMEOUT = "timeout"                 # APITimeoutError или httpx.TimeoutException
    CONNECTION = "connection"           # APIConnectionError или httpx.TransportError (сеть, прокси)
    SERVER_ERROR = "server_error"       # 5xx
    UNKNOWN = "unknown"                 # всё остальное


class Severity(str, Enum):
    """Серьёзность инцидента — определяет стратегию уведомления."""

    CRITICAL = "critical"   # отправляем сразу + cooldown
    WARNING = "warning"     # отправляем по порогу в окне


# Соответствие категории → серьёзности
_SEVERITY: dict[ErrorCategory, Severity] = {
    ErrorCategory.QUOTA_EXCEEDED: Severity.CRITICAL,
    ErrorCategory.AUTH: Severity.CRITICAL,
    ErrorCategory.PERMISSION: Severity.CRITICAL,
    ErrorCategory.NOT_FOUND: Severity.CRITICAL,
    ErrorCategory.BAD_REQUEST: Severity.WARNING,
    ErrorCategory.RATE_LIMIT: Severity.WARNING,
    ErrorCategory.TIMEOUT: Severity.WARNING,
    ErrorCategory.CONNECTION: Severity.WARNING,
    ErrorCategory.SERVER_ERROR: Severity.WARNING,
    ErrorCategory.UNKNOWN: Severity.WARNING,
}


@dataclass(frozen=True)
class ClassifiedError:
    """Результат классификации исключения OpenAI."""

    category: ErrorCategory
    severity: Severity
    http_status: int | None
    code: str | None
    message: str  # человекочитаемое короткое описание (для уведомлений)


# Маркеры закончившейся квоты / биллинга.
# Двойная проверка нужна, т. к. совместимые провайдеры (DeepSeek, OpenRouter, vLLM)
# могут возвращать ошибки в произвольной структуре — без поля error.code.
_QUOTA_CODES: frozenset[str] = frozenset({
    "insufficient_quota",
    "billing_hard_limit_reached",
    "billing_not_active",
    "account_deactivated",
})

_QUOTA_PHRASES: tuple[str, ...] = (
    "exceeded your current quota",
    "insufficient_quota",
    "billing hard limit",
    "billing_hard_limit",
    "account is not active",
    "account_deactivated",
)


def _extract_code(exc: Exception) -> str | None:
    """Пытается извлечь error.code из тела ответа OpenAI SDK.

    SDK кладёт распарсенное тело в exc.body (dict) или exc.code (атрибут).
    """
    code = getattr(exc, "code", None)
    if isinstance(code, str) and code:
        return code

    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict):
            inner_code = err.get("code")
            if isinstance(inner_code, str) and inner_code:
                return inner_code
    return None


def _extract_status(exc: Exception) -> int | None:
    """Извлекает HTTP-статус — у SDK он в `status_code`, у httpx в `response`."""
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        return status

    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    if isinstance(status, int):
        return status
    return None


def _extract_message(exc: Exception) -> str:
    """Короткое человекочитаемое описание (без лишних трейсбеков)."""
    msg = getattr(exc, "message", None)
    if isinstance(msg, str) and msg:
        return msg
    return str(exc) or exc.__class__.__name__


def _is_quota(exc: Exception, code: str | None, message: str) -> bool:
    """Определяет, является ли ошибка следствием исчерпания квоты/биллинга."""
    if code and code in _QUOTA_CODES:
        return True
    lowered = message.lower()
    return any(phrase in lowered for phrase in _QUOTA_PHRASES)


def _category_by_status(exc: Exception, status: int, code: str | None, message: str) -> ErrorCategory:
    """Категория по HTTP-статусу ответа провайдера."""
    if status >= 500:
        return ErrorCategory.SERVER_ERROR
    if status == 429:
        return (
            ErrorCategory.QUOTA_EXCEEDED
            if _is_quota(exc, code, message)
            else ErrorCategory.RATE_LIMIT
        )
    if status == 401:
        return ErrorCategory.AUTH
    if status == 403:
        return (
            ErrorCategory.QUOTA_EXCEEDED
            if _is_quota(exc, code, message)
            else ErrorCategory.PERMISSION
        )
    if status == 404:
        return ErrorCategory.NOT_FOUND
    if status in (400, 422):
        return ErrorCategory.BAD_REQUEST
    return ErrorCategory.UNKNOWN


def classify(exc: Exception) -> ClassifiedError:
    """Классифицирует исключение обращения к LLM — от openai SDK или от httpx.

    Порядок проверок важен, более специфичные классы идут до общих.
    """
    code = _extract_code(exc)
    status = _extract_status(exc)
    message = _extract_message(exc)

    # 1. RateLimitError + quota → critical
    # 2. RateLimitError → warning
    if isinstance(exc, openai.RateLimitError):
        if _is_quota(exc, code, message):
            category = ErrorCategory.QUOTA_EXCEEDED
        else:
            category = ErrorCategory.RATE_LIMIT
        return ClassifiedError(category, _SEVERITY[category], status, code, message)

    # 3. AuthenticationError → critical
    if isinstance(exc, openai.AuthenticationError):
        return ClassifiedError(
            ErrorCategory.AUTH, _SEVERITY[ErrorCategory.AUTH], status, code, message,
        )

    # 4-5. PermissionDeniedError: с quota-маркерами → QUOTA_EXCEEDED, иначе PERMISSION
    if isinstance(exc, openai.PermissionDeniedError):
        if _is_quota(exc, code, message):
            category = ErrorCategory.QUOTA_EXCEEDED
        else:
            category = ErrorCategory.PERMISSION
        return ClassifiedError(category, _SEVERITY[category], status, code, message)

    # 6. NotFoundError → critical (404, неверная модель)
    if isinstance(exc, openai.NotFoundError):
        return ClassifiedError(
            ErrorCategory.NOT_FOUND, _SEVERITY[ErrorCategory.NOT_FOUND],
            status, code, message,
        )

    # 7. BadRequestError | UnprocessableEntityError → critical
    if isinstance(exc, (openai.BadRequestError, openai.UnprocessableEntityError)):
        return ClassifiedError(
            ErrorCategory.BAD_REQUEST, _SEVERITY[ErrorCategory.BAD_REQUEST],
            status, code, message,
        )

    # 8. ConflictError → unknown/warning (редкий случай)
    if isinstance(exc, openai.ConflictError):
        return ClassifiedError(
            ErrorCategory.UNKNOWN, _SEVERITY[ErrorCategory.UNKNOWN],
            status, code, message,
        )

    # 9. APITimeoutError → warning
    if isinstance(exc, openai.APITimeoutError):
        return ClassifiedError(
            ErrorCategory.TIMEOUT, _SEVERITY[ErrorCategory.TIMEOUT],
            status, code, message,
        )

    # 10. APIConnectionError → warning
    if isinstance(exc, openai.APIConnectionError):
        return ClassifiedError(
            ErrorCategory.CONNECTION, _SEVERITY[ErrorCategory.CONNECTION],
            status, code, message,
        )

    # 11. InternalServerError → warning (5xx)
    if isinstance(exc, openai.InternalServerError):
        return ClassifiedError(
            ErrorCategory.SERVER_ERROR, _SEVERITY[ErrorCategory.SERVER_ERROR],
            status, code, message,
        )

    # 12. Всё со статусом — APIStatusError от SDK и сбои httpx. Ниже проверок по классу, те точнее статуса
    if isinstance(exc, httpx.TimeoutException):
        return ClassifiedError(
            ErrorCategory.TIMEOUT, _SEVERITY[ErrorCategory.TIMEOUT],
            status, code, message,
        )
    if status is not None:
        category = _category_by_status(exc, status, code, message)
        return ClassifiedError(category, _SEVERITY[category], status, code, message)
    if isinstance(exc, httpx.TransportError):
        return ClassifiedError(
            ErrorCategory.CONNECTION, _SEVERITY[ErrorCategory.CONNECTION],
            status, code, message,
        )

    # 13. Любое другое исключение → UNKNOWN/warning
    return ClassifiedError(
        ErrorCategory.UNKNOWN, _SEVERITY[ErrorCategory.UNKNOWN],
        status, code, message,
    )


# Все категории — для инициализации метрик и тестов.
ALL_CATEGORIES: tuple[ErrorCategory, ...] = tuple(ErrorCategory)


# Наружу уходит только ключ категории — текст исключения различает отказ соединения, DNS, TLS
# и статус, то есть отвечает, что стоит по присланному клиентом адресу.
def public_key(exc: Exception) -> str:
    """Ключ локализации категории сбоя — подставляется как {reason}."""
    return f"llmError.{classify(exc).category.value}"
