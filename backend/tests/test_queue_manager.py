"""Поведение AnalyzeQueue: лимит слотов, ожидание, уход из очереди, дренаж.

Ключевые свойства, которые здесь закрепляются:
- слот освобождает только тот, кто его занял (уход из очереди чужой слот не трогает);
- лимит не превышается при конкурентной нагрузке;
- в замер длительности попадает работа, а не время ожидания в очереди.
"""

import asyncio

from queue_manager import AnalyzeQueue


async def test_limit_and_queue_position():
    """Свободные слоты занимаются сразу, лишний запрос встаёт в очередь с позицией."""
    queue = AnalyzeQueue(max_concurrent=2, name="test")

    async with queue.ticket("a") as first, queue.ticket("b") as second, queue.ticket("c") as third:
        assert await first.wait(timeout=0) is True
        assert await second.wait(timeout=0) is True
        assert await third.wait(timeout=0) is False

        assert queue.active_count == 2
        assert queue.waiting_count == 1
        assert third.position == 1
        assert first.position is None  # занявший слот в очереди не стоит

    assert queue.active_count == 0
    assert queue.waiting_count == 0


async def test_slot_passes_to_waiter_after_exit():
    """Выход из ticket() освобождает слот, и ожидающий его получает."""
    queue = AnalyzeQueue(max_concurrent=1, name="test")

    async with queue.ticket("waiter") as waiter:
        async with queue.ticket("holder") as holder:
            assert await holder.wait(timeout=0) is True
            assert await waiter.wait(timeout=0) is False

        assert await waiter.wait(timeout=1) is True
        assert queue.active_count == 1

    assert queue.active_count == 0


async def test_leaving_queue_does_not_touch_others_slot():
    """Уход из очереди без слота (обрыв SSE) не освобождает слот работающего.

    Регресс: release() в finally срабатывал и когда слот не занимался, из-за чего
    счётчик активных уезжал и лимит параллельности деградировал.
    """
    queue = AnalyzeQueue(max_concurrent=1, name="test")

    async with queue.ticket("holder") as holder:
        assert await holder.wait(timeout=0) is True

        # Постоял в очереди и ушёл, слота так и не получив
        async with queue.ticket("gone") as gone:
            assert await gone.wait(timeout=0) is False
            assert queue.waiting_count == 1

        assert queue.waiting_count == 0
        assert queue.active_count == 1

        # Слот держателя по-прежнему занят, новый желающий не проходит
        async with queue.ticket("next") as nxt:
            assert await nxt.wait(timeout=0) is False

    assert queue.active_count == 0


async def test_slot_arriving_after_leave_returns_to_pool():
    """Слот, пришедший ушедшему тикету, возвращается в пул, а не теряется."""
    queue = AnalyzeQueue(max_concurrent=1, name="test")

    # Контекст открываем вручную, чтобы задать точный порядок событий
    holder_ctx = queue.ticket("holder")
    holder = await holder_ctx.__aenter__()
    assert await holder.wait(timeout=0) is True

    late_ctx = queue.ticket("late")
    late = await late_ctx.__aenter__()
    assert await late.wait(timeout=0) is False

    await holder_ctx.__aexit__(None, None, None)  # слот уходит ожидающему late
    await asyncio.sleep(0)                        # даём задаче late забрать разрешение
    await late_ctx.__aexit__(None, None, None)    # late ушёл, не спросив wait()

    assert queue.active_count == 0
    async with queue.ticket("next") as nxt:
        assert await nxt.wait(timeout=0) is True


async def test_limit_is_never_exceeded_under_concurrency():
    """При конкурентной нагрузке число активных не превышает лимит.

    Регресс: в окне activation_delay ожидающий инкрементил счётчик без проверки
    лимита, и параллельность выходила за max_concurrent на единицу.
    """
    queue = AnalyzeQueue(max_concurrent=2, name="test")
    peak = 0

    async def worker(index: int) -> None:
        nonlocal peak
        async with queue.ticket(f"r{index}") as ticket:
            while not await ticket.wait(timeout=0.01):
                pass
            peak = max(peak, queue.active_count)
            await asyncio.sleep(0.01)

    await asyncio.gather(*(worker(i) for i in range(20)))

    assert peak == 2
    assert queue.active_count == 0
    assert queue.waiting_count == 0


async def test_duration_counts_work_without_queue_wait():
    """В замер длительности попадает работа, а не ожидание в очереди."""
    queue = AnalyzeQueue(max_concurrent=1, name="test")

    async with queue.ticket("waiter") as waiter:
        async with queue.ticket("holder") as holder:
            await holder.wait(timeout=0)
            await asyncio.sleep(0.3)  # waiter всё это время стоит в очереди
            assert await waiter.wait(timeout=0) is False

        assert await waiter.wait(timeout=1) is True

    assert queue.get_status()["avg_duration"] is not None
    # У waiter замер близок к нулю, значит 0.3 с ожидания в него не вошли
    assert min(queue._durations) < 0.1


async def test_drain_releases_waiters():
    """drain() снимает ожидающих: wait() отдаёт False и помечает тикет."""
    queue = AnalyzeQueue(max_concurrent=1, name="test")

    async with queue.ticket("holder") as holder:
        assert await holder.wait(timeout=0) is True

        async with queue.ticket("waiter") as waiter:
            assert await waiter.wait(timeout=0) is False
            assert queue.drain() == 1

            assert await waiter.wait(timeout=1) is False
            assert waiter.drained is True

    assert queue.active_count == 0


async def test_activation_delay_applies_to_waiters_only(monkeypatch):
    """Задержка тормозит только того, кто стоял в очереди.

    Сны записываются, а не отсчитываются по часам - порог, равный самой задержке,
    ложно срабатывал на загруженной машине.
    """
    delays: list[float] = []
    real_sleep = asyncio.sleep

    async def recording_sleep(delay, *args, **kwargs):
        if delay:
            delays.append(delay)
            return None
        return await real_sleep(delay, *args, **kwargs)  # нулевой сон это шаг цикла событий

    monkeypatch.setattr(asyncio, "sleep", recording_sleep)
    queue = AnalyzeQueue(max_concurrent=1, name="test", activation_delay=0.2)

    holder_ctx = queue.ticket("holder")
    holder = await holder_ctx.__aenter__()

    assert await holder.wait(timeout=0) is True
    assert delays == [], "свободный слот занимается без задержки"

    async with queue.ticket("waiter") as waiter:
        assert await waiter.wait(timeout=0) is False
        await holder_ctx.__aexit__(None, None, None)

        assert await waiter.wait(timeout=2) is True
        assert delays == [0.2], "ждавший в очереди тормозится ровно на задержку"


def test_status_and_eta_defaults():
    """Пустая очередь отдаёт нулевое состояние, ETA без замеров — минута на позицию."""
    queue = AnalyzeQueue(max_concurrent=3, name="server")

    status = queue.get_status()
    assert status == {
        "name": "server",
        "max_concurrent": 3,
        "active": 0,
        "waiting": 0,
        "avg_duration": None,
    }
    assert queue.get_eta(1) == 60
    assert queue.get_eta(2) == 120
