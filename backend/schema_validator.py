"""Валидация собранного JSON-шаблона по JSON-схеме wb-mqtt-serial.

Схемы хранятся в backend/schemas/ и загружаются при первом вызове.
Поддерживают JSON с комментариями (//) из репозитория драйвера.
"""

import json
import logging
import re
from functools import lru_cache
from pathlib import Path

from jsonschema import Draft7Validator

logger = logging.getLogger("wb-template-gen")

SCHEMAS_DIR = Path(__file__).parent / "schemas"
TEMPLATE_SCHEMA_FILE = SCHEMAS_DIR / "wb-mqtt-serial-device-template.schema.json"
COMMON_SCHEMA_FILE = SCHEMAS_DIR / "wb-mqtt-serial-confed-common.schema.json"

# Паттерн для удаления однострочных JS-комментариев из JSON
# Не трогает // внутри строк (e.g. "http://...")
_COMMENT_RE = re.compile(r'(?<!["\w:])//[^\n]*')


def _load_json_with_comments(path: Path) -> dict:
    """Загружает JSON-файл, удаляя однострочные комментарии (//)."""
    text = path.read_text(encoding="utf-8")
    clean = _COMMENT_RE.sub("", text)
    return json.loads(clean)


@lru_cache
def _load_schema() -> dict:
    """Загружает и объединяет template + common схемы.

    Common-определения инжектируются в definitions template-схемы,
    чтобы $ref-ссылки работали без внешнего resolver.
    """
    template_schema = _load_json_with_comments(TEMPLATE_SCHEMA_FILE)
    common_schema = _load_json_with_comments(COMMON_SCHEMA_FILE)

    # Инжектируем definitions из common в template
    # (template-схема ссылается на #/definitions/... которые живут в common)
    defs = template_schema.setdefault("definitions", {})
    for key, value in common_schema.get("definitions", {}).items():
        if key not in defs:
            defs[key] = value

    return template_schema


_CHANNEL_NAME_PATTERN = "does not match '^[^$#+\\\\/"


def _humanize_error(path: str, msg: str) -> str:
    """Заменяет cryptic regex-сообщения на i18n-ключи с параметрами.

    Возвращает строку формата "i18n:key|param1=val1|param2=val2"
    если ошибка распознана, иначе — оригинальное сообщение.
    """
    # Имя канала содержит запрещённые символы ($, #, +, \, /, ", ')
    if ".name" in path and _CHANNEL_NAME_PATTERN in msg:
        value = msg.split("'")[1] if "'" in msg else "?"
        return f"i18n:schema.invalidChannelName|value={value}"

    if len(msg) > 150:
        msg = msg[:150] + "..."
    return msg


def validate_template(template: dict) -> list[str]:
    """Валидирует собранный JSON-шаблон по схеме wb-mqtt-serial.

    Returns:
        Список строк с описанием ошибок. Пустой список = валидно.
    """
    try:
        schema = _load_schema()
    except Exception as e:
        logger.error("Не удалось загрузить JSON-схему: %s", e)
        return [f"Ошибка загрузки схемы: {e}"]

    validator = Draft7Validator(schema)
    raw_errors: list[tuple[str, str]] = []  # (path, message)

    def _collect(error, depth: int = 0) -> None:
        """Рекурсивно собирает конкретные ошибки, пропуская oneOf-обёртки."""
        if error.context and depth < 3:
            for sub in error.context:
                _collect(sub, depth + 1)
        else:
            path = ".".join(str(p) for p in error.absolute_path) or "(root)"
            raw_errors.append((path, error.message))

    for error in validator.iter_errors(template):
        _collect(error)

    # Фильтруем шум от oneOf-вариантов (protocol required, пустые parameters и т.д.)
    noise_patterns = {
        "'protocol' is a required property",
        "should not be valid under",
        "'device_type' is a required property",
        "is not of type 'string'",  # address может быть int для Modbus
    }

    # Паттерны адресов bitwise (7:0:1) — валидны для Modbus, но не матчат OBIS/DLMS
    address_pattern_noise = "does not match '^(\\\\d"

    seen: set[str] = set()
    errors: list[str] = []
    for path, msg in raw_errors:
        # Пропускаем известный шум
        if any(noise in msg for noise in noise_patterns):
            continue
        # Bitwise-адреса (7:0:1) не матчат OBIS-паттерн — это не ошибка для Modbus
        if ".address" in path and address_pattern_noise in msg:
            continue
        # Дедупликация (oneOf генерирует дубли)
        key = f"{path}:{msg[:80]}"
        if key in seen:
            continue
        seen.add(key)
        # Человекочитаемые сообщения вместо regex
        msg = _humanize_error(path, msg)
        errors.append(f"{path}: {msg}")

    return errors
