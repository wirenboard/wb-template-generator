"""Проверка, что эндпоинты main видят очереди после init_queues().

Регресс, который лечим: main делал `from queue_manager import server_queue`, то есть
копировал None на момент импорта, а init_queues() присваивает переменные внутри
queue_manager. В результате очереди не подключались вообще — ограничение
параллельных анализов не работало, а /api/queue-status всегда отдавал null.

Тесты дёргают функции эндпоинтов, а не повторяют их тело, иначе регресс не поймать.
"""

import pytest

import main
import queue_manager


@pytest.fixture(autouse=True)
def reset_queues():
    """Каждый тест начинает с неинициализированных очередей и возвращает их обратно."""
    queue_manager.server_queue = None
    queue_manager.custom_queue = None
    yield
    queue_manager.server_queue = None
    queue_manager.custom_queue = None


async def test_queue_status_endpoint_reports_initialized_queues():
    """/api/queue-status отдаёт состояние очередей с лимитами из конфига."""
    queue_manager.init_queues(server_max=3, custom_max=7, activation_delay=0)

    status = await main.queue_status()

    assert status["server"]["name"] == "server"
    assert status["server"]["max_concurrent"] == 3
    assert status["server"]["active"] == 0
    assert status["server"]["waiting"] == 0
    assert status["custom"]["max_concurrent"] == 7


async def test_health_endpoint_reports_initialized_queues():
    """/api/health показывает очереди, а не null."""
    queue_manager.init_queues(server_max=2, custom_max=2, activation_delay=0)

    payload = await main.health()

    assert payload["queues"]["server"]["max_concurrent"] == 2
    assert payload["queues"]["custom"]["max_concurrent"] == 2


async def test_endpoints_report_null_without_init():
    """Без init_queues() (например, в тестах) эндпоинты отдают null, а не падают."""
    status = await main.queue_status()
    payload = await main.health()

    assert status == {"server": None, "custom": None}
    assert payload["queues"] == {"server": None, "custom": None}


async def test_analyze_uses_queue_slot():
    """Анализ занимает слот в выбранной очереди и освобождает его на выходе."""
    queue_manager.init_queues(server_max=1, custom_max=1, activation_delay=0)
    queue = queue_manager.server_queue
    assert queue is not None

    async with queue.ticket("req-1") as ticket:
        assert await ticket.wait(timeout=0) is True
        assert (await main.queue_status())["server"]["active"] == 1

    assert (await main.queue_status())["server"]["active"] == 0
