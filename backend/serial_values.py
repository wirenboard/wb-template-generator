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


def parse_address(value: object) -> object:
    """Число для десятичной записи, строка для hex и побитовой.

    Неразобранное возвращается как пришло — его пометит валидатор.
    """
    if not isinstance(value, str):
        return value
    text = value.strip()
    if _DECIMAL_REGEX.match(text):
        return int(text)
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
        return int(text)
    if _HEX_REGEX.match(text):
        return int(text, 16)
    return None


def address_sort_value(value: object) -> int:
    """Значение для сортировки. Побитовый адрес — по своему регистру.

    Неразобранное даёт 0, чтобы сортировка не падала на мусорном адресе.
    """
    number = _address_as_int(value)
    if number is not None:
        return number
    if isinstance(value, str):
        head = _address_as_int(value.split(":")[0])
        if head is not None:
            return head
    return 0


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
    number = float(text)
    if not math.isfinite(number):
        return None
    return int(number) if number.is_integer() and "." not in text else number


def numeric_value(value: object) -> int | float | None:
    """Числовое значение поля в любой из записей. None — не разобрано.

    Нужно для сравнений: `min` и `max` бывают записаны по-разному.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    if not isinstance(value, str):
        return None
    text = value.strip()
    if _HEX_REGEX.match(text):
        return int(text, 16)
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
