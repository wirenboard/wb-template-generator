"""Текст ошибки провайдера не уходит клиенту.

Адрес LLM задаёт сам клиент, а сырой текст исключения различает отказ соединения,
ошибку DNS, TLS и HTTP-статус — то есть превращает проверку адреса в оракул по
внутренней сети. Наружу идёт фраза по категории, сырой текст остаётся в логе и в
поле `raw` для внутренних эвристик.
"""

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

# Добавляем backend/ в sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import Settings  # noqa: E402, I001
from llm_service import (  # noqa: E402
    LLMApiError,
    _is_file_unsupported,
    analyze_document,
    fix_registers,
)
from models import Register  # noqa: E402
from user_errors import render_key  # noqa: E402

INTERNAL_DETAIL = "Connection refused to 10.11.12.13:8080 (internal-registry.local)"


def _make_settings(**overrides) -> Settings:
    defaults = {
        "LLM_API_URL": "https://api.server.example.com/v1",
        "LLM_API_KEY": "sk-server",
        "LLM_MODEL": "gpt-4o",
        "LLM_TIMEOUT": 60,
        "LLM_SOFT_TIMEOUT": 30,
        "LLM_PROXY": "",
    }
    defaults.update(overrides)
    return Settings(**defaults)


def _mock_llm_response(content: str = '{"device_info":{"name":"T","id":"t"},"registers":[]}'):
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message.content = content
    resp.choices[0].finish_reason = "stop"
    resp.usage = MagicMock(prompt_tokens=10, completion_tokens=10, total_tokens=20)
    return resp


async def _collect_events(gen) -> str:
    """Склеивает все SSE-события в одну строку."""
    return "".join([event async for event in gen])


# ---------------------------------------------------------------------------
# Разделение публичного и сырого текста
# ---------------------------------------------------------------------------

class TestLLMApiError:
    """Ошибка обращения к LLM несёт два текста."""

    def test_public_and_raw_split(self):
        """Наружу — обобщённая фраза по ключу, внутрь — текст провайдера."""
        err = LLMApiError("llmError.connection", raw=INTERNAL_DETAIL)

        assert str(err) == render_key("llmError.connection")
        assert INTERNAL_DETAIL not in str(err)
        assert err.raw == INTERNAL_DETAIL

    def test_message_cannot_diverge_from_key(self):
        """Текст собирается из ключа, поэтому несогласованный отказ не создаётся."""
        err = LLMApiError.from_provider(httpx.ConnectError(INTERNAL_DETAIL))

        assert err.key == "llmError.connection"
        assert str(err) == render_key("llmError.connection")
        assert INTERNAL_DETAIL not in str(err)
        assert INTERNAL_DETAIL in err.raw

    def test_raw_defaults_to_message(self):
        """Собственные сообщения (пустой ответ LLM) остаются одним текстом."""
        err = LLMApiError("serverError.llmEmptyResponse")

        assert err.raw == render_key("serverError.llmEmptyResponse")

    def test_file_unsupported_heuristic_reads_raw(self):
        """Определение «модель не понимает файл» работает от сырого текста.

        Обобщённая фраза маркеров провайдера не содержит, поэтому эвристика обязана
        смотреть в raw — иначе откат на конвертацию перестал бы срабатывать.
        """
        err = LLMApiError(
            "llmError.bad_request",
            raw="Invalid content type 'file' is not supported by this model",
        )

        assert _is_file_unsupported(err.raw) is True
        assert _is_file_unsupported(str(err)) is False


# ---------------------------------------------------------------------------
# Анализ документа
# ---------------------------------------------------------------------------

class TestAnalyzeDisclosure:
    """Поток анализа не отдаёт текст исключения."""

    @pytest.mark.asyncio
    async def test_api_error_reported_as_category(self):
        """Сбой обращения к LLM описывается категорией, без текста провайдера."""
        settings = _make_settings()

        with (
            patch("llm_service.AsyncOpenAI") as mock_openai,
            patch("llm_service.open_image", return_value=MagicMock()),
            patch("llm_service.image_to_base64", return_value="dGVzdA=="),
        ):
            mock_client = AsyncMock()
            mock_openai.return_value = mock_client
            mock_client.chat.completions.create = AsyncMock(
                side_effect=Exception(INTERNAL_DETAIL),
            )

            events = await _collect_events(analyze_document(
                files=[("test.png", b"fake-png-data")],
                template_type="full",
                settings=settings,
                is_custom_llm=False,
            ))

        assert "10.11.12.13" not in events
        assert "internal-registry.local" not in events
        assert "провайдеру LLM" in events or "провайдера LLM" in events

    @pytest.mark.asyncio
    async def test_unexpected_error_reported_generically(self):
        """Непредвиденный сбой отдаёт общий текст, детали только в лог."""
        settings = _make_settings()

        with (
            patch("llm_service.AsyncOpenAI") as mock_openai,
            patch("llm_service.open_image", return_value=MagicMock()),
            patch("llm_service.image_to_base64", return_value="dGVzdA=="),
            patch("llm_service._merge_batch_results", side_effect=Exception(INTERNAL_DETAIL)),
        ):
            mock_client = AsyncMock()
            mock_openai.return_value = mock_client
            mock_client.chat.completions.create = AsyncMock(return_value=_mock_llm_response())

            events = await _collect_events(analyze_document(
                files=[("test.png", b"fake-png-data")],
                template_type="full",
                settings=settings,
                is_custom_llm=False,
            ))

        assert INTERNAL_DETAIL not in events
        assert "10.11.12.13" not in events
        assert "Внутренняя ошибка" in events


# ---------------------------------------------------------------------------
# Исправление регистров
# ---------------------------------------------------------------------------

class TestFixRegistersDisclosure:
    """Кнопка «Исправить через AI» ведёт себя так же."""

    @pytest.mark.asyncio
    async def test_api_error_without_provider_text(self):
        """В SSE уходит публичная фраза ошибки, не текст провайдера."""

        async def _boom(*args, **kwargs):
            raise LLMApiError("llmError.auth", raw=INTERNAL_DETAIL)

        with (
            patch("llm_service.AsyncOpenAI"),
            patch("llm_service._fix_registers_core", _boom),
        ):
            events = await _collect_events(fix_registers(
                [Register(id="r0", address=70000, name="Bad")],
                "адрес больше 65535",
                effective_url="https://api.provider.example/v1",
                effective_key="sk-user",
                effective_model="gpt-4o",
            ))

        assert INTERNAL_DETAIL not in events
        # Категория обёрнута в предложение, а ключ уходит вложенным для перевода
        assert "Не удалось исправить регистры — провайдер LLM не принял ключ." in events
        assert '"message_key": "serverError.fixFailed"' in events
        assert '"reasonKey": "llmError.auth"' in events


# ---------------------------------------------------------------------------
# Обычные JSON-ответы
# ---------------------------------------------------------------------------

class TestJsonResponseDisclosure:
    """Маршруты без SSE закрыты так же, как поток анализа.

    Список моделей и перевод отдают обычный JSON — отдельный путь текста наружу.
    """

    @pytest.fixture
    def client(self, monkeypatch):
        from fastapi.testclient import TestClient

        import main

        # Свой адрес LLM проверку проходит: интересует текст ответа, а не гард
        async def _skip_url_check(url, allow_private=False):
            return None

        monkeypatch.setattr(main, "ensure_public_llm_url", _skip_url_check)
        main._rate_limit_store.clear()
        return TestClient(main.app)

    def test_models_error_hides_provider_text(self, client, monkeypatch):
        """`/api/models` отдаёт 502 с категорией, без текста провайдера."""
        import main

        # Настоящий транспортный сбой httpx: заодно проверяется, что классификатор
        # разбирает его в категорию, а не сваливает в «неизвестно»
        failing = AsyncMock()
        failing.get = AsyncMock(side_effect=httpx.ConnectError(INTERNAL_DETAIL))
        monkeypatch.setattr(
            main, "get_llm_http_client", lambda proxy=None, is_custom=False: failing,
        )

        resp = client.post("/api/models", data={
            "llm_api_url": "https://api.provider.example/v1", "llm_api_key": "sk-user",
        })
        body = resp.json()

        assert resp.status_code == 502
        assert INTERNAL_DETAIL not in resp.text
        assert "10.11.12.13" not in resp.text
        assert "internal-registry.local" not in resp.text
        assert body["message_key"] == "serverError.modelsFailed"
        # Категория уходит ключом, поэтому интерфейс переведёт её сам
        assert body["message_params"] == {"reasonKey": "llmError.connection"}

    def test_translate_error_hides_provider_text(self, client, monkeypatch):
        """`/api/translate` отдаёт 500 с категорией, без текста провайдера."""
        import main

        # Роняем сам вызов к провайдеру: создание клиента идёт до try, и сбой
        # там ушёл бы в общий обработчик, а проверяем мы ветку перевода
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(
            side_effect=httpx.ConnectError(INTERNAL_DETAIL),
        )
        monkeypatch.setattr(main, "AsyncOpenAI", lambda **kwargs: mock_client)

        resp = client.post("/api/translate", json={
            "strings": {"a": "Voltage"},
            "target_lang": "de",
            "target_lang_name": "Deutsch",
            "llm_api_url": "https://api.provider.example/v1",
            "llm_api_key": "sk-user",
        })
        body = resp.json()

        assert resp.status_code == 500
        assert INTERNAL_DETAIL not in resp.text
        assert "10.11.12.13" not in resp.text
        assert body["message_key"] == "serverError.translateFailed"
        assert body["message_params"] == {"reasonKey": "llmError.connection"}

    def test_translate_unparsable_answer_is_not_provider_failure(self, client, monkeypatch):
        """Проза вместо JSON — наш сбой разбора, категорией провайдера не называется.

        Провайдер в этот момент ответил штатно, поэтому категория `llmError.*` увела бы
        и пользователя, и поддержку к нему, а нотификатор поднял бы дежурного зря.
        """
        import main

        alerts = []

        async def _record_alert(exc, **kwargs):
            alerts.append(exc)

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(
            return_value=_mock_llm_response("Sure! Here are your translations."),
        )
        monkeypatch.setattr(main, "AsyncOpenAI", lambda **kwargs: mock_client)
        monkeypatch.setattr(main, "report_llm_api_error", _record_alert)

        resp = client.post("/api/translate", json={
            "strings": {"a": "Voltage"},
            "target_lang": "de",
            "target_lang_name": "Deutsch",
            "llm_api_url": "https://api.provider.example/v1",
            "llm_api_key": "sk-user",
        })
        body = resp.json()

        assert resp.status_code == 500
        assert body["message_key"] == "serverError.translateFailed"
        assert body["message_params"] == {"reasonKey": "serverError.llmUnparsableResponse"}
        assert alerts == []

    def test_models_unparsable_answer_is_not_provider_failure(self, client, monkeypatch):
        """Не-JSON по адресу списка моделей (HTML прокси) — тоже наш сбой разбора."""
        import main

        not_json = MagicMock()
        not_json.raise_for_status = MagicMock(return_value=None)
        not_json.json = MagicMock(
            side_effect=json.JSONDecodeError("Expecting value", "<html>502</html>", 0),
        )
        failing = AsyncMock()
        failing.get = AsyncMock(return_value=not_json)
        monkeypatch.setattr(
            main, "get_llm_http_client", lambda proxy=None, is_custom=False: failing,
        )

        resp = client.post("/api/models", data={
            "llm_api_url": "https://api.provider.example/v1", "llm_api_key": "sk-user",
        })
        body = resp.json()

        assert resp.status_code == 502
        assert "<html>" not in resp.text
        assert body["message_key"] == "serverError.modelsFailed"
        assert body["message_params"] == {"reasonKey": "serverError.llmUnparsableResponse"}

    def test_unhandled_error_hides_internals(self, client, monkeypatch):
        """Непредвиденное падение отдаёт общий текст, а не трейс и не адрес."""
        from fastapi.testclient import TestClient

        import main

        def _boom():
            raise RuntimeError(INTERNAL_DETAIL)

        monkeypatch.setattr(main, "get_settings", _boom)
        # raise_server_exceptions=False — нужен ответ 500, а не проброс в тест
        crashing = TestClient(main.app, raise_server_exceptions=False)

        resp = crashing.get("/api/status")

        assert resp.status_code == 500
        assert INTERNAL_DETAIL not in resp.text
        assert resp.json()["message_key"] == "serverError.internal"
