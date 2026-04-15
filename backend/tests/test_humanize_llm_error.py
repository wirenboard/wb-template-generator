"""Тесты для _humanize_llm_error — человекочитаемые сообщения об ошибках LLM API."""

import pytest

from llm_service import _humanize_llm_error


class TestHumanizeLlmError:
    """Проверяет, что типичные ошибки OpenAI SDK преобразуются в понятные сообщения."""

    # --- Аутентификация (401) ---

    def test_401_error_code(self):
        msg = _humanize_llm_error(
            "Error code: 401 - {'error': {'message': 'Incorrect API key provided'}}"
        )
        assert "Неверный API-ключ" in msg
        assert "401" in msg  # технические детали сохранены

    def test_authentication_error(self):
        msg = _humanize_llm_error("Authentication error: invalid api key")
        assert "Неверный API-ключ" in msg

    def test_unauthorized(self):
        msg = _humanize_llm_error("Unauthorized")
        assert "Неверный API-ключ" in msg

    # --- Доступ запрещён (403) ---

    def test_403_permission_denied(self):
        msg = _humanize_llm_error(
            "Error code: 403 - {'error': {'message': 'Permission denied'}}"
        )
        assert "Доступ запрещён" in msg

    def test_forbidden(self):
        msg = _humanize_llm_error("Forbidden: you don't have access to this resource")
        assert "Доступ запрещён" in msg

    # --- Модель не найдена (404) ---

    def test_model_not_found(self):
        msg = _humanize_llm_error(
            "Error code: 404 - {'error': {'message': "
            "'The model `gpt-5-turbo` does not exist or you do not have access to it.'}}"
        )
        assert "Модель не найдена" in msg

    def test_model_not_found_keyword(self):
        msg = _humanize_llm_error("model_not_found: no such model")
        assert "Модель не найдена" in msg

    # --- Другой 404 (неверный URL) ---

    def test_404_endpoint_not_found(self):
        msg = _humanize_llm_error("Error code: 404 - endpoint not available")
        assert "Эндпоинт не найден" in msg

    # --- Rate limit (429) ---

    def test_429_rate_limit(self):
        msg = _humanize_llm_error(
            "Error code: 429 - {'error': {'message': 'Rate limit reached'}}"
        )
        assert "лимит запросов" in msg

    def test_too_many_requests(self):
        msg = _humanize_llm_error("Too Many Requests")
        assert "лимит запросов" in msg

    def test_quota_exceeded(self):
        msg = _humanize_llm_error("You exceeded your current quota")
        assert "лимит запросов" in msg

    # --- Контекст / токены ---

    def test_context_length_exceeded(self):
        msg = _humanize_llm_error(
            "This model's maximum context length is 128000 tokens"
        )
        assert "контекстного окна" in msg

    def test_context_too_long(self):
        msg = _humanize_llm_error(
            "Request too long: context length exceeds the maximum"
        )
        assert "контекстного окна" in msg

    # --- Таймаут ---

    def test_timeout(self):
        msg = _humanize_llm_error("Request timed out.")
        assert "Таймаут" in msg

    def test_timeout_keyword(self):
        msg = _humanize_llm_error("Connection timeout after 300s")
        assert "Таймаут" in msg

    # --- Ошибки соединения ---

    def test_connection_error(self):
        msg = _humanize_llm_error("Connection error.")
        assert "Не удалось подключиться" in msg

    def test_connection_refused(self):
        msg = _humanize_llm_error("Connection refused: localhost:8080")
        assert "Не удалось подключиться" in msg

    def test_dns_resolution(self):
        msg = _humanize_llm_error(
            "Could not resolve hostname: api.example.com"
        )
        assert "Не удалось определить адрес" in msg

    def test_getaddrinfo(self):
        msg = _humanize_llm_error(
            "getaddrinfo failed for api.example.com"
        )
        assert "Не удалось определить адрес" in msg

    # --- SSL ---

    def test_ssl_error(self):
        msg = _humanize_llm_error("SSL: CERTIFICATE_VERIFY_FAILED")
        assert "SSL" in msg

    # --- Серверные ошибки (5xx) ---

    def test_500_internal(self):
        msg = _humanize_llm_error(
            "Error code: 500 - Internal server error"
        )
        assert "Внутренняя ошибка сервера" in msg

    def test_502_bad_gateway(self):
        msg = _humanize_llm_error("Error code: 502 - Bad Gateway")
        assert "шлюза" in msg

    def test_503_unavailable(self):
        msg = _humanize_llm_error("Error code: 503 - Service Unavailable")
        assert "недоступен" in msg

    def test_503_overloaded(self):
        msg = _humanize_llm_error("Server is overloaded")
        assert "недоступен" in msg

    def test_529_overloaded(self):
        msg = _humanize_llm_error("Error code: 529 - Overloaded")
        assert "перегружен" in msg

    # --- Невалидный JSON ---

    def test_json_decode_error(self):
        msg = _humanize_llm_error("JSON decode error: unexpected token")
        assert "невалидный ответ" in msg

    # --- Неизвестная ошибка ---

    def test_unknown_error_passthrough(self):
        raw = "Some completely unknown error text"
        msg = _humanize_llm_error(raw)
        assert msg == f"Ошибка LLM API: {raw}"

    # --- Технические детали сохраняются ---

    def test_technical_details_preserved(self):
        raw = "Error code: 401 - {'error': {'message': 'Incorrect API key provided: sk-1234****'}}"
        msg = _humanize_llm_error(raw)
        assert "Технические детали:" in msg
        assert raw in msg

    def test_unknown_has_no_technical_section(self):
        """Неизвестные ошибки идут как есть, без секции «Технические детали»."""
        raw = "Weird error XYZ"
        msg = _humanize_llm_error(raw)
        assert "Технические детали" not in msg
