"""Тесты для template_builder — сборка JSON-шаблонов из регистров."""

import json
import sys
from pathlib import Path

import pytest

# Добавляем backend/ в sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from models import BuildRequest, DeviceInfo, EnumEntry, Register, RegisterGroup
from template_builder import _make_group_id, _make_param_id, build_template

FIXTURES = Path(__file__).parent / "fixtures"


# --- Хелперы ---

def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def _make_request(fixture_name: str = "sdm230_registers.json") -> BuildRequest:
    data = _load_fixture(fixture_name)
    return BuildRequest(**data)


# --- Тесты вспомогательных функций ---

class TestMakeGroupId:
    def test_simple(self):
        assert _make_group_id("power_meters") == "g_power_meters"

    def test_spaces(self):
        assert _make_group_id("Power Meters") == "g_power_meters"

    def test_special_chars(self):
        assert _make_group_id("HW Info (v2)") == "g_hw_info_v2"

    def test_uppercase(self):
        assert _make_group_id("GENERAL") == "g_general"


class TestMakeParamId:
    def test_simple(self):
        assert _make_param_id("Baud Rate") == "baud_rate"

    def test_complex(self):
        assert _make_param_id("Modbus Address") == "modbus_address"

    def test_special(self):
        assert _make_param_id("Safety Action (v2)") == "safety_action_v2"


# --- Тест с эталонной фикстурой SDM-230 ---

class TestBuildTemplateSDM230:
    @pytest.fixture
    def result(self):
        request = _make_request()
        return build_template(request)

    @pytest.fixture
    def expected(self):
        return _load_fixture("sdm230_expected.json")

    def test_device_type(self, result):
        assert result["device_type"] == "sdm230"

    def test_title_key(self, result):
        assert result["title"] == "sdm230_template_title"

    def test_device_group(self, result):
        assert result["group"] == "g-power-meter"

    def test_device_name(self, result):
        assert result["device"]["name"] == "Eastron SDM-230"

    def test_device_id(self, result):
        assert result["device"]["id"] == "sdm230"

    def test_groups_count(self, result):
        assert len(result["device"]["groups"]) == 4

    def test_groups_order(self, result):
        group_ids = [g["id"] for g in result["device"]["groups"]]
        # Каналы идут перед параметрами → hw_info (канал) перед general (параметры)
        assert group_ids == ["g_power_meters", "g_energy", "g_hw_info", "g_general"]

    def test_channels_count(self, result):
        # 5 каналов + 1 текстовый (Serial NO) + 1 disabled (включён с enabled: false)
        assert len(result["device"]["channels"]) == 7

    def test_disabled_register_included_with_flag(self, result):
        """Disabled канал включается в шаблон с enabled: false."""
        disabled = [ch for ch in result["device"]["channels"] if ch.get("name") == "Disabled Register"]
        assert len(disabled) == 1
        assert disabled[0]["enabled"] is False

    def test_channel_voltage(self, result):
        ch = result["device"]["channels"][0]
        assert ch["name"] == "Voltage"
        assert "type" not in ch  # "value" — дефолт, не выводится
        assert ch["format"] == "float"
        assert ch["units"] == "V"
        assert ch["reg_type"] == "input"
        assert ch["group"] == "g_power_meters"

    def test_channel_serial_no(self, result):
        ch = result["device"]["channels"][5]
        assert ch["name"] == "Serial NO"
        assert ch["type"] == "text"
        assert ch["format"] == "string"
        assert ch["string_data_size"] == 4
        assert ch["readonly"] is True
        assert ch["group"] == "g_hw_info"

    def test_parameters_count(self, result):
        assert len(result["device"]["parameters"]) == 2

    def test_param_baud_rate(self, result):
        param = result["device"]["parameters"]["baud_rate"]
        assert param["title"] == "Baud Rate"
        assert param["address"] == 28
        assert param["enum"] == [0, 1, 2, 5]
        assert param["enum_titles"] == ["2400", "4800", "9600", "1200"]
        assert param["group"] == "g_general"
        assert param["order"] == 0

    def test_param_modbus_address(self, result):
        param = result["device"]["parameters"]["modbus_address"]
        assert param["title"] == "Modbus Address"
        assert param["min"] == 1
        assert param["max"] == 247
        assert param["order"] == 1

    def test_translations_en(self, result):
        en = result["device"]["translations"]["en"]
        # EN содержит только записи где key != value (title key)
        assert en["sdm230_template_title"] == "Eastron SDM-230"
        # Self-referential записи НЕ должны быть в EN
        assert "Voltage" not in en
        assert "Power Meters" not in en

    def test_translations_ru(self, result):
        ru = result["device"]["translations"]["ru"]
        assert ru["Voltage"] == "Напряжение"
        assert ru["Baud Rate"] == "Скорость обмена"

    def test_full_match(self, result, expected):
        """Полное сравнение с эталонным JSON."""
        assert result == expected


# --- Граничные случаи ---

class TestEdgeCases:
    def test_empty_registers(self):
        request = BuildRequest(
            device_info=DeviceInfo(name="Empty", id="empty"),
            registers=[],
        )
        result = build_template(request)
        assert result["device"]["channels"] == []
        assert result["device"]["parameters"] == {}
        assert result["device"]["groups"] == []

    def test_all_disabled(self):
        """Disabled каналы включаются в шаблон с enabled: false."""
        request = BuildRequest(
            device_info=DeviceInfo(name="Test", id="test"),
            registers=[
                Register(address=0, name="R1", enabled=False),
                Register(address=1, name="R2", enabled=False),
            ],
        )
        result = build_template(request)
        channels = result["device"]["channels"]
        assert len(channels) == 2
        assert all(ch["enabled"] is False for ch in channels)

    def test_no_device_group(self):
        request = BuildRequest(
            device_info=DeviceInfo(name="Test", id="test"),
            registers=[Register(address=0, name="R1")],
        )
        result = build_template(request)
        assert "group" not in result

    def test_channel_with_scale(self):
        request = BuildRequest(
            device_info=DeviceInfo(name="Test", id="test"),
            registers=[
                Register(address=0, name="Temp", scale=0.1, units="deg C"),
            ],
        )
        result = build_template(request)
        ch = result["device"]["channels"][0]
        assert ch["scale"] == 0.1
        assert ch["units"] == "deg C"

    def test_channel_without_units(self):
        request = BuildRequest(
            device_info=DeviceInfo(name="Test", id="test"),
            registers=[Register(address=0, name="Counter")],
        )
        result = build_template(request)
        ch = result["device"]["channels"][0]
        assert "units" not in ch

    def test_channel_with_condition(self):
        request = BuildRequest(
            device_info=DeviceInfo(name="Test", id="test"),
            registers=[
                Register(address=0, name="R1", condition="safety_mode==1"),
            ],
        )
        result = build_template(request)
        ch = result["device"]["channels"][0]
        assert ch["condition"] == "safety_mode==1"

    def test_channel_range_min_max(self):
        request = BuildRequest(
            device_info=DeviceInfo(name="Test", id="test"),
            registers=[
                Register(
                    address=0, name="Brightness",
                    channel_type="range", min=0, max=100,
                ),
            ],
        )
        result = build_template(request)
        ch = result["device"]["channels"][0]
        assert ch["type"] == "range"
        assert ch["min"] == 0
        assert ch["max"] == 100

    def test_channel_word_order(self):
        request = BuildRequest(
            device_info=DeviceInfo(name="Test", id="test"),
            registers=[
                Register(
                    address=0, name="Energy",
                    format="float", word_order="little_endian",
                ),
            ],
        )
        result = build_template(request)
        ch = result["device"]["channels"][0]
        assert ch["word_order"] == "little_endian"

    def test_duplicate_param_names(self):
        request = BuildRequest(
            device_info=DeviceInfo(name="Test", id="test"),
            registers=[
                Register(address=0, name="Threshold", is_parameter=True),
                Register(address=1, name="Threshold", is_parameter=True),
            ],
        )
        result = build_template(request)
        param_ids = list(result["device"]["parameters"].keys())
        assert param_ids == ["threshold", "threshold_2"]

    def test_parameter_with_condition(self):
        request = BuildRequest(
            device_info=DeviceInfo(name="Test", id="test"),
            registers=[
                Register(
                    address=0, name="Safety Mode",
                    is_parameter=True, enum=[0, 1],
                    enum_titles=["Off", "On"],
                ),
                Register(
                    address=1, name="Safety Threshold",
                    is_parameter=True, condition="safety_mode==1",
                    min=0, max=100,
                ),
            ],
        )
        result = build_template(request)
        param = result["device"]["parameters"]["safety_threshold"]
        assert param["condition"] == "safety_mode==1"


# --- Тесты: группы из запроса ---

class TestRequestGroups:
    def test_groups_from_request(self):
        """Группы из request.groups используются вместо автогенерации."""
        request = BuildRequest(
            device_info=DeviceInfo(name="Test", id="test"),
            registers=[
                Register(address=0, name="R1", group="power"),
                Register(address=1, name="R2", group="settings"),
            ],
            groups=[
                RegisterGroup(id="power", title="Power", order=0),
                RegisterGroup(id="settings", title="Settings", order=1),
            ],
        )
        result = build_template(request)
        groups = result["device"]["groups"]
        assert len(groups) == 2
        assert groups[0] == {"title": "Power", "id": "power"}
        assert groups[1] == {"title": "Settings", "id": "settings"}

    def test_groups_order_from_request(self):
        """Порядок групп из request.groups учитывается."""
        request = BuildRequest(
            device_info=DeviceInfo(name="Test", id="test"),
            registers=[
                Register(address=0, name="R1", group="b_group"),
                Register(address=1, name="R2", group="a_group"),
            ],
            groups=[
                RegisterGroup(id="a_group", title="A Group", order=1),
                RegisterGroup(id="b_group", title="B Group", order=0),
            ],
        )
        result = build_template(request)
        group_ids = [g["id"] for g in result["device"]["groups"]]
        assert group_ids == ["b_group", "a_group"]

    def test_group_translations_from_request(self):
        """Переводы групп берутся из request.groups.translations."""
        request = BuildRequest(
            device_info=DeviceInfo(name="Test", id="test"),
            registers=[Register(address=0, name="R1", group="power")],
            groups=[
                RegisterGroup(
                    id="power", title="Power Meters", order=0,
                    translations={"ru": {"title": "Измерения"}},
                ),
            ],
        )
        result = build_template(request)
        ru = result["device"]["translations"]["ru"]
        assert ru["Power Meters"] == "Измерения"

    def test_channels_use_group_id_from_request(self):
        """Каналы используют group id напрямую когда есть request.groups."""
        request = BuildRequest(
            device_info=DeviceInfo(name="Test", id="test"),
            registers=[Register(address=0, name="R1", group="my_group")],
            groups=[
                RegisterGroup(id="my_group", title="My Group", order=0),
            ],
        )
        result = build_template(request)
        ch = result["device"]["channels"][0]
        assert ch["group"] == "my_group"

    def test_group_description(self):
        """Description группы попадает в JSON."""
        request = BuildRequest(
            device_info=DeviceInfo(name="Test", id="test"),
            registers=[Register(address=0, name="R1", group="power")],
            groups=[
                RegisterGroup(
                    id="power", title="Power", order=0,
                    description="Power measurement channels",
                ),
            ],
        )
        result = build_template(request)
        groups = result["device"]["groups"]
        assert groups[0]["description"] == "Power measurement channels"

    def test_group_description_translation(self):
        """Переводы description группы попадают в translations."""
        request = BuildRequest(
            device_info=DeviceInfo(name="Test", id="test"),
            registers=[Register(address=0, name="R1", group="power")],
            groups=[
                RegisterGroup(
                    id="power", title="Power", order=0,
                    description="Power measurement channels",
                    translations={"ru": {"title": "Мощность", "description": "Каналы измерений мощности"}},
                ),
            ],
        )
        result = build_template(request)
        ru = result["device"]["translations"]["ru"]
        assert ru["Power measurement channels"] == "Каналы измерений мощности"


# --- Тесты: enum_entries ---

class TestEnumEntries:
    def test_enum_entries_priority(self):
        """enum_entries имеет приоритет над enum + enum_titles."""
        request = BuildRequest(
            device_info=DeviceInfo(name="Test", id="test"),
            registers=[
                Register(
                    address=0, name="Mode", is_parameter=True,
                    enum=[0, 1],
                    enum_titles=["Old Off", "Old On"],
                    enum_entries=[
                        EnumEntry(value=0, title="Off"),
                        EnumEntry(value=1, title="On"),
                    ],
                ),
            ],
        )
        result = build_template(request)
        param = result["device"]["parameters"]["mode"]
        assert param["enum"] == [0, 1]
        assert param["enum_titles"] == ["Off", "On"]

    def test_enum_entries_translations(self):
        """Переводы enum_entries попадают в translations."""
        request = BuildRequest(
            device_info=DeviceInfo(name="Test", id="test"),
            registers=[
                Register(
                    address=0, name="Mode", is_parameter=True,
                    enum_entries=[
                        EnumEntry(value=0, title="Off", translations={"ru": "Выкл"}),
                        EnumEntry(value=1, title="On", translations={"ru": "Вкл"}),
                    ],
                    translations={"ru": {"name": "Режим"}},
                ),
            ],
        )
        result = build_template(request)
        ru = result["device"]["translations"]["ru"]
        assert ru["Off"] == "Выкл"
        assert ru["On"] == "Вкл"
        # EN: self-referential записи enum НЕ попадают (нет EN override)
        en = result["device"]["translations"]["en"]
        assert "Off" not in en
        assert "On" not in en


# --- Тесты: новые поля ---

class TestNewFields:
    def test_round_to_channel(self):
        """round_to попадает в канал."""
        request = BuildRequest(
            device_info=DeviceInfo(name="Test", id="test"),
            registers=[
                Register(address=0, name="Temp", round_to=0.1),
            ],
        )
        result = build_template(request)
        ch = result["device"]["channels"][0]
        assert ch["round_to"] == 0.1

    def test_byte_order_channel(self):
        """byte_order попадает в канал."""
        request = BuildRequest(
            device_info=DeviceInfo(name="Test", id="test"),
            registers=[
                Register(address=0, name="R1", byte_order="little_endian"),
            ],
        )
        result = build_template(request)
        ch = result["device"]["channels"][0]
        assert ch["byte_order"] == "little_endian"

    def test_on_off_value_channel(self):
        """on_value и off_value попадают в канал."""
        request = BuildRequest(
            device_info=DeviceInfo(name="Test", id="test"),
            registers=[
                Register(
                    address=0, name="Switch",
                    channel_type="switch", on_value=0xFF00, off_value=0x0000,
                ),
            ],
        )
        result = build_template(request)
        ch = result["device"]["channels"][0]
        assert ch["on_value"] == 0xFF00
        assert ch["off_value"] == 0x0000

    def test_default_value_parameter(self):
        """default_value переопределяет default для параметра."""
        request = BuildRequest(
            device_info=DeviceInfo(name="Test", id="test"),
            registers=[
                Register(
                    address=0, name="Threshold", is_parameter=True,
                    default_value=42.0, min=0, max=100,
                ),
            ],
        )
        result = build_template(request)
        param = result["device"]["parameters"]["threshold"]
        assert param["default"] == 42.0

    def test_description_translation(self):
        """description перевод из translations попадает в translations шаблона."""
        request = BuildRequest(
            device_info=DeviceInfo(name="Test", id="test"),
            registers=[
                Register(
                    address=0, name="Mode", is_parameter=True,
                    description="Operating mode",
                    translations={"ru": {"name": "Режим", "description": "Режим работы"}},
                ),
            ],
        )
        result = build_template(request)
        ru = result["device"]["translations"]["ru"]
        assert ru["Operating mode"] == "Режим работы"
        # EN: нет EN override для description → self-referential не добавляется
        en = result["device"]["translations"]["en"]
        assert "Operating mode" not in en

    def test_channel_description_not_in_translations(self):
        """Описание канала (не параметра) НЕ попадает в translations шаблона."""
        request = BuildRequest(
            device_info=DeviceInfo(name="Test", id="test"),
            registers=[
                Register(
                    address=0, name="Voltage", is_parameter=False,
                    description="Line voltage measurement",
                    translations={"ru": {"name": "Напряжение", "description": "Измерение напряжения"}},
                ),
            ],
        )
        result = build_template(request)
        ru = result["device"]["translations"]["ru"]
        # Имя канала с переводом — есть в RU
        assert ru["Voltage"] == "Напряжение"
        # EN: нет EN override → self-referential не добавляется
        en = result["device"]["translations"]["en"]
        assert "Voltage" not in en
        # Описание канала НЕ должно попадать в translations
        assert "Line voltage measurement" not in en
        assert "Line voltage measurement" not in ru

    def test_parameter_order(self):
        """Параметры содержат order."""
        request = BuildRequest(
            device_info=DeviceInfo(name="Test", id="test"),
            registers=[
                Register(address=0, name="Param A", is_parameter=True),
                Register(address=1, name="Param B", is_parameter=True),
                Register(address=2, name="Param C", is_parameter=True),
            ],
        )
        result = build_template(request)
        params = result["device"]["parameters"]
        assert params["param_a"]["order"] == 0
        assert params["param_b"]["order"] == 1
        assert params["param_c"]["order"] == 2


# --- Тесты: побитовый адрес ---

class TestBitAddress:
    def test_bitwise_address_string(self):
        """Побитовый адрес '109:1:2' передаётся как строка."""
        request = BuildRequest(
            device_info=DeviceInfo(name="Test", id="test"),
            registers=[
                Register(address="109:1:2", name="Bit Field"),
            ],
        )
        result = build_template(request)
        ch = result["device"]["channels"][0]
        assert ch["address"] == "109:1:2"

    def test_numeric_string_address(self):
        """Числовой адрес в строке '42' конвертируется в int."""
        request = BuildRequest(
            device_info=DeviceInfo(name="Test", id="test"),
            registers=[
                Register(address="42", name="R1"),
            ],
        )
        result = build_template(request)
        ch = result["device"]["channels"][0]
        assert ch["address"] == 42

    def test_int_address_unchanged(self):
        """Обычный int-адрес остаётся int."""
        request = BuildRequest(
            device_info=DeviceInfo(name="Test", id="test"),
            registers=[
                Register(address=100, name="R1"),
            ],
        )
        result = build_template(request)
        ch = result["device"]["channels"][0]
        assert ch["address"] == 100
        assert isinstance(ch["address"], int)

    def test_parameter_readonly(self):
        """Параметр с readonly=True содержит 'readonly': True."""
        request = BuildRequest(
            device_info=DeviceInfo(name="Test", id="test"),
            registers=[
                Register(
                    address=0, name="FW Version",
                    is_parameter=True, readonly=True,
                ),
            ],
        )
        result = build_template(request)
        param = result["device"]["parameters"]["fw_version"]
        assert param["readonly"] is True


# --- Тесты: обратная совместимость legacy-формата ---

class TestLegacyCompat:
    def test_register_name_ru_migration(self):
        """Legacy name_ru/description_ru мигрирует в translations."""
        reg = Register(
            address=0, name="Voltage",
            name_ru="Напряжение",
            description="Line voltage",
            description_ru="Напряжение сети",
        )
        assert reg.translations is not None
        assert reg.translations["ru"].name == "Напряжение"
        assert reg.translations["ru"].description == "Напряжение сети"

    def test_enum_entry_legacy(self):
        """Legacy title_en/title_ru мигрирует в title + translations."""
        entry = EnumEntry(value=0, title_en="Off", title_ru="Выкл")
        assert entry.title == "Off"
        assert entry.translations == {"ru": "Выкл"}

    def test_group_legacy(self):
        """Legacy title_en/title_ru мигрирует в title + translations."""
        group = RegisterGroup(id="g1", title_en="Power", title_ru="Мощность", order=0)
        assert group.title == "Power"
        assert group.translations is not None
        assert group.translations["ru"].title == "Мощность"

    def test_enum_entry_legacy_no_ru(self):
        """Legacy title_en без title_ru — только title, без translations."""
        entry = EnumEntry(value=0, title_en="Off")
        assert entry.title == "Off"
        assert entry.translations is None

    def test_group_legacy_no_ru(self):
        """Legacy title_en без title_ru — только title, без translations."""
        group = RegisterGroup(id="g1", title_en="Power", order=0)
        assert group.title == "Power"
        assert group.translations is None


# --- Тесты: множество языков ---

class TestMultiLanguage:
    def test_multiple_languages(self):
        """Несколько языков переводов собираются в translations."""
        request = BuildRequest(
            device_info=DeviceInfo(name="Test", id="test"),
            registers=[
                Register(
                    address=0, name="Temperature",
                    translations={
                        "ru": {"name": "Температура"},
                        "de": {"name": "Temperatur"},
                    },
                ),
            ],
        )
        result = build_template(request)
        tr = result["device"]["translations"]
        assert "en" in tr
        assert "ru" in tr
        assert "de" in tr
        assert tr["ru"]["Temperature"] == "Температура"
        assert tr["de"]["Temperature"] == "Temperatur"

    def test_no_translations_only_en(self):
        """Без переводов — только en в translations."""
        request = BuildRequest(
            device_info=DeviceInfo(name="Test", id="test"),
            registers=[Register(address=0, name="R1")],
        )
        result = build_template(request)
        tr = result["device"]["translations"]
        assert list(tr.keys()) == ["en"]

    def test_empty_lang_removed(self):
        """Язык без реальных переводов (все совпадают с ключами) удаляется."""
        request = BuildRequest(
            device_info=DeviceInfo(name="Test", id="test"),
            registers=[
                Register(
                    address=0, name="R1",
                    translations={"de": {}},
                ),
            ],
        )
        result = build_template(request)
        tr = result["device"]["translations"]
        # de не содержит реальных переводов — должен быть удалён
        assert "de" not in tr


# --- Тесты: конфликты переводов ---

class TestTranslationConflicts:
    def test_enum_conflict_warning(self):
        """Конфликтующие переводы enum генерируют предупреждение."""
        request = BuildRequest(
            device_info=DeviceInfo(name="Test", id="test"),
            registers=[
                Register(
                    address=0, name="Mode1", is_parameter=True,
                    enum_entries=[
                        EnumEntry(value=0, title="Off", translations={"ru": "Выкл"}),
                    ],
                    translations={"ru": {"name": "Режим 1"}},
                ),
                Register(
                    address=1, name="Mode2", is_parameter=True,
                    enum_entries=[
                        EnumEntry(value=0, title="Off", translations={"ru": "Откл"}),
                    ],
                    translations={"ru": {"name": "Режим 2"}},
                ),
            ],
        )
        result = build_template(request)
        assert "_warnings" in result
        assert len(result["_warnings"]) >= 1
        assert "Off" in result["_warnings"][0]

    def test_no_conflict_no_warnings(self):
        """Без конфликтов — нет предупреждений."""
        request = BuildRequest(
            device_info=DeviceInfo(name="Test", id="test"),
            registers=[
                Register(
                    address=0, name="Mode", is_parameter=True,
                    enum_entries=[
                        EnumEntry(value=0, title="Off", translations={"ru": "Выкл"}),
                        EnumEntry(value=1, title="On", translations={"ru": "Вкл"}),
                    ],
                    translations={"ru": {"name": "Режим"}},
                ),
            ],
        )
        result = build_template(request)
        assert "_warnings" not in result
