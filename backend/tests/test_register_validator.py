"""Тесты для register_validator — валидация и авто-исправление регистров."""

import sys
from pathlib import Path

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

    def test_enable_in_name_value_no_enum_warning(self):
        reg = _reg(name="Anti-Freezing Enable", channel_type="value")
        result = validate_register(reg)
        warnings = [e for e in result.errors if e.message_key == "validation.probablySwitch"]
        assert len(warnings) == 1

    def test_enable_in_name_switch_no_warning(self):
        reg = _reg(name="Anti-Freezing Enable", channel_type="switch")
        result = validate_register(reg)
        warnings = [e for e in result.errors if e.message_key == "validation.probablySwitch"]
        assert len(warnings) == 0

    def test_enable_in_name_with_enum_no_warning(self):
        reg = _reg(name="Mode Enable", channel_type="value", enum=[0, 1, 2], enum_titles=["Off", "On", "Auto"])
        result = validate_register(reg)
        warnings = [e for e in result.errors if e.message_key == "validation.probablySwitch"]
        assert len(warnings) == 0

    def test_enable_in_name_parameter_no_warning(self):
        reg = _reg(name="Feature Enable", channel_type="value", is_parameter=True)
        result = validate_register(reg)
        warnings = [e for e in result.errors if e.message_key == "validation.probablySwitch"]
        assert len(warnings) == 0

    def test_disable_in_name_warning(self):
        reg = _reg(name="Alarm Disable", channel_type="value")
        result = validate_register(reg)
        warnings = [e for e in result.errors if e.message_key == "validation.probablySwitch"]
        assert len(warnings) == 1

    def test_on_off_in_name_warning(self):
        reg = _reg(name="Pump On/Off", channel_type="value")
        result = validate_register(reg)
        warnings = [e for e in result.errors if e.message_key == "validation.probablySwitch"]
        assert len(warnings) == 1

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


# ===================================================================
# Тесты format_validation_errors
# ===================================================================


class TestFormatValidationErrors:
    """Форматирование ошибок для LLM retry."""

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
