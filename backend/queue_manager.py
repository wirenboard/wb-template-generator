"""Ограничение числа параллельных анализов.

Лимит держит `asyncio.Semaphore`, поверх него — позиция в очереди и ETA для UI.
Слот занимает только `QueueTicket.wait()`, а освобождает только выход из
`AnalyzeQueue.ticket()`, поэтому освободить незанятый слот невозможно.
Отдельного пути отмены нет: клиент рвёт SSE, генератор закрывается, выход из
`ticket()` снимает ожидание сам.
"""

import asyncio
import logging
import time
from collections import deque
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)


class QueueTicket:
    """Место в очереди на анализ. Создаётся только через `AnalyzeQueue.ticket()`."""

    def __init__(self, queue: "AnalyzeQueue", request_id: str):
        self.request_id = request_id
        self.drained = False  # сервис останавливается, слота не будет
        self._queue = queue
        self._acquire: asyncio.Task[bool] | None = None
        self._acquired = False
        self._started_at: float | None = None
        self._was_queued = False

    @property
    def acquired(self) -> bool:
        """Слот занят и анализ можно начинать."""
        return self._acquired

    @property
    def position(self) -> int | None:
        """Позиция в очереди ожидания (1-based). None если слот уже занят."""
        return self._queue.position_of(self)

    @property
    def eta(self) -> int:
        """Оценка ожидания в секундах для текущей позиции."""
        return self._queue.get_eta(self.position or 1)

    async def wait(self, timeout: float | None = None) -> bool:
        """Дождаться слота, но не дольше `timeout` секунд.

        `timeout=0` отвечает на вопрос «есть ли свободный слот прямо сейчас»,
        поэтому вызывающий код может сначала попробовать без ожидания, а затем
        ждать в цикле, обновляя позицию по SSE.

        Returns:
            True если слот занят, False если время вышло или сервис останавливается.
        """
        if self._acquired:
            return True
        if self.drained:
            return False

        if self._acquire is None:
            self._acquire = asyncio.create_task(self._queue._semaphore.acquire())
            # Один прогон цикла: на свободном слоте задача завершается сразу.
            await asyncio.sleep(0)

        if not self._acquire.done():
            self._was_queued = True
            # asyncio.wait по таймауту НЕ отменяет задачу, ожидание слота живёт дальше.
            await asyncio.wait({self._acquire}, timeout=timeout)

        if not self._acquire.done():
            return False

        if self._acquire.cancelled():
            self.drained = True
            logger.info("[%s] %s: ожидание снято, сервис останавливается",
                        self._queue.name, self.request_id)
            return False

        self._acquired = True
        self._started_at = time.monotonic()
        self._queue._on_acquired(self)

        # Антиспам: тем, кто стоял в очереди, даём стартовать не залпом.
        if self._was_queued and self._queue._activation_delay > 0:
            await asyncio.sleep(self._queue._activation_delay)

        return True


class AnalyzeQueue:
    """Очередь с ограничением числа одновременных анализов.

    Args:
        max_concurrent: сколько анализов выполняется одновременно.
        name: имя очереди (для логов и /api/queue-status).
        activation_delay: задержка (сек) перед стартом того, кто ждал в очереди.
    """

    def __init__(self, max_concurrent: int = 1, name: str = "queue", activation_delay: float = 0):
        self.name = name
        self._activation_delay = activation_delay
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._max_concurrent = max_concurrent
        self._active = 0
        self._waiting: list[QueueTicket] = []
        self._durations: deque[float] = deque(maxlen=20)  # скользящее среднее

    @property
    def active_count(self) -> int:
        return self._active

    @property
    def waiting_count(self) -> int:
        return len(self._waiting)

    @asynccontextmanager
    async def ticket(self, request_id: str) -> AsyncIterator[QueueTicket]:
        """Взять место в очереди. Выход из контекста освобождает слот при любом исходе."""
        item = QueueTicket(self, request_id)
        self._waiting.append(item)
        try:
            yield item
        finally:
            self._finish(item)

    def _on_acquired(self, item: QueueTicket) -> None:
        """Слот занят — тикет уходит из очереди ожидания в активные."""
        if item in self._waiting:
            self._waiting.remove(item)
        self._active += 1
        logger.info("[%s] %s: слот занят (%d/%d)",
                    self.name, item.request_id, self._active, self._max_concurrent)

    def position_of(self, item: QueueTicket) -> int | None:
        """Позиция тикета в очереди ожидания (1-based). None если он не ждёт."""
        try:
            return self._waiting.index(item) + 1
        except ValueError:
            return None

    def _finish(self, item: QueueTicket) -> None:
        """Освободить всё, что тикет успел занять."""
        if item in self._waiting:
            self._waiting.remove(item)

        if item.acquired:
            self._active -= 1
            if item._started_at is not None:
                self._durations.append(time.monotonic() - item._started_at)
            self._semaphore.release()
            logger.info("[%s] %s: слот освобождён (%d/%d)",
                        self.name, item.request_id, self._active, self._max_concurrent)
            return

        task = item._acquire
        if task is None:
            return

        if task.done() and not task.cancelled() and not task.exception():
            # Слот пришёл в момент, когда ждать его уже некому.
            self._semaphore.release()
            logger.info("[%s] %s: слот пришёл после ухода, возвращён в пул",
                        self.name, item.request_id)
        else:
            task.cancel()
            logger.info("[%s] %s: ожидание в очереди прервано", self.name, item.request_id)

    def drain(self) -> int:
        """Снять всех ожидающих при остановке сервиса. Возвращает число снятых."""
        count = 0
        for item in list(self._waiting):
            item.drained = True
            if item._acquire is not None:
                item._acquire.cancel()
            count += 1
        return count

    def get_eta(self, position: int) -> int:
        """Оценка времени ожидания в секундах на основе скользящего среднего."""
        if not self._durations:
            return position * 60  # дефолт 60 секунд на запрос
        avg = sum(self._durations) / len(self._durations)
        return max(1, int(avg * position / self._max_concurrent))

    def get_status(self) -> dict:
        """Текущее состояние очереди."""
        return {
            "name": self.name,
            "max_concurrent": self._max_concurrent,
            "active": self._active,
            "waiting": self.waiting_count,
            "avg_duration": round(sum(self._durations) / len(self._durations), 1) if self._durations else None,
        }


# Глобальные экземпляры. Создаются в init_queues() при старте приложения, поэтому
# обращаться к ним нужно через модуль (`queue_manager.server_queue`) — импорт по
# имени скопирует None и очередь не подключится.
server_queue: AnalyzeQueue | None = None
custom_queue: AnalyzeQueue | None = None


def init_queues(server_max: int = 1, custom_max: int = 5, activation_delay: float = 0) -> None:
    """Инициализация глобальных очередей с настройками из конфига."""
    global server_queue, custom_queue
    server_queue = AnalyzeQueue(max_concurrent=server_max, name="server", activation_delay=activation_delay)
    custom_queue = AnalyzeQueue(max_concurrent=custom_max, name="custom", activation_delay=activation_delay)
    logger.info("Очереди: server(max=%d), custom(max=%d), delay=%.1fs", server_max, custom_max, activation_delay)
