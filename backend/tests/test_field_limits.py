"""Потолки на поля запроса и на детекцию паттернов.

Сборка, валидация и jinja-экспорт идут в event loop, поэтому объём работы одного
запроса обязан быть ограничен.
"""

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

# Добавляем backend/ в sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

import main  # noqa: E402, I001
from jinja_exporter import MAX_NUMBER_VARIANTS, _extract_number_variants  # noqa: E402
from models import (  # noqa: E402
    MAX_ENUM_ENTRIES,
    MAX_GROUPS,
    MAX_REGISTERS,
    MAX_TRANSLATE_STRINGS,
    BuildRequest,
    Register,
    TranslateRequest,
    ValidateRequest,
)


def _request(registers: list[dict], groups: list[dict] | None = None) -> dict:
    return {
        "device_info": {"name": "Test", "id": "test"},
        "registers": registers,
        "groups": groups or [],
    }


# ---------------------------------------------------------------------------
# Детекция паттернов
# ---------------------------------------------------------------------------

class TestNumberVariants:
    """Число вариантов на строку ограничено."""

    def test_real_name_unaffected(self):
        """Обычное имя канала разбирается целиком."""
        variants = _extract_number_variants("Input 3 voltage L2")

        assert len(variants) == 2
        assert [num for _, num, _, _ in variants] == [3, 2]

    def test_variants_capped(self):
        """На строке из одних цифр вариантов не больше потолка."""
        variants = _extract_number_variants("1 " * 5_000)

        assert len(variants) == MAX_NUMBER_VARIANTS

    def test_variants_capped_at_max_field_length(self):
        """Потолок работает и на самом длинном имени, которое пропускает валидация."""
        variants = _extract_number_variants("1 " * 256)  # ровно 512 символов

        assert len(variants) == MAX_NUMBER_VARIANTS

    def test_variants_are_the_first_numbers(self):
        """Берутся первые числа по порядку — результат детерминирован.

        Случайный отбор или отбор с конца давал бы разные шаблоны на одном входе.
        """
        variants = _extract_number_variants(" ".join(str(i) for i in range(1, 100)))

        assert [num for _, num, _, _ in variants] == list(range(1, MAX_NUMBER_VARIANTS + 1))


# ---------------------------------------------------------------------------
# Потолки полей
# ---------------------------------------------------------------------------

class TestFieldLimits:
    """Длина строк и размер списков ограничены на уровне моделей."""

    def test_long_name_rejected(self):
        """Имя канала длиннее потолка не принимается."""
        with pytest.raises(ValidationError):
            Register(id="r0", address=1, name="x" * 513)

    def test_normal_name_accepted(self):
        """Самое длинное имя из боевых шаблонов проходит с запасом."""
        reg = Register(id="r0", address=1, name="x" * 127)

        assert len(reg.name) == 127

    def test_long_description_rejected(self):
        """Описание длиннее потолка не принимается."""
        with pytest.raises(ValidationError):
            Register(id="r0", address=1, name="ok", description="x" * 2049)

    def test_bitwise_address_still_works(self):
        """Побитовый адрес строкой остаётся допустимым."""
        reg = Register(id="r0", address="109:1:2", name="ok")

        assert reg.address == "109:1:2"

    def test_too_many_registers_rejected(self):
        """Список каналов ограничен."""
        registers = [{"id": f"r{i}", "address": i, "name": "ok"} for i in range(MAX_REGISTERS + 1)]

        with pytest.raises(ValidationError):
            ValidateRequest(registers=registers)

    def test_too_many_groups_rejected(self):
        """Список групп ограничен."""
        groups = [{"id": f"g{i}", "title": "g"} for i in range(MAX_GROUPS + 1)]

        with pytest.raises(ValidationError):
            BuildRequest(**_request([{"id": "r0", "address": 1, "name": "ok"}], groups))

    def test_too_many_enum_entries_rejected(self):
        """Список значений enum ограничен."""
        with pytest.raises(ValidationError):
            Register(id="r0", address=1, name="ok", enum=list(range(MAX_ENUM_ENTRIES + 1)))

    def test_too_many_translate_strings_rejected(self):
        """Словарь строк на перевод ограничен — он уезжает на серверный ключ."""
        strings = {f"k{i}": "Voltage" for i in range(MAX_TRANSLATE_STRINGS + 1)}

        with pytest.raises(ValidationError):
            TranslateRequest(strings=strings, target_lang="de", target_lang_name="Deutsch")


# ---------------------------------------------------------------------------
# Эндпоинты
# ---------------------------------------------------------------------------

class TestEndpointRejection:
    """Отказ приходит от валидации запроса, до всякой работы."""

    @pytest.fixture
    def client(self):
        # Без lifespan: очереди для проверки отказов не нужны
        return TestClient(main.app)

    def test_build_rejects_too_many_registers(self, client):
        registers = [{"id": f"r{i}", "address": i, "name": "ok"} for i in range(MAX_REGISTERS + 1)]

        resp = client.post("/api/build", json=_request(registers))

        assert resp.status_code == 422

    def test_build_jinja_rejects_long_name(self, client):
        resp = client.post(
            "/api/build-jinja",
            json=_request([{"id": "r0", "address": 1, "name": "1 " * 20_000}]),
        )

        assert resp.status_code == 422
