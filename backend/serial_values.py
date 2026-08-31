"""Разбор значений в записи wb-mqtt-serial — одна трактовка на весь бэкенд.

Схема драйвера допускает у адреса три записи — десятичную, hex «0xFF» и побитовую
«109:1:2», у числовых полей две. Записи равноправны, поэтому здесь они разбираются,
а не сводятся к одной. Развёрнутый в число hex — уже не та запись, что в шаблоне.
"""

import math
import re

_DECIMAL_REGEX = re.compile(r"^\d+$")
_HEX_REGEX = re.compile(r"^0x[\dA-F]+$", re.IGNORECASE)
_NUMBER_REGEX = re.compile(r"^-?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$")

# Шире u64 драйвер значений не читает (stoull), а int за пределами ~4300 цифр не
# сериализуется в JSON — запись сверх потолка считаем неразобранной
_MAX_SERIAL_VALUE = 0xFFFF_FFFF_FFFF_FFFF


def parse_address(value: object) -> object:
    """Число для десятичной записи, строка для hex и побитовой.

    Неразобранное возвращается как пришло — его пометит валидатор.
    """
    if not isinstance(value, str):
        return value
    text = value.strip()
    if _DECIMAL_REGEX.match(text):
        try:
            return int(text)
        except ValueError:  # длиннее лимита CPython на разбор десятичной записи
            return text
    if _HEX_REGEX.match(text):
        # Схема требует префикс в нижнем регистре, сами цифры — в любом
        return "0x" + text[2:]
    return text


def _address_as_int(value: object) -> int | None:
    """Числовое значение простого адреса. None — побитовый или неразобранный.

    Побитовый адрес числом не выражается: «109:0:1» — это бит 0 регистра 109.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if not isinstance(value, str):
        return None
    text = value.strip()
    if _DECIMAL_REGEX.match(text):
        try:
            number = int(text)
        except ValueError:  # длиннее лимита CPython на разбор десятичной записи
            return None
    elif _HEX_REGEX.match(text):
        number = int(text, 16)
    else:
        return None
    return number if number <= _MAX_SERIAL_VALUE else None


def address_sort_key(value: object) -> tuple[tuple[int, ...], str]:
    """Ключ сортировки — значения всех частей записи, при равенстве сама запись.

    Биты одного регистра идут по порядку смещения, неразобранные записи (OBIS-коды)
    упорядочиваются строкой. Порядок общий с compareAddresses на фронте — контракт
    в serial_values_contract.json.
    """
    text = value if isinstance(value, str) else str(value)
    if isinstance(value, str) and ":" in value:
        parts = tuple(_address_as_int(part) or 0 for part in value.split(":"))
        return parts, text
    number = _address_as_int(value)
    return ((number,) if number is not None else (0,)), text


def parse_number(value: object) -> object:
    """Число из строковой записи, точка и запятая равноправны.

    Драйвер ждёт в дробных полях JSON-число, а в шаблоне попадается строка. Hex
    возвращается строкой — в этих полях схема его разрешает.
    """
    if not isinstance(value, str):
        return value
    text = value.strip().replace(",", ".")
    number = _as_number(text)
    return value if number is None else number


def _as_number(text: str) -> int | float | None:
    """Число из уже нормализованной строки, целое не превращается в дробное."""
    if not _NUMBER_REGEX.match(text):
        return None
    if "." not in text and "e" not in text and "E" not in text:
        # Целую запись парсим напрямую — через float она теряет точность после 15 цифр
        try:
            return int(text)
        except ValueError:  # длиннее лимита CPython на разбор
            return None
    number = float(text)
    if not math.isfinite(number):
        return None
    return int(number) if number.is_integer() and "." not in text else number


def numeric_value(value: object) -> int | float | None:
    """Числовое значение поля в любой из записей. None — не разобрано.

    Им разворачиваются `min` и `max` — лимиты редактор держит числом.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    if not isinstance(value, str):
        return None
    text = value.strip()
    if _HEX_REGEX.match(text):
        number = int(text, 16)
        return number if number <= _MAX_SERIAL_VALUE else None
    return _as_number(text.replace(",", "."))


def decimal_address(value: object) -> int | None:
    """Число, если адрес записан десятичным. Для hex и побитовой записи — None.

    Обе записи в число не сворачиваются. В jinja-цикле адрес выражен как «база плюс
    шаг», и hex стал бы там десятичным, а у не-Modbus протоколов hex-код законно
    выходит за 16-битный диапазон.
    """
    if isinstance(value, bool):
        return None
    parsed = parse_address(value)
    return parsed if isinstance(parsed, int) else None


def canonical_address(value: object) -> str:
    """Канонический ключ адреса — разные записи дают одну строку.

    «0xFF», «0xff» и 255 — один регистр. Побитовая запись нормализуется по частям,
    «0x6D:0:1» → «109:0:1».
    """
    if isinstance(value, str) and ":" in value:
        parts = []
        for part in value.split(":"):
            number = _address_as_int(part)
            parts.append(str(number) if number is not None else part.strip())
        return ":".join(parts)
    number = _address_as_int(value)
    return str(number) if number is not None else str(value)
