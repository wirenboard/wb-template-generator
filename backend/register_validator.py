"""Валидация и авто-исправление регистров по схеме wb-mqtt-serial.

Источник истины — JSON-схемы драйвера:
- wb-mqtt-serial-device-template.schema.json
- wb-mqtt-serial-confed-common.schema.json
"""

import re
from dataclasses import dataclass, field
from enum import Enum

from models import Register

# ---------------------------------------------------------------------------
# Типы
# ---------------------------------------------------------------------------


class Severity(str, Enum):
    """Уровень серьёзности ошибки валидации."""

    ERROR = "error"  # шаблон будет сломан
    WARNING = "warning"  # подозрительно, но может работать


@dataclass
class FieldError:
    """Ошибка валидации конкретного поля регистра."""

    field: str
    severity: Severity
    message_key: str
    message_params: dict = field(default_factory=dict)
    suggestion: str | None = None


@dataclass
class RegisterValidation:
    """Результат валидации одного регистра."""

    register_id: str
    errors: list[FieldError] = field(default_factory=list)


@dataclass
class ValidationResult:
    """Результат валидации всех регистров."""

    registers: list[RegisterValidation] = field(default_factory=list)
    error_count: int = 0
    warning_count: int = 0
    auto_fixed_count: int = 0


# ---------------------------------------------------------------------------
# Допустимые значения из JSON-схемы wb-mqtt-serial
# ---------------------------------------------------------------------------

VALID_FORMATS = frozenset({
    "s16", "u16", "s8", "u8", "s24", "u24", "s32", "u32", "s64", "u64",
    "bcd8", "bcd16", "bcd24", "bcd32",
    "float", "double", "char8", "string", "string8",
})

VALID_REG_TYPES = frozenset({
    "coil", "discrete", "holding", "holding_single", "holding_multi",
    "input", "direct",
})

VALID_CHANNEL_TYPES = frozenset({
    "switch", "wo-switch", "pushbutton", "range", "rgb", "text", "value",
    "temperature", "rel_humidity", "atmospheric_pressure", "rainfall",
    "wind_speed", "power", "power_consumption", "voltage", "water_flow",
    "water_consumption", "resistance", "concentration", "heat_energy",
    "heat_power", "dimmer", "lux", "pressure", "current", "sound_level",
    "alarm",
})

# Для параметров допустим только value
PARAMETER_CHANNEL_TYPES = frozenset({"value"})

VALID_WORD_ORDER = frozenset({"big_endian", "little_endian"})
VALID_BYTE_ORDER = frozenset({"big_endian", "little_endian"})

# Форматы, занимающие более одного 16-бит регистра
MULTI_REG_FORMATS = frozenset({"u32", "s32", "u64", "s64", "float", "double"})

# Строковые форматы
STRING_FORMATS = frozenset({"string", "string8"})

# Битовые типы регистров (coil/discrete — 1-битные)
BIT_REG_TYPES = frozenset({"coil", "discrete"})

# Регулярка адреса из JSON-схемы драйвера
ADDRESS_REGEX = re.compile(r"^(?:0x[A-Fa-f0-9]+|\d+)(?::\d+:\d+)?$")

# ---------------------------------------------------------------------------
# Маппинг синонимов для авто-исправления
# ---------------------------------------------------------------------------

FORMAT_SYNONYMS: dict[str, str] = {
    "uint16": "u16", "int16": "s16",
    "uint32": "u32", "int32": "s32",
    "uint64": "u64", "int64": "s64",
    "uint8": "u8", "int8": "s8",
    "unsigned16": "u16", "signed16": "s16",
    "unsigned32": "u32", "signed32": "s32",
    "unsigned8": "u8", "signed8": "s8",
    "word": "u16", "dword": "u32", "qword": "u64", "byte": "u8",
    "float32": "float", "float64": "double",
    "ieee754": "float", "real": "float",
    "real32": "float", "real64": "double",
    "string16": "string", "ascii": "string", "str": "string",
    "bcd": "bcd16",
    "int": "s16", "uint": "u16",
    "integer": "s16", "unsigned": "u16",
    "u16be": "u16", "u16le": "u16",
    "u32be": "u32", "u32le": "u32",
    "s32be": "s32", "s32le": "s32",
}

REG_TYPE_SYNONYMS: dict[str, str] = {
    "holding_register": "holding",
    "holding_registers": "holding",
    "input_register": "input",
    "input_registers": "input",
    "coil_register": "coil",
    "discrete_input": "discrete",
    "discrete_inputs": "discrete",
    "hr": "holding", "ir": "input", "di": "discrete",
    # Коды функций Modbus
    "3": "holding", "4": "input", "1": "coil", "2": "discrete",
    "03": "holding", "04": "input", "01": "coil", "02": "discrete",
    "fc03": "holding", "fc04": "input", "fc01": "coil", "fc02": "discrete",
    "fc3": "holding", "fc4": "input", "fc1": "coil", "fc2": "discrete",
    "register": "holding",
}

CHANNEL_TYPE_SYNONYMS: dict[str, str] = {
    "on_off": "switch",
    "toggle": "switch",
    "button": "pushbutton",
    "write_only_switch": "wo-switch",
    "color": "rgb",
    "string": "text",
}

ACCESS_SYNONYMS: dict[str, str] = {
    "r": "read", "w": "write", "rw": "readwrite",
    "read_only": "read", "write_only": "write",
    "read/write": "readwrite", "read_write": "readwrite",
    "ro": "read", "wo": "write",
}

WORD_ORDER_SYNONYMS: dict[str, str] = {
    "be": "big_endian", "le": "little_endian",
    "big": "big_endian", "little": "little_endian",
    "msb": "big_endian", "lsb": "little_endian",
    "msb_first": "big_endian", "lsb_first": "little_endian",
}


# ---------------------------------------------------------------------------
# Авто-исправление
# ---------------------------------------------------------------------------

def _try_fix(value: str | None, synonyms: dict[str, str],
             valid_set: frozenset[str]) -> tuple[str | None, str | None]:
    """Пытается исправить значение по маппингу синонимов.

    Возвращает (исправленное_значение, оригинал_если_исправлено).
    Если исправление не нужно или невозможно — (original, None).
    """
    if value is None:
        return None, None
    lower = value.strip().lower()
    # Уже валидное
    if lower in valid_set:
        # Нормализуем регистр, если отличается
        if lower != value:
            return lower, value
        return value, None
    # Ищем в синонимах
    fixed = synonyms.get(lower)
    if fixed:
        return fixed, value
    return value, None


def auto_fix_register(raw_reg: dict) -> tuple[dict, list[FieldError]]:
    """Авто-исправление полей регистра перед Pydantic-парсингом.

    Мутирует raw_reg. Возвращает (исправленный dict, список fix-записей).
    """
    fixes: list[FieldError] = []

    # format
    if "format" in raw_reg:
        fixed, original = _try_fix(str(raw_reg["format"]), FORMAT_SYNONYMS, VALID_FORMATS)
        if original is not None and fixed is not None:
            raw_reg["format"] = fixed
            fixes.append(FieldError(
                field="format", severity=Severity.WARNING,
                message_key="validation.autoFixed",
                message_params={"field": "format", "from": original, "to": fixed},
                suggestion=fixed,
            ))

    # reg_type
    if "reg_type" in raw_reg:
        fixed, original = _try_fix(str(raw_reg["reg_type"]), REG_TYPE_SYNONYMS, VALID_REG_TYPES)
        if original is not None and fixed is not None:
            raw_reg["reg_type"] = fixed
            fixes.append(FieldError(
                field="reg_type", severity=Severity.WARNING,
                message_key="validation.autoFixed",
                message_params={"field": "reg_type", "from": original, "to": fixed},
                suggestion=fixed,
            ))

    # channel_type
    if "channel_type" in raw_reg:
        fixed, original = _try_fix(
            str(raw_reg["channel_type"]), CHANNEL_TYPE_SYNONYMS, VALID_CHANNEL_TYPES,
        )
        if original is not None and fixed is not None:
            raw_reg["channel_type"] = fixed
            fixes.append(FieldError(
                field="channel_type", severity=Severity.WARNING,
                message_key="validation.autoFixed",
                message_params={"field": "channel_type", "from": original, "to": fixed},
                suggestion=fixed,
            ))

    # access
    if "access" in raw_reg:
        fixed, original = _try_fix(
            str(raw_reg["access"]), ACCESS_SYNONYMS, frozenset({"read", "write", "readwrite"}),
        )
        if original is not None and fixed is not None:
            raw_reg["access"] = fixed
            fixes.append(FieldError(
                field="access", severity=Severity.WARNING,
                message_key="validation.autoFixed",
                message_params={"field": "access", "from": original, "to": fixed},
                suggestion=fixed,
            ))

    # word_order
    if "word_order" in raw_reg and raw_reg["word_order"] is not None:
        fixed, original = _try_fix(
            str(raw_reg["word_order"]), WORD_ORDER_SYNONYMS, VALID_WORD_ORDER,
        )
        if original is not None and fixed is not None:
            raw_reg["word_order"] = fixed
            fixes.append(FieldError(
                field="word_order", severity=Severity.WARNING,
                message_key="validation.autoFixed",
                message_params={"field": "word_order", "from": original, "to": fixed},
                suggestion=fixed,
            ))

    # byte_order
    if "byte_order" in raw_reg and raw_reg["byte_order"] is not None:
        fixed, original = _try_fix(
            str(raw_reg["byte_order"]), WORD_ORDER_SYNONYMS, VALID_BYTE_ORDER,
        )
        if original is not None and fixed is not None:
            raw_reg["byte_order"] = fixed
            fixes.append(FieldError(
                field="byte_order", severity=Severity.WARNING,
                message_key="validation.autoFixed",
                message_params={"field": "byte_order", "from": original, "to": fixed},
                suggestion=fixed,
            ))

    return raw_reg, fixes


# ---------------------------------------------------------------------------
# Валидация одного регистра
# ---------------------------------------------------------------------------

def validate_register(reg: Register) -> RegisterValidation:
    """Валидирует один регистр, возвращает список ошибок/предупреждений."""
    errors: list[FieldError] = []

    # --- ERROR-уровневые проверки ---

    # Пустое имя
    if not reg.name or not reg.name.strip():
        errors.append(FieldError(
            field="name", severity=Severity.ERROR,
            message_key="validation.emptyName",
        ))

    # Невалидный format
    if reg.format not in VALID_FORMATS:
        errors.append(FieldError(
            field="format", severity=Severity.ERROR,
            message_key="validation.invalidFormat",
            message_params={"value": reg.format},
        ))

    # Невалидный reg_type
    if reg.reg_type not in VALID_REG_TYPES:
        errors.append(FieldError(
            field="reg_type", severity=Severity.ERROR,
            message_key="validation.invalidRegType",
            message_params={"value": reg.reg_type},
        ))

    # Невалидный channel_type
    if reg.channel_type not in VALID_CHANNEL_TYPES:
        errors.append(FieldError(
            field="channel_type", severity=Severity.ERROR,
            message_key="validation.invalidChannelType",
            message_params={"value": reg.channel_type},
        ))

    # Невалидный адрес
    if isinstance(reg.address, str):
        if not ADDRESS_REGEX.match(reg.address):
            errors.append(FieldError(
                field="address", severity=Severity.ERROR,
                message_key="validation.invalidAddress",
                message_params={"value": reg.address},
            ))
    elif isinstance(reg.address, int):
        if reg.address < 0:
            errors.append(FieldError(
                field="address", severity=Severity.ERROR,
                message_key="validation.invalidAddress",
                message_params={"value": str(reg.address)},
            ))

    # Невалидный word_order
    if reg.word_order is not None and reg.word_order not in VALID_WORD_ORDER:
        errors.append(FieldError(
            field="word_order", severity=Severity.ERROR,
            message_key="validation.invalidWordOrder",
            message_params={"value": reg.word_order},
        ))

    # Невалидный byte_order
    if reg.byte_order is not None and reg.byte_order not in VALID_BYTE_ORDER:
        errors.append(FieldError(
            field="byte_order", severity=Severity.ERROR,
            message_key="validation.invalidByteOrder",
            message_params={"value": reg.byte_order},
        ))

    # enum и enum_titles разной длины
    if reg.enum is not None and reg.enum_titles is not None:
        if len(reg.enum) != len(reg.enum_titles):
            errors.append(FieldError(
                field="enum", severity=Severity.ERROR,
                message_key="validation.enumLengthMismatch",
                message_params={
                    "enumLen": len(reg.enum),
                    "titlesLen": len(reg.enum_titles),
                },
            ))

    # --- WARNING-уровневые проверки ---

    # Параметр с channel_type != value
    if reg.is_parameter and reg.channel_type not in PARAMETER_CHANNEL_TYPES:
        errors.append(FieldError(
            field="channel_type", severity=Severity.WARNING,
            message_key="validation.parameterChannelType",
            message_params={"channelType": reg.channel_type},
        ))

    # switch с enum (enum игнорируется драйвером)
    if reg.channel_type in ("switch", "wo-switch") and reg.enum:
        errors.append(FieldError(
            field="enum", severity=Severity.WARNING,
            message_key="validation.switchWithEnum",
        ))

    # wo-switch но access != write
    if reg.channel_type == "wo-switch" and reg.access != "write":
        errors.append(FieldError(
            field="access", severity=Severity.WARNING,
            message_key="validation.woSwitchNotWriteOnly",
            message_params={"access": reg.access},
        ))

    # Многорегистровый формат без word_order
    if reg.format in MULTI_REG_FORMATS and reg.word_order is None:
        # Не предупреждать для bit-регистров
        if reg.reg_type not in BIT_REG_TYPES:
            errors.append(FieldError(
                field="word_order", severity=Severity.WARNING,
                message_key="validation.missingWordOrder",
                message_params={"format": reg.format},
            ))

    # Строковый формат без string_data_size
    if reg.format in STRING_FORMATS and reg.string_data_size is None:
        errors.append(FieldError(
            field="string_data_size", severity=Severity.WARNING,
            message_key="validation.missingStringDataSize",
            message_params={"format": reg.format},
        ))

    # coil/discrete с channel_type не switch/wo-switch/pushbutton/value
    if reg.reg_type in BIT_REG_TYPES:
        typical_bit_types = {"switch", "wo-switch", "pushbutton", "value"}
        if reg.channel_type not in typical_bit_types:
            errors.append(FieldError(
                field="channel_type", severity=Severity.WARNING,
                message_key="validation.bitRegNotSwitch",
                message_params={"regType": reg.reg_type, "channelType": reg.channel_type},
            ))

    return RegisterValidation(register_id=reg.id, errors=errors)


# ---------------------------------------------------------------------------
# Валидация списка регистров
# ---------------------------------------------------------------------------

def validate_registers(registers: list[Register]) -> ValidationResult:
    """Валидирует все регистры, включая кросс-регистровые проверки."""
    validations: list[RegisterValidation] = []
    error_count = 0
    warning_count = 0

    # Проверяем каждый регистр
    for reg in registers:
        rv = validate_register(reg)
        validations.append(rv)

    # Кросс-регистровая проверка: дубликаты адресов
    seen_addresses: dict[str, str] = {}  # "(address, reg_type)" → register_id первого
    for reg in registers:
        key = f"{reg.address}:{reg.reg_type}"
        if key in seen_addresses:
            # Находим validation для этого регистра
            for rv in validations:
                if rv.register_id == reg.id:
                    rv.errors.append(FieldError(
                        field="address", severity=Severity.WARNING,
                        message_key="validation.duplicateAddress",
                        message_params={
                            "address": str(reg.address),
                            "regType": reg.reg_type,
                        },
                    ))
                    break
        else:
            seen_addresses[key] = reg.id

    # Подсчёт
    for rv in validations:
        for e in rv.errors:
            if e.severity == Severity.ERROR:
                error_count += 1
            else:
                warning_count += 1

    return ValidationResult(
        registers=validations,
        error_count=error_count,
        warning_count=warning_count,
    )


# ---------------------------------------------------------------------------
# Комбинированный пайплайн: авто-фикс → парсинг → валидация
# ---------------------------------------------------------------------------

def auto_fix_and_validate(
    raw_registers: list[dict],
) -> tuple[list[Register], ValidationResult, int]:
    """Авто-исправление + парсинг + валидация сырых данных от LLM.

    Возвращает: (список Register, результат валидации, количество авто-исправлений).
    """
    import logging
    logger = logging.getLogger("wb-template-gen")

    registers: list[Register] = []
    auto_fixed_count = 0

    for raw_reg in raw_registers:
        if not isinstance(raw_reg, dict):
            continue
        raw_reg.pop("id", None)

        # Авто-фикс
        fixed_reg, fixes = auto_fix_register(raw_reg)
        auto_fixed_count += len(fixes)

        # Парсинг
        try:
            reg = Register(**fixed_reg)
            registers.append(reg)
        except Exception as e:
            logger.warning("Ошибка парсинга регистра после авто-фикса %s: %s", raw_reg, e)
            try:
                reg = Register(
                    address=int(raw_reg.get("address", 0)),
                    name=str(raw_reg.get("name", "Unknown")),
                )
                registers.append(reg)
            except Exception:
                logger.error("Не удалось распарсить регистр, пропускаем: %s", raw_reg)

    # Валидация
    result = validate_registers(registers)
    result.auto_fixed_count = auto_fixed_count
    return registers, result, auto_fixed_count


# ---------------------------------------------------------------------------
# Форматирование ошибок для LLM retry промпта
# ---------------------------------------------------------------------------

def format_validation_errors(
    result: ValidationResult, registers: list[Register],
) -> str:
    """Форматирует ошибки валидации в текст для LLM retry-промпта."""
    reg_map = {r.id: r for r in registers}
    lines: list[str] = []

    for rv in result.registers:
        error_items = [e for e in rv.errors if e.severity == Severity.ERROR]
        if not error_items:
            continue
        reg = reg_map.get(rv.register_id)
        if not reg:
            continue

        reg_label = f'Register "{reg.name}" (address={reg.address})'
        for e in error_items:
            if e.field == "format":
                lines.append(
                    f'{reg_label}: format "{e.message_params.get("value", "")}" is invalid. '
                    f"Valid formats: s16, u16, s8, u8, s24, u24, s32, u32, s64, u64, "
                    f"bcd8, bcd16, bcd24, bcd32, float, double, char8, string, string8"
                )
            elif e.field == "reg_type":
                lines.append(
                    f'{reg_label}: reg_type "{e.message_params.get("value", "")}" is invalid. '
                    f"Valid types: coil, discrete, holding, holding_single, holding_multi, input"
                )
            elif e.field == "channel_type":
                lines.append(
                    f'{reg_label}: channel_type "{e.message_params.get("value", "")}" is invalid. '
                    f"Use 'value' for measurements, 'switch' for on/off toggles"
                )
            elif e.field == "address":
                lines.append(
                    f'{reg_label}: address "{e.message_params.get("value", "")}" is invalid. '
                    f"Must be a non-negative integer or 'register:bit:width' string"
                )
            elif e.field == "name":
                lines.append(f"{reg_label}: name is empty")
            elif e.field == "enum":
                lines.append(
                    f"{reg_label}: enum has {e.message_params.get('enumLen', '?')} values "
                    f"but enum_titles has {e.message_params.get('titlesLen', '?')}"
                )
            else:
                lines.append(f"{reg_label}: {e.field} — {e.message_key}")

    return "\n".join(lines) if lines else "No critical errors found."
