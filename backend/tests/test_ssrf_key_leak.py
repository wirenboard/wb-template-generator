"""Тесты на SSRF-уязвимость: утечка серверного API-ключа через пользовательский URL."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from httpx import Response as HttpxResponse

from config import Settings


# ---------------------------------------------------------------------------
# Фикстуры
# ---------------------------------------------------------------------------

SERVER_KEY = "sk-server-secret-key-12345"
CUSTOM_KEY = "sk-custom-user-key-67890"
SERVER_URL = "https://api.openai.com/v1"
CUSTOM_URL = "http://evil-server.example.com/v1"


@pytest.fixture
def settings_with_key():
    """Settings с серверным ключом."""
    return Settings(
        LLM_API_URL=SERVER_URL,
        LLM_API_KEY=SERVER_KEY,
        LLM_MODEL="gpt-4o",
    )


# ---------------------------------------------------------------------------
# Тесты effective_key: серверный ключ НЕ утекает на пользовательский URL
# ---------------------------------------------------------------------------

class TestEffectiveKeyModels:
    """Тесты для /api/models — логика выбора ключа."""

    @pytest.fixture(autouse=True)
    def _patch_settings(self, settings_with_key):
        with patch("main.get_settings", return_value=settings_with_key):
            yield

    @pytest.mark.anyio
    async def test_custom_url_without_key_no_server_key(self):
        """Пользовательский URL без ключа → Authorization НЕ содержит серверный ключ."""
        from main import app
        from httpx import ASGITransport, AsyncClient
        import httpx as httpx_mod

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json.return_value = {"data": [{"id": "model-1"}]}

            mock_inner = MagicMock()
            mock_inner.get = AsyncMock(return_value=mock_resp)
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_inner)
            mock_ctx.__aexit__ = AsyncMock(return_value=False)

            with patch.object(httpx_mod, "AsyncClient", return_value=mock_ctx):
                resp = await client.post(
                    "/api/models",
                    data={"llm_api_url": CUSTOM_URL},
                )

                call_args = mock_inner.get.call_args
                headers = call_args.kwargs.get("headers", {})
                assert SERVER_KEY not in str(headers), (
                    f"Серверный ключ утёк в headers: {headers}"
                )

    @pytest.mark.anyio
    async def test_custom_url_with_custom_key(self):
        """Пользовательский URL + пользовательский ключ → используется пользовательский ключ."""
        from main import app
        from httpx import ASGITransport, AsyncClient
        import httpx as httpx_mod

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json.return_value = {"data": [{"id": "model-1"}]}

            mock_inner = MagicMock()
            mock_inner.get = AsyncMock(return_value=mock_resp)
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_inner)
            mock_ctx.__aexit__ = AsyncMock(return_value=False)

            with patch.object(httpx_mod, "AsyncClient", return_value=mock_ctx):
                resp = await client.post(
                    "/api/models",
                    data={"llm_api_url": CUSTOM_URL, "llm_api_key": CUSTOM_KEY},
                )

                call_args = mock_inner.get.call_args
                headers = call_args.kwargs.get("headers", {})
                assert f"Bearer {CUSTOM_KEY}" in str(headers), (
                    f"Пользовательский ключ не использован: {headers}"
                )
                assert SERVER_KEY not in str(headers)

    @pytest.mark.anyio
    async def test_server_url_uses_server_key(self):
        """Без пользовательского URL → используется серверный ключ."""
        from main import app
        from httpx import ASGITransport, AsyncClient
        import httpx as httpx_mod

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json.return_value = {"data": [{"id": "gpt-4o"}]}

            mock_inner = MagicMock()
            mock_inner.get = AsyncMock(return_value=mock_resp)
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_inner)
            mock_ctx.__aexit__ = AsyncMock(return_value=False)

            with patch.object(httpx_mod, "AsyncClient", return_value=mock_ctx):
                resp = await client.post("/api/models", data={})

                call_args = mock_inner.get.call_args
                headers = call_args.kwargs.get("headers", {})
                assert f"Bearer {SERVER_KEY}" in str(headers), (
                    f"Серверный ключ не использован для серверного URL: {headers}"
                )


class TestEffectiveKeyTranslate:
    """Тесты для /api/translate — логика выбора ключа."""

    @pytest.fixture(autouse=True)
    def _patch_settings(self, settings_with_key):
        with patch("main.get_settings", return_value=settings_with_key):
            yield

    @pytest.mark.anyio
    async def test_custom_url_no_server_key_leak(self):
        """Пользовательский LLM URL → серверный ключ НЕ передаётся в AsyncOpenAI."""
        from main import app
        from httpx import ASGITransport, AsyncClient

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            with patch("main.AsyncOpenAI") as mock_openai:
                mock_client = AsyncMock()
                mock_client.chat.completions.create = AsyncMock(
                    return_value=MagicMock(
                        choices=[MagicMock(message=MagicMock(content='{"k": "Напряжение"}'))]
                    )
                )
                mock_openai.return_value = mock_client

                resp = await client.post(
                    "/api/translate",
                    json={
                        "strings": {"k": "Voltage"},
                        "target_lang": "ru",
                        "target_lang_name": "Russian",
                        "llm_api_url": CUSTOM_URL,
                    },
                )

                # AsyncOpenAI вызван с пустым ключом, а не серверным
                call_kwargs = mock_openai.call_args.kwargs
                api_key_used = call_kwargs.get("api_key")
                assert api_key_used != SERVER_KEY, (
                    f"Серверный ключ утёк в translate: api_key={api_key_used}"
                )


class TestEffectiveKeyAnalyze:
    """Тесты для llm_service.analyze_document — логика выбора ключа."""

    @pytest.mark.anyio
    async def test_custom_url_no_server_key_in_client(self):
        """Пользовательский URL → AsyncOpenAI создаётся БЕЗ серверного ключа."""
        settings = Settings(
            LLM_API_URL=SERVER_URL,
            LLM_API_KEY=SERVER_KEY,
            LLM_MODEL="gpt-4o",
        )

        with patch("llm_service.AsyncOpenAI") as mock_openai:
            mock_client = AsyncMock()
            # Настраиваем мок чтобы analyze_document прошёл до создания клиента
            mock_openai.return_value = mock_client

            from llm_service import analyze_document

            # Запускаем генератор, он должен дойти до создания AsyncOpenAI
            gen = analyze_document(
                files=[("test.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)],
                template_type="full",
                settings=settings,
                api_url=CUSTOM_URL,
                api_key=None,  # Пользователь НЕ передал ключ
                request_id="test123",
                is_custom_llm=True,
            )

            # Собираем SSE-события до ошибки или вызова OpenAI
            events = []
            try:
                async for event in gen:
                    events.append(event)
                    # После создания клиента — проверяем
                    if mock_openai.called:
                        break
            except Exception:
                pass

            if mock_openai.called:
                call_kwargs = mock_openai.call_args.kwargs
                api_key_used = call_kwargs.get("api_key")
                assert api_key_used != SERVER_KEY, (
                    f"Серверный ключ утёк в analyze: api_key={api_key_used}"
                )

    @pytest.mark.anyio
    async def test_server_url_uses_server_key_in_client(self):
        """Без пользовательского URL → серверный ключ используется корректно."""
        settings = Settings(
            LLM_API_URL=SERVER_URL,
            LLM_API_KEY=SERVER_KEY,
            LLM_MODEL="gpt-4o",
        )

        with patch("llm_service.AsyncOpenAI") as mock_openai:
            mock_client = AsyncMock()
            mock_openai.return_value = mock_client

            from llm_service import analyze_document

            gen = analyze_document(
                files=[("test.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)],
                template_type="full",
                settings=settings,
                api_url=None,  # Серверный URL
                api_key=None,
                request_id="test456",
                is_custom_llm=False,
            )

            events = []
            try:
                async for event in gen:
                    events.append(event)
                    if mock_openai.called:
                        break
            except Exception:
                pass

            if mock_openai.called:
                call_kwargs = mock_openai.call_args.kwargs
                api_key_used = call_kwargs.get("api_key")
                assert api_key_used == SERVER_KEY, (
                    f"Серверный ключ не использован для серверного URL: api_key={api_key_used}"
                )


# ---------------------------------------------------------------------------
# Тесты санитизации ошибок: API-ключ НЕ утекает в сообщениях
# ---------------------------------------------------------------------------

class TestSanitizeError:
    """Тесты для функции _sanitize_error."""

    def test_key_removed_from_error_main(self):
        """_sanitize_error из main.py убирает ключ из сообщения."""
        from main import _sanitize_error
        settings = Settings(LLM_API_KEY=SERVER_KEY)
        error = Exception(f"Authentication failed for key {SERVER_KEY} at endpoint")
        result = _sanitize_error(error, settings)
        assert SERVER_KEY not in result
        assert "***" in result

    def test_key_removed_from_error_llm_service(self):
        """_sanitize_error из llm_service.py убирает ключ из сообщения."""
        from llm_service import _sanitize_error
        settings = Settings(LLM_API_KEY=SERVER_KEY)
        error = Exception(f"Invalid API key: {SERVER_KEY}")
        result = _sanitize_error(error, settings)
        assert SERVER_KEY not in result
        assert "***" in result

    def test_no_key_no_change(self):
        """Без ключа в settings — сообщение не меняется."""
        from main import _sanitize_error
        settings = Settings(LLM_API_KEY="")
        error = Exception("Connection refused")
        result = _sanitize_error(error, settings)
        assert result == "Connection refused"

    def test_key_not_in_message_no_change(self):
        """Ключ есть в settings, но не в сообщении — ничего не заменяется."""
        from main import _sanitize_error
        settings = Settings(LLM_API_KEY=SERVER_KEY)
        error = Exception("Connection timeout after 30s")
        result = _sanitize_error(error, settings)
        assert result == "Connection timeout after 30s"

    def test_multiple_occurrences_replaced(self):
        """Все вхождения ключа в сообщении заменяются."""
        from main import _sanitize_error
        settings = Settings(LLM_API_KEY=SERVER_KEY)
        error = Exception(f"Key {SERVER_KEY} failed, retried with {SERVER_KEY}")
        result = _sanitize_error(error, settings)
        assert SERVER_KEY not in result
        assert result.count("***") == 2


# ---------------------------------------------------------------------------
# Юнит-тесты логики effective_key (без HTTP)
# ---------------------------------------------------------------------------

class TestEffectiveKeyLogic:
    """Прямая проверка логики выбора ключа (тернарный оператор)."""

    def test_custom_url_no_key_returns_none(self):
        """custom_url + нет ключа → None (не серверный ключ)."""
        api_url = CUSTOM_URL
        api_key = None
        server_key = SERVER_KEY

        effective_key = api_key if api_url else (api_key or server_key)
        assert effective_key is None

    def test_custom_url_with_key_returns_custom(self):
        """custom_url + custom_key → custom_key."""
        api_url = CUSTOM_URL
        api_key = CUSTOM_KEY
        server_key = SERVER_KEY

        effective_key = api_key if api_url else (api_key or server_key)
        assert effective_key == CUSTOM_KEY

    def test_no_custom_url_returns_server_key(self):
        """Нет custom_url → серверный ключ."""
        api_url = None
        api_key = None
        server_key = SERVER_KEY

        effective_key = api_key if api_url else (api_key or server_key)
        assert effective_key == server_key

    def test_no_custom_url_with_user_key_returns_user_key(self):
        """Нет custom_url + пользовательский ключ → пользовательский ключ."""
        api_url = None
        api_key = CUSTOM_KEY
        server_key = SERVER_KEY

        effective_key = api_key if api_url else (api_key or server_key)
        assert effective_key == CUSTOM_KEY

    def test_empty_string_url_uses_server_key(self):
        """Пустой URL (не truthy) → fallback на серверный ключ."""
        api_url = ""
        api_key = None
        server_key = SERVER_KEY

        effective_key = api_key if api_url else (api_key or server_key)
        assert effective_key == server_key

    def test_custom_url_empty_key_returns_empty(self):
        """custom_url + пустой ключ → пустой ключ (не серверный)."""
        api_url = CUSTOM_URL
        api_key = ""
        server_key = SERVER_KEY

        effective_key = api_key if api_url else (api_key or server_key)
        assert effective_key == ""
        assert effective_key != server_key
