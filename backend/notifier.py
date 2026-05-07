"""Отправка уведомлений в Telegram при сбоях OpenAI API.

Архитектура:
- TelegramNotifier — синглтон, создаётся в lifespan main.py (init_notifier).
- Антиспам:
    * CRITICAL — отправляется сразу, далее cooldown по категории.
    * WARNING — отправляется только если за окно времени накопилось
                >= TELEGRAM_NOTIFY_THRESHOLD_COUNT событий категории.
- Точка входа для прикладного кода — report_llm_api_error(exc, ...).
- Метрики обновляются через хуки (register_metric_hook), чтобы
  избежать циркулярного импорта main ↔ notifier.

Notifier НЕ должен бросать исключения наружу — все ошибки httpx
гасятся и логируются. Сетевая отправка не блокирует вызывающий код
(asyncio.create_task).
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import httpx

from llm_errors import ClassifiedError, ErrorCategory, Severity, classify

if TYPE_CHECKING:
    from config import Settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Метрики: callback-хуки, регистрируемые в main.py
# ---------------------------------------------------------------------------

MetricHook = Callable[[ErrorCategory], None]
_metric_hooks: list[MetricHook] = []


def register_metric_hook(fn: MetricHook) -> None:
    """Регистрирует callback, вызываемый при каждой ошибке LLM API.

    Используется в main.py для инкремента _metrics["llm_errors_by_category"].
    Несколько хуков допустимы (например, для будущего Prometheus-экспортёра).
    """
    _metric_hooks.append(fn)


def clear_metric_hooks() -> None:
    """Сбрасывает все хуки (используется в тестах)."""
    _metric_hooks.clear()


# ---------------------------------------------------------------------------
# Антиспам-стейт
# ---------------------------------------------------------------------------


@dataclass
class _AntiSpamState:
    """Состояние антиспам-логики, индексированное по категории."""

    # Время последней успешной отправки по категории (monotonic seconds)
    last_sent_at: dict[ErrorCategory, float] = field(default_factory=dict)
    # Деки таймстемпов событий warning по категории (для подсчёта в окне)
    warning_events: dict[ErrorCategory, deque[float]] = field(
        default_factory=lambda: defaultdict(deque),
    )


# ---------------------------------------------------------------------------
# TelegramNotifier
# ---------------------------------------------------------------------------


class TelegramNotifier:
    """Отправляет уведомления о сбоях LLM API в Telegram-чат.

    Создаётся один раз на жизненный цикл приложения (lifespan).
    """

    def __init__(
        self,
        *,
        enabled: bool,
        bot_token: str,
        chat_id: str,
        message_thread_id: int = 0,
        api_url: str = "https://api.telegram.org",
        proxy: str | None = None,
        request_timeout: float = 10.0,
        cooldown_seconds: int = 900,
        threshold_window_seconds: int = 300,
        threshold_count: int = 5,
        version: str = "",
        clock: Callable[[], float] = time.monotonic,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._enabled = enabled and bool(bot_token) and bool(chat_id)
        self._bot_token = bot_token
        self._chat_id = chat_id
        self._message_thread_id = message_thread_id if message_thread_id > 0 else 0
        self._api_url = api_url.rstrip("/")
        self._cooldown = cooldown_seconds
        self._threshold_window = threshold_window_seconds
        self._threshold_count = threshold_count
        self._version = version
        self._clock = clock
        self._state = _AntiSpamState()
        # httpx-клиент создаётся лениво (или передаётся в тестах)
        self._injected_client = client
        self._proxy = proxy or None
        self._request_timeout = request_timeout
        self._client: httpx.AsyncClient | None = None
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Публичный API
    # ------------------------------------------------------------------

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def notify_llm_error(
        self,
        classified: ClassifiedError,
        *,
        endpoint: str,
        request_id: str = "",
        model: str = "",
    ) -> bool:
        """Решает, надо ли отправлять уведомление, и инициирует отправку.

        Возвращает True, если сообщение действительно ушло (или поставлено
        в фоновую отправку), False — если подавлено антиспам-логикой
        или notifier выключен.
        """
        if not self._enabled:
            return False

        if not self._should_send(classified):
            return False

        text = self._format_message(classified, endpoint=endpoint,
                                     request_id=request_id, model=model)
        # Не блокируем вызывающий код: отправка в фоне.
        asyncio.create_task(self._send(text))
        return True

    async def aclose(self) -> None:
        """Закрывает httpx-клиент (вызывается из lifespan shutdown)."""
        if self._client is not None:
            try:
                await self._client.aclose()
            except Exception:  # noqa: BLE001
                logger.exception("Ошибка при закрытии httpx-клиента notifier")
            finally:
                self._client = None

    # ------------------------------------------------------------------
    # Антиспам-логика
    # ------------------------------------------------------------------

    def _should_send(self, classified: ClassifiedError) -> bool:
        """Проверяет, разрешает ли антиспам отправить уведомление сейчас."""
        now = self._clock()
        category = classified.category

        if classified.severity == Severity.CRITICAL:
            last = self._state.last_sent_at.get(category)
            if last is not None and (now - last) < self._cooldown:
                logger.debug(
                    "TelegramNotifier: подавлено по cooldown (category=%s, осталось %.0fs)",
                    category.value, self._cooldown - (now - last),
                )
                return False
            self._state.last_sent_at[category] = now
            return True

        # WARNING: пишем событие в окно, шлём только при превышении порога.
        events = self._state.warning_events[category]
        events.append(now)
        # Чистим хвост за пределами окна
        cutoff = now - self._threshold_window
        while events and events[0] < cutoff:
            events.popleft()

        if len(events) < self._threshold_count:
            return False

        # Уведомление по порогу — но не чаще раза за окно (cooldown == window).
        last = self._state.last_sent_at.get(category)
        if last is not None and (now - last) < self._threshold_window:
            return False
        self._state.last_sent_at[category] = now
        return True

    # ------------------------------------------------------------------
    # Форматирование
    # ------------------------------------------------------------------

    def _format_message(
        self,
        classified: ClassifiedError,
        *,
        endpoint: str,
        request_id: str,
        model: str,
    ) -> str:
        """Формирует HTML-сообщение для Telegram."""
        emoji = "🚨" if classified.severity == Severity.CRITICAL else "⚠️"
        lines = [
            f"{emoji} <b>WB Template Generator: ошибка LLM</b>",
            f"Категория: <code>{_html_escape(classified.category.value)}</code> "
            f"({_html_escape(classified.severity.value)})",
        ]
        if classified.http_status is not None:
            status_line = f"HTTP: {classified.http_status}"
            if classified.code:
                status_line += f" | Код: <code>{_html_escape(classified.code)}</code>"
            lines.append(status_line)
        elif classified.code:
            lines.append(f"Код: <code>{_html_escape(classified.code)}</code>")

        if endpoint:
            lines.append(f"Эндпоинт: <code>{_html_escape(endpoint)}</code>")
        if model:
            lines.append(f"Модель: <code>{_html_escape(model)}</code>")
        if request_id:
            lines.append(f"request_id: <code>{_html_escape(request_id)}</code>")
        if self._version:
            lines.append(f"Версия: <code>{_html_escape(self._version)}</code>")

        # Сообщение от провайдера — обрезаем длинное (Telegram лимит 4096)
        msg = classified.message.strip()
        if msg:
            if len(msg) > 1000:
                msg = msg[:1000] + "…"
            lines.append("")
            lines.append(f"<i>{_html_escape(msg)}</i>")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # HTTP-отправка
    # ------------------------------------------------------------------

    async def _get_client(self) -> httpx.AsyncClient:
        """Лениво создаёт httpx-клиент (учитывает прокси и таймаут)."""
        if self._injected_client is not None:
            return self._injected_client
        if self._client is None:
            async with self._lock:
                if self._client is None:
                    kwargs: dict = {"timeout": self._request_timeout}
                    if self._proxy:
                        kwargs["proxy"] = self._proxy
                    self._client = httpx.AsyncClient(**kwargs)
        return self._client

    async def _send(self, text: str) -> None:
        """Фактическая отправка через Bot API. Ошибки только логируются."""
        url = f"{self._api_url}/bot{self._bot_token}/sendMessage"
        payload: dict = {
            "chat_id": self._chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if self._message_thread_id:
            payload["message_thread_id"] = self._message_thread_id
        try:
            client = await self._get_client()
            response = await client.post(url, json=payload)
            if response.status_code >= 400:
                logger.warning(
                    "Telegram API вернул %d: %s",
                    response.status_code, response.text[:300],
                )
        except Exception:  # noqa: BLE001
            logger.exception("Не удалось отправить уведомление в Telegram")


def _html_escape(value: str) -> str:
    """Минимальный HTML-эскейп для Telegram parse_mode=HTML."""
    return (
        value.replace("&", "&amp;")
             .replace("<", "&lt;")
             .replace(">", "&gt;")
    )


# ---------------------------------------------------------------------------
# Глобальный синглтон
# ---------------------------------------------------------------------------

_notifier: TelegramNotifier | None = None


def init_notifier(settings: Settings, version: str = "") -> TelegramNotifier:
    """Создаёт и регистрирует глобальный TelegramNotifier из настроек.

    Вызывается из lifespan startup в main.py.
    """
    global _notifier
    _notifier = TelegramNotifier(
        enabled=getattr(settings, "TELEGRAM_NOTIFY_ENABLED", False),
        bot_token=getattr(settings, "TELEGRAM_BOT_TOKEN", ""),
        chat_id=getattr(settings, "TELEGRAM_CHAT_ID", ""),
        message_thread_id=getattr(settings, "TELEGRAM_MESSAGE_THREAD_ID", 0),
        api_url=getattr(settings, "TELEGRAM_API_URL", "https://api.telegram.org"),
        proxy=getattr(settings, "TELEGRAM_PROXY", "") or None,
        request_timeout=getattr(settings, "TELEGRAM_REQUEST_TIMEOUT", 10.0),
        cooldown_seconds=getattr(settings, "TELEGRAM_NOTIFY_COOLDOWN_SECONDS", 900),
        threshold_window_seconds=getattr(
            settings, "TELEGRAM_NOTIFY_THRESHOLD_WINDOW_SECONDS", 300,
        ),
        threshold_count=getattr(settings, "TELEGRAM_NOTIFY_THRESHOLD_COUNT", 5),
        version=version,
    )
    return _notifier


def get_notifier() -> TelegramNotifier | None:
    """Возвращает глобальный TelegramNotifier (или None, если не инициализирован)."""
    return _notifier


def set_notifier(instance: TelegramNotifier | None) -> None:
    """Подменяет глобальный экземпляр (используется в тестах)."""
    global _notifier
    _notifier = instance


async def shutdown_notifier() -> None:
    """Закрывает глобальный notifier (вызывается из lifespan shutdown)."""
    global _notifier
    if _notifier is not None:
        await _notifier.aclose()
        _notifier = None


# ---------------------------------------------------------------------------
# Высокоуровневая точка входа для прикладного кода
# ---------------------------------------------------------------------------


async def report_llm_api_error(
    exc: Exception,
    *,
    endpoint: str,
    request_id: str = "",
    model: str = "",
    is_custom_llm: bool = False,
) -> ClassifiedError | None:
    """Классифицирует ошибку LLM API, инкрементирует метрики и шлёт уведомление.

    Для пользовательского LLM (is_custom_llm=True) — только классифицирует
    и НЕ дёргает метрики/уведомления (чужой ключ — наша зона
    ответственности нулевая).

    Возвращает ClassifiedError для диагностики (или None, если is_custom_llm).
    """
    if is_custom_llm:
        return None

    classified = classify(exc)

    # Метрики
    for hook in _metric_hooks:
        try:
            hook(classified.category)
        except Exception:  # noqa: BLE001
            logger.exception("Ошибка в metric_hook (category=%s)", classified.category)

    # Telegram
    notifier = get_notifier()
    if notifier is not None:
        try:
            await notifier.notify_llm_error(
                classified, endpoint=endpoint,
                request_id=request_id, model=model,
            )
        except Exception:  # noqa: BLE001
            logger.exception("Ошибка в notify_llm_error")

    return classified
