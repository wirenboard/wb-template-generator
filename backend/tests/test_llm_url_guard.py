"""Проверка адреса пользовательского LLM (SSRF).

Адрес приходит в запросе без авторизации и становится base_url клиента OpenAI,
то есть сервер идёт по нему сам. Здесь закрыты схема, приватные диапазоны, флаг
LLM_ALLOW_PRIVATE_URLS для своего развёртывания и запрет редиректов, которым
проверка обходится в один ответ 302.
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from openai import APIStatusError, AsyncOpenAI

# Добавляем backend/ в sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from llm_service import (  # noqa: E402, I001
    UnsafeLLMUrlError,
    build_llm_http_client,
    ensure_public_llm_url,
)


# ---------------------------------------------------------------------------
# Схема и хост
# ---------------------------------------------------------------------------

class TestUrlShape:
    """Отбраковка адреса до резолва имени."""

    @pytest.mark.parametrize("url", [
        "file:///etc/passwd",
        "ftp://example.com/v1",
        "gopher://example.com:70/v1",
        "example.com/v1",  # без схемы
    ])
    async def test_non_http_scheme_rejected(self, url):
        """Всё кроме http и https отклоняется."""
        with pytest.raises(UnsafeLLMUrlError):
            await ensure_public_llm_url(url)

    async def test_missing_host_rejected(self):
        """Адрес без хоста отклоняется — резолвить нечего."""
        with pytest.raises(UnsafeLLMUrlError):
            await ensure_public_llm_url("http:///v1")

    @pytest.mark.parametrize("url", [
        "http://[evil/v1",       # незакрытая скобка читается как IPv6-литерал
        "http://[::1/v1",
        "http://\x1b[31mevil/v1",
    ])
    async def test_unparsable_url_rejected(self, url):
        """Адрес, который не разбирается вовсе, тоже отказ, а не пятисотка."""
        with pytest.raises(UnsafeLLMUrlError):
            await ensure_public_llm_url(url)

    async def test_unresolvable_host_rejected(self):
        """Имя не резолвится — считаем адрес непригодным, а не пропускаем дальше."""
        with patch("llm_service._resolve_host", AsyncMock(side_effect=OSError("no such host"))):
            with pytest.raises(UnsafeLLMUrlError):
                await ensure_public_llm_url("https://no-such-host.example/v1")

    async def test_slow_resolver_rejected(self):
        """Молчащий NS не держит резолвер процесса — потолок на разрешение имени."""
        with patch("llm_service._resolve_host", AsyncMock(side_effect=TimeoutError)):
            with pytest.raises(UnsafeLLMUrlError):
                await ensure_public_llm_url("https://slow-ns.example/v1")


# ---------------------------------------------------------------------------
# Диапазоны адресов
# ---------------------------------------------------------------------------

class TestAddressRanges:
    """Внутренняя сеть закрыта, публичные адреса проходят."""

    @pytest.mark.parametrize("address", [
        "10.0.0.5",            # RFC1918
        "192.168.1.10",        # RFC1918
        "172.16.0.1",          # RFC1918
        "127.0.0.1",           # loopback
        "169.254.169.254",     # link-local, служебный адрес облака
        "224.0.0.1",           # multicast
        "240.0.0.1",           # reserved
        "0.0.0.0",             # unspecified
        "::1",                 # loopback IPv6
        "::ffff:10.0.0.1",     # приватный IPv4 в обёртке IPv6
        "100.64.0.1",          # CGNAT, он же диапазон Tailscale
        "100.127.255.254",     # верхняя граница того же диапазона
        "fec0::1",             # site-local IPv6
        "2002:0a00:0001::1",   # 6to4-обёртка 10.0.0.1
    ])
    async def test_internal_address_rejected(self, address):
        """Хост, разрешающийся во внутренний адрес, отклоняется.

        Последние четыре пункта закрыты отдельным списком сетей — CGNAT и
        site-local `ipaddress` приватными не считает (у site-local вдобавок
        is_global=True), а 6to4 считает только начиная с Python 3.12.4.
        """
        with patch("llm_service._resolve_host", AsyncMock(return_value=[address])):
            with pytest.raises(UnsafeLLMUrlError):
                await ensure_public_llm_url("https://llm.attacker.example/v1")

    @pytest.mark.parametrize("address", ["8.8.8.8", "1.1.1.1", "2001:4860:4860::8888"])
    async def test_public_address_allowed(self, address):
        """Публичный адрес проходит — BYO-LLM остаётся рабочей фичей."""
        with patch("llm_service._resolve_host", AsyncMock(return_value=[address])):
            await ensure_public_llm_url("https://api.provider.example/v1")

    async def test_mixed_answer_rejected(self):
        """Одного внутреннего адреса в ответе DNS достаточно для отказа."""
        with patch("llm_service._resolve_host", AsyncMock(return_value=["8.8.8.8", "10.0.0.5"])):
            with pytest.raises(UnsafeLLMUrlError):
                await ensure_public_llm_url("https://llm.attacker.example/v1")


# ---------------------------------------------------------------------------
# Флаг LLM_ALLOW_PRIVATE_URLS
# ---------------------------------------------------------------------------

class TestAllowPrivateFlag:
    """Своё развёртывание с локальной LLM."""

    async def test_private_address_allowed_with_flag(self):
        """С флагом внутренний адрес проходит и имя не резолвится вовсе."""
        resolver = AsyncMock(return_value=["10.0.0.5"])
        with patch("llm_service._resolve_host", resolver):
            await ensure_public_llm_url("http://ollama.local:11434/v1", allow_private=True)

        assert resolver.await_count == 0, (
            "С разрешёнными приватными адресами резолв не нужен — внутреннее имя "
            "снаружи всё равно не разрешается"
        )

    async def test_scheme_still_checked_with_flag(self):
        """Флаг снимает проверку сети, но не схемы."""
        with pytest.raises(UnsafeLLMUrlError):
            await ensure_public_llm_url("file:///etc/passwd", allow_private=True)


# ---------------------------------------------------------------------------
# Редиректы
# ---------------------------------------------------------------------------

class TestHttpClient:
    """Клиент httpx для обращений к LLM."""

    async def test_redirects_disabled(self):
        """Редиректы запрещены: иначе 302 на публичном адресе уводит во внутреннюю сеть."""
        client = build_llm_http_client()
        try:
            assert client.follow_redirects is False
        finally:
            await client.aclose()

    async def test_redirects_disabled_with_proxy(self):
        """С прокси запрет редиректов сохраняется."""
        client = build_llm_http_client("http://proxy.example:3128")
        try:
            assert client.follow_redirects is False
        finally:
            await client.aclose()

    async def test_sdk_does_not_follow_redirect(self):
        """Запрос через AsyncOpenAI на 302 внутрь не идёт.

        Настройки клиента мало — SDK умеет перекрывать её на уровне запроса, а версия
        openai у нас диапазоном, так что свойство надо проверять поведением. Транспорт
        подменяем на готовом клиенте, аргументом фабрика его не принимает.
        """
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(str(request.url))
            if len(seen) == 1:
                return httpx.Response(302, headers={"location": "http://10.0.0.1/v1/chat/completions"})
            return httpx.Response(200, json={"choices": [{"message": {"content": "внутренний ответ"}}]})

        client = build_llm_http_client()
        client._transport = httpx.MockTransport(handler)
        sdk = AsyncOpenAI(
            base_url="https://provider.example/v1", api_key="k", http_client=client, max_retries=0,
        )
        try:
            with pytest.raises(APIStatusError):
                await sdk.chat.completions.create(model="m", messages=[{"role": "user", "content": "x"}])
        finally:
            await client.aclose()

        assert seen == ["https://provider.example/v1/chat/completions"]



# ---------------------------------------------------------------------------
# Эндпоинт
# ---------------------------------------------------------------------------

class TestEndpointRejection:
    """Проверка стоит на маршруте, а не только в функции."""

    INTERNAL_URL = "http://127.0.0.1:8080/v1"

    @pytest.fixture(autouse=True)
    def _clean_rate_limit(self):
        # Бакет лимитера общий на процесс, а /api/analyze троттлится по IP — чистим
        # с двух сторон, иначе соседние тесты дают здесь 429 вместо 400 и наоборот.
        import main

        main._rate_limit_store.clear()
        yield
        main._rate_limit_store.clear()

    @staticmethod
    def _client():
        from fastapi.testclient import TestClient

        import main

        # Без lifespan: очереди и уведомления для этой проверки не нужны
        return TestClient(main.app)

    def test_models_rejects_internal_url(self):
        """Список моделей по внутреннему адресу — 400 до всякого запроса в сеть."""
        resp = self._client().post("/api/models", data={"llm_api_url": self.INTERNAL_URL})

        assert resp.status_code == 400
        assert resp.json()["message_key"] == "serverError.llmUrlPrivate"

    def test_analyze_rejects_internal_url(self):
        """Ответ обычный 400, хотя маршрут отдаёт SSE: адрес проверяется до потока."""
        resp = self._client().post(
            "/api/analyze",
            files=[("files", ("p.png", b"x", "image/png"))],
            data={"llm_api_url": self.INTERNAL_URL},
        )

        assert resp.status_code == 400
        assert resp.json()["message_key"] == "serverError.llmUrlPrivate"

    def test_fix_registers_rejects_internal_url(self):
        resp = self._client().post(
            "/api/fix-registers",
            json={"registers": [], "llm_api_url": self.INTERNAL_URL},
        )

        assert resp.status_code == 400
        assert resp.json()["message_key"] == "serverError.llmUrlPrivate"

    def test_translate_rejects_internal_url(self):
        resp = self._client().post(
            "/api/translate",
            json={
                "strings": {"a": "b"}, "target_lang": "de", "target_lang_name": "Deutsch",
                "llm_api_url": self.INTERNAL_URL,
            },
        )

        assert resp.status_code == 400
        assert resp.json()["message_key"] == "serverError.llmUrlPrivate"

    def test_rejection_carries_request_id(self):
        """Общий обработчик отдаёт номер запроса — по нему ищут в логе."""
        resp = self._client().post("/api/models", data={"llm_api_url": self.INTERNAL_URL})

        assert resp.json()["request_id"]
