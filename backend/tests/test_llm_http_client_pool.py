"""Общие httpx-клиенты процесса для обращений к LLM.

Клиентов два, серверный и пользовательский. Оба выдаются из одного места и
закрываются в lifespan. Клиент на запрос означал бы TCP и TLS-handshake на
каждое обращение, а сокет освобождался бы недетерминированно, когда до объекта
доберётся сборщик мусора.
"""

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Добавляем backend/ в sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

import llm_service  # noqa: E402, I001
import main  # noqa: E402
from llm_service import close_llm_http_clients, get_llm_http_client  # noqa: E402

PROXY = "http://proxy.example:3128"


@pytest.fixture
def factory_calls(monkeypatch):
    """Запоминает, с какими аргументами создавались клиенты."""
    calls: list[tuple] = []
    original = llm_service.build_llm_http_client

    def spy(proxy=None, limits=None):
        calls.append((proxy, limits))
        return original(proxy, limits)

    monkeypatch.setattr(llm_service, "build_llm_http_client", spy)
    return calls


class TestSharedClients:
    """Выдача из одного места: экземпляр на флаг, а не на запрос."""

    async def test_same_flag_returns_same_instance(self):
        assert get_llm_http_client() is get_llm_http_client()
        await close_llm_http_clients()

    async def test_server_and_custom_are_different(self):
        """Чужой медленный хост не должен выбирать пул соединений на всех."""
        server = get_llm_http_client()
        custom = get_llm_http_client(is_custom=True)

        assert server is not custom
        await close_llm_http_clients()

    async def test_client_created_once_per_flag(self, factory_calls):
        for _ in range(3):
            get_llm_http_client()

        assert len(factory_calls) == 1
        await close_llm_http_clients()

    async def test_close_then_reissue(self):
        """После закрытия следующее обращение получает новый живой клиент."""
        stale = get_llm_http_client()
        await close_llm_http_clients()

        assert stale.is_closed
        fresh = get_llm_http_client()

        assert fresh is not stale
        assert not fresh.is_closed
        await close_llm_http_clients()


class TestProxyAndLimits:
    """Прокси оператора и потолок соединений раздаются по признаку «чей адрес»."""

    async def test_server_client_gets_proxy(self, factory_calls):
        get_llm_http_client(PROXY)

        assert factory_calls == [(PROXY, None)]
        await close_llm_http_clients()

    async def test_custom_client_never_gets_proxy(self, factory_calls):
        """Прокси не уходит чужому адресу, даже если его передали аргументом."""
        get_llm_http_client(PROXY, is_custom=True)

        assert factory_calls == [(None, llm_service._CUSTOM_LIMITS)]
        await close_llm_http_clients()


def test_shutdown_closes_shared_clients():
    """Остановка приложения закрывает клиенты.

    TestClient как контекст поднимает и останавливает lifespan, то есть выход из
    блока это и есть остановка сервиса. Без закрытия соединения переживут её.
    """
    with TestClient(main.app):
        client = get_llm_http_client()
        assert not client.is_closed

    assert client.is_closed
