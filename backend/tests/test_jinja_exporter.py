"""Тесты для jinja_exporter — экспорт JSON-шаблона в .json.jinja."""

import json
import os

import jinja2
import pytest

from jinja_exporter import (
    build_jinja_template,
    _detect_channel_patterns,
    _detect_group_patterns,
    _detect_param_patterns,
)


class TestNoPatterns:
    """Без паттернов — возвращается обычный JSON."""

    def test_simple_template(self):
        template = {
            "device_type": "test",
            "title": "test_title",
            "device": {
                "name": "Test",
                "id": "test",
                "groups": [{"title": "Main", "id": "main"}],
                "channels": [
                    {"name": "Voltage", "address": 0, "reg_type": "input", "type": "value", "format": "float", "group": "main"},
                    {"name": "Current", "address": 2, "reg_type": "input", "type": "value", "format": "float", "group": "main"},
                ],
                "parameters": {},
                "translations": {},
            },
        }
        result = build_jinja_template(template)
        parsed = json.loads(result)
        assert parsed["device_type"] == "test"
        assert len(parsed["device"]["channels"]) == 2

    def test_single_channel_not_pattern(self):
        """Один канал — не паттерн."""
        channels = [
            {"name": "Ch 1", "address": 0, "reg_type": "holding", "type": "value", "format": "u16", "group": "main"},
        ]
        patterns = _detect_channel_patterns(channels)
        assert len(patterns) == 0

    def test_non_sequential_numbers(self):
        """Непоследовательные номера — не паттерн."""
        channels = [
            {"name": "Ch 1", "address": 0, "reg_type": "holding", "type": "value", "format": "u16", "group": "main"},
            {"name": "Ch 3", "address": 2, "reg_type": "holding", "type": "value", "format": "u16", "group": "main"},
        ]
        patterns = _detect_channel_patterns(channels)
        assert len(patterns) == 0

    def test_different_fields_not_pattern(self):
        """Разные поля — не паттерн."""
        channels = [
            {"name": "Ch 1", "address": 0, "reg_type": "holding", "type": "value", "format": "u16", "group": "main"},
            {"name": "Ch 2", "address": 1, "reg_type": "input", "type": "value", "format": "u16", "group": "main"},
        ]
        patterns = _detect_channel_patterns(channels)
        assert len(patterns) == 0


class TestSimpleChannelPattern:
    """Обнаружение простого паттерна каналов (число в конце)."""

    def _make_template(self, count=4, base_addr=100, step=1):
        channels = []
        for i in range(1, count + 1):
            channels.append({
                "name": f"Ch {i}",
                "address": base_addr + (i - 1) * step,
                "reg_type": "holding",
                "type": "value",
                "format": "u16",
                "group": "main",
            })
        return {
            "device_type": "test",
            "title": "test_title",
            "device": {
                "name": "Test",
                "id": "test",
                "groups": [{"title": "Main", "id": "main"}],
                "channels": channels,
                "parameters": {},
                "translations": {},
            },
        }

    def test_pattern_detected(self):
        template = self._make_template(4, 100, 1)
        patterns = _detect_channel_patterns(template["device"]["channels"])
        assert len(patterns) == 1
        assert patterns[0]["count"] == 4
        assert patterns[0]["base_address"] == 100
        assert patterns[0]["address_step"] == 1

    def test_two_channels_detected(self):
        """Два канала — минимальный паттерн (порог = 2)."""
        channels = [
            {"name": "Ch 1", "address": 0, "reg_type": "holding", "type": "value", "format": "u16", "group": "main"},
            {"name": "Ch 2", "address": 1, "reg_type": "holding", "type": "value", "format": "u16", "group": "main"},
        ]
        patterns = _detect_channel_patterns(channels)
        assert len(patterns) == 1
        assert patterns[0]["count"] == 2

    def test_jinja_output_contains_for(self):
        template = self._make_template(4, 100, 1)
        result = build_jinja_template(template)
        assert "{% for" in result
        assert "{% set" in result
        assert "CH_NUMBER" in result

    def test_jinja_renders_back_to_valid_json(self):
        """Jinja-результат после рендеринга должен быть валидным JSON."""
        template = self._make_template(4, 100, 1)
        jinja_text = build_jinja_template(template)
        env = jinja2.Environment(undefined=jinja2.Undefined)
        rendered = env.from_string(jinja_text).render()
        parsed = json.loads(rendered)
        assert len(parsed["device"]["channels"]) == 4
        assert parsed["device"]["channels"][0]["name"] == "Ch 1"
        assert parsed["device"]["channels"][3]["name"] == "Ch 4"


class TestMiddleNumberPattern:
    """Обнаружение паттерна с числом в середине имени."""

    def test_input_n_state(self):
        """'Input 1 state', 'Input 2 state' — число в середине."""
        channels = [
            {"name": "Input 1 state", "address": 0, "reg_type": "discrete", "type": "value", "format": "u16", "group": "g"},
            {"name": "Input 2 state", "address": 1, "reg_type": "discrete", "type": "value", "format": "u16", "group": "g"},
        ]
        patterns = _detect_channel_patterns(channels)
        assert len(patterns) == 1
        assert patterns[0]["count"] == 2
        assert patterns[0]["name_prefix"] == "Input "
        assert patterns[0]["name_suffix"] == " state"

    def test_middle_number_three_channels(self):
        """Три канала с числом в середине."""
        channels = [
            {"name": "Temperature DS18B20 Input 1", "address": 7, "reg_type": "input", "type": "value", "format": "s16", "group": "g"},
            {"name": "Temperature DS18B20 Input 2", "address": 8, "reg_type": "input", "type": "value", "format": "s16", "group": "g"},
            {"name": "Temperature DS18B20 Input 3", "address": 9, "reg_type": "input", "type": "value", "format": "s16", "group": "g"},
        ]
        patterns = _detect_channel_patterns(channels)
        assert len(patterns) == 1
        assert patterns[0]["count"] == 3
        assert "DS18B20" in patterns[0]["name_prefix"]
        assert patterns[0]["name_suffix"] == ""

    def test_model_number_not_confused(self):
        """Числа в названии модели (DS18B20) не путаются с индексом."""
        channels = [
            {"name": "DS18B20 Sensor 1 OK", "address": 16, "reg_type": "discrete", "type": "value", "format": "u16", "group": "g"},
            {"name": "DS18B20 Sensor 2 OK", "address": 17, "reg_type": "discrete", "type": "value", "format": "u16", "group": "g"},
        ]
        patterns = _detect_channel_patterns(channels)
        assert len(patterns) == 1
        p = patterns[0]
        assert p["name_prefix"] == "DS18B20 Sensor "
        assert p["name_suffix"] == " OK"

    def test_middle_number_jinja_renders(self):
        """Jinja с числом в середине рендерится корректно."""
        channels = [
            {"name": "Input 1 state", "address": 0, "reg_type": "discrete", "type": "value", "format": "u16", "group": "g"},
            {"name": "Input 2 state", "address": 1, "reg_type": "discrete", "type": "value", "format": "u16", "group": "g"},
            {"name": "Input 3 state", "address": 2, "reg_type": "discrete", "type": "value", "format": "u16", "group": "g"},
        ]
        template = {
            "device_type": "test",
            "title": "test_title",
            "device": {
                "name": "Test",
                "id": "test",
                "groups": [],
                "channels": channels,
                "parameters": {},
                "translations": {},
            },
        }
        jinja_text = build_jinja_template(template)
        assert "{% for" in jinja_text
        assert "Input {{ i }} state" in jinja_text

        env = jinja2.Environment(undefined=jinja2.Undefined)
        rendered = env.from_string(jinja_text).render()
        parsed = json.loads(rendered)
        assert len(parsed["device"]["channels"]) == 3
        assert parsed["device"]["channels"][0]["name"] == "Input 1 state"
        assert parsed["device"]["channels"][2]["name"] == "Input 3 state"

    def test_multiple_middle_patterns(self):
        """Несколько разных паттернов с числом в середине."""
        channels = [
            {"name": "Input 1 state", "address": 0, "reg_type": "discrete", "type": "value", "format": "u16", "group": "g"},
            {"name": "Input 2 state", "address": 1, "reg_type": "discrete", "type": "value", "format": "u16", "group": "g"},
            {"name": "Input 1 counter", "address": 277, "reg_type": "input", "type": "value", "format": "u16", "group": "g"},
            {"name": "Input 2 counter", "address": 278, "reg_type": "input", "type": "value", "format": "u16", "group": "g"},
        ]
        patterns = _detect_channel_patterns(channels)
        assert len(patterns) == 2
        var_names = {p["var_name"] for p in patterns}
        assert "INPUT_STATE_NUMBER" in var_names
        assert "INPUT_COUNTER_NUMBER" in var_names


class TestAddressArithmetic:
    """Тесты арифметики адресов."""

    def test_step_1(self):
        channels = [
            {"name": f"Input {i}", "address": 100 + i - 1, "reg_type": "input", "type": "value", "format": "u16", "group": "g"}
            for i in range(1, 5)
        ]
        patterns = _detect_channel_patterns(channels)
        assert len(patterns) == 1
        assert patterns[0]["address_step"] == 1

    def test_step_2(self):
        channels = [
            {"name": f"Sensor {i}", "address": 100 + (i - 1) * 2, "reg_type": "input", "type": "value", "format": "float", "group": "g"}
            for i in range(1, 5)
        ]
        patterns = _detect_channel_patterns(channels)
        assert len(patterns) == 1
        assert patterns[0]["address_step"] == 2

    def test_non_arithmetic_addresses(self):
        """Непостоянный шаг адресов — не паттерн."""
        channels = [
            {"name": "Ch 1", "address": 0, "reg_type": "holding", "type": "value", "format": "u16", "group": "g"},
            {"name": "Ch 2", "address": 5, "reg_type": "holding", "type": "value", "format": "u16", "group": "g"},
            {"name": "Ch 3", "address": 7, "reg_type": "holding", "type": "value", "format": "u16", "group": "g"},
        ]
        patterns = _detect_channel_patterns(channels)
        assert len(patterns) == 0


class TestVarNameGeneration:
    """Генерация имён переменных Jinja."""

    def test_leading_digit_prefixed(self):
        """Переменная не может начинаться с цифры."""
        channels = [
            {"name": "1-Wire Input 1", "address": 16, "reg_type": "discrete", "type": "value", "format": "u16", "group": "g"},
            {"name": "1-Wire Input 2", "address": 17, "reg_type": "discrete", "type": "value", "format": "u16", "group": "g"},
        ]
        patterns = _detect_channel_patterns(channels)
        assert len(patterns) == 1
        assert not patterns[0]["var_name"][0].isdigit()

    def test_unique_var_names(self):
        """Разные паттерны получают разные имена переменных."""
        channels = [
            {"name": "Input 1 state", "address": 0, "reg_type": "discrete", "type": "value", "format": "u16", "group": "g"},
            {"name": "Input 2 state", "address": 1, "reg_type": "discrete", "type": "value", "format": "u16", "group": "g"},
            {"name": "Output 1 value", "address": 100, "reg_type": "holding", "type": "value", "format": "u16", "group": "g"},
            {"name": "Output 2 value", "address": 101, "reg_type": "holding", "type": "value", "format": "u16", "group": "g"},
        ]
        patterns = _detect_channel_patterns(channels)
        var_names = [p["var_name"] for p in patterns]
        assert len(var_names) == len(set(var_names))


class TestMixedChannels:
    """Шаблон с паттернами и обычными каналами одновременно."""

    def test_mixed(self):
        channels = [
            {"name": "Status", "address": 0, "reg_type": "input", "type": "value", "format": "u16", "group": "main"},
        ]
        for i in range(1, 5):
            channels.append({
                "name": f"Ch {i}",
                "address": 10 + i - 1,
                "reg_type": "holding",
                "type": "value",
                "format": "u16",
                "group": "main",
            })
        channels.append(
            {"name": "Error", "address": 99, "reg_type": "input", "type": "value", "format": "u16", "group": "main"},
        )

        template = {
            "device_type": "test",
            "title": "test_title",
            "device": {
                "name": "Test",
                "id": "test",
                "groups": [{"title": "Main", "id": "main"}],
                "channels": channels,
                "parameters": {},
                "translations": {},
            },
        }

        result = build_jinja_template(template)
        assert "{% for" in result
        assert '"Status"' in result
        assert '"Error"' in result


class TestEndToEndJinja:
    """Интеграционные тесты: экспорт → Jinja рендер → валидный JSON."""

    def test_wb_m1w2_like_template(self):
        """Шаблон типа WB-M1W2: 2 входа, несколько типов каналов на каждый."""
        channels = []
        for i in range(1, 3):  # 2 входа
            channels.extend([
                {"name": f"Input {i} state", "address": i - 1, "reg_type": "discrete", "type": "value", "format": "u16", "group": "g_io"},
                {"name": f"Input {i} counter", "address": 277 + i - 1, "reg_type": "input", "type": "value", "format": "u16", "group": "g_io"},
                {"name": f"Short press counter Input {i}", "address": 464 + i - 1, "reg_type": "input", "type": "value", "format": "u16", "group": "g_io"},
                {"name": f"Temperature DS18B20 Input {i}", "address": 7 + i - 1, "reg_type": "input", "type": "value", "format": "s16", "group": "g_env", "units": "deg C", "scale": 0.0625},
            ])
        template = {
            "device_type": "test",
            "title": "test_title",
            "device": {
                "name": "Test M1W2",
                "id": "test-m1w2",
                "groups": [],
                "channels": channels,
                "parameters": {},
                "translations": {},
            },
        }

        jinja_text = build_jinja_template(template)
        assert "{% for" in jinja_text
        assert "{% set" in jinja_text

        env = jinja2.Environment(undefined=jinja2.Undefined)
        rendered = env.from_string(jinja_text).render()
        parsed = json.loads(rendered)
        assert len(parsed["device"]["channels"]) == 8
        names = [ch["name"] for ch in parsed["device"]["channels"]]
        assert "Input 1 state" in names
        assert "Input 2 state" in names
        assert "Temperature DS18B20 Input 1" in names
        assert "Temperature DS18B20 Input 2" in names


# =====================================================================
# Новые тесты: шаблонизируемые поля, группы, параметры
# =====================================================================


class TestChannelsWithTemplatedGroup:
    """Каналы с варьирующимся полем group (как MCM8)."""

    def test_varying_group_detected(self):
        """Каналы Input 1 freq...Input 4 freq с group=gg_in1_channels...gg_in4_channels."""
        channels = [
            {
                "name": f"Input {i} freq",
                "address": 40 + (i - 1) * 2,
                "reg_type": "input",
                "type": "value",
                "format": "u32",
                "group": f"gg_in{i}_channels",
            }
            for i in range(1, 5)
        ]
        patterns = _detect_channel_patterns(channels)
        assert len(patterns) == 1
        p = patterns[0]
        assert p["count"] == 4
        assert p["start_num"] == 1
        assert p["base_address"] == 40
        assert p["address_step"] == 2
        assert "group" in p["templated_fields"]

    def test_varying_group_renders_jinja(self):
        """Каналы с варьирующимся group рендерятся в валидный JSON."""
        channels = [
            {
                "name": f"Input {i} freq",
                "address": 40 + (i - 1) * 2,
                "reg_type": "input",
                "type": "value",
                "format": "u32",
                "group": f"gg_in{i}_channels",
            }
            for i in range(1, 5)
        ]
        template = {
            "device_type": "test",
            "title": "test_title",
            "device": {
                "name": "Test",
                "id": "test",
                "groups": [],
                "channels": channels,
                "parameters": {},
                "translations": {},
            },
        }
        jinja_text = build_jinja_template(template)
        assert "{% for" in jinja_text
        assert "gg_in{{ i }}_channels" in jinja_text

        env = jinja2.Environment(undefined=jinja2.Undefined)
        rendered = env.from_string(jinja_text).render()
        parsed = json.loads(rendered)
        assert len(parsed["device"]["channels"]) == 4
        assert parsed["device"]["channels"][0]["group"] == "gg_in1_channels"
        assert parsed["device"]["channels"][3]["group"] == "gg_in4_channels"


class TestChannelsWithTemplatedCondition:
    """Каналы с варьирующимся полем condition."""

    def test_varying_condition_detected(self):
        """Каналы с condition=in1_mode==1...in4_mode==1."""
        channels = [
            {
                "name": f"Input {i} Single Press",
                "address": 464 + i - 1,
                "reg_type": "input",
                "type": "value",
                "format": "u16",
                "group": f"gg_in{i}_channels",
                "condition": f"in{i}_mode==1",
            }
            for i in range(1, 5)
        ]
        patterns = _detect_channel_patterns(channels)
        assert len(patterns) == 1
        p = patterns[0]
        assert p["count"] == 4
        assert "condition" in p["templated_fields"]
        assert "group" in p["templated_fields"]

    def test_varying_condition_renders_jinja(self):
        """Каналы с варьирующимся condition и group рендерятся в Jinja."""
        channels = [
            {
                "name": f"Input {i} Single Press",
                "address": 464 + i - 1,
                "reg_type": "input",
                "type": "value",
                "format": "u16",
                "group": f"gg_in{i}_channels",
                "condition": f"in{i}_mode==1",
            }
            for i in range(1, 5)
        ]
        template = {
            "device_type": "test",
            "title": "test",
            "device": {
                "name": "Test",
                "id": "test",
                "groups": [],
                "channels": channels,
                "parameters": {},
                "translations": {},
            },
        }
        jinja_text = build_jinja_template(template)
        assert "in{{ i }}_mode==1" in jinja_text

        env = jinja2.Environment(undefined=jinja2.Undefined)
        rendered = env.from_string(jinja_text).render()
        parsed = json.loads(rendered)
        assert len(parsed["device"]["channels"]) == 4
        assert parsed["device"]["channels"][0]["condition"] == "in1_mode==1"
        assert parsed["device"]["channels"][2]["condition"] == "in3_mode==1"


class TestGroupPatterns:
    """Паттерны в группах."""

    def test_simple_group_pattern(self):
        """Группы g_in1...g_in4 с title Input 1...Input 4."""
        groups = [
            {"title": f"Input {i}", "id": f"g_in{i}"}
            for i in range(1, 5)
        ]
        patterns = _detect_group_patterns(groups)
        assert len(patterns) == 1
        p = patterns[0]
        assert p["count"] == 4
        assert p["start_num"] == 1
        assert "title" in p["templated_fields"]

    def test_subgroup_pattern(self):
        """Подгруппы gg_in1_press_params...gg_in4_press_params с parent g_in1...g_in4."""
        groups = [
            {
                "title": "Press Parameters",
                "id": f"gg_in{i}_press_params",
                "group": f"g_in{i}",
            }
            for i in range(1, 5)
        ]
        patterns = _detect_group_patterns(groups)
        assert len(patterns) == 1
        p = patterns[0]
        assert p["count"] == 4
        assert "group" in p["templated_fields"]

    def test_group_pattern_renders_jinja(self):
        """Группы-паттерны рендерятся в Jinja с for-циклом."""
        groups = [
            {"title": f"Input {i}", "id": f"g_in{i}"}
            for i in range(1, 5)
        ]
        # Добавляем статическую группу
        groups.append({"title": "General", "id": "g_general"})

        template = {
            "device_type": "test",
            "title": "test",
            "device": {
                "name": "Test",
                "id": "test",
                "groups": groups,
                "channels": [
                    {"name": "Status", "address": 0, "reg_type": "input", "type": "value", "format": "u16", "group": "g_general"},
                ],
                "parameters": {},
                "translations": {},
            },
        }
        jinja_text = build_jinja_template(template)
        assert "{% for" in jinja_text
        assert "g_in{{ i }}" in jinja_text

        env = jinja2.Environment(undefined=jinja2.Undefined)
        rendered = env.from_string(jinja_text).render()
        parsed = json.loads(rendered)
        assert len(parsed["device"]["groups"]) == 5
        assert parsed["device"]["groups"][0]["id"] == "g_in1"
        assert parsed["device"]["groups"][3]["id"] == "g_in4"
        assert parsed["device"]["groups"][4]["id"] == "g_general"


class TestParamPatterns:
    """Паттерны в параметрах."""

    def test_simple_param_pattern(self):
        """Параметры in1_mode...in4_mode с арифметической прогрессией адресов."""
        params = {}
        for i in range(1, 5):
            params[f"in{i}_mode"] = {
                "title": "Mode",
                "address": 9 + i - 1,
                "reg_type": "holding",
                "enum": [0, 1],
                "default": 0,
                "group": f"g_in{i}",
                "order": 1,
            }
        patterns = _detect_param_patterns(params)
        assert len(patterns) == 1
        p = patterns[0]
        assert p["count"] == 4
        assert p["start_num"] == 1
        assert p["base_address"] == 9
        assert p["address_step"] == 1
        assert "group" in p["templated_fields"]

    def test_param_pattern_with_condition(self):
        """Параметры с варьирующимся condition."""
        params = {}
        for i in range(1, 5):
            params[f"in{i}_lp_hold_time"] = {
                "title": "Long Press Time",
                "address": 1100 + i - 1,
                "reg_type": "holding",
                "default": 1000,
                "min": 500,
                "max": 5000,
                "group": f"gg_in{i}_press_params",
                "condition": f"in{i}_mode==1",
                "order": 1,
            }
        patterns = _detect_param_patterns(params)
        assert len(patterns) == 1
        p = patterns[0]
        assert "group" in p["templated_fields"]
        assert "condition" in p["templated_fields"]

    def test_param_pattern_renders_jinja(self):
        """Параметры-паттерны рендерятся в Jinja с for-циклом."""
        params = {}
        for i in range(1, 5):
            params[f"in{i}_mode"] = {
                "title": "Mode",
                "address": 9 + i - 1,
                "reg_type": "holding",
                "enum": [0, 1],
                "default": 0,
                "group": f"g_in{i}",
                "order": 1,
            }
        # Статический параметр
        params["baud_rate"] = {
            "title": "Baud rate",
            "address": 110,
            "reg_type": "holding",
            "enum": [96, 192],
            "default": 96,
            "group": "g_general",
            "order": 1,
        }

        template = {
            "device_type": "test",
            "title": "test",
            "device": {
                "name": "Test",
                "id": "test",
                "groups": [],
                "channels": [
                    {"name": "Status", "address": 0, "reg_type": "input", "type": "value", "format": "u16", "group": "g_general"},
                ],
                "parameters": params,
                "translations": {},
            },
        }
        jinja_text = build_jinja_template(template)
        assert "{% for" in jinja_text
        assert "in{{ i }}_mode" in jinja_text

        env = jinja2.Environment(undefined=jinja2.Undefined)
        rendered = env.from_string(jinja_text).render()
        parsed = json.loads(rendered)
        assert "in1_mode" in parsed["device"]["parameters"]
        assert "in4_mode" in parsed["device"]["parameters"]
        assert "baud_rate" in parsed["device"]["parameters"]
        assert parsed["device"]["parameters"]["in1_mode"]["address"] == 9
        assert parsed["device"]["parameters"]["in4_mode"]["address"] == 12


class TestAllSectionsIntegration:
    """Интеграционный тест: все три секции с паттернами → рендер → валидный JSON."""

    def test_all_sections_with_patterns(self):
        """Группы + каналы + параметры с одинаковыми count/start_num."""
        count = 4

        groups = []
        for i in range(1, count + 1):
            groups.append({"title": f"Input {i}", "id": f"g_in{i}"})
            groups.append({
                "title": "Channels",
                "id": f"gg_in{i}_channels",
                "group": f"g_in{i}",
            })
        groups.append({"title": "General", "id": "g_general"})

        channels = []
        for i in range(1, count + 1):
            channels.append({
                "name": f"Input {i} freq",
                "address": 40 + (i - 1) * 2,
                "reg_type": "input",
                "type": "value",
                "format": "u32",
                "group": f"gg_in{i}_channels",
                "condition": f"in{i}_mode==0",
            })
        channels.append({
            "name": "Reset all counters",
            "address": 100,
            "reg_type": "holding",
            "type": "pushbutton",
            "group": "g_general",
        })

        params = {}
        for i in range(1, count + 1):
            params[f"in{i}_mode"] = {
                "title": "Mode",
                "address": 9 + i - 1,
                "reg_type": "holding",
                "enum": [0, 1],
                "default": 0,
                "group": f"g_in{i}",
                "order": 1,
            }
        params["baud_rate"] = {
            "title": "Baud rate",
            "address": 110,
            "reg_type": "holding",
            "default": 96,
            "group": "g_general",
        }

        template = {
            "device_type": "test-mcm",
            "title": "Test MCM",
            "device": {
                "name": "Test MCM",
                "id": "test-mcm",
                "groups": groups,
                "channels": channels,
                "parameters": params,
                "translations": {},
            },
        }

        jinja_text = build_jinja_template(template)

        # Проверяем наличие for-циклов
        assert "{% for" in jinja_text
        assert "{% set" in jinja_text

        # Рендерим
        env = jinja2.Environment(undefined=jinja2.Undefined)
        rendered = env.from_string(jinja_text).render()
        parsed = json.loads(rendered)

        # Проверяем количества
        assert len(parsed["device"]["groups"]) == count * 2 + 1  # 4*2 подгруппы + General
        assert len(parsed["device"]["channels"]) == count + 1  # 4 + Reset
        assert len(parsed["device"]["parameters"]) == count + 1  # 4 + baud_rate

        # Проверяем содержимое
        assert parsed["device"]["groups"][0]["id"] == "g_in1"
        group_ids = [g["id"] for g in parsed["device"]["groups"]]
        assert "g_general" in group_ids

        assert parsed["device"]["channels"][0]["name"] == "Input 1 freq"
        assert parsed["device"]["channels"][0]["condition"] == "in1_mode==0"
        assert parsed["device"]["channels"][0]["group"] == "gg_in1_channels"

        assert parsed["device"]["parameters"]["in1_mode"]["address"] == 9
        assert parsed["device"]["parameters"]["in1_mode"]["group"] == "g_in1"
        assert "baud_rate" in parsed["device"]["parameters"]


class TestTwoDifferentPatterns:
    """Два разных паттерна (INPUTS + ENCODERS) с разными count."""

    def test_two_patterns_different_count(self):
        """8 входов + 3 энкодера — два отдельных паттерна с разными переменными."""
        channels = []
        # 8 входов
        for i in range(1, 9):
            channels.append({
                "name": f"Input {i} freq",
                "address": 40 + (i - 1) * 2,
                "reg_type": "input",
                "type": "value",
                "format": "u32",
                "group": f"gg_in{i}_channels",
            })
        # 3 энкодера
        for i in range(1, 4):
            channels.append({
                "name": f"Encoder {i} position",
                "address": 368 + (i - 1) * 2,
                "reg_type": "holding",
                "type": "value",
                "format": "s32",
                "group": "gg_encoder_channels",
            })

        patterns = _detect_channel_patterns(channels)
        assert len(patterns) == 2

        # Проверяем что count разный
        counts = sorted([p["count"] for p in patterns])
        assert counts == [3, 8]

        # Проверяем что var_name разные
        var_names = {p["var_name"] for p in patterns}
        assert len(var_names) == 2

    def test_two_patterns_render_jinja(self):
        """Два паттерна с разными count рендерятся корректно."""
        channels = []
        for i in range(1, 5):
            channels.append({
                "name": f"Input {i} freq",
                "address": 40 + (i - 1) * 2,
                "reg_type": "input",
                "type": "value",
                "format": "u32",
                "group": f"gg_in{i}_channels",
            })
        for i in range(1, 3):
            channels.append({
                "name": f"Encoder {i} position",
                "address": 368 + (i - 1) * 2,
                "reg_type": "holding",
                "type": "value",
                "format": "s32",
                "group": "gg_encoder_channels",
            })

        template = {
            "device_type": "test",
            "title": "test",
            "device": {
                "name": "Test",
                "id": "test",
                "groups": [],
                "channels": channels,
                "parameters": {},
                "translations": {},
            },
        }
        jinja_text = build_jinja_template(template)

        # Должно быть два {% set и два {% for
        assert jinja_text.count("{% set") == 2
        assert jinja_text.count("{% for") == 2

        env = jinja2.Environment(undefined=jinja2.Undefined)
        rendered = env.from_string(jinja_text).render()
        parsed = json.loads(rendered)
        assert len(parsed["device"]["channels"]) == 6
        assert parsed["device"]["channels"][0]["name"] == "Input 1 freq"
        assert parsed["device"]["channels"][4]["name"] == "Encoder 1 position"


class TestMCM8EndToEnd:
    """E2E тест: MCM8 оригинальный шаблон → развёрнутый JSON → build_jinja_template → рендер."""

    @pytest.fixture
    def mcm8_path(self):
        """Путь к оригинальному MCM8 шаблону."""
        # Ищем в tmp/ относительно корня backend (backend/tests/ → backend/ → tmp/)
        # В Docker: /app/tests/test_*.py → /app/ → /app/tmp/
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(base, "tmp", "config-wb-mcm8.json.jinja")
        if not os.path.exists(path):
            pytest.skip("Файл config-wb-mcm8.json.jinja не найден в tmp/")
        return path

    def _render_jinja_file(self, path: str) -> dict:
        """Рендерит Jinja-файл и возвращает parsed JSON."""
        with open(path) as f:
            jinja_text = f.read()
        env = jinja2.Environment(undefined=jinja2.Undefined)
        rendered = env.from_string(jinja_text).render()
        return json.loads(rendered)

    def test_mcm8_roundtrip(self, mcm8_path):
        """
        1. Читаем оригинальный MCM8 .json.jinja
        2. Рендерим → развёрнутый JSON
        3. Пропускаем через build_jinja_template() → Jinja-шаблон
        4. Рендерим результат → JSON
        5. Сравниваем количество каналов, параметров, групп
        6. Проверяем наличие {% for
        """
        # Шаг 1-2: рендерим оригинал
        original_parsed = self._render_jinja_file(mcm8_path)

        original_channels = original_parsed["device"]["channels"]
        original_params = original_parsed["device"]["parameters"]
        original_groups = original_parsed["device"]["groups"]

        # Шаг 3: пропускаем через build_jinja_template
        jinja_output = build_jinja_template(original_parsed)

        # Шаг 6: проверяем наличие for-циклов (паттерны обнаружены)
        assert "{% for" in jinja_output, (
            "build_jinja_template не обнаружил паттерны в MCM8 шаблоне"
        )
        assert "{% set" in jinja_output

        # Шаг 4: рендерим результат
        env = jinja2.Environment(undefined=jinja2.Undefined)
        rendered = env.from_string(jinja_output).render()
        result_parsed = json.loads(rendered)

        result_channels = result_parsed["device"]["channels"]
        result_params = result_parsed["device"]["parameters"]
        result_groups = result_parsed["device"]["groups"]

        # Шаг 5: сравниваем количества
        assert len(result_channels) == len(original_channels), (
            f"Количество каналов не совпадает: {len(result_channels)} != {len(original_channels)}"
        )
        assert len(result_params) == len(original_params), (
            f"Количество параметров не совпадает: {len(result_params)} != {len(original_params)}"
        )
        assert len(result_groups) == len(original_groups), (
            f"Количество групп не совпадает: {len(result_groups)} != {len(original_groups)}"
        )

        # Дополнительные проверки содержимого
        result_channel_names = {ch["name"] for ch in result_channels}
        original_channel_names = {ch["name"] for ch in original_channels}
        assert result_channel_names == original_channel_names, (
            f"Имена каналов не совпадают. "
            f"Отсутствуют: {original_channel_names - result_channel_names}. "
            f"Лишние: {result_channel_names - original_channel_names}"
        )

        assert set(result_params.keys()) == set(original_params.keys()), (
            f"Ключи параметров не совпадают"
        )
