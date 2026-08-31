"""Настройки LLM в теле запроса объявлены один раз, миксином `LlmOverrides`.

Набор полей общий у исправления регистров и перевода. Разъедется он — разъедутся
и правила приоритета параметров на маршрутах.
"""

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

# Добавляем backend/ в sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

import llm_service  # noqa: E402, I001
import main  # noqa: E402
from models import (  # noqa: E402
    FixRegistersRequest,
    LlmOverrides,
    TranslateRequest,
    ValidateRequest,
)

OVERRIDES = {
    "llm_api_url": "https://user.example/v1",
    "llm_api_key": "sk-user",
    "llm_model": "local-model",
    "llm_timeout": 42,
    "llm_legacy_max_tokens": True,
    "llm_temperature": 0.0,
}


@pytest.mark.parametrize("model", [FixRegistersRequest, TranslateRequest])
def test_both_requests_expose_all_overrides(model):
    """Набор полей у обоих запросов один и тот же — иначе маршруты разъедутся."""
    assert set(LlmOverrides.model_fields) <= set(model.model_fields)


@pytest.mark.parametrize("field", list(LlmOverrides.model_fields))
def test_override_is_optional(field):
    """Каждое поле необязательное: «не прислал» должно отличаться от значения."""
    assert LlmOverrides().model_dump()[field] is None


@pytest.mark.parametrize("bad", [-0.1, 2.5])
def test_temperature_outside_bounds_rejected(bad):
    """0..2 — потолок OpenAI-совместимых провайдеров, зажат на модели."""
    with pytest.raises(ValidationError):
        LlmOverrides(llm_temperature=bad)


def test_fix_registers_accepts_registers_and_overrides():
    request = FixRegistersRequest(
        registers=[{"id": "r0", "address": 1, "name": "ok"}], **OVERRIDES,
    )

    assert request.llm_temperature == 0.0
    assert request.llm_legacy_max_tokens is True
    assert len(request.registers) == 1


def test_translate_accepts_strings_and_overrides():
    request = TranslateRequest(
        strings={"a": "Voltage"}, target_lang="de", target_lang_name="Deutsch", **OVERRIDES,
    )

    assert request.llm_api_url == "https://user.example/v1"
    assert request.target_lang_name == "Deutsch"


def test_registers_field_inherited_not_copied():
    """Поле регистров унаследовано от валидации, иначе правка типа проедет мимо второго."""
    inherited = ValidateRequest.model_fields["registers"]
    assert FixRegistersRequest.model_fields["registers"].annotation == inherited.annotation
    assert FixRegistersRequest.model_fields["registers"].metadata == inherited.metadata


def test_validate_request_has_no_llm_fields():
    """`/api/validate` к LLM не ходит, лишний ключ ему принимать незачем."""
    assert not set(LlmOverrides.model_fields) & set(ValidateRequest.model_fields)


class TestFixRegistersReadsBodyOnly:
    """Маршрут берёт настройки из тела, а из строки запроса не берёт.

    Проверка идёт через сам маршрут — модель полей может быть правильной, а
    эндпоинт объявит их не там, и ключ уедет в access-логи nginx и uvicorn.
    """

    BAD_REGISTER = {"id": "r0", "address": 70000, "name": "Bad", "reg_type": "holding", "format": "u16"}

    @pytest.fixture
    def captured(self, monkeypatch):
        """Подменяем сам вызов LLM и запоминаем, с какой целью его позвали."""
        calls: dict = {}

        async def fake_fix_registers(*args, **kwargs):
            calls.update(kwargs)
            yield "event: done\ndata: {}\n\n"

        monkeypatch.setattr(llm_service, "fix_registers", fake_fix_registers)

        async def _skip_url_check(url, allow_private=False):
            return None

        monkeypatch.setattr(main, "ensure_public_llm_url", _skip_url_check)
        # Без явного серверного LLM в CI маршрут ответит «LLM не настроен»
        settings = main.get_settings()
        monkeypatch.setattr(settings, "LLM_API_URL", "https://server.example/v1")
        monkeypatch.setattr(settings, "LLM_MODEL", "server-model")
        return calls

    def test_body_fields_are_used(self, captured):
        resp = TestClient(main.app).post("/api/fix-registers", json={
            "registers": [self.BAD_REGISTER],
            "llm_api_url": "https://user.example/v1",
            "llm_api_key": "sk-user",
            "llm_model": "user-model",
        })

        assert resp.status_code == 200
        assert captured["effective_url"] == "https://user.example/v1"
        assert captured["effective_key"] == "sk-user"
        assert captured["effective_model"] == "user-model"
        assert captured["is_custom_llm"] is True

    def test_query_fields_are_ignored(self, captured):
        resp = TestClient(main.app).post(
            "/api/fix-registers?llm_api_url=https://user.example/v1&llm_api_key=sk-user",
            json={"registers": [self.BAD_REGISTER]},
        )

        assert resp.status_code == 200
        assert captured["effective_url"] == "https://server.example/v1"
        assert captured["is_custom_llm"] is False
