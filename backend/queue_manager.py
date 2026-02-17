"""In-memory очередь запросов на анализ. Без Redis/RabbitMQ — на asyncio.Event."""

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class QueueItem:
    """Элемент очереди."""
    request_id: str
    created_at: float = field(default_factory=time.monotonic)
    ready_event: asyncio.Event = field(default_factory=asyncio.Event)
    cancelled: bool = False


class AnalyzeQueue:
    """Очередь с ограничением параллельных запросов.

    Args:
        max_concurrent: максимальное количество одновременно обрабатываемых запросов.
        name: имя очереди (для логов).
        activation_delay: задержка (сек) между активациями из очереди (антиспам).
    """

    def __init__(self, max_concurrent: int = 1, name: str = "queue", activation_delay: float = 0):
        self._max_concurrent = max_concurrent
        self._name = name
        self._activation_delay = activation_delay
        self._active = 0
        self._waiting: deque[QueueItem] = deque()
        self._durations: deque[float] = deque(maxlen=20)  # скользящее среднее

    @property
    def active_count(self) -> int:
        return self._active

    @property
    def waiting_count(self) -> int:
        return len(self._waiting)

    async def acquire(self, item: QueueItem) -> bool:
        """Встать в очередь и дождаться своей очереди.

        Returns:
            True если запрос готов к обработке, False если отменён.
        """
        if self._active < self._max_concurrent:
            self._active += 1
            logger.info("[%s] %s: слот свободен, запускаем сразу (%d/%d)",
                        self._name, item.request_id, self._active, self._max_concurrent)
            return True

        # Добавляем в очередь ожидания
        self._waiting.append(item)
        pos = len(self._waiting)
        logger.info("[%s] %s: в очереди, позиция %d", self._name, item.request_id, pos)

        # Ждём сигнала
        await item.ready_event.wait()

        if item.cancelled:
            logger.info("[%s] %s: отменён в очереди", self._name, item.request_id)
            return False

        self._active += 1
        logger.info("[%s] %s: дождался слота (%d/%d)",
                    self._name, item.request_id, self._active, self._max_concurrent)
        return True

    def release(self, duration: float | None = None) -> None:
        """Освободить слот после завершения обработки."""
        self._active = max(0, self._active - 1)

        if duration is not None and duration > 0:
            self._durations.append(duration)

        # Активируем следующего из очереди (с задержкой для антиспама)
        while self._waiting:
            next_item = self._waiting.popleft()
            if next_item.cancelled:
                continue
            if self._activation_delay > 0:
                loop = asyncio.get_running_loop()
                loop.call_later(self._activation_delay, next_item.ready_event.set)
                logger.info("[%s] %s: активация через %.1fс",
                            self._name, next_item.request_id, self._activation_delay)
            else:
                next_item.ready_event.set()
                logger.info("[%s] %s: активирован из очереди", self._name, next_item.request_id)
            return

        logger.debug("[%s] Слот освобождён, очередь пуста (%d/%d)",
                     self._name, self._active, self._max_concurrent)

    def cancel(self, request_id: str) -> bool:
        """Отменить ожидание запроса в очереди.

        Returns:
            True если запрос был в очереди и отменён.
        """
        for item in self._waiting:
            if item.request_id == request_id and not item.cancelled:
                item.cancelled = True
                item.ready_event.set()  # разблокируем await
                logger.info("[%s] %s: отменён пользователем", self._name, request_id)
                return True
        return False

    def get_position(self, request_id: str) -> int | None:
        """Возвращает позицию запроса в очереди (1-based). None если не найден."""
        pos = 1
        for item in self._waiting:
            if item.cancelled:
                continue
            if item.request_id == request_id:
                return pos
            pos += 1
        return None

    def get_eta(self, position: int) -> int:
        """Оценка времени ожидания в секундах на основе скользящего среднего."""
        if not self._durations:
            return position * 60  # дефолт 60 секунд на запрос
        avg = sum(self._durations) / len(self._durations)
        return max(1, int(avg * position / self._max_concurrent))

    def get_status(self) -> dict:
        """Текущее состояние очереди."""
        return {
            "name": self._name,
            "max_concurrent": self._max_concurrent,
            "active": self._active,
            "waiting": self.waiting_count,
            "avg_duration": round(sum(self._durations) / len(self._durations), 1) if self._durations else None,
        }

    def cancel_all(self) -> int:
        """Отменить всех ожидающих. Возвращает количество отменённых."""
        count = 0
        for item in self._waiting:
            if not item.cancelled:
                item.cancelled = True
                item.ready_event.set()
                count += 1
        return count


# Глобальные экземпляры — инициализируются при первом импорте,
# переконфигурируются в lifespan при старте приложения
server_queue: AnalyzeQueue | None = None
custom_queue: AnalyzeQueue | None = None


def init_queues(server_max: int = 1, custom_max: int = 5, activation_delay: float = 0) -> None:
    """Инициализация глобальных очередей с настройками из конфига."""
    global server_queue, custom_queue
    server_queue = AnalyzeQueue(max_concurrent=server_max, name="server", activation_delay=activation_delay)
    custom_queue = AnalyzeQueue(max_concurrent=custom_max, name="custom", activation_delay=activation_delay)
    logger.info("Очереди: server(max=%d), custom(max=%d), delay=%.1fs", server_max, custom_max, activation_delay)
