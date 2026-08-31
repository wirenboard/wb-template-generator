"""Тесты для template_importer — импорт JSON/Jinja шаблонов в формат редактора."""

import json
import time
from pathlib import Path

import pytest

from models import Register
from template_importer import (
    MAX_JINJA_SOURCE_CHARS,
    TemplateImportError,
    detect_and_import,
    import_template,
)

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def akko_template():
    """Реальный JSON-шаблон AKKO из wb-mqtt-serial."""
    raw = json.loads((FIXTURES / "config-akko.json").read_text())
    return raw


@pytest.fixture
def channel_template():
    """Шаблон с одним каналом: поля канала задаёт тест."""
    def build(fields: dict) -> dict:
        channel = {
            "name": "Ch", "reg_type": "holding", "address": 0,
            "type": "value", "format": "u16", "group": "main",
        }
        channel.update(fields)
        return {
            "device_type": "test-device",
            "title": "test_template_title",
            "device": {
                "name": "Test Device", "id": "test-device",
                "groups": [{"title": "Main", "id": "main"}],
                "channels": [channel],
            },
        }
    return build


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
        assert reg["readonly"] is True  # флаг readonly сохраняется для roundtrip
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


class TestJinjaSandbox:
    """Рендер загруженного шаблона идёт в песочнице.

    Лечим RCE: обычный Environment исполнял код из файла, гаджет
    cycler.__init__.__globals__.os.popen давал команды ОС до разбора JSON.
    """

    @pytest.mark.parametrize("gadget", [
        "{{ cycler.__init__.__globals__.os }}",
        "{{ self.__init__.__globals__ }}",
        "{{ ''.__class__.__mro__ }}",
        "{% set x = cycler.__init__.__globals__ %}{}",
    ])
    def test_attribute_gadgets_rejected(self, gadget):
        """Доступ к внутренним атрибутам отклоняется с понятной ошибкой."""
        with pytest.raises(TemplateImportError) as exc:
            detect_and_import(gadget.encode("utf-8"), "evil.json.jinja")

        assert exc.value.key == "serverError.importJinjaUnsafe"

    def test_function_globals_do_not_leak(self):
        """Часть гаджетов песочница не роняет, а обнуляет — уходит пустота.

        Обычный Environment подставил бы сюда словарь модулей.
        """
        jinja_text = """{
    "device_type": "test",
    "device": {
        "name": "{{ lipsum.__globals__ }}{{ cycler.__init__ }}{{ range.__self__ }}",
        "id": "test", "groups": [], "channels": [], "parameters": {}, "translations": {}
    }
}"""
        result = detect_and_import(jinja_text.encode("utf-8"), "probe.json.jinja")

        assert result["device_info"]["name"] == ""

    def test_list_append_still_imports(self):
        """Накопление в список работает — на нём держится боевой wb-mcm8.

        Страховка от «ужесточения» до ImmutableSandboxedEnvironment.
        """
        jinja_text = """{% set names = [] %}
{% for i in range(1, 3) %}{% set _ = names.append("Ch " ~ i) %}{% endfor %}
{
    "device_type": "test",
    "device": {
        "name": "Test", "id": "test", "groups": [],
        "channels": [
            {% for n in names -%}
            {"name": "{{ n }}", "address": {{ loop.index0 }}, "reg_type": "holding",
             "type": "value", "format": "u16", "group": "general"}{% if not loop.last %},{% endif %}
            {% endfor -%}
        ],
        "parameters": {}, "translations": {}
    }
}"""
        result = detect_and_import(jinja_text.encode("utf-8"), "template.json.jinja")

        assert [r["name"] for r in result["registers"]] == ["Ch 1", "Ch 2"]

    def test_oversized_jinja_rejected(self):
        """Слишком крупный исходник не уходит в рендер."""
        oversized = "{% raw %}" + "x" * MAX_JINJA_SOURCE_CHARS + "{% endraw %}"

        with pytest.raises(TemplateImportError) as exc:
            detect_and_import(oversized.encode("utf-8"), "big.json.jinja")

        assert exc.value.key == "serverError.importJinjaTooLarge"
        # В сообщении мегабайты, а не «1024 КБ»
        assert exc.value.params["max"] == 1

    def test_large_plain_json_not_limited(self):
        """Лимит не задевает обычный JSON — в wb-mqtt-serial есть шаблоны до 1.8 МБ."""
        template = {
            "device_type": "big-device",
            "device": {
                "name": "Big", "id": "big", "groups": [],
                "channels": [{
                    "name": "Ch", "address": 0, "reg_type": "holding",
                    "type": "value", "format": "u16", "group": "general",
                    "description": "y" * (MAX_JINJA_SOURCE_CHARS + 1000),
                }],
                "parameters": {}, "translations": {},
            },
        }
        payload = json.dumps(template).encode("utf-8")
        assert len(payload) > MAX_JINJA_SOURCE_CHARS

        result = detect_and_import(payload, "big.json")

        assert len(result["registers"]) == 1


class TestImportValidation:
    """Тесты валидации входного JSON."""

    def test_invalid_json_raises(self):
        """Не-шаблон отклоняется с ключом локализации."""
        with pytest.raises(TemplateImportError) as exc:
            import_template({"name": "package.json", "version": "1.0.0"})

        assert exc.value.key == "serverError.importNotTemplate"

    def test_empty_dict_raises(self):
        """Пустой dict — не шаблон."""
        with pytest.raises(TemplateImportError) as exc:
            import_template({})

        assert exc.value.key == "serverError.importNotTemplate"

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

    def test_readonly_channel_roundtrip(self, minimal_template):
        """readonly (без подчёркивания) у канала не теряется при import → build."""
        from models import BuildRequest, DeviceInfo, Register, RegisterGroup
        from template_builder import build_template

        imported = import_template(minimal_template)
        request = BuildRequest(
            device_info=DeviceInfo(**imported["device_info"]),
            registers=[Register(**r) for r in imported["registers"]],
            groups=[RegisterGroup(**g) for g in imported["groups"]],
        )
        built = build_template(request)

        channel = built["device"]["channels"][0]
        assert channel.get("readonly") is True

    def test_readonly_parameter_roundtrip(self):
        """readonly у параметра не теряется при import → build."""
        from models import BuildRequest, DeviceInfo, Register, RegisterGroup
        from template_builder import build_template

        template = {
            "device_type": "test-device",
            "title": "test_template_title",
            "device": {
                "name": "Test Device",
                "id": "test-device",
                "groups": [{"title": "Main", "id": "main"}],
                "channels": [],
                "parameters": {
                    "serial": {
                        "title": "Serial Number",
                        "address": 10,
                        "reg_type": "input",
                        "group": "main",
                        "order": 1,
                        "readonly": True,
                    }
                },
                "translations": {},
            },
        }

        imported = import_template(template)
        reg = imported["registers"][0]
        assert reg["readonly"] is True

        request = BuildRequest(
            device_info=DeviceInfo(**imported["device_info"]),
            registers=[Register(**r) for r in imported["registers"]],
            groups=[RegisterGroup(**g) for g in imported["groups"]],
        )
        built = build_template(request)

        param = built["device"]["parameters"]["serial"]
        assert param.get("readonly") is True


class TestJinjaErrorsAreDiagnostic:
    """Ошибка в самом шаблоне доходит до автора текстом, а не общей фразой.

    Два последних теста стерегут порядок except-веток: SecurityError и
    TemplateNotFound — подклассы TemplateError и должны ловиться до общей.
    """

    def test_syntax_error_reaches_author(self):
        broken = b'{% for i in range(3) %}{"device_type": "x"}'

        with pytest.raises(TemplateImportError) as exc:
            detect_and_import(broken, "broken.json.jinja")

        assert exc.value.key == "serverError.importJinjaErrorLine"
        assert "endfor" in exc.value.params["error"]
        assert exc.value.params["line"] == 1

    def test_undefined_attribute_reaches_author(self):
        template = b'{% set d = {} %}{"device_type": "{{ d.missing.deep }}"}'

        with pytest.raises(TemplateImportError) as exc:
            detect_and_import(template, "undef.json.jinja")

        assert "has no attribute" in exc.value.params["error"]

    def test_sandbox_resource_limit_is_not_silent(self):
        """`range` больше MAX_RANGE даёт OverflowError, а он не TemplateError.

        Без своей ветки такой шаблон уходил бы в общий except немым 422 плюс
        трейсбеком в логе — регресс, который вносит сама песочница.
        """
        with pytest.raises(TemplateImportError) as exc:
            detect_and_import(b"{% for i in range(10000000) %}{}{% endfor %}", "big.json.jinja")

        assert exc.value.key == "serverError.importJinjaLimit"
        assert "MAX_RANGE" in exc.value.params["error"]

    def test_sandbox_branch_not_shadowed(self):
        """SecurityError даёт свой ключ, а не общий диагностический."""
        with pytest.raises(TemplateImportError) as exc:
            detect_and_import(b"{{ cycler.__init__.__globals__.os }}", "evil.json.jinja")

        assert exc.value.key == "serverError.importJinjaUnsafe"

    def test_include_branch_not_shadowed(self):
        """Шаблон с {% include %} по-прежнему разбирается, а не падает ошибкой."""
        text = ('{% with device_id = "dev-1", title_en = "Dev" %}'
                '{% include "common.json.jinja" %}{% endwith %}')

        result = detect_and_import(text.encode("utf-8"), "with-include.json.jinja")

        assert result["device_info"]["id"] == "dev-1"
        assert result["include"] == "common.json.jinja"


class TestJsonComments:
    """Комментарии // вычищаются, а пустые строки не делают разбор квадратичным."""

    def test_line_and_inline_comments_stripped(self):
        # Inline // стрипер поддерживает только после числа/true/false/null
        text = """{
    // ведущий комментарий
    "device_type": "test",
    "device": {
        "id": "t",
        "channels": [{"name": "Ch", "address": 0, "reg_type": "holding",
                      "type": "value", "format": "u16", "group": "general",
                      "enabled": true // inline после булева
                      }],
        "parameters": {}, "translations": {}
    }
}"""
        result = detect_and_import(text.encode("utf-8"), "with-comments.json")

        assert result["device_info"]["id"] == "t"
        assert len(result["registers"]) == 1

    def test_many_blank_lines_import_fast(self):
        """Регресс ReDoS: прежний `^\\s*//` на 100 КБ пустых строк занимал ~13 с."""
        payload = ('{"device_type": "x", "device": {"id": "x"}}'
                   + "\n" * (100 * 1024)).encode("utf-8")

        started = time.monotonic()
        result = detect_and_import(payload, "sparse.json")
        elapsed = time.monotonic() - started

        assert result["device_info"]["id"] == "x"
        assert elapsed < 3.0, f"разбор занял {elapsed:.1f} с — регулярка снова квадратична"


class TestAddressNotation:
    """Импорт сохраняет запись адреса — hex не разворачивается в число."""

    @pytest.mark.parametrize("address", ["0xff", "0x012F0000", "109:0:1"])
    def test_notation_survives_import(self, channel_template, address):
        """Разворот в число вывел бы четырёхбайтный код за 16-битный диапазон."""
        imported = import_template(channel_template({"address": address}))
        assert imported["registers"][0]["address"] == address

    @pytest.mark.parametrize("address,expected", [(255, 255), ("255", 255)])
    def test_decimal_becomes_number(self, channel_template, address, expected):
        imported = import_template(channel_template({"address": address}))
        assert imported["registers"][0]["address"] == expected


class TestFieldNotation:
    """Числовые поля — запятая и точка дают число, hex остаётся там, где схема его разрешает."""

    @pytest.mark.parametrize("field,raw,expected", [
        ("scale", "0,5", 0.5),
        ("scale", "0.5", 0.5),
        ("scale", 0.5, 0.5),
        ("min", "1,5", 1.5),
        ("max", "1,5", 1.5),
        ("round_to", "1,5", 1.5),
    ])
    def test_comma_and_dot_become_number(self, channel_template, field, raw, expected):
        """Строковое значение приводится к числу — иначе шаблон не собрать обратно."""
        imported = import_template(channel_template({field: raw}))
        assert imported["registers"][0][field] == expected

    @pytest.mark.parametrize("field,value", [
        ("error_value", "0xFFFF"),   # hex-запись стоит 333 раза в 38 шаблонах драйвера
        ("error_value", 65535),      # то же поле числом, 1602 раза
        ("on_value", "0x0101"),      # config-somfy-sdn.json
        ("off_value", 1),
        ("min", 0),
    ])
    def test_both_notations_accepted(self, channel_template, field, value):
        """Схема драйвера разрешает в этих полях и число, и hex-строку."""
        imported = import_template(channel_template({field: value}))
        reg = imported["registers"][0]
        assert reg[field] == value
        Register(**reg)   # модель редактора обязана принять обе записи

    @pytest.mark.parametrize("written,expected", [("0xff", 255), ("0x10", 16), ("5", 5)])
    def test_hex_limit_becomes_number(self, channel_template, written, expected):
        """Лимит редактор держит числом — hex из шаблона разворачивается при импорте."""
        imported = import_template(channel_template({"max": written}))
        assert imported["registers"][0]["max"] == expected

    def test_serial_int_string_is_trimmed(self, channel_template):
        """Пробелы по краям приезжают из копипасты даташита."""
        imported = import_template(channel_template({"error_value": " 0x7FFF "}))
        assert imported["registers"][0]["error_value"] == "0x7FFF"

    def test_giant_hex_limit_is_dropped(self, channel_template):
        """int из hex не ограничен лимитом CPython, а сериализация ответа ограничена."""
        imported = import_template(channel_template({"max": "0x" + "F" * 3600}))
        assert "max" not in imported["registers"][0]

    def test_unparsable_limit_is_dropped(self, channel_template):
        """Регистр важнее одного поля — остальные поля должны доехать."""
        imported = import_template(channel_template({"max": "мин", "scale": 0.1}))
        reg = imported["registers"][0]
        assert "max" not in reg
        assert reg["scale"] == 0.1
