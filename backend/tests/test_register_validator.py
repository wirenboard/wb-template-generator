"""Тесты для register_validator — валидация и авто-исправление регистров."""

import sys
from pathlib import Path

import pytest

# Добавляем backend/ в sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from models import Register
from register_validator import (
    Severity,
    auto_fix_and_validate,
    auto_fix_register,
    format_validation_errors,
    validate_register,
    validate_registers,
)

# --- Хелперы ---


def _reg(**kwargs) -> Register:
    """Создаёт Register с дефолтами для обязательных полей."""
    defaults = {"address": 0, "name": "Test Register"}
    defaults.update(kwargs)
    return Register(**defaults)


# ===================================================================
# Тесты auto_fix_register
# ===================================================================


class TestAutoFix:
    """Авто-исправление полей по маппингу синонимов."""

    def test_fix_format_uint16(self):
        raw = {"format": "uint16"}
        fixed, fixes = auto_fix_register(raw)
        assert fixed["format"] == "u16"
        assert len(fixes) == 1
        assert fixes[0].field == "format"

    @pytest.mark.parametrize("written,expected", [("0xff", 255), ("1,5", 1.5), ("100", 100)])
    def test_fix_limit_notation(self, written, expected):
        """Лимит от модели приходит и строкой — до pydantic разворачиваем в число."""
        fixed, fixes = auto_fix_register({"max": written})
        assert fixed["max"] == expected
        assert [f.field for f in fixes] == ["max"]

    def test_unparsable_limit_dropped(self):
        """Регистр важнее одного поля — иначе он уедет в мягкую ветку с дефолтами."""
        fixed, _ = auto_fix_register({"min": "до 100", "scale": 0.1})
        assert "min" not in fixed
        assert fixed["scale"] == 0.1

    def test_fix_format_int32(self):
        raw = {"format": "int32"}
        fixed, fixes = auto_fix_register(raw)
        assert fixed["format"] == "s32"

    def test_fix_format_float32(self):
        raw = {"format": "float32"}
        fixed, fixes = auto_fix_register(raw)
        assert fixed["format"] == "float"

    def test_fix_format_uppercase(self):
        raw = {"format": "FLOAT"}
        fixed, fixes = auto_fix_register(raw)
        assert fixed["format"] == "float"
        assert len(fixes) == 1

    def test_fix_format_already_valid(self):
        raw = {"format": "u16"}
        fixed, fixes = auto_fix_register(raw)
        assert fixed["format"] == "u16"
        assert len(fixes) == 0

    def test_fix_format_word(self):
        raw = {"format": "word"}
        fixed, fixes = auto_fix_register(raw)
        assert fixed["format"] == "u16"

    def test_fix_format_dword(self):
        raw = {"format": "dword"}
        fixed, fixes = auto_fix_register(raw)
        assert fixed["format"] == "u32"

    def test_fix_reg_type_holding_register(self):
        raw = {"reg_type": "holding_register"}
        fixed, fixes = auto_fix_register(raw)
        assert fixed["reg_type"] == "holding"

    def test_fix_reg_type_input_register(self):
        raw = {"reg_type": "input_register"}
        fixed, fixes = auto_fix_register(raw)
        assert fixed["reg_type"] == "input"

    def test_fix_reg_type_fc03(self):
        raw = {"reg_type": "fc03"}
        fixed, fixes = auto_fix_register(raw)
        assert fixed["reg_type"] == "holding"

    def test_fix_reg_type_fc04(self):
        raw = {"reg_type": "fc04"}
        fixed, fixes = auto_fix_register(raw)
        assert fixed["reg_type"] == "input"

    def test_fix_reg_type_uppercase(self):
        raw = {"reg_type": "HOLDING"}
        fixed, fixes = auto_fix_register(raw)
        assert fixed["reg_type"] == "holding"

    def test_fix_channel_type_on_off(self):
        raw = {"channel_type": "on_off"}
        fixed, fixes = auto_fix_register(raw)
        assert fixed["channel_type"] == "switch"

    def test_fix_access_read_only(self):
        raw = {"access": "read_only"}
        fixed, fixes = auto_fix_register(raw)
        assert fixed["access"] == "read"

    def test_fix_access_rw(self):
        raw = {"access": "rw"}
        fixed, fixes = auto_fix_register(raw)
        assert fixed["access"] == "readwrite"

    def test_fix_word_order_le(self):
        raw = {"word_order": "le"}
        fixed, fixes = auto_fix_register(raw)
        assert fixed["word_order"] == "little_endian"

    def test_fix_word_order_be(self):
        raw = {"word_order": "be"}
        fixed, fixes = auto_fix_register(raw)
        assert fixed["word_order"] == "big_endian"

    def test_fix_byte_order_msb(self):
        raw = {"byte_order": "msb"}
        fixed, fixes = auto_fix_register(raw)
        assert fixed["byte_order"] == "big_endian"

    def test_unknown_format_not_fixed(self):
        raw = {"format": "completely_unknown"}
        fixed, fixes = auto_fix_register(raw)
        assert fixed["format"] == "completely_unknown"
        assert len(fixes) == 0  # не фиксим, валидация поймает

    def test_multiple_fixes(self):
        raw = {"format": "uint16", "reg_type": "holding_register", "access": "ro"}
        fixed, fixes = auto_fix_register(raw)
        assert fixed["format"] == "u16"
        assert fixed["reg_type"] == "holding"
        assert fixed["access"] == "read"
        assert len(fixes) == 3

    def test_none_word_order_skipped(self):
        raw = {"word_order": None}
        fixed, fixes = auto_fix_register(raw)
        assert len(fixes) == 0

    def test_empty_dict(self):
        raw = {}
        fixed, fixes = auto_fix_register(raw)
        assert len(fixes) == 0


# ===================================================================
# Тесты validate_register
# ===================================================================


class TestValidateRegister:
    """Валидация одиночного регистра."""

    def test_valid_register_no_errors(self):
        reg = _reg(format="u16", reg_type="holding", channel_type="value")
        result = validate_register(reg)
        assert len(result.errors) == 0

    def test_valid_register_with_enum(self):
        reg = _reg(enum=[0, 1, 2], enum_titles=["Off", "On", "Auto"])
        result = validate_register(reg)
        errors = [e for e in result.errors if e.severity == Severity.ERROR]
        assert len(errors) == 0

    def test_invalid_format_error(self):
        reg = _reg(format="uint16")
        result = validate_register(reg)
        errors = [e for e in result.errors if e.field == "format"]
        assert len(errors) == 1
        assert errors[0].severity == Severity.ERROR
        assert errors[0].message_key == "validation.invalidFormat"

    def test_invalid_reg_type_error(self):
        reg = _reg(reg_type="unknown_type")
        result = validate_register(reg)
        errors = [e for e in result.errors if e.field == "reg_type"]
        assert len(errors) == 1
        assert errors[0].severity == Severity.ERROR

    def test_invalid_channel_type_error(self):
        reg = _reg(channel_type="nonexistent")
        result = validate_register(reg)
        errors = [e for e in result.errors if e.field == "channel_type"]
        assert len(errors) == 1
        assert errors[0].severity == Severity.ERROR

    def test_invalid_address_string(self):
        reg = _reg(address="garbage_address")
        result = validate_register(reg)
        errors = [e for e in result.errors if e.field == "address"]
        assert len(errors) == 1
        assert errors[0].severity == Severity.ERROR

    def test_valid_address_int(self):
        reg = _reg(address=100)
        result = validate_register(reg)
        errors = [e for e in result.errors if e.field == "address"]
        assert len(errors) == 0

    def test_valid_address_hex_string(self):
        reg = _reg(address="0x0064")
        result = validate_register(reg)
        errors = [e for e in result.errors if e.field == "address"]
        assert len(errors) == 0

    def test_valid_address_bitwise(self):
        reg = _reg(address="109:1:2")
        result = validate_register(reg)
        errors = [e for e in result.errors if e.field == "address"]
        assert len(errors) == 0

    def test_valid_address_hex_bitwise(self):
        reg = _reg(address="0x6D:1:2")
        result = validate_register(reg)
        errors = [e for e in result.errors if e.field == "address"]
        assert len(errors) == 0

    def test_negative_address_error(self):
        reg = _reg(address=-1)
        result = validate_register(reg)
        errors = [e for e in result.errors if e.field == "address"]
        assert len(errors) == 1

    def test_empty_name_error(self):
        reg = _reg(name="")
        result = validate_register(reg)
        errors = [e for e in result.errors if e.field == "name"]
        assert len(errors) == 1
        assert errors[0].severity == Severity.ERROR

    def test_whitespace_name_error(self):
        reg = _reg(name="   ")
        result = validate_register(reg)
        errors = [e for e in result.errors if e.field == "name"]
        assert len(errors) == 1

    def test_name_with_forbidden_char_error(self):
        # Символы $ # + / \ " ' ломают MQTT-топик → ошибка (схема отклонит при экспорте)
        reg = _reg(name="Temp #1")
        result = validate_register(reg)
        errors = [e for e in result.errors if e.message_key == "validation.invalidNameChars"]
        assert len(errors) == 1
        assert errors[0].severity == Severity.ERROR

    def test_name_with_slash_error(self):
        reg = _reg(name="Pump On/Off")
        result = validate_register(reg)
        errors = [e for e in result.errors if e.message_key == "validation.invalidNameChars"]
        assert len(errors) == 1

    def test_name_clean_no_forbidden_char_warning(self):
        reg = _reg(name="Voltage L1-N (RMS)")
        result = validate_register(reg)
        errors = [e for e in result.errors if e.message_key == "validation.invalidNameChars"]
        assert len(errors) == 0

    def test_empty_name_no_forbidden_char_error(self):
        # У пустого имени проверяем только emptyName, не дублируем invalidNameChars
        reg = _reg(name="")
        result = validate_register(reg)
        errors = [e for e in result.errors if e.message_key == "validation.invalidNameChars"]
        assert len(errors) == 0

    def test_w1_id_is_valid_channel_type(self):
        # w1-id есть в перечне control_type схемы (раньше отсутствовал в хардкоде)
        reg = _reg(channel_type="w1-id")
        result = validate_register(reg)
        ct_errors = [e for e in result.errors if e.field == "channel_type"]
        assert len(ct_errors) == 0

    def test_enum_length_mismatch_error(self):
        reg = _reg(enum=[0, 1, 2], enum_titles=["Off", "On"])
        result = validate_register(reg)
        errors = [e for e in result.errors if e.message_key == "validation.enumLengthMismatch"]
        assert len(errors) == 1
        assert errors[0].severity == Severity.ERROR

    def test_enum_matching_length_ok(self):
        reg = _reg(enum=[0, 1], enum_titles=["Off", "On"])
        result = validate_register(reg)
        errors = [e for e in result.errors if e.message_key == "validation.enumLengthMismatch"]
        assert len(errors) == 0

    def test_invalid_word_order_error(self):
        reg = _reg(word_order="mixed_endian")
        result = validate_register(reg)
        errors = [e for e in result.errors if e.field == "word_order"]
        assert len(errors) == 1
        assert errors[0].severity == Severity.ERROR

    def test_invalid_byte_order_error(self):
        reg = _reg(byte_order="unknown")
        result = validate_register(reg)
        errors = [e for e in result.errors if e.field == "byte_order"]
        assert len(errors) == 1

    # --- Warnings ---

    def test_parameter_channel_type_warning(self):
        reg = _reg(is_parameter=True, channel_type="switch")
        result = validate_register(reg)
        warnings = [e for e in result.errors if e.message_key == "validation.parameterChannelType"]
        assert len(warnings) == 1
        assert warnings[0].severity == Severity.WARNING

    def test_parameter_value_channel_no_warning(self):
        reg = _reg(is_parameter=True, channel_type="value")
        result = validate_register(reg)
        warnings = [e for e in result.errors if e.message_key == "validation.parameterChannelType"]
        assert len(warnings) == 0

    def test_string_without_data_size_warning(self):
        reg = _reg(format="string", string_data_size=None)
        result = validate_register(reg)
        warnings = [e for e in result.errors if e.message_key == "validation.missingStringDataSize"]
        assert len(warnings) == 1

    def test_string_with_data_size_no_warning(self):
        reg = _reg(format="string", string_data_size=10)
        result = validate_register(reg)
        warnings = [e for e in result.errors if e.message_key == "validation.missingStringDataSize"]
        assert len(warnings) == 0

    def test_string_width_in_address_no_warning(self):
        # Ширина строки задана через адрес "N:offset:width" — string_data_size не нужен
        reg = _reg(format="string", string_data_size=None, address="0:0:8")
        result = validate_register(reg)
        warnings = [e for e in result.errors if e.message_key == "validation.missingStringDataSize"]
        assert len(warnings) == 0

    def test_press_counter_is_valid_reg_type(self):
        # press_counter валиден по схеме драйвера (раньше ложно флагался как ошибка)
        reg = _reg(reg_type="press_counter")
        result = validate_register(reg)
        rt_errors = [e for e in result.errors if e.field == "reg_type"]
        assert len(rt_errors) == 0

    def test_min_greater_than_max_warning(self):
        reg = _reg(min=100, max=50)
        result = validate_register(reg)
        warnings = [e for e in result.errors if e.message_key == "validation.minGreaterThanMax"]
        assert len(warnings) == 1

    def test_min_less_than_max_no_warning(self):
        reg = _reg(min=10, max=100)
        result = validate_register(reg)
        warnings = [e for e in result.errors if e.message_key == "validation.minGreaterThanMax"]
        assert len(warnings) == 0

    def test_disabled_parameter_warning(self):
        reg = _reg(is_parameter=True, enabled=False)
        result = validate_register(reg)
        warnings = [e for e in result.errors if e.message_key == "validation.disabledParameter"]
        assert len(warnings) == 1

    def test_enabled_parameter_no_warning(self):
        reg = _reg(is_parameter=True, enabled=True)
        result = validate_register(reg)
        warnings = [e for e in result.errors if e.message_key == "validation.disabledParameter"]
        assert len(warnings) == 0

    def test_disabled_channel_no_warning(self):
        reg = _reg(is_parameter=False, enabled=False)
        result = validate_register(reg)
        warnings = [e for e in result.errors if e.message_key == "validation.disabledParameter"]
        assert len(warnings) == 0

    def test_readonly_conflict_warning(self):
        reg = _reg(readonly=True, read_only=False)
        result = validate_register(reg)
        warnings = [e for e in result.errors if e.message_key == "validation.readonlyConflict"]
        assert len(warnings) == 1

    def test_readonly_no_conflict(self):
        reg = _reg(readonly=True, read_only=True)
        result = validate_register(reg)
        warnings = [e for e in result.errors if e.message_key == "validation.readonlyConflict"]
        assert len(warnings) == 0

    def test_all_valid_formats_pass(self):
        """Каждый валидный формат должен проходить без ошибок."""
        from register_validator import VALID_FORMATS
        for fmt in VALID_FORMATS:
            reg = _reg(format=fmt)
            result = validate_register(reg)
            format_errors = [e for e in result.errors if e.field == "format"]
            assert len(format_errors) == 0, f"Format {fmt} should be valid"

    def test_all_valid_reg_types_pass(self):
        """Каждый валидный тип регистра должен проходить без ошибок."""
        from register_validator import VALID_REG_TYPES
        for rt in VALID_REG_TYPES:
            reg = _reg(reg_type=rt)
            result = validate_register(reg)
            rt_errors = [e for e in result.errors if e.field == "reg_type"]
            assert len(rt_errors) == 0, f"reg_type {rt} should be valid"

    def test_all_valid_channel_types_pass(self):
        """Каждый валидный тип канала должен проходить без ошибок."""
        from register_validator import VALID_CHANNEL_TYPES
        for ct in VALID_CHANNEL_TYPES:
            reg = _reg(channel_type=ct)
            result = validate_register(reg)
            ct_errors = [e for e in result.errors if e.field == "channel_type"]
            assert len(ct_errors) == 0, f"channel_type {ct} should be valid"


# ===================================================================
# Тесты validate_registers (кросс-регистровые)
# ===================================================================


class TestValidateRegisters:
    """Кросс-регистровые проверки."""

    def test_duplicate_address_warning(self):
        regs = [
            _reg(address=100, reg_type="holding", name="Reg A"),
            _reg(address=100, reg_type="holding", name="Reg B"),
        ]
        result = validate_registers(regs)
        dup_warnings = [
            e for rv in result.registers for e in rv.errors
            if e.message_key == "validation.duplicateAddress"
        ]
        assert len(dup_warnings) == 1  # только у второго

    def test_duplicate_address_with_condition_no_warning(self):
        # condition-gated пары на одном адресе — штатный паттерн (драйвер оставит один),
        # реального дубликата нет → предупреждать не нужно.
        regs = [
            _reg(address=100, reg_type="holding", name="A", condition="mode==1"),
            _reg(address=100, reg_type="holding", name="B", condition="mode==2"),
        ]
        result = validate_registers(regs)
        dup_warnings = [
            e for rv in result.registers for e in rv.errors
            if e.message_key == "validation.duplicateAddress"
        ]
        assert len(dup_warnings) == 0

    def test_same_address_different_reg_type_ok(self):
        regs = [
            _reg(address=100, reg_type="holding", name="Reg A"),
            _reg(address=100, reg_type="input", name="Reg B"),
        ]
        result = validate_registers(regs)
        dup_warnings = [
            e for rv in result.registers for e in rv.errors
            if e.message_key == "validation.duplicateAddress"
        ]
        assert len(dup_warnings) == 0

    @pytest.mark.parametrize("first,second", [(255, "0xff"), ("0xff", "0xFF")])
    def test_duplicate_across_address_notations(self, first, second):
        """Один адрес в разных записях — форма записи дубликат не прячет."""
        regs = [
            _reg(address=first, reg_type="holding", name="Reg A"),
            _reg(address=second, reg_type="holding", name="Reg B"),
        ]
        result = validate_registers(regs)
        dup_warnings = [
            e for rv in result.registers for e in rv.errors
            if e.message_key == "validation.duplicateAddress"
        ]
        assert len(dup_warnings) == 1

    def test_no_duplicates_clean(self):
        regs = [
            _reg(address=100, name="Reg A"),
            _reg(address=101, name="Reg B"),
            _reg(address=102, name="Reg C"),
        ]
        result = validate_registers(regs)
        assert result.warning_count == 0

    def test_counts_correct(self):
        regs = [
            _reg(address=0, format="invalid_fmt", name="Bad Reg"),  # 1 error
            _reg(address=1, min=100, max=50, name="OK Reg"),  # 1 warning (min>max)
        ]
        result = validate_registers(regs)
        assert result.error_count == 1
        assert result.warning_count == 1

    def test_empty_list(self):
        result = validate_registers([])
        assert result.error_count == 0
        assert result.warning_count == 0
        assert len(result.registers) == 0


# ===================================================================
# Тесты auto_fix_and_validate (интеграция)
# ===================================================================


class TestAutoFixAndValidate:
    """Интеграционные тесты: сырые данные → авто-фикс → парсинг → валидация."""

    def test_raw_with_synonym_format(self):
        raw = [{"address": 0, "name": "Voltage", "format": "uint16"}]
        registers, result, fixed_count = auto_fix_and_validate(raw)
        assert len(registers) == 1
        assert registers[0].format == "u16"
        assert fixed_count == 1
        assert result.error_count == 0

    def test_raw_with_invalid_address(self):
        raw = [{"address": "garbage", "name": "Bad"}]
        registers, result, _ = auto_fix_and_validate(raw)
        assert len(registers) == 1
        assert result.error_count >= 1

    def test_raw_with_mixed_errors(self):
        raw = [
            {"address": 0, "name": "Good", "format": "u16"},
            {"address": 1, "name": "Fixable", "format": "uint32"},
            {"address": 2, "name": "", "format": "totally_broken"},
        ]
        registers, result, fixed_count = auto_fix_and_validate(raw)
        assert len(registers) == 3
        assert fixed_count == 1  # uint32→u32
        assert result.error_count >= 2  # пустое имя + невалидный format

    def test_unparseable_register_skipped(self):
        raw = [
            {"address": 0, "name": "Good"},
            "not a dict",
            {"address": 1, "name": "Also Good"},
        ]
        registers, result, _ = auto_fix_and_validate(raw)
        assert len(registers) == 2

    def test_empty_list(self):
        registers, result, fixed_count = auto_fix_and_validate([])
        assert len(registers) == 0
        assert result.error_count == 0
        assert fixed_count == 0

    def test_hex_address_survives_soft_branch(self):
        """Регистр с ошибкой в другом поле не должен теряться из-за записи адреса."""
        raw = [{"address": "0xff", "name": "Voltage", "enum": "не список"}]
        registers, _, _ = auto_fix_and_validate(raw)
        assert [r.address for r in registers] == ["0xff"]


# ===================================================================
# Тесты format_validation_errors
# ===================================================================



class TestFormatValidationErrors:
    """Форматирование ошибок для LLM retry."""

    def test_zero_scale_message_is_text(self):
        """Модель должна получить фразу, а не ключ локализации."""
        reg = _reg(scale=0)
        text = format_validation_errors(validate_registers([reg]), [reg])
        assert "scale is 0" in text
        assert "validation.zeroScale" not in text

    def test_format_error_output(self):
        reg = _reg(format="invalid_fmt", name="Voltage")
        result = validate_registers([reg])
        text = format_validation_errors(result, [reg])
        assert "Voltage" in text
        assert "invalid_fmt" in text
        assert "format" in text.lower()

    def test_no_errors_output(self):
        reg = _reg()
        result = validate_registers([reg])
        text = format_validation_errors(result, [reg])
        assert text == "No critical errors found."

    def test_multiple_errors_output(self):
        regs = [
            _reg(format="bad1", name="Reg1"),
            _reg(format="bad2", name="Reg2"),
        ]
        result = validate_registers(regs)
        text = format_validation_errors(result, regs)
        assert "Reg1" in text
        assert "Reg2" in text


# ===================================================================
# Баг 4X: шестизначная legacy-нотация адреса (Eastron SDM630MCT)
# ===================================================================


class TestLegacySixDigitAddress:
    """Даташит мешает 5- и 6-значную запись 4X, модель конвертирует только 5-значную.

    Шестизначный адрес всегда > 65535 (16-битный Modbus), поэтому опознаётся
    однозначно и правится детерминированно, до валидации и без обращения к LLM.
    """

    def test_holding_6digit_converted(self):
        """461457 → 61456 (вычитаем 400001), реальные адреса SDM630MCT."""
        for raw_addr, expected in ((461457, 61456), (464513, 64512),
                                   (464515, 64514), (464516, 64515)):
            fixed, fixes = auto_fix_register({"address": raw_addr, "name": "Reset"})
            assert fixed["address"] == expected, raw_addr
            assert [f.field for f in fixes] == ["address"]

    def test_input_6digit_converted(self):
        """361457 → 61456 (вычитаем 300001)."""
        fixed, fixes = auto_fix_register({"address": 361457})
        assert fixed["address"] == 61456
        assert fixes[0].field == "address"

    def test_numeric_string_converted(self):
        """Адрес строкой из цифр правится так же."""
        fixed, _ = auto_fix_register({"address": "464513"})
        assert fixed["address"] == 64512

    def test_valid_address_untouched(self):
        """Корректный offset не трогаем — он всегда ≤ 65535."""
        for addr in (0, 1, 40001, 65535):
            fixed, fixes = auto_fix_register({"address": addr})
            assert fixed["address"] == addr
            assert fixes == []

    def test_bitwise_and_hex_untouched(self):
        """Побитовый и hex-адрес не наши клиенты — приводит к числу драйвер."""
        for addr in ("109:0:1", "0xF010"):
            fixed, fixes = auto_fix_register({"address": addr})
            assert fixed["address"] == addr
            assert fixes == []

    def test_unrepairable_address_is_error(self):
        """Что не удалось починить — ERROR, а не тихий проезд на железо."""
        result = validate_register(_reg(address=999999))
        assert any(e.field == "address" and e.severity == Severity.ERROR for e in result.errors)

    def test_max_address_is_valid(self):
        """65535 — верхняя граница, ошибкой быть не должна."""
        result = validate_register(_reg(address=65535))
        assert not any(e.field == "address" and e.severity == Severity.ERROR for e in result.errors)

    def test_end_to_end_via_auto_fix_and_validate(self):
        """Сквозной путь парсинга: 6-значный адрес приходит починенным и без ошибок."""
        regs, result, fixed_count = auto_fix_and_validate([
            {"address": 464513, "name": "Serial Number", "reg_type": "holding",
             "format": "u16", "channel_type": "value"},
        ])
        assert regs[0].address == 64512
        assert fixed_count >= 1
        assert result.error_count == 0

    def test_numeric_string_address_is_checked_too(self):
        """Адрес строкой «999999» — тоже ERROR: модель нередко отдаёт числа строками."""
        result = validate_register(_reg(address="999999"))
        assert any(e.field == "address" and e.severity == Severity.ERROR for e in result.errors)

    def test_hex_and_bitwise_addresses_are_not_range_checked(self):
        """Hex и побитовая запись под правило 65535 не попадают.

        У не-Modbus протоколов (neva, energomera_iec, energomera_ce) адрес — код
        параметра: в официальных шаблонах wb-mqtt-serial 125 таких значений, например
        0x012F0000. Проверка диапазона пометила бы рабочие шаблоны сломанными.
        """
        for addr in ("0x012F0000", "0x400304", "109:0:1"):
            result = validate_register(_reg(address=addr))
            assert not any(
                e.field == "address" and e.severity == Severity.ERROR for e in result.errors
            ), f"адрес {addr} не должен считаться ошибкой"


class TestNumericFieldNotation:
    """Запись поля с двумя записями проверяется паттерном схемы."""

    @pytest.mark.parametrize("field,value", [
        ("error_value", "0xFFFF"), ("error_value", 65535),
        ("on_value", "0x0101"), ("off_value", 0),
    ])
    def test_both_notations_are_valid(self, field, value):
        """Схема разрешает в этих полях и число, и hex — ошибкой это не считаем."""
        rv = validate_register(_reg(**{field: value}))
        assert [e for e in rv.errors if e.field == field] == []

    @pytest.mark.parametrize("field,value", [
        ("on_value", "1.5"),        # serial_int дробную часть не разрешает
        ("error_value", "1e5"),     # экспоненту не разрешает ни один паттерн
        ("off_value", "выкл"),
        ("on_value", " 0xff "),     # пробелы по краям схему не проходят
    ])
    def test_notation_outside_schema_is_an_error(self, field, value):
        rv = validate_register(_reg(**{field: value}))
        assert any(e.field == field and e.message_key == "validation.invalidNumber"
                   for e in rv.errors)

    def test_zero_scale_is_an_error(self):
        """Канал с scale=0 читает константный ноль; отключают каналы флагом enabled."""
        rv = validate_register(_reg(scale=0))
        assert any(e.field == "scale" and e.message_key == "validation.zeroScale"
                   for e in rv.errors)

    def test_llm_gets_actionable_text(self):
        """Ключ локализации в подсказке для модели бесполезен — нужен текст."""
        regs = [_reg(id="r", name="Voltage", address=100, on_value="1.5")]
        result = validate_registers(regs)
        text = format_validation_errors(result, regs)
        assert "validation." not in text
        assert "0xFF" in text
