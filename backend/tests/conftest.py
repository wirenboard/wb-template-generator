"""Общие фикстуры бэкенд-тестов."""

import sys
from pathlib import Path

# Добавляем backend/ в sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest  # noqa: E402

import llm_service  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate_shared_llm_http_clients():
    """Изолирует кэш общих httpx-клиентов между тестами.

    Без очистки клиент одного теста, в том числе мок, остаётся в кэше и уезжает
    в соседние. Настоящие клиенты тест закрывает сам.
    """
    yield
    llm_service._llm_http_clients.clear()
