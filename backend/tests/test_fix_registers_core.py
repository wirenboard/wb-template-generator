"""Тесты ядра автофикса `_fix_registers_core` (общее для кнопки и автофикса анализа).

LLM замокан — проверяем сериализацию подмножества с ошибками, парсинг ответа и
вмёрдживание исправлений обратно в полный список по позициям.
"""

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import llm_service  # noqa: E402
from llm_service import LLMApiError, _fix_registers_core  # noqa: E402
from models import Register  # noqa: E402


def _llm_returning(payload: dict) -> AsyncMock:
    """Мок _call_llm: возвращает (json_текст, usage=None)."""
    return AsyncMock(return_value=(json.dumps(payload, ensure_ascii=False), None))


@pytest.mark.asyncio
async def test_core_merges_fix_back_by_position():
    """Правится только кривой регистр, остальные не тронуты, id восстановлен."""
    ok = Register(id="reg-ok", address=1, name="Ok", reg_type="holding")
    bad = Register(id="reg-bad", address=2, name="", reg_type="holding")  # пустое имя
    all_regs = [ok, bad]

    # LLM возвращает исправленный регистр под временным тегом __fix_0
    llm_payload = {
        "device_info": {"name": "device", "id": "device"},
        "registers": [{"id": "__fix_0", "address": 2, "name": "Fixed", "reg_type": "holding"}],
    }

    with patch("llm_service._call_llm", _llm_returning(llm_payload)):
        result = await _fix_registers_core(
            MagicMock(), "gpt-test", [bad], "Register: name is empty",
            all_registers=all_regs, error_positions=[1],
        )

    assert len(result) == 2
    assert result[0].name == "Ok"                     # не тронут
    assert result[1].name == "Fixed"                  # исправлен
    assert result[1].id == "reg-bad"                  # исходный id восстановлен


@pytest.mark.asyncio
async def test_core_raises_on_empty_response():
    with patch("llm_service._call_llm", AsyncMock(return_value=("", None))):
        with pytest.raises(LLMApiError):
            await _fix_registers_core(
                MagicMock(), "gpt-test",
                [Register(address=1, name="", reg_type="holding")],
                "err", all_registers=None, error_positions=None,
            )


@pytest.mark.asyncio
async def test_core_raises_when_no_registers_returned():
    payload = {"device_info": {"name": "device", "id": "device"}, "registers": []}
    with patch("llm_service._call_llm", _llm_returning(payload)):
        with pytest.raises(LLMApiError):
            await _fix_registers_core(
                MagicMock(), "gpt-test",
                [Register(address=1, name="", reg_type="holding")],
                "err", all_registers=None, error_positions=None,
            )


def test_deterministic_fix_applies_synonyms():
    """Детерминированный проход канонизирует синонимы без обращения к LLM."""
    from llm_service import _deterministic_fix_registers

    regs = [Register(address=1, name="Voltage", reg_type="holding", format="uint16")]

    fixed, count = _deterministic_fix_registers(regs)

    assert fixed[0].format == "u16"
    assert count >= 1


def test_deterministic_fix_keeps_register_when_rebuild_fails():
    """Если пересборка Register упала, остаётся исходный регистр, а не потеря данных.

    Единственная защита от исчезновения регистра на бесплатном шаге автофикса.
    Ломаем именно пересборку: auto_fix_register отдаёт «исправление», которое
    Pydantic принять не может.
    """
    from llm_service import _deterministic_fix_registers

    original = Register(address=1, name="Voltage", reg_type="holding", format="u16")

    def broken_fix(raw):
        raw["reg_type"] = object()  # непригодное значение, Register(**raw) бросит
        return raw, ["fix-запись, чтобы дойти до пересборки"]

    with patch("register_validator.auto_fix_register", broken_fix):
        fixed, count = _deterministic_fix_registers([original])

    assert len(fixed) == 1, "регистр не должен исчезнуть"
    assert fixed[0] is original, "должен остаться исходный объект"
    assert fixed[0].reg_type == "holding"
    assert count == 1  # исправление посчитано, хотя применить его не удалось


@pytest.mark.asyncio
async def test_manual_button_sends_keepalive_while_llm_works(monkeypatch):
    """Кнопка «Исправить через AI» шлёт события, пока идёт фикс.

    Без них nginx закрывает SSE по proxy_read_timeout, и результат теряется.
    """
    monkeypatch.setattr(llm_service, "_KEEPALIVE_INTERVAL", 0.05)

    async def slow_core(*args, **kwargs):
        await asyncio.sleep(0.2)
        return [Register(address=1, name="Fixed", reg_type="holding")]

    with (
        patch("llm_service.AsyncOpenAI", MagicMock()),
        patch("llm_service._fix_registers_core", AsyncMock(side_effect=slow_core)),
    ):
        events = [
            ev async for ev in llm_service.fix_registers(
                [Register(address=1, name="", reg_type="holding")], "name is empty",
                effective_url="https://api.example.com/v1", effective_key="sk-test",
                effective_model="gpt-test", request_id="rid",
            )
        ]

    assert [e for e in events if "LLM исправляет ошибки..." in e and "(0:00)" in e], (
        "во время фикса в поток не ушло ни одного keepalive-события"
    )
    assert any("event: result" in e for e in events)
    assert not any("event: error" in e for e in events)
