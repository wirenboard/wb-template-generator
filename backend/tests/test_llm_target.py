"""Единая точка разрешения цели LLM.

Правило разное для двух вещей. Доступ (адрес, ключ, прокси) изолирован,
настройки модели — оверрайд поверх серверных, потому что окно «Настройки LLM»
донастраивает в том числе серверную модель.
"""

import sys
from pathlib import Path

import pytest

# Добавляем backend/ в sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import Settings  # noqa: E402, I001
from llm_service import is_custom_llm_url, resolve_llm_target  # noqa: E402


def _settings(**overrides) -> Settings:
    base = {
        "LLM_API_URL": "https://server.example/v1",
        "LLM_API_KEY": "server-key",
        "LLM_MODEL": "server-model",
        "LLM_TIMEOUT": 600,
        "LLM_MAX_TOKENS": 0,
        "LLM_LEGACY_MAX_TOKENS": False,
        "LLM_TEMPERATURE": None,
        "LLM_PROXY": "",
    }
    base.update(overrides)
    return Settings(**base)


class TestServerTarget:
    """Без пользовательского адреса действуют настройки оператора."""

    def test_defaults_to_server_settings(self):
        target = resolve_llm_target(_settings())

        assert target.url == "https://server.example/v1"
        assert target.key == "server-key"
        assert target.model == "server-model"
        assert target.timeout == 600
        assert not target.is_custom

    def test_client_values_override_server_settings(self):
        """Настройки модели донастраивают и серверный LLM, так задумано окно настроек."""
        target = resolve_llm_target(
            _settings(), model="other-model", timeout=120,
            legacy_max_tokens=True, temperature=0.7, max_tokens=8192,
        )

        assert target.model == "other-model"
        assert target.timeout == 120
        assert target.legacy_max_tokens is True
        assert target.temperature == 0.7
        assert target.max_tokens == 8192
        # Ключ и адрес при этом остаются серверными
        assert target.url == "https://server.example/v1"
        assert target.key == "server-key"
        assert not target.is_custom

    def test_server_proxy_applied(self):
        target = resolve_llm_target(_settings(LLM_PROXY="http://proxy.example:3128"))

        assert target.proxy == "http://proxy.example:3128"

    def test_shorter_timeout_applies(self):
        target = resolve_llm_target(_settings(LLM_TIMEOUT=600), timeout=30)

        assert target.timeout == 30

    def test_timeout_cannot_exceed_server_value(self):
        """Поднять таймаут на серверном ключе нельзя, длинный запрос держит воркер."""
        target = resolve_llm_target(_settings(LLM_TIMEOUT=600), timeout=36_000)

        assert target.timeout == 600

    def test_zero_server_timeout_does_not_clamp_to_zero(self):
        """`LLM_TIMEOUT=0` у оператора значит «без потолка», а не «мгновенно»."""
        target = resolve_llm_target(_settings(LLM_TIMEOUT=0), timeout=30)

        assert target.timeout == 30


class TestCustomCriterion:
    """Признак «свой LLM» считается по адресу и только по нему."""

    @pytest.mark.parametrize("url", ["https://user.example/v1", "http://ollama.local:11434/v1"])
    def test_url_makes_target_custom(self, url):
        assert is_custom_llm_url(url)

    @pytest.mark.parametrize("url", [None, ""])
    def test_no_url_is_server_target(self, url):
        assert not is_custom_llm_url(url)

    def test_custom_without_key_stays_custom(self):
        """Ключ в критерий не входит, локальные модели авторизации не требуют.

        Иначе свой LLM без ключа уехал бы на серверный ключ, то есть за наш счёт.
        """
        target = resolve_llm_target(_settings(), url="https://user.example/v1")

        assert target.is_custom
        assert target.key is None


class TestCustomTarget:
    """Со своим адресом применяются значения клиента."""

    def test_custom_url_and_key(self):
        target = resolve_llm_target(
            _settings(), url="https://user.example/v1", key="user-key",
        )

        assert target.url == "https://user.example/v1"
        assert target.key == "user-key"
        assert target.is_custom

    def test_server_key_never_leaks_to_custom_url(self):
        """Изоляция ключа: без своего ключа уходит пустой, а не серверный."""
        target = resolve_llm_target(_settings(), url="https://user.example/v1")

        assert target.key is None

    def test_custom_params_win(self):
        target = resolve_llm_target(
            _settings(), url="https://user.example/v1",
            model="user-model", timeout=30, max_tokens=2048,
            legacy_max_tokens=True, temperature=0.2,
        )

        assert target.model == "user-model"
        assert target.timeout == 30
        assert target.max_tokens == 2048
        assert target.legacy_max_tokens is True
        assert target.temperature == 0.2

    def test_missing_params_fall_back_to_settings(self):
        target = resolve_llm_target(_settings(), url="https://user.example/v1")

        assert target.model == "server-model"
        assert target.timeout == 600

    def test_own_provider_may_get_longer_timeout(self):
        """Потолок оператора защищает его ключ, а чужой провайдер ждёт как просят."""
        target = resolve_llm_target(
            _settings(LLM_TIMEOUT=600), url="https://user.example/v1", timeout=1_200,
        )

        assert target.timeout == 1_200

    def test_system_prompt_isolation_not_affected(self):
        """Промпт в резолвер не входит, его изоляция живёт в analyze_document."""
        assert not hasattr(resolve_llm_target(_settings()), "system_prompt")

    def test_server_proxy_not_used_for_custom_url(self):
        """Через прокси оператора чужой адрес не гоняем."""
        target = resolve_llm_target(
            _settings(LLM_PROXY="http://proxy.example:3128"),
            url="https://user.example/v1",
        )

        assert target.proxy is None


class TestMeaningfulZeroes:
    """Ноль и False значимы, а сентинела `-1` больше нет."""

    @pytest.mark.parametrize("temperature", [0, 0.0])
    def test_zero_temperature_survives(self, temperature):
        """gpt-4o и локальные модели детерминируются нулём — его нельзя терять."""
        target = resolve_llm_target(
            _settings(LLM_TEMPERATURE=1.0), url="https://user.example/v1",
            temperature=temperature,
        )

        assert target.temperature == 0

    def test_false_flag_survives(self):
        target = resolve_llm_target(
            _settings(LLM_LEGACY_MAX_TOKENS=True), url="https://user.example/v1",
            legacy_max_tokens=False,
        )

        assert target.legacy_max_tokens is False

    def test_none_temperature_means_not_sent(self):
        """Разрешённая None это «не отправлять параметр вовсе»."""
        target = resolve_llm_target(_settings(), url="https://user.example/v1")

        assert target.temperature is None
