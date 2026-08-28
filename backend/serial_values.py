"""Разбор значений в записи wb-mqtt-serial — одна трактовка на весь бэкенд.

Схема драйвера (wb-mqtt-serial-confed-common.schema.json) допускает у адреса три
записи — десятичное число, hex-строку «0xFF» и побитовую «109:1:2», — а у числовых
полей две: число и hex-строку. Записи равноправны, поэтому здесь они разбираются,
а не приводятся к одной: развёрнутый в число hex перестаёт быть той записью, что
стоит в шаблоне.
"""

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
    return value


def address_as_int(value: object) -> int | None:
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
    number = address_as_int(value)
    if number is not None:
        return number
    if isinstance(value, str):
        head = address_as_int(value.split(":")[0])
        if head is not None:
            return head
    return 0


def parse_number(value: object) -> object:
    """Число из строковой записи, точка и запятая равноправны.

    Драйвер ждёт в дробных полях JSON-число, а в шаблоне попадается строка. Hex
    возвращается строкой: в `min` и `max` она законна (`definitions/serial_num`).
    """
    if not isinstance(value, str):
        return value
    text = value.strip().replace(",", ".")
    if _NUMBER_REGEX.match(text):
        number = float(text)
        return int(number) if number.is_integer() and "." not in text else number
    return value


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
    text = text.replace(",", ".")
    return float(text) if _NUMBER_REGEX.match(text) else None


def progression_address(value: object) -> int | None:
    """Адрес для свёртки в арифметическую прогрессию Jinja-цикла.

    Только числовая запись: цикл выражает адрес как «база + шаг», поэтому hex стал
    бы в нём десятичным числом, а побитовая запись числом не выражается вовсе.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and _DECIMAL_REGEX.match(value.strip()):
        return int(value)
    return None


def canonical_address(value: object) -> str:
    """Канонический ключ адреса — разные записи дают одну строку.

    «0xFF», «0xff» и 255 — один регистр. Побитовая запись нормализуется по
    частям: «0x6D:0:1» → «109:0:1».
    """
    if isinstance(value, str) and ":" in value:
        parts = []
        for part in value.split(":"):
            number = address_as_int(part)
            parts.append(str(number) if number is not None else part.strip())
        return ":".join(parts)
    number = address_as_int(value)
    return str(number) if number is not None else str(value)
