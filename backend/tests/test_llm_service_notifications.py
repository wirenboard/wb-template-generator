"""Интеграционные тесты: интеграция notifier и метрик в llm_service.

Проверяем, что при сбое OpenAI API в `analyze_document`:
- для серверного LLM срабатывает классификация, инкремент метрик и Telegram-нотификация;
- для пользовательского LLM (is_custom_llm=True) ничего не дёргается
  (чужой ключ — наша зона ответственности нулевая).
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import openai
import pytest

# Добавляем backend/ в sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import Settings  # noqa: E402, I001
from llm_errors import ErrorCategory  # noqa: E402
from llm_service import analyze_document  # noqa: E402
from notifier import (  # noqa: E402
    TelegramNotifier,
    clear_metric_hooks,
    register_metric_hook,
    set_notifier,
)


# ---------------------------------------------------------------------------
# Вспомогательные утилиты
# ---------------------------------------------------------------------------

def _make_settings() -> Settings:
    return Settings(
        LLM_API_URL="https://api.server.example.com/v1",
        LLM_API_KEY="sk-server",
        LLM_MODEL="gpt-4o",
        LLM_MAX_TOKENS=0,
        LLM_TIMEOUT=60,
        LLM_SOFT_TIMEOUT=30,
        LLM_LEGACY_MAX_TOKENS=False,
        LLM_TEMPERATURE=0,
        LLM_PROXY="",
    )


def _make_quota_error() -> openai.RateLimitError:
    """Реалистичная ошибка «закончились деньги на счёте»."""
    response = MagicMock()
    response.status_code = 429
    response.headers = {}
    response.request = MagicMock()
    body = {
        "error": {
            "message": "You exceeded your current quota, please check your plan and billing details.",
            "type": "insufficient_quota",
            "code": "insufficient_quota",
        },
    }
    return openai.RateLimitError(
        message="429 You exceeded your current quota",
        response=response,
        body=body,
    )


async def _collect(gen) -> list[str]:
    out = []
    async for event in gen:
        out.append(event)
    return out


@pytest.fixture
def captured_metrics() -> list[ErrorCategory]:
    """Регистрирует метрический хук, собирающий все категории."""
    captured: list[ErrorCategory] = []
    clear_metric_hooks()
    register_metric_hook(captured.append)
    yield captured
    clear_metric_hooks()


@pytest.fixture
def fake_notifier() -> TelegramNotifier:
    """Подменяет глобальный TelegramNotifier на включённый (с моком отправки)."""
    notifier = TelegramNotifier(
        enabled=True,
        bot_token="test-token",
        chat_id="123",
        cooldown_seconds=900,
        threshold_window_seconds=300,
        threshold_count=5,
    )
    # Подменяем _send, чтобы не лезть в сеть
    notifier._send = AsyncMock()  # type: ignore[method-assign]
    set_notifier(notifier)
    yield notifier
    set_notifier(None)


# ---------------------------------------------------------------------------
# Тесты
# ---------------------------------------------------------------------------

class TestServerLLMErrorReporting:
    """Серверный LLM: ошибки квоты доходят до метрик и Telegram."""

    @pytest.mark.asyncio
    async def test_quota_error_increments_metric_and_notifies(
        self, captured_metrics, fake_notifier,
    ):
        """RateLimitError(insufficient_quota) → CRITICAL → метрика + sendMessage."""
        settings = _make_settings()

        with (
            patch("llm_service.AsyncOpenAI") as mock_openai,
            patch("llm_service.Image") as mock_image,
            patch("llm_service.image_to_base64", return_value="dGVzdA=="),
        ):
            mock_client = AsyncMock()
            mock_openai.return_value = mock_client
            # Каждый _call_llm бросает quota-ошибку (включая retry)
            mock_client.chat.completions.create = AsyncMock(side_effect=_make_quota_error())
            mock_image.open.return_value = MagicMock()

            events = await _collect(analyze_document(
                files=[("test.png", b"fake-png")],
                template_type="full",
                settings=settings,
                is_custom_llm=False,
                request_id="req-test-1",
            ))

        # Должна быть инкрементирована метрика QUOTA_EXCEEDED как минимум один раз
        assert ErrorCategory.QUOTA_EXCEEDED in captured_metrics, (
            f"Ожидали QUOTA_EXCEEDED в метриках, получили {captured_metrics!r}"
        )
        # Telegram: CRITICAL уходит немедленно (без задержки порогом)
        assert fake_notifier._send.await_count >= 1, (
            "TelegramNotifier._send должен был быть вызван"
        )
        # Сообщение должно содержать признаки квоты
        sent_text = fake_notifier._send.await_args_list[0].args[0]
        assert "quota_exceeded" in sent_text
        assert "critical" in sent_text
        assert "analyze_document" in sent_text
        # SSE-поток вернул ошибку (поток корректно дозавершился)
        assert any("error" in e for e in events)


class TestCustomLLMSkipsReporting:
    """Пользовательский LLM: ничего не репортим (чужой ключ)."""

    @pytest.mark.asyncio
    async def test_custom_llm_quota_error_does_not_notify(
        self, captured_metrics, fake_notifier,
    ):
        """is_custom_llm=True → ни метрик, ни Telegram-сообщений."""
        settings = _make_settings()

        with (
            patch("llm_service.AsyncOpenAI") as mock_openai,
            patch("llm_service.Image") as mock_image,
            patch("llm_service.image_to_base64", return_value="dGVzdA=="),
        ):
            mock_client = AsyncMock()
            mock_openai.return_value = mock_client
            mock_client.chat.completions.create = AsyncMock(side_effect=_make_quota_error())
            mock_image.open.return_value = MagicMock()

            await _collect(analyze_document(
                files=[("test.png", b"fake-png")],
                template_type="full",
                settings=settings,
                api_url="https://api.user.example.com/v1",
                api_key="sk-user",
                is_custom_llm=True,
                request_id="req-test-2",
            ))

        assert captured_metrics == [], (
            f"Для custom-LLM не должно быть метрик, получили {captured_metrics!r}"
        )
        assert fake_notifier._send.await_count == 0, (
            "Для custom-LLM не должно быть Telegram-уведомлений"
        )


class TestNotifierDisabled:
    """Notifier выключен (TELEGRAM_NOTIFY_ENABLED=False) — метрики работают, Telegram молчит."""

    @pytest.mark.asyncio
    async def test_disabled_notifier_still_records_metrics(self, captured_metrics):
        settings = _make_settings()
        # Выключённый notifier
        notifier = TelegramNotifier(enabled=False, bot_token="", chat_id="")
        notifier._send = AsyncMock()  # type: ignore[method-assign]
        set_notifier(notifier)
        try:
            with (
                patch("llm_service.AsyncOpenAI") as mock_openai,
                patch("llm_service.Image") as mock_image,
                patch("llm_service.image_to_base64", return_value="dGVzdA=="),
            ):
                mock_client = AsyncMock()
                mock_openai.return_value = mock_client
                mock_client.chat.completions.create = AsyncMock(side_effect=_make_quota_error())
                mock_image.open.return_value = MagicMock()

                await _collect(analyze_document(
                    files=[("test.png", b"fake-png")],
                    template_type="full",
                    settings=settings,
                    is_custom_llm=False,
                    request_id="req-test-3",
                ))
        finally:
            set_notifier(None)

        # Метрики обновились
        assert ErrorCategory.QUOTA_EXCEEDED in captured_metrics
        # Telegram молчит (notifier disabled)
        assert notifier._send.await_count == 0
