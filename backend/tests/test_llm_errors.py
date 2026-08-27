"""Тесты классификатора ошибок OpenAI API (llm_errors.py)."""

import sys
from pathlib import Path

import httpx
import openai
import pytest

# Добавляем backend/ в sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from llm_errors import (  # noqa: E402, I001
    ALL_CATEGORIES,
    ErrorCategory,
    Severity,
    classify,
    public_key,
)


# ---------------------------------------------------------------------------
# Фабрики для создания исключений openai SDK
# ---------------------------------------------------------------------------


def _make_response(status: int, body: dict | None = None) -> httpx.Response:
    """Создаёт httpx.Response для конструктора openai-исключений."""
    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    return httpx.Response(status_code=status, request=request, json=body or {})


def _make_status_error(
    cls: type[openai.APIStatusError],
    status: int,
    *,
    code: str | None = None,
    message: str = "error",
) -> openai.APIStatusError:
    """Конструирует openai.APIStatusError-подобный объект."""
    body: dict = {"error": {"message": message}}
    if code:
        body["error"]["code"] = code
    response = _make_response(status, body)
    # Сигнатура: (message, *, response, body)
    return cls(message=message, response=response, body=body["error"])


# ---------------------------------------------------------------------------
# Quota-маркеры (главный сценарий — закончились деньги)
# ---------------------------------------------------------------------------


class TestQuotaExceeded:
    """Сценарии «закончилась квота / биллинг» — должны быть critical."""

    def test_insufficient_quota_via_code(self):
        """RateLimitError с body.error.code='insufficient_quota' → QUOTA_EXCEEDED."""
        exc = _make_status_error(
            openai.RateLimitError, 429,
            code="insufficient_quota",
            message="You exceeded your current quota, please check your plan and billing details.",
        )
        result = classify(exc)
        assert result.category == ErrorCategory.QUOTA_EXCEEDED
        assert result.severity == Severity.CRITICAL
        assert result.code == "insufficient_quota"
        assert result.http_status == 429

    def test_insufficient_quota_via_message_only(self):
        """RateLimitError без code, но с фразой в сообщении → QUOTA_EXCEEDED.

        Совместимые провайдеры могут не возвращать структурированный код.
        """
        exc = _make_status_error(
            openai.RateLimitError, 429,
            code=None,
            message="You exceeded your current quota.",
        )
        result = classify(exc)
        assert result.category == ErrorCategory.QUOTA_EXCEEDED
        assert result.severity == Severity.CRITICAL

    def test_billing_hard_limit_via_permission_denied(self):
        """PermissionDeniedError с code='billing_hard_limit_reached' → QUOTA_EXCEEDED."""
        exc = _make_status_error(
            openai.PermissionDeniedError, 403,
            code="billing_hard_limit_reached",
            message="Billing hard limit has been reached",
        )
        result = classify(exc)
        assert result.category == ErrorCategory.QUOTA_EXCEEDED
        assert result.severity == Severity.CRITICAL

    def test_billing_not_active(self):
        """code='billing_not_active' → QUOTA_EXCEEDED (возможен в RateLimit или Permission)."""
        exc = _make_status_error(
            openai.PermissionDeniedError, 403,
            code="billing_not_active",
            message="Billing is not active for this account",
        )
        result = classify(exc)
        assert result.category == ErrorCategory.QUOTA_EXCEEDED
        assert result.severity == Severity.CRITICAL

    def test_account_deactivated(self):
        """code='account_deactivated' → QUOTA_EXCEEDED."""
        exc = _make_status_error(
            openai.PermissionDeniedError, 403,
            code="account_deactivated",
            message="Your account has been deactivated.",
        )
        result = classify(exc)
        assert result.category == ErrorCategory.QUOTA_EXCEEDED
        assert result.severity == Severity.CRITICAL

    def test_plain_rate_limit_is_not_quota(self):
        """Обычный 429 без quota-маркеров → RATE_LIMIT/warning, НЕ QUOTA_EXCEEDED."""
        exc = _make_status_error(
            openai.RateLimitError, 429,
            code="rate_limit_exceeded",
            message="Rate limit reached for requests",
        )
        result = classify(exc)
        assert result.category == ErrorCategory.RATE_LIMIT
        assert result.severity == Severity.WARNING


# ---------------------------------------------------------------------------
# Остальные категории
# ---------------------------------------------------------------------------


class TestOtherCategories:
    """Полная карта типов исключений openai SDK."""

    def test_authentication_error(self):
        """401 → AUTH/critical."""
        exc = _make_status_error(
            openai.AuthenticationError, 401,
            code="invalid_api_key",
            message="Incorrect API key provided",
        )
        result = classify(exc)
        assert result.category == ErrorCategory.AUTH
        assert result.severity == Severity.CRITICAL

    def test_permission_denied_without_quota(self):
        """403 без quota-маркеров → PERMISSION/critical."""
        exc = _make_status_error(
            openai.PermissionDeniedError, 403,
            code="model_not_accessible",
            message="You do not have access to this model",
        )
        result = classify(exc)
        assert result.category == ErrorCategory.PERMISSION
        assert result.severity == Severity.CRITICAL

    def test_not_found_error(self):
        """404 → NOT_FOUND/critical (например, модель не существует)."""
        exc = _make_status_error(
            openai.NotFoundError, 404,
            code="model_not_found",
            message="The model 'gpt-bogus' does not exist",
        )
        result = classify(exc)
        assert result.category == ErrorCategory.NOT_FOUND
        assert result.severity == Severity.CRITICAL

    def test_bad_request_error(self):
        """400 → BAD_REQUEST/warning."""
        exc = _make_status_error(
            openai.BadRequestError, 400,
            message="Invalid request",
        )
        result = classify(exc)
        assert result.category == ErrorCategory.BAD_REQUEST
        assert result.severity == Severity.WARNING

    def test_unprocessable_entity_error(self):
        """422 → BAD_REQUEST/warning."""
        exc = _make_status_error(
            openai.UnprocessableEntityError, 422,
            message="Unprocessable",
        )
        result = classify(exc)
        assert result.category == ErrorCategory.BAD_REQUEST

    def test_conflict_error(self):
        """409 → UNKNOWN/warning (редкий случай)."""
        exc = _make_status_error(
            openai.ConflictError, 409,
            message="Conflict",
        )
        result = classify(exc)
        assert result.category == ErrorCategory.UNKNOWN
        assert result.severity == Severity.WARNING

    def test_internal_server_error(self):
        """5xx → SERVER_ERROR/warning."""
        exc = _make_status_error(
            openai.InternalServerError, 503,
            message="Service unavailable",
        )
        result = classify(exc)
        assert result.category == ErrorCategory.SERVER_ERROR
        assert result.severity == Severity.WARNING

    def test_api_timeout_error(self):
        """APITimeoutError → TIMEOUT/warning."""
        exc = openai.APITimeoutError(
            request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions"),
        )
        result = classify(exc)
        assert result.category == ErrorCategory.TIMEOUT
        assert result.severity == Severity.WARNING

    def test_api_connection_error(self):
        """APIConnectionError → CONNECTION/warning (сеть, прокси)."""
        exc = openai.APIConnectionError(
            request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions"),
        )
        result = classify(exc)
        assert result.category == ErrorCategory.CONNECTION
        assert result.severity == Severity.WARNING

    def test_unknown_exception(self):
        """Любое другое исключение → UNKNOWN/warning."""
        exc = ValueError("something else")
        result = classify(exc)
        assert result.category == ErrorCategory.UNKNOWN
        assert result.severity == Severity.WARNING
        assert result.message == "something else"

    def test_classified_message_uses_exc_message_attr(self):
        """ClassifiedError.message должен быть человекочитаемым."""
        exc = _make_status_error(
            openai.AuthenticationError, 401,
            message="Incorrect API key",
        )
        result = classify(exc)
        assert "Incorrect API key" in result.message


# ---------------------------------------------------------------------------
# Edge-cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Граничные ситуации."""

    def test_rate_limit_with_uppercase_quota_phrase(self):
        """Регистронезависимая проверка фраз."""
        exc = _make_status_error(
            openai.RateLimitError, 429,
            code=None,
            message="YOU EXCEEDED YOUR CURRENT QUOTA today",
        )
        result = classify(exc)
        assert result.category == ErrorCategory.QUOTA_EXCEEDED

    def test_message_in_exc_attribute(self):
        """Если у исключения есть .message — используется он."""
        exc = ValueError("plain text")
        result = classify(exc)
        # У ValueError нет .message — берётся str(exc)
        assert result.message == "plain text"

    def test_none_body_does_not_crash(self):
        """Отсутствие body не должно ронять классификатор."""
        request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
        response = httpx.Response(status_code=429, request=request)
        exc = openai.RateLimitError(
            message="rate limited",
            response=response,
            body=None,
        )
        result = classify(exc)
        assert result.category in (ErrorCategory.RATE_LIMIT, ErrorCategory.QUOTA_EXCEEDED)


class TestHttpxErrors:
    """Список моделей запрашивается напрямую через httpx, минуя openai SDK.

    Без этих ветвей его сбои попадали бы в «неизвестно».
    """

    def _status_error(self, status: int, message: str = "error") -> httpx.HTTPStatusError:
        request = httpx.Request("GET", "https://api.provider.example/v1/models")
        response = httpx.Response(status_code=status, request=request, json={})
        return httpx.HTTPStatusError(message, request=request, response=response)

    def test_unauthorized_is_auth(self):
        """401 от провайдера — не принят ключ."""
        assert classify(self._status_error(401)).category == ErrorCategory.AUTH

    def test_not_found_is_not_found(self):
        """404 — адрес или модель не найдены."""
        assert classify(self._status_error(404)).category == ErrorCategory.NOT_FOUND

    def test_server_error(self):
        """5xx — сбой на стороне провайдера."""
        result = classify(self._status_error(503))
        assert result.category == ErrorCategory.SERVER_ERROR
        assert result.severity == Severity.WARNING

    @pytest.mark.parametrize("status,expected", [
        (429, ErrorCategory.RATE_LIMIT),
        (403, ErrorCategory.PERMISSION),
    ])
    def test_status_with_own_branch(self, status, expected):
        """429 и 403 разветвляются внутри по quota-маркеру — без SDK-класса тоже.

        Через httpx у этих статусов нет своего класса исключения, а список моделей
        ходит только так, и 429 для него самый частый сбой.
        """
        assert classify(self._status_error(status)).category == expected

    @pytest.mark.parametrize("status", [429, 403])
    def test_quota_marker_wins_on_both_statuses(self, status):
        """Маркер квоты в тексте важнее статуса: серьёзность у категорий разная."""
        exc = self._status_error(status, "insufficient_quota")

        result = classify(exc)
        assert result.category == ErrorCategory.QUOTA_EXCEEDED
        assert result.severity == Severity.CRITICAL

    def test_connect_error_is_connection(self):
        """Соединение не установилось."""
        exc = httpx.ConnectError("connection refused")
        assert classify(exc).category == ErrorCategory.CONNECTION

    def test_timeout_is_timeout(self):
        """Таймаут отличается от отказа соединения."""
        exc = httpx.ReadTimeout("timed out")
        assert classify(exc).category == ErrorCategory.TIMEOUT


class TestStatusBranchOrder:
    """Классификация по статусу общая для SDK и httpx, и стоит ниже проверок по классу.

    Поднять её выше нельзя — RateLimitError с quota-маркерами перестанет попадать
    в QUOTA_EXCEEDED.
    """

    def _status_error(self, status: int) -> openai.APIStatusError:
        request = httpx.Request("POST", "https://api.provider.example/v1/chat/completions")
        response = httpx.Response(status_code=status, request=request, json={})
        return openai.APIStatusError("error", response=response, body=None)

    @pytest.mark.parametrize("status,expected", [
        (401, ErrorCategory.AUTH),
        (404, ErrorCategory.NOT_FOUND),
        (400, ErrorCategory.BAD_REQUEST),
        (503, ErrorCategory.SERVER_ERROR),
    ])
    def test_bare_api_status_error_classified_by_status(self, status, expected):
        assert classify(self._status_error(status)).category == expected

    def test_quota_still_wins_over_status(self):
        """Специфичная ветка выше общей: 429 с quota-маркером — не rate limit."""
        request = httpx.Request("POST", "https://api.provider.example/v1/chat/completions")
        response = httpx.Response(status_code=429, request=request, json={})
        exc = openai.RateLimitError(
            "You exceeded your current quota", response=response, body=None,
        )

        assert classify(exc).category == ErrorCategory.QUOTA_EXCEEDED


class TestPublicPhrases:
    """У каждой категории есть текст в каталоге.

    `render_key` бросает `KeyError` на незнакомом ключе, поэтому новая категория без
    записи в каталоге уронила бы саму обработку ошибки.
    """

    @pytest.mark.parametrize("category", ALL_CATEGORIES, ids=lambda c: c.value)
    def test_every_category_has_text(self, category):
        from user_errors import render_key

        text = render_key(f"llmError.{category.value}")

        assert text.strip()
        assert "{" not in text  # плейсхолдеров у этих фраз нет, подставлять нечего

    def test_unclassified_exception_still_gets_key(self):
        """Любое исключение получает ключ, а не пустую строку.

        Сборка фразы из ключа и сокрытие текста провайдера проверяются на самой
        ошибке — `test_error_disclosure.TestLLMApiError`.
        """
        assert public_key(RuntimeError("boom")) == "llmError.unknown"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
