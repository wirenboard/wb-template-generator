"""Тесты для template_importer — импорт JSON/Jinja шаблонов в формат редактора."""

import json
from pathlib import Path

import pytest

from template_importer import detect_and_import, import_template

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def akko_template():
    """Реальный JSON-шаблон AKKO из wb-mqtt-serial."""
    raw = json.loads((FIXTURES / "config-akko.json").read_text())
    return raw


@pytest.fixture
def minimal_template():
    """Минимальный шаблон с одним каналом."""
    return {
        "device_type": "test-device",
        "title": "test_template_title",
        "device": {
            "name": "Test Device",
            "id": "test-device",
            "groups": [{"title": "Main", "id": "main"}],
            "channels": [
                {
                    "name": "Temperature",
                    "reg_type": "input",
                    "address": 0,
                    "type": "value",
                    "format": "s16",
                    "units": "deg C",
                    "scale": 0.1,
                    "group": "main",
                    "readonly": True,
                }
            ],
            "parameters": {},
            "translations": {
                "en": {
                    "test_template_title": "Test Device",
                    "Main": "Main",
                    "Temperature": "Temperature",
                },
                "ru": {
                    "test_template_title": "Тестовое устройство",
                    "Main": "Основное",
                    "Temperature": "Температура",
                },
            },
        },
    }


class TestImportChannels:
    """Тесты импорта каналов."""

    def test_basic_channel(self, minimal_template):
        result = import_template(minimal_template)
        regs = result["registers"]
        assert len(regs) == 1
        reg = regs[0]
        assert reg["name"] == "Temperature"
        assert reg["is_parameter"] is False
        assert reg["reg_type"] == "input"
        assert reg["format"] == "s16"
        assert reg["units"] == "deg C"
        assert reg["scale"] == 0.1
        assert reg["access"] == "read"  # readonly=True → access="read"
        assert reg["group"] == "main"

    def test_channel_translations(self, minimal_template):
        result = import_template(minimal_template)
        reg = result["registers"][0]
        assert reg["translations"] is not None
        assert reg["translations"]["ru"]["name"] == "Температура"


class TestImportParameters:
    """Тесты импорта параметров."""

    def test_parameters_from_dict(self, akko_template):
        result = import_template(akko_template)
        params = [r for r in result["registers"] if r["is_parameter"]]
        assert len(params) > 0
        # power_on_remind — есть в шаблоне AKKO
        remind = [p for p in params if "remind" in p["name"].lower()]
        assert len(remind) == 1
        assert remind[0]["enum_entries"] is not None
        assert len(remind[0]["enum_entries"]) == 4

    def test_parameter_default_value(self, akko_template):
        result = import_template(akko_template)
        params = [r for r in result["registers"] if r["is_parameter"]]
        remind = [p for p in params if "remind" in p["name"].lower()][0]
        assert remind.get("default_value") == 0


class TestImportGroups:
    """Тесты импорта групп."""

    def test_groups_extracted(self, akko_template):
        result = import_template(akko_template)
        groups = result["groups"]
        assert len(groups) >= 2
        group_titles = [g["title"] for g in groups]
        assert "Main" in group_titles
        assert "Settings" in group_titles

    def test_group_order(self, akko_template):
        result = import_template(akko_template)
        groups = result["groups"]
        orders = [g["order"] for g in groups]
        assert orders == sorted(orders)


class TestImportTranslations:
    """Тесты маппинга переводов."""

    def test_register_translations(self, minimal_template):
        result = import_template(minimal_template)
        reg = result["registers"][0]
        assert "ru" in reg["translations"]
        assert reg["translations"]["ru"]["name"] == "Температура"

    def test_group_translations(self, minimal_template):
        result = import_template(minimal_template)
        groups = result["groups"]
        main_group = [g for g in groups if g["id"] == "main"][0]
        assert main_group["translations"]["ru"]["title"] == "Основное"


class TestImportEnum:
    """Тесты enum_entries с переводами."""

    def test_enum_entries_built(self):
        template = {
            "device_type": "test",
            "device": {
                "name": "Test",
                "id": "test",
                "groups": [],
                "channels": [
                    {
                        "name": "Mode",
                        "address": 0,
                        "reg_type": "holding",
                        "type": "value",
                        "format": "u16",
                        "enum": [0, 1, 2],
                        "enum_titles": ["Off", "Auto", "Manual"],
                        "group": "general",
                    }
                ],
                "parameters": {},
                "translations": {
                    "en": {"Mode": "Mode", "Off": "Off", "Auto": "Auto", "Manual": "Manual"},
                    "ru": {"Mode": "Режим", "Off": "Выкл", "Auto": "Авто", "Manual": "Ручной"},
                },
            },
        }
        result = import_template(template)
        reg = result["registers"][0]
        entries = reg["enum_entries"]
        assert len(entries) == 3
        assert entries[0]["value"] == 0
        assert entries[0]["title"] == "Off"
        assert entries[0]["translations"]["ru"] == "Выкл"
        assert entries[2]["translations"]["ru"] == "Ручной"


class TestImportDeviceInfo:
    """Тесты извлечения DeviceInfo."""

    def test_device_info(self, akko_template):
        result = import_template(akko_template)
        info = result["device_info"]
        assert info["id"] == "akko"
        assert info.get("device_group") == "g-curtain"

    def test_device_info_minimal(self, minimal_template):
        result = import_template(minimal_template)
        info = result["device_info"]
        assert info["id"] == "test-device"


class TestDetectAndImport:
    """Тесты detect_and_import (авто-определение формата)."""

    def test_json_file(self, minimal_template):
        content = json.dumps(minimal_template).encode("utf-8")
        result = detect_and_import(content, "template.json")
        assert "device_info" in result
        assert "registers" in result
        assert "groups" in result

    def test_real_akko(self):
        """Тест с реальным config-akko.json."""
        content = (FIXTURES / "config-akko.json").read_bytes()
        result = detect_and_import(content, "config-akko.json")
        assert len(result["registers"]) > 0
        assert result["device_info"]["id"] == "akko"


class TestJinjaImport:
    """Тесты импорта Jinja-шаблонов."""

    def test_jinja_detected_by_extension(self):
        """Jinja-файл по расширению .json.jinja."""
        fixture = FIXTURES / "config-arlight-dali-logic-lite-ps-x1.json.jinja"
        if not fixture.exists():
            pytest.skip("Фикстура jinja не найдена")
        content = fixture.read_bytes()
        result = detect_and_import(content, fixture.name)
        assert len(result["registers"]) > 0
        assert result["device_info"]["id"] == "dali_logic_lite_ps_x1"

    def test_jinja_detected_by_content(self):
        """Jinja определяется по наличию '{%' в содержимом."""
        jinja_text = """{
    "device_type": "test",
    "device": {
        "name": "Test",
        "id": "test",
        "groups": [],
        "channels": [
            {% for i in range(1, 3) -%}
            {
                "name": "Ch {{ i }}",
                "address": {{ i - 1 }},
                "reg_type": "holding",
                "type": "value",
                "format": "u16",
                "group": "general"
            }{% if not loop.last %},{% endif %}
            {% endfor -%}
        ],
        "parameters": {},
        "translations": {}
    }
}"""
        result = detect_and_import(jinja_text.encode("utf-8"), "template.json")
        assert len(result["registers"]) == 2
        assert result["registers"][0]["name"] == "Ch 1"
        assert result["registers"][1]["name"] == "Ch 2"


class TestImportValidation:
    """Тесты валидации входного JSON."""

    def test_invalid_json_raises(self):
        """Невалидный JSON (не wb-mqtt-serial) должен выбросить ValueError."""
        with pytest.raises(ValueError, match="Not a wb-mqtt-serial template"):
            import_template({"name": "package.json", "version": "1.0.0"})

    def test_empty_dict_raises(self):
        """Пустой dict — не шаблон."""
        with pytest.raises(ValueError, match="Not a wb-mqtt-serial template"):
            import_template({})

    def test_device_type_only_passes(self):
        """Шаблон с device_type, но без channels/parameters — допускается."""
        result = import_template({"device_type": "test-device", "device": {}})
        assert result["device_info"]["id"] == "test-device"

    def test_channels_only_passes(self):
        """Шаблон только с каналами — допускается."""
        result = import_template({
            "device": {
                "name": "Test",
                "id": "test",
                "channels": [{"name": "Ch", "address": 0, "reg_type": "holding", "type": "value", "format": "u16"}],
            }
        })
        assert len(result["registers"]) == 1

    def test_parameters_only_passes(self):
        """Шаблон только с параметрами (без каналов) — допускается."""
        result = import_template({
            "device": {
                "name": "Test",
                "id": "test",
                "parameters": {
                    "baud_rate": {
                        "title": "Baud rate",
                        "address": 110,
                        "reg_type": "holding",
                        "format": "u16",
                        "enum": [1200, 2400, 9600],
                        "enum_titles": ["1200", "2400", "9600"],
                        "default": 9600,
                    },
                },
            }
        })
        assert len(result["registers"]) == 1
        assert result["registers"][0]["is_parameter"] is True

    def test_device_id_without_device_type_passes(self):
        """Шаблон с device.id, но без device_type — допускается."""
        result = import_template({
            "device": {
                "id": "my-device",
                "channels": [{"name": "Ch", "address": 0, "reg_type": "holding", "type": "value", "format": "u16"}],
            }
        })
        assert result["device_info"]["id"] == "my-device"

    def test_parameters_as_list_passes(self):
        """Параметры как list (альтернативный формат) — допускается."""
        result = import_template({
            "device": {
                "name": "Test",
                "id": "test",
                "parameters": [
                    {
                        "title": "Baud rate",
                        "address": 110,
                        "reg_type": "holding",
                        "format": "u16",
                        "default": 9600,
                    },
                ],
            }
        })
        assert len(result["registers"]) == 1
        assert result["registers"][0]["is_parameter"] is True
        assert result["registers"][0]["name"] == "Baud rate"


class TestRoundtrip:
    """Тест roundtrip: import → build → проверка ключевых полей."""

    def test_minimal_roundtrip(self, minimal_template):
        """Импорт минимального шаблона → сборка → проверка структуры."""
        from models import BuildRequest, DeviceInfo, Register, RegisterGroup

        imported = import_template(minimal_template)

        # Строим BuildRequest из импортированных данных
        registers = [Register(**r) for r in imported["registers"]]
        groups = [RegisterGroup(**g) for g in imported["groups"]]
        device_info = DeviceInfo(**imported["device_info"])

        request = BuildRequest(
            device_info=device_info,
            registers=registers,
            groups=groups,
        )

        from template_builder import build_template

        built = build_template(request)

        # Проверяем ключевые поля
        assert built["device"]["id"] == minimal_template["device"]["id"]
        assert len(built["device"]["channels"]) == len(minimal_template["device"]["channels"])
        assert built["device"]["channels"][0]["name"] == "Temperature"
        assert built["device"]["channels"][0]["format"] == "s16"
        assert built["device"]["channels"][0]["units"] == "deg C"
        # Переводы сохранились
        assert "ru" in built["device"]["translations"]
