"""Импорт существующих JSON/Jinja шаблонов wb-mqtt-serial в формат редактора."""

import json
import re

import jinja2
from jinja2.sandbox import SandboxedEnvironment, SecurityError

from serial_values import numeric_value, parse_address, parse_number
from user_errors import UserError

# Шаблон приходит от пользователя, а обычный Environment исполняет из него любой код
# (`cycler.__init__.__globals__.os.popen`). Immutable-вариант не подходит — запрещает
# list.append, на котором держится config-wb-mcm8.json.jinja.
_JINJA_ENV = SandboxedEnvironment(undefined=jinja2.Undefined)

# Самый крупный боевой .json.jinja — 124 КБ. На обычный JSON лимита нет: там бывает
# до 1.8 МБ, а разбор JSON код не исполняет.
MAX_JINJA_SOURCE_CHARS = 1024 * 1024


class TemplateImportError(UserError):
    """Шаблон нельзя импортировать: ключ локализации плюс русский текст в `detail`."""


# Опциональные поля, которые копируются из канала/параметра в регистр as-is
_OPTIONAL_FIELDS = (
    "condition", "error_value", "word_order", "byte_order",
    "string_data_size", "round_to", "on_value", "off_value", "min", "max",
)

# Дополнительные поля для roundtrip
_ROUNDTRIP_FIELDS = (
    "sporadic", "read_only", "readonly", "required", "fw",
)


def _extract_register_translations(
    name: str,
    description: str | None,
    translations: dict[str, dict[str, str]],
) -> dict[str, dict[str, str]] | None:
    """Извлекает переводы для регистра из секции translations шаблона.

    Возвращает {lang: {name?, description?}} или None если переводов нет.
    Включает EN для записей где key != value (name overrides, description keys).
    """
    result: dict[str, dict[str, str]] = {}
    for lang, lang_dict in translations.items():
        tr: dict[str, str] = {}
        if name in lang_dict and lang_dict[name] != name:
            tr["name"] = lang_dict[name]
        if description and description in lang_dict and lang_dict[description] != description:
            tr["description"] = lang_dict[description]
        if tr:
            result[lang] = tr
    return result or None


def _build_enum_entries(
    enum_values: list[int],
    enum_titles: list[str] | None,
    translations: dict[str, dict[str, str]],
) -> list[dict]:
    """Строит enum_entries из enum + enum_titles + translations."""
    entries: list[dict] = []
    titles = enum_titles or [str(v) for v in enum_values]
    for i, value in enumerate(enum_values):
        title = titles[i] if i < len(titles) else str(value)
        entry: dict = {"value": value, "title": title}
        entry_translations: dict[str, str] = {}
        for lang, lang_dict in translations.items():
            if title in lang_dict and lang_dict[title] != title:
                entry_translations[lang] = lang_dict[title]
        if entry_translations:
            entry["translations"] = entry_translations
        entries.append(entry)
    return entries


def _extract_group_translations(
    title: str,
    description: str | None,
    translations: dict[str, dict[str, str]],
) -> dict[str, dict[str, str]] | None:
    """Извлекает переводы для группы из секции translations шаблона.

    Включает EN для записей где key != value (description keys с реальным EN текстом).
    """
    result: dict[str, dict[str, str]] = {}
    for lang, lang_dict in translations.items():
        tr: dict[str, str] = {}
        if title in lang_dict and lang_dict[title] != title:
            tr["title"] = lang_dict[title]
        if description and description in lang_dict and lang_dict[description] != description:
            tr["description"] = lang_dict[description]
        if tr:
            result[lang] = tr
    return result or None


# Драйвер ждёт здесь число, а шаблон приносит и строку — с точкой или запятой.
# У `on_value` и `off_value` hex законен, parse_number его не трогает
_NUMERIC_FIELDS = frozenset({"round_to", "string_data_size", "on_value", "off_value"})

# Лимиты в редакторе всегда число, поэтому hex разворачиваем. Неразобранную запись
# не переносим — регистр важнее одного поля
_LIMIT_FIELDS = frozenset({"min", "max"})


def _copy_optional_fields(source: dict, target: dict, fields: tuple[str, ...] = _OPTIONAL_FIELDS) -> None:
    """Копирует опциональные поля из source в target, если они не None."""
    for field in fields:
        value = source.get(field)
        if value is None:
            continue
        if field in _LIMIT_FIELDS:
            number = numeric_value(value)
            if number is not None:
                target[field] = number
            continue
        target[field] = parse_number(value) if field in _NUMERIC_FIELDS else value


def _to_register(
    source: dict,
    translations: dict[str, dict[str, str]],
    *,
    is_parameter: bool,
    name_key: str = "name",
    original_id: str | None = None,
) -> dict:
    """Общая конвертация channel/parameter шаблона в Register редактора."""
    name = source.get(name_key, "")
    description = source.get("description")
    reg: dict = {
        "id": original_id or re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "unknown",
        "name": name,
        "address": parse_address(source.get("address", 0)),
        "reg_type": source.get("reg_type", "holding"),
        "channel_type": source.get("type", "value"),
        "group": source.get("group", "general"),
        "is_parameter": is_parameter,
        "enabled": source.get("enabled", True),
        "scale": parse_number(source.get("scale", 1)),
        "offset": parse_number(source.get("offset", 0)),
    }

    # format: сохраняем только если явно задан в оригинале
    if "format" in source:
        reg["format"] = source["format"]
    else:
        reg["format"] = "u16"

    # access: на основе read_only и readonly
    if source.get("read_only") or source.get("readonly"):
        reg["access"] = "read"
    else:
        reg["access"] = "readwrite"

    if description:
        reg["description"] = description
    if source.get("units"):
        reg["units"] = source["units"]

    _copy_optional_fields(source, reg)

    # Roundtrip поля
    _copy_optional_fields(source, reg, _ROUNDTRIP_FIELDS)

    # Сохраняем оригинальный ID канала/параметра для roundtrip
    if original_id:
        reg["original_channel_id"] = original_id
    elif source.get("id"):
        reg["original_channel_id"] = source["id"]

    # default (только у параметров, в шаблоне ключ "default", в редакторе "default_value")
    if source.get("default") is not None:
        reg["default_value"] = source["default"]

    # order параметра (для roundtrip)
    if source.get("order") is not None:
        reg["param_order"] = source["order"]

    # Enum
    if source.get("enum") is not None:
        reg["enum_entries"] = _build_enum_entries(
            source["enum"], source.get("enum_titles"), translations,
        )

    # Переводы (включая EN где key != value)
    tr = _extract_register_translations(name, description, translations)
    if tr:
        reg["translations"] = tr

    return reg


def _channel_to_register(ch: dict, translations: dict[str, dict[str, str]]) -> dict:
    """Конвертирует channel шаблона в Register редактора."""
    return _to_register(ch, translations, is_parameter=False)


def _parameter_to_register(
    param_id: str,
    param: dict,
    translations: dict[str, dict[str, str]],
) -> dict:
    """Конвертирует parameter шаблона в Register редактора."""
    # В parameters имя хранится в "title", а не "name"
    if "title" in param:
        return _to_register(param, translations, is_parameter=True, name_key="title", original_id=param_id)
    return _to_register({**param, "name": param_id}, translations, is_parameter=True, original_id=param_id)


def import_template(raw: dict) -> dict:
    """Обратное преобразование JSON-шаблона wb-mqtt-serial в формат редактора.

    Возвращает {device_info, registers, groups} — тот же формат что /api/analyze.
    """
    device = raw.get("device", {})

    # Валидация: проверяем что это шаблон wb-mqtt-serial
    has_channels = bool(device.get("channels"))
    has_parameters = bool(device.get("parameters"))
    has_device_type = bool(raw.get("device_type") or device.get("id"))
    if not has_channels and not has_parameters and not has_device_type:
        raise TemplateImportError("serverError.importNotTemplate")

    translations = device.get("translations", {})

    # DeviceInfo
    device_name = device.get("name", raw.get("device_type", ""))
    device_id = device.get("id", raw.get("device_type", ""))
    device_group = raw.get("group")

    # Оригинальный title key
    title_key = raw.get("title", "")

    # device.name из шаблона — короткое имя (например "WB-UPS v.3").
    # НЕ подменяем его переводом title key (который может быть длиннее).
    # Если device.name пуст — пытаемся достать из translations или title.
    if not device_name:
        if title_key and "en" in translations and title_key in translations["en"]:
            device_name = translations["en"][title_key]
        elif title_key and not title_key.endswith("_template_title"):
            device_name = title_key

    # Извлекаем переводы заголовка для всех языков
    title_translations: dict[str, str] = {}
    if title_key:
        for lang, lang_dict in translations.items():
            if title_key in lang_dict:
                title_translations[lang] = lang_dict[title_key]

    device_info: dict = {
        "name": device_name,
        "id": device_id,
    }
    if device_group:
        device_info["device_group"] = device_group
    if title_key:
        device_info["title_key"] = title_key
    if title_translations:
        device_info["title_translations"] = title_translations

    # Device-level properties (для roundtrip)
    if raw.get("hw"):
        device_info["hw"] = raw["hw"]
    for prop in ("max_read_registers", "response_timeout_ms", "frame_timeout_ms", "enable_wb_continuous_read"):
        if device.get(prop) is not None:
            device_info[prop] = device[prop]

    # Groups
    raw_groups = device.get("groups", [])
    groups: list[dict] = []
    for i, g in enumerate(raw_groups):
        group: dict = {
            "id": g.get("id", f"g_{i}"),
            "title": g.get("title", ""),
            "order": i,
        }
        if g.get("description"):
            group["description"] = g["description"]
        # Вложенные группы — parent group
        if g.get("group"):
            group["parent_group"] = g["group"]
        # UI options
        if g.get("ui_options"):
            group["ui_options"] = g["ui_options"]
        tr = _extract_group_translations(g.get("title", ""), g.get("description"), translations)
        if tr:
            group["translations"] = tr
        groups.append(group)

    # Channels → Register[]
    registers: list[dict] = []
    for ch in device.get("channels", []):
        registers.append(_channel_to_register(ch, translations))

    # Parameters → Register[]
    raw_params = device.get("parameters", {})
    if isinstance(raw_params, dict):
        # parameters как dict {id: param}
        for param_id, param in raw_params.items():
            registers.append(_parameter_to_register(param_id, param, translations))
    elif isinstance(raw_params, list):
        # parameters как list (некоторые шаблоны используют массив)
        for param in raw_params:
            raw_title = param.get("title", param.get("name", "param")).lower()
            param_id = param.get("id") or re.sub(r"[^a-z0-9]+", "_", raw_title).strip("_")
            registers.append(_parameter_to_register(param_id, param, translations))

    return {
        "device_info": device_info,
        "registers": registers,
        "groups": groups,
    }


def _extract_with_variables(text: str) -> dict[str, str]:
    """Извлекает переменные из {% with var = "value", ... %} блока."""
    result: dict[str, str] = {}
    match = re.search(r'\{%\s*with\b(.*?)%\}', text, re.DOTALL)
    if not match:
        return result
    body = match.group(1)
    # Парсим присваивания: var = "value" или var = true/false
    for m in re.finditer(r'(\w+)\s*=\s*(?:"([^"]*?)"|(\w+))', body):
        key = m.group(1)
        result[key] = m.group(2) if m.group(2) is not None else m.group(3)
    return result


def _extract_include_filename(text: str) -> str | None:
    """Извлекает имя файла из {% include "filename" %}."""
    match = re.search(r'\{%\s*include\s+"([^"]+)"', text)
    return match.group(1) if match else None


def import_jinja_template(text: str) -> dict:
    """Рендерит Jinja-шаблон с пустым контекстом → JSON → import_template().

    Если шаблон использует {% include %}, извлекает device_info из {% with %}
    и возвращает пустой набор регистров с пометкой об include.
    """
    if len(text) > MAX_JINJA_SOURCE_CHARS:
        raise TemplateImportError(
            "serverError.importJinjaTooLarge", max=MAX_JINJA_SOURCE_CHARS // (1024 * 1024),
        )

    try:
        rendered = _JINJA_ENV.from_string(text).render()
        raw = json.loads(rendered)
        return import_template(raw)
    except SecurityError as e:
        raise TemplateImportError("serverError.importJinjaUnsafe") from e
    except OverflowError as e:
        # Ресурсные лимиты песочницы (range больше MAX_RANGE) не наследуют
        # TemplateError, поэтому им нужна своя ветка
        raise TemplateImportError("serverError.importJinjaLimit", error=str(e)) from e
    except (jinja2.TemplateNotFound, TypeError):
        # Шаблон использует {% include %} — извлекаем что можно из {% with %}.
        # Эта ветка и SecurityError выше — подклассы TemplateError, поэтому обе
        # обязаны стоять до общей ниже.
        variables = _extract_with_variables(text)
        include_file = _extract_include_filename(text)

        device_info: dict[str, str] = {
            "name": variables.get("title_en") or variables.get("device_name", ""),
            "id": variables.get("device_id") or variables.get("device_type", ""),
        }
        if variables.get("group"):
            device_info["device_group"] = variables["group"]

        return {
            "device_info": device_info,
            "registers": [],
            "groups": [],
            "include": include_file,
        }
    except jinja2.TemplateError as e:
        # Ошибка в файле пользователя, а не наши внутренности — текст показываем,
        # иначе автор шаблона не поймёт, что чинить
        lineno = getattr(e, "lineno", None)
        if lineno:
            raise TemplateImportError(
                "serverError.importJinjaErrorLine", line=lineno, error=str(e),
            ) from e
        raise TemplateImportError("serverError.importJinjaError", error=str(e)) from e


def _strip_json_comments(text: str) -> str:
    """Удаляет однострочные комментарии (//) из JSON, не трогая строки.

    Удаляет как строки, начинающиеся с //, так и inline-комментарии после значений.
    """
    # [ \t]*, а не \s*: \s матчит перевод строки, и на пустых строках разбор
    # становился квадратичным, а сюда файл приходит без потолка размера
    # Удаляем строки, начинающиеся с комментария
    text = re.sub(r'^[ \t]*//.*$', '', text, flags=re.MULTILINE)
    # Удаляем inline-комментарии: значение // комментарий
    # Ищем // которые НЕ внутри строк (упрощённо: после числа/true/false/null)
    text = re.sub(r'(\b\d+|true|false|null)[ \t]*//.*$', r'\1', text, flags=re.MULTILINE)
    return text


def detect_and_import(content: bytes, filename: str) -> dict:
    """Определяет формат файла и импортирует шаблон.

    Jinja определяется по расширению .json.jinja или по наличию '{%' в содержимом.
    Поддерживает JSON с комментариями (//).
    """
    text = content.decode("utf-8")

    is_jinja = filename.endswith(".json.jinja") or "{%" in text

    if is_jinja:
        return import_jinja_template(text)
    else:
        cleaned = _strip_json_comments(text)
        raw = json.loads(cleaned)
        return import_template(raw)
