"""Автофикс внутри analyze_document: keepalive в потоке и фолбэк при сбое.

LLM замокан. Проверяется то, что нельзя увидеть тестами `_fix_registers_core` —
поведение автофикса как этапа SSE-потока.
"""

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import llm_service  # noqa: E402
from config import Settings  # noqa: E402
from llm_service import LLMApiError, analyze_document  # noqa: E402
from models import Register  # noqa: E402

# Регистр с пустым именем — валидатор даёт ERROR, детерминированный проход его не правит
_BAD_REGISTER_RESPONSE = json.dumps({
    "device_info": {"name": "Test", "id": "test"},
    "registers": [{"address": 1, "name": "", "reg_type": "holding"}],
})


def _settings() -> Settings:
    return Settings(
        LLM_API_URL="https://api.example.com/v1",
        LLM_API_KEY="sk-test",
        LLM_MODEL="gpt-test",
        LLM_TIMEOUT=60,
        LLM_SOFT_TIMEOUT=30,
    )


def _llm_response(content: str) -> MagicMock:
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message.content = content
    resp.choices[0].finish_reason = "stop"
    resp.usage = MagicMock(prompt_tokens=10, completion_tokens=10, total_tokens=20)
    return resp


def _parse(events: list[str]) -> list[dict]:
    """Достаёт data-словари из SSE-строк."""
    parsed = []
    for ev in events:
        for line in ev.splitlines():
            if line.startswith("data: "):
                parsed.append(json.loads(line[6:]))
    return parsed


async def _run_analysis(fix_mock, settings: Settings | None = None) -> list[dict]:
    """Прогоняет analyze_document с замоканным LLM и подменённым ядром автофикса."""
    with (
        patch("llm_service.AsyncOpenAI") as mock_openai,
        patch("llm_service.Image") as mock_image,
        patch("llm_service.image_to_base64", return_value="dGVzdA=="),
        patch("llm_service._fix_registers_core", fix_mock),
    ):
        client = AsyncMock()
        mock_openai.return_value = client
        client.chat.completions.create = AsyncMock(return_value=_llm_response(_BAD_REGISTER_RESPONSE))
        mock_image.open.return_value = MagicMock()

        events = []
        async for event in analyze_document(
            files=[("doc.png", b"fake-png")],
            template_type="full",
            settings=settings or _settings(),
            request_id="test1234",
        ):
            events.append(event)

    return _parse(events)


@pytest.fixture
def fast_keepalive(monkeypatch):
    """Ускоряет keepalive-цикл, иначе тест ждал бы 15 секунд."""
    monkeypatch.setattr(llm_service, "_KEEPALIVE_INTERVAL", 0.05)


async def test_autofix_sends_keepalive_while_llm_works(fast_keepalive):
    """Долгий LLM-фикс шлёт промежуточные события, иначе nginx рвёт SSE по таймауту."""

    async def slow_fix(*args, **kwargs):
        await asyncio.sleep(0.2)
        return [Register(address=1, name="Fixed", reg_type="holding")]

    data = await _run_analysis(AsyncMock(side_effect=slow_fix))

    autofix_events = [d for d in data if d.get("stage") == "autofix"]
    with_timer = [d for d in autofix_events if "AI правит некорректные регистры" in d["message"]
                  and "(0:00)" in d["message"]]

    assert with_timer, "во время LLM-фикса в поток не ушло ни одного keepalive-события"
    # Стадия slow для автофикса выключена — она про основной анализ
    assert not [d for d in data if d.get("stage") == "slow"]

    result = [d for d in data if "registers" in d]
    assert result and result[0]["registers"][0]["name"] == "Fixed"


async def test_autofix_failure_falls_back_to_manual_button(fast_keepalive):
    """Сбой LLM-фикса не роняет анализ — результат приходит с исходными регистрами."""
    data = await _run_analysis(AsyncMock(side_effect=LLMApiError("429 quota")))

    assert not [d for d in data if d.get("stage") == "error"]
    result = [d for d in data if "registers" in d]
    assert result, "анализ должен отдать результат даже при неудачном автофиксе"
    assert result[0]["registers"][0]["name"] == ""  # исправить не удалось, отдаём как есть


async def test_client_disconnect_cancels_llm_request(fast_keepalive):
    """Обрыв SSE отменяет запрос к LLM — результат доставить некуда, квоту не жжём."""
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def never_ending_call(*args, **kwargs):
        started.set()
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            cancelled.set()
            raise
        return MagicMock()

    with (
        patch("llm_service.AsyncOpenAI") as mock_openai,
        patch("llm_service.Image") as mock_image,
        patch("llm_service.image_to_base64", return_value="dGVzdA=="),
    ):
        client = AsyncMock()
        mock_openai.return_value = client
        client.chat.completions.create = AsyncMock(side_effect=never_ending_call)
        mock_image.open.return_value = MagicMock()

        gen = analyze_document(
            files=[("doc.png", b"fake-png")],
            template_type="full",
            settings=_settings(),
            request_id="test1234",
        )
        # Читаем поток до момента, когда запрос к LLM уже ушёл
        async for _ in gen:
            if started.is_set():
                break

        await gen.aclose()  # клиент закрыл вкладку

    await asyncio.wait_for(cancelled.wait(), timeout=1)


async def test_broken_image_stops_analysis_with_clear_message():
    """Битый файл прекращает анализ до вызова LLM и называет пользователю имя файла."""
    with patch("llm_service.AsyncOpenAI") as mock_openai:
        client = AsyncMock()
        mock_openai.return_value = client
        client.chat.completions.create = AsyncMock()

        events = []
        async for event in analyze_document(
            files=[("scan.png", b"\x00\x01\x02not-an-image" * 10)],
            template_type="full",
            settings=_settings(),
            request_id="test1234",
        ):
            events.append(event)

    errors = [d for d in _parse(events) if "scan.png" in d.get("message", "")]
    assert errors, "пользователь должен увидеть, какой файл повреждён"
    assert "повреждён" in errors[0]["message"]
    client.chat.completions.create.assert_not_called()  # деньги на битый файл не тратим


async def test_api_error_is_not_reported_as_document_format_problem():
    """Ошибка LLM API не выдаётся за проблему с форматом документа."""
    with (
        patch("llm_service.AsyncOpenAI") as mock_openai,
        patch("llm_service.Image") as mock_image,
        patch("llm_service.image_to_base64", return_value="dGVzdA=="),
    ):
        client = AsyncMock()
        mock_openai.return_value = client
        client.chat.completions.create = AsyncMock(side_effect=LLMApiError("429 insufficient_quota"))
        mock_image.open.return_value = MagicMock()

        events = []
        async for event in analyze_document(
            files=[("doc.png", b"fake-png")],
            template_type="full",
            settings=_settings(),
            request_id="test1234",
        ):
            events.append(event)

    messages = [d.get("message", "") for d in _parse(events)]
    api_errors = [m for m in messages if "LLM API" in m]
    assert api_errors, "ошибка API должна быть названа ошибкой API"
    assert "квоты" in api_errors[0]
    assert not any("Проверьте формат документа" in m for m in messages)


async def test_no_llm_call_when_deterministic_pass_fixed_everything(fast_keepalive):
    """Если бесплатный проход убрал все ошибки, за проход через AI не платим.

    Ветвление про деньги: сейчас его ничто не защищает, и регресс «звать AI всегда»
    прошёл бы незаметно — вырос бы только счёт от провайдера.
    """
    def fake_deterministic_fix(regs):
        """Бесплатный проход всё починил: пустое имя заполнено, ошибок не осталось."""
        return [r.model_copy(update={"name": "Repaired"}) for r in regs], 1

    fix_core = AsyncMock()

    with (
        patch("llm_service._deterministic_fix_registers", fake_deterministic_fix),
        patch("llm_service._fix_registers_core", fix_core),
    ):
        data = await _run_analysis_with_real_core()

    fix_core.assert_not_called()  # платный проход не понадобился
    assert [d for d in data if d.get("stage") == "autofix"], "этап автофикса должен быть в логе"
    result = [d for d in data if "registers" in d]
    assert result and result[0]["registers"][0]["name"] == "Repaired"


async def _run_analysis_with_real_core() -> list[dict]:
    """Прогон анализа без подмены ядра автофикса (его патчит сам тест)."""
    with (
        patch("llm_service.AsyncOpenAI") as mock_openai,
        patch("llm_service.Image") as mock_image,
        patch("llm_service.image_to_base64", return_value="dGVzdA=="),
    ):
        client = AsyncMock()
        mock_openai.return_value = client
        client.chat.completions.create = AsyncMock(return_value=_llm_response(_BAD_REGISTER_RESPONSE))
        mock_image.open.return_value = MagicMock()

        events = []
        async for event in analyze_document(
            files=[("doc.png", b"fake-png")],
            template_type="full",
            settings=_settings(),
            request_id="test1234",
        ):
            events.append(event)

    return _parse(events)


async def test_autofix_metrics_counted(fast_keepalive):
    """autofix_runs растёт на прогоне с ошибками, autofix_cleared — когда фикс их убрал."""
    llm_service.analysis_metrics["autofix_runs"] = 0
    llm_service.analysis_metrics["autofix_cleared"] = 0

    await _run_analysis(AsyncMock(return_value=[Register(address=1, name="Fixed", reg_type="holding")]))

    assert llm_service.analysis_metrics["autofix_runs"] == 1
    assert llm_service.analysis_metrics["autofix_cleared"] == 1
