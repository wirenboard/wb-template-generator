"""Тесты для TelegramNotifier (notifier.py)."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import httpx
import openai
import pytest

# Добавляем backend/ в sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from llm_errors import ClassifiedError, ErrorCategory, Severity, classify  # noqa: E402, I001
import notifier as notifier_module  # noqa: E402
from notifier import (  # noqa: E402
    TelegramNotifier,
    clear_metric_hooks,
    register_metric_hook,
    report_llm_api_error,
    set_notifier,
)


# ---------------------------------------------------------------------------
# Утилиты
# ---------------------------------------------------------------------------


class FakeClock:
    """Контролируемые часы для тестирования антиспама без time.sleep."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _make_classified(
    category: ErrorCategory,
    severity: Severity | None = None,
) -> ClassifiedError:
    """Создаёт ClassifiedError для тестов."""
    if severity is None:
        # Дефолтная серьёзность из карты
        sev_map = {
            ErrorCategory.QUOTA_EXCEEDED: Severity.CRITICAL,
            ErrorCategory.AUTH: Severity.CRITICAL,
            ErrorCategory.PERMISSION: Severity.CRITICAL,
            ErrorCategory.NOT_FOUND: Severity.CRITICAL,
            ErrorCategory.BAD_REQUEST: Severity.CRITICAL,
            ErrorCategory.RATE_LIMIT: Severity.WARNING,
            ErrorCategory.TIMEOUT: Severity.WARNING,
            ErrorCategory.CONNECTION: Severity.WARNING,
            ErrorCategory.SERVER_ERROR: Severity.WARNING,
            ErrorCategory.UNKNOWN: Severity.WARNING,
        }
        severity = sev_map[category]
    return ClassifiedError(
        category=category,
        severity=severity,
        http_status=429 if category == ErrorCategory.RATE_LIMIT else 500,
        code=None,
        message="test error",
    )


def _make_httpx_response(status_code: int = 200, text: str = "ok") -> MagicMock:
    """Мок ответа httpx."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    return resp


def _make_notifier(
    *,
    enabled: bool = True,
    cooldown: int = 900,
    threshold_window: int = 300,
    threshold_count: int = 5,
    clock: FakeClock | None = None,
    client: MagicMock | None = None,
) -> TelegramNotifier:
    """Создаёт TelegramNotifier с мок-клиентом."""
    if clock is None:
        clock = FakeClock()
    if client is None:
        client = MagicMock(spec=httpx.AsyncClient)
        client.post = AsyncMock(return_value=_make_httpx_response())
    return TelegramNotifier(
        enabled=enabled,
        bot_token="test-bot-token",
        chat_id="-100123456",
        cooldown_seconds=cooldown,
        threshold_window_seconds=threshold_window,
        threshold_count=threshold_count,
        clock=clock,
        client=client,
        version="1.2.3",
    )


@pytest.fixture(autouse=True)
def _reset_metric_hooks():
    """Сбрасываем глобальные хуки между тестами."""
    clear_metric_hooks()
    yield
    clear_metric_hooks()


@pytest.fixture(autouse=True)
def _reset_notifier_singleton():
    """Сбрасываем глобальный notifier между тестами."""
    set_notifier(None)
    yield
    set_notifier(None)


# ---------------------------------------------------------------------------
# Базовое поведение
# ---------------------------------------------------------------------------


class TestEnabledFlag:
    """Если notifier выключен — отправки не происходит."""

    @pytest.mark.asyncio
    async def test_disabled_via_flag(self):
        client = MagicMock(spec=httpx.AsyncClient)
        client.post = AsyncMock(return_value=_make_httpx_response())
        n = _make_notifier(enabled=False, client=client)
        sent = await n.notify_llm_error(
            _make_classified(ErrorCategory.AUTH),
            endpoint="analyze_document",
        )
        assert sent is False
        # Дать шанс фоновой задаче (если бы она была) — её не должно быть
        await asyncio.sleep(0)
        client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_disabled_when_no_token(self):
        n = TelegramNotifier(
            enabled=True,
            bot_token="",
            chat_id="-100",
        )
        assert n.enabled is False

    @pytest.mark.asyncio
    async def test_disabled_when_no_chat_id(self):
        n = TelegramNotifier(
            enabled=True,
            bot_token="t",
            chat_id="",
        )
        assert n.enabled is False


# ---------------------------------------------------------------------------
# CRITICAL: cooldown по категории
# ---------------------------------------------------------------------------


class TestCriticalCooldown:
    """Critical-уведомления: первое — сразу, повторные — после cooldown."""

    @pytest.mark.asyncio
    async def test_first_critical_sends_immediately(self):
        clock = FakeClock()
        client = MagicMock(spec=httpx.AsyncClient)
        client.post = AsyncMock(return_value=_make_httpx_response())
        n = _make_notifier(clock=clock, client=client)

        sent = await n.notify_llm_error(
            _make_classified(ErrorCategory.QUOTA_EXCEEDED),
            endpoint="analyze_document",
        )
        assert sent is True
        await asyncio.sleep(0)  # дать фоновой задаче выполниться
        await asyncio.sleep(0)
        client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_second_critical_within_cooldown_suppressed(self):
        clock = FakeClock()
        client = MagicMock(spec=httpx.AsyncClient)
        client.post = AsyncMock(return_value=_make_httpx_response())
        n = _make_notifier(cooldown=900, clock=clock, client=client)

        await n.notify_llm_error(
            _make_classified(ErrorCategory.AUTH), endpoint="x",
        )
        clock.advance(60)  # ещё в cooldown
        sent = await n.notify_llm_error(
            _make_classified(ErrorCategory.AUTH), endpoint="x",
        )
        assert sent is False

    @pytest.mark.asyncio
    async def test_critical_after_cooldown_sends_again(self):
        clock = FakeClock()
        client = MagicMock(spec=httpx.AsyncClient)
        client.post = AsyncMock(return_value=_make_httpx_response())
        n = _make_notifier(cooldown=900, clock=clock, client=client)

        await n.notify_llm_error(
            _make_classified(ErrorCategory.AUTH), endpoint="x",
        )
        clock.advance(901)
        sent = await n.notify_llm_error(
            _make_classified(ErrorCategory.AUTH), endpoint="x",
        )
        assert sent is True

    @pytest.mark.asyncio
    async def test_quota_exceeded_sends_immediately_and_respects_cooldown(self):
        """Главный сценарий: «закончились деньги» — мгновенный алерт + cooldown."""
        clock = FakeClock()
        client = MagicMock(spec=httpx.AsyncClient)
        client.post = AsyncMock(return_value=_make_httpx_response())
        n = _make_notifier(cooldown=900, clock=clock, client=client)

        # Первый вызов — отправляется сразу
        sent1 = await n.notify_llm_error(
            _make_classified(ErrorCategory.QUOTA_EXCEEDED),
            endpoint="analyze_document",
        )
        assert sent1 is True

        # Второй вызов через 5 минут — подавлен cooldown'ом
        clock.advance(300)
        sent2 = await n.notify_llm_error(
            _make_classified(ErrorCategory.QUOTA_EXCEEDED),
            endpoint="analyze_document",
        )
        assert sent2 is False

        # Третий вызов после cooldown — снова отправляется
        clock.advance(700)  # суммарно 1000 от первого
        sent3 = await n.notify_llm_error(
            _make_classified(ErrorCategory.QUOTA_EXCEEDED),
            endpoint="analyze_document",
        )
        assert sent3 is True


# ---------------------------------------------------------------------------
# WARNING: порог в окне
# ---------------------------------------------------------------------------


class TestWarningThreshold:
    """Warning: первые N-1 событий молчат, N-е — триггерит уведомление."""

    @pytest.mark.asyncio
    async def test_below_threshold_no_send(self):
        clock = FakeClock()
        n = _make_notifier(threshold_count=5, clock=clock)
        for _ in range(4):
            sent = await n.notify_llm_error(
                _make_classified(ErrorCategory.TIMEOUT), endpoint="x",
            )
            assert sent is False
            clock.advance(1)

    @pytest.mark.asyncio
    async def test_threshold_reached_sends(self):
        clock = FakeClock()
        n = _make_notifier(threshold_count=3, threshold_window=300, clock=clock)
        await n.notify_llm_error(_make_classified(ErrorCategory.TIMEOUT), endpoint="x")
        clock.advance(10)
        await n.notify_llm_error(_make_classified(ErrorCategory.TIMEOUT), endpoint="x")
        clock.advance(10)
        sent = await n.notify_llm_error(
            _make_classified(ErrorCategory.TIMEOUT), endpoint="x",
        )
        assert sent is True

    @pytest.mark.asyncio
    async def test_events_outside_window_not_counted(self):
        """События, выпавшие из окна, не считаются."""
        clock = FakeClock()
        n = _make_notifier(threshold_count=3, threshold_window=300, clock=clock)
        await n.notify_llm_error(_make_classified(ErrorCategory.TIMEOUT), endpoint="x")
        await n.notify_llm_error(_make_classified(ErrorCategory.TIMEOUT), endpoint="x")
        # Прошло больше окна — старые события должны выпасть
        clock.advance(400)
        sent = await n.notify_llm_error(
            _make_classified(ErrorCategory.TIMEOUT), endpoint="x",
        )
        # Только 1 событие в текущем окне → меньше порога
        assert sent is False

    @pytest.mark.asyncio
    async def test_after_threshold_send_no_repeat_in_window(self):
        """После отправки по порогу повторов в том же окне нет."""
        clock = FakeClock()
        n = _make_notifier(threshold_count=2, threshold_window=300, clock=clock)
        await n.notify_llm_error(_make_classified(ErrorCategory.TIMEOUT), endpoint="x")
        sent_a = await n.notify_llm_error(
            _make_classified(ErrorCategory.TIMEOUT), endpoint="x",
        )
        assert sent_a is True
        # Ещё одно событие сразу после — не должно слать (cooldown == window)
        clock.advance(10)
        sent_b = await n.notify_llm_error(
            _make_classified(ErrorCategory.TIMEOUT), endpoint="x",
        )
        assert sent_b is False


# ---------------------------------------------------------------------------
# Изоляция категорий
# ---------------------------------------------------------------------------


class TestCategoryIsolation:
    """Cooldown и счётчики разных категорий не пересекаются."""

    @pytest.mark.asyncio
    async def test_different_critical_categories_independent(self):
        clock = FakeClock()
        n = _make_notifier(cooldown=900, clock=clock)
        sent_a = await n.notify_llm_error(
            _make_classified(ErrorCategory.AUTH), endpoint="x",
        )
        sent_b = await n.notify_llm_error(
            _make_classified(ErrorCategory.QUOTA_EXCEEDED), endpoint="x",
        )
        assert sent_a is True
        assert sent_b is True


# ---------------------------------------------------------------------------
# Сетевые ошибки не падают
# ---------------------------------------------------------------------------


class TestNetworkResilience:
    """Ошибки httpx при отправке не должны пробрасываться наружу."""

    @pytest.mark.asyncio
    async def test_httpx_failure_does_not_raise(self, caplog):
        client = MagicMock(spec=httpx.AsyncClient)
        client.post = AsyncMock(side_effect=httpx.ConnectError("network"))
        n = _make_notifier(client=client)

        # Не должно бросать
        sent = await n.notify_llm_error(
            _make_classified(ErrorCategory.AUTH), endpoint="x",
        )
        assert sent is True
        # Дать фоновой задаче упасть
        await asyncio.sleep(0)
        await asyncio.sleep(0)

    @pytest.mark.asyncio
    async def test_telegram_4xx_logged_not_raised(self):
        client = MagicMock(spec=httpx.AsyncClient)
        client.post = AsyncMock(return_value=_make_httpx_response(401, "Unauthorized"))
        n = _make_notifier(client=client)
        sent = await n.notify_llm_error(
            _make_classified(ErrorCategory.AUTH), endpoint="x",
        )
        assert sent is True
        await asyncio.sleep(0)
        await asyncio.sleep(0)


# ---------------------------------------------------------------------------
# Форматирование сообщения
# ---------------------------------------------------------------------------


class TestMessageFormatting:
    """Сообщение содержит все ожидаемые поля и корректно эскейпит HTML."""

    @pytest.mark.asyncio
    async def test_message_contains_context(self):
        captured = {}

        async def capture_post(url, **kwargs):
            captured["url"] = url
            captured["json"] = kwargs.get("json")
            return _make_httpx_response()

        client = MagicMock(spec=httpx.AsyncClient)
        client.post = AsyncMock(side_effect=capture_post)
        n = _make_notifier(client=client)

        await n.notify_llm_error(
            ClassifiedError(
                ErrorCategory.QUOTA_EXCEEDED, Severity.CRITICAL,
                429, "insufficient_quota", "You exceeded your quota",
            ),
            endpoint="analyze_document",
            request_id="req-abc",
            model="gpt-4o",
        )
        # Дать фоновой задаче выполниться
        await asyncio.sleep(0)
        await asyncio.sleep(0)

        assert "/bottest-bot-token/sendMessage" in captured["url"]
        text = captured["json"]["text"]
        assert "quota_exceeded" in text
        assert "critical" in text
        assert "429" in text
        assert "insufficient_quota" in text
        assert "analyze_document" in text
        assert "gpt-4o" in text
        assert "req-abc" in text
        assert "1.2.3" in text  # версия
        assert captured["json"]["chat_id"] == "-100123456"
        assert captured["json"]["parse_mode"] == "HTML"

    @pytest.mark.asyncio
    async def test_html_escaping(self):
        captured = {}

        async def capture_post(url, **kwargs):
            captured["json"] = kwargs.get("json")
            return _make_httpx_response()

        client = MagicMock(spec=httpx.AsyncClient)
        client.post = AsyncMock(side_effect=capture_post)
        n = _make_notifier(client=client)

        await n.notify_llm_error(
            ClassifiedError(
                ErrorCategory.UNKNOWN, Severity.CRITICAL,  # форсируем отправку
                500, None, "<script>alert('xss')</script>",
            ),
            endpoint="<endpoint>",
        )
        await asyncio.sleep(0)
        await asyncio.sleep(0)

        text = captured["json"]["text"]
        assert "<script>" not in text
        assert "&lt;script&gt;" in text


# ---------------------------------------------------------------------------
# report_llm_api_error: интеграция с метриками и singleton'ом
# ---------------------------------------------------------------------------


class TestReportLLMApiError:
    """Высокоуровневая точка входа: classify + metrics + notifier."""

    @pytest.mark.asyncio
    async def test_metric_hook_called_with_category(self):
        captured: list[ErrorCategory] = []
        register_metric_hook(captured.append)

        client = MagicMock(spec=httpx.AsyncClient)
        client.post = AsyncMock(return_value=_make_httpx_response())
        set_notifier(_make_notifier(client=client))

        request = httpx.Request(
            "POST", "https://api.openai.com/v1/chat/completions",
        )
        exc = openai.AuthenticationError(
            message="bad key",
            response=httpx.Response(401, request=request, json={"error": {}}),
            body={},
        )
        result = await report_llm_api_error(
            exc, endpoint="analyze_document", model="gpt-4o",
        )
        assert result is not None
        assert result.category == ErrorCategory.AUTH
        assert captured == [ErrorCategory.AUTH]

    @pytest.mark.asyncio
    async def test_custom_llm_skips_metrics_and_notifier(self):
        """is_custom_llm=True — метрики и нотификации НЕ дёргаются."""
        captured: list[ErrorCategory] = []
        register_metric_hook(captured.append)

        client = MagicMock(spec=httpx.AsyncClient)
        client.post = AsyncMock(return_value=_make_httpx_response())
        set_notifier(_make_notifier(client=client))

        request = httpx.Request(
            "POST", "https://api.openai.com/v1/chat/completions",
        )
        exc = openai.AuthenticationError(
            message="bad key",
            response=httpx.Response(401, request=request, json={"error": {}}),
            body={},
        )
        result = await report_llm_api_error(
            exc, endpoint="analyze_document",
            model="gpt-4o", is_custom_llm=True,
        )
        assert result is None
        assert captured == []
        await asyncio.sleep(0)
        client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_notifier_registered_does_not_crash(self):
        """Если notifier не инициализирован — функция всё равно работает."""
        set_notifier(None)
        captured: list[ErrorCategory] = []
        register_metric_hook(captured.append)

        request = httpx.Request("POST", "https://x/y")
        exc = openai.APITimeoutError(request=request)
        result = await report_llm_api_error(exc, endpoint="x")
        assert result is not None
        assert result.category == ErrorCategory.TIMEOUT
        assert captured == [ErrorCategory.TIMEOUT]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
