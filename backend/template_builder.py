"""Детерминированная сборка JSON-шаблона wb-mqtt-serial из массива регистров."""

import re

from models import BuildRequest, DeviceInfo, Register, RegisterGroup


def _make_group_id(group: str) -> str:
    """Генерация id группы из названия: 'Power Meters' → 'g_power_meters'."""
    slug = re.sub(r"[^a-z0-9]+", "_", group.lower()).strip("_")
    return f"g_{slug}"


def _build_groups(
    registers: list[Register],
    request_groups: list[RegisterGroup],
) -> list[dict]:
    """Собирает список групп.

    Если в запросе переданы группы — использует их.
    Иначе — строит из регистров, сохраняя порядок первого появления.
    """
    if request_groups:
        sorted_groups = sorted(request_groups, key=lambda g: g.order)
        result = []
        for g in sorted_groups:
            entry: dict = {"title": g.title, "id": g.id}
            if g.description:
                entry["description"] = g.description
            if g.parent_group:
                entry["group"] = g.parent_group
            if g.ui_options:
                entry["ui_options"] = g.ui_options
            result.append(entry)
        return result

    seen: dict[str, dict] = {}
    for reg in registers:
        gid = _make_group_id(reg.group)
        if gid not in seen:
            seen[gid] = {
                "title": reg.group_title or reg.group,
                "id": gid,
            }
    return list(seen.values())


def _format_address(address: int | str) -> int | str:
    """Адрес: строка с ':' для побитового, иначе int."""
    if isinstance(address, str) and ":" in address:
        return address
    if isinstance(address, str):
        try:
            return int(address)
        except ValueError:
            return address
    return address


def _get_enum_data(reg: Register) -> tuple[list[int] | None, list[str] | None]:
    """Извлекает enum данные: приоритет у enum_entries, иначе enum + enum_titles."""
    if reg.enum_entries:
        values = [e.value for e in reg.enum_entries]
        titles = [e.title for e in reg.enum_entries]
        return values, titles
    return reg.enum, reg.enum_titles


def _make_channel_id(name: str) -> str:
    """Генерация id канала из имени: 'Active Power' → 'active_power'."""
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")



def _build_channel(reg: Register, group_id: str, channel_id: str) -> dict:
    """Собирает описание канала из регистра."""
    ch: dict = {
        "id": channel_id,
        "name": reg.name,
        "reg_type": reg.reg_type,
        "address": _format_address(reg.address),
        "group": group_id,
    }

    # type: не выводим дефолтное значение "value"
    if reg.channel_type and reg.channel_type != "value":
        ch["type"] = reg.channel_type

    # format: не выводим дефолтное значение "u16"
    if reg.format and reg.format != "u16":
        ch["format"] = reg.format

    if not reg.enabled:
        ch["enabled"] = False

    # read_only (с подчёркиванием — формат wb-mqtt-serial для каналов)
    if reg.read_only:
        ch["read_only"] = True

    if reg.sporadic:
        ch["sporadic"] = True

    if reg.fw:
        ch["fw"] = reg.fw

    if reg.units:
        ch["units"] = reg.units

    if reg.scale != 1:
        ch["scale"] = reg.scale

    if reg.offset != 0:
        ch["offset"] = reg.offset

    # readonly (без подчёркивания — альтернативный формат)
    if reg.readonly and not reg.read_only:
        ch["readonly"] = True

    if reg.error_value is not None:
        ch["error_value"] = reg.error_value

    if reg.word_order is not None:
        ch["word_order"] = reg.word_order

    if reg.byte_order is not None:
        ch["byte_order"] = reg.byte_order

    if reg.string_data_size is not None:
        ch["string_data_size"] = reg.string_data_size

    if reg.condition is not None:
        ch["condition"] = reg.condition

    if reg.round_to is not None:
        ch["round_to"] = reg.round_to

    if reg.on_value is not None:
        ch["on_value"] = reg.on_value

    if reg.off_value is not None:
        ch["off_value"] = reg.off_value

    enum_values, enum_titles = _get_enum_data(reg)
    if enum_values is not None:
        ch["enum"] = enum_values
        if enum_titles is not None:
            ch["enum_titles"] = enum_titles

    if reg.channel_type == "range":
        if reg.min is not None:
            ch["min"] = reg.min
        if reg.max is not None:
            ch["max"] = reg.max

    return ch


def _make_param_id(name: str) -> str:
    """Генерация id параметра из имени: 'Baud Rate' → 'baud_rate'."""
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def _build_parameter(reg: Register, group_id: str, order: int) -> tuple[str, dict]:
    """Собирает описание параметра из регистра. Возвращает (id, dict)."""
    # Используем оригинальный ID если есть, иначе генерируем из имени
    param_id = reg.original_channel_id or _make_param_id(reg.name)

    param: dict = {
        "title": reg.name,
        "address": _format_address(reg.address),
        "reg_type": reg.reg_type,
        "group": group_id,
        "order": order,
    }

    if reg.description:
        param["description"] = reg.description

    if reg.format and reg.format != "u16":
        param["format"] = reg.format

    if reg.required:
        param["required"] = True

    enum_values, enum_titles = _get_enum_data(reg)
    if enum_values is not None:
        param["enum"] = enum_values
        if enum_titles is not None:
            param["enum_titles"] = enum_titles
        if reg.default_value is not None:
            param["default"] = reg.default_value
        else:
            param["default"] = enum_values[0] if enum_values else 0
    else:
        if reg.default_value is not None:
            param["default"] = reg.default_value
        if reg.min is not None:
            param["min"] = reg.min
        if reg.max is not None:
            param["max"] = reg.max

    if reg.scale != 1:
        param["scale"] = reg.scale

    if reg.offset != 0:
        param["offset"] = reg.offset

    if reg.condition is not None:
        param["condition"] = reg.condition

    if reg.word_order is not None:
        param["word_order"] = reg.word_order

    if reg.byte_order is not None:
        param["byte_order"] = reg.byte_order

    if reg.round_to is not None:
        param["round_to"] = reg.round_to

    if reg.readonly:
        param["readonly"] = True

    if reg.fw:
        param["fw"] = reg.fw

    return param_id, param


def _build_translations(
    registers: list[Register],
    groups: list[dict],
    request_groups: list[RegisterGroup],
    device_info: DeviceInfo,
    title_key: str,
) -> tuple[dict, list[str]]:
    """Собирает секцию translations из данных регистров и групп.

    EN: только записи где key != value (description ключи, enum ключи, name overrides).
    Остальные языки: все переводы.

    Returns:
        Кортеж (translations_dict, warnings_list).
    """
    warnings: list[str] = []

    # Собираем все языки
    all_langs: set[str] = set()

    for reg in registers:
        if reg.translations:
            all_langs.update(k for k in reg.translations.keys() if k != "en")
        if reg.enum_entries:
            for entry in reg.enum_entries:
                if entry.translations:
                    all_langs.update(k for k in entry.translations.keys() if k != "en")

    if request_groups:
        for rg in request_groups:
            if rg.translations:
                all_langs.update(k for k in rg.translations.keys() if k != "en")

    # Инициализация словарей: en + все найденные языки
    result: dict[str, dict[str, str]] = {"en": {}}
    for lang in sorted(all_langs):
        result[lang] = {}

    def _set_translation(lang: str, key: str, value: str) -> None:
        """Устанавливает перевод с проверкой конфликтов."""
        existing = result[lang].get(key)
        if existing is not None and existing != value:
            warnings.append(
                f"Конфликт перевода [{lang}]: \"{key}\" → \"{existing}\" vs \"{value}\""
            )
        result[lang][key] = value

    # Заголовок шаблона — используем сохранённые переводы если есть
    if device_info.title_translations:
        for lang, text in device_info.title_translations.items():
            if lang in result:
                result[lang][title_key] = text
            elif lang == "en":
                result["en"][title_key] = text
        # Если EN не было в title_translations, ставим имя устройства
        if "en" not in device_info.title_translations:
            result["en"][title_key] = device_info.name
        # Добавляем заголовок в языки, которых нет в title_translations
        for lang in all_langs:
            if lang not in device_info.title_translations:
                result[lang][title_key] = device_info.name
    else:
        result["en"][title_key] = device_info.name
        for lang in all_langs:
            result[lang][title_key] = device_info.name

    # Группы
    if request_groups:
        for rg in request_groups:
            group_title = rg.title

            # EN: добавляем title группы только если есть EN override
            en_tr = rg.translations.get("en") if rg.translations else None
            if en_tr and en_tr.title:
                result["en"][group_title] = en_tr.title

            # EN: добавляем description ключ → EN текст (если есть)
            if rg.description and en_tr and en_tr.description:
                result["en"][rg.description] = en_tr.description

            # Другие языки
            for lang in all_langs:
                tr = rg.translations.get(lang) if rg.translations else None
                if tr and tr.title:
                    _set_translation(lang, group_title, tr.title)
                if rg.description and tr and tr.description:
                    _set_translation(lang, rg.description, tr.description)
    else:
        for reg in registers:
            gid = _make_group_id(reg.group)
            title = reg.group_title or reg.group
            for g in groups:
                if g["id"] == gid:
                    title = g["title"]
                    break
            # Не добавляем self-referential в EN
            for lang in all_langs:
                result[lang][title] = title

    # Каналы и параметры
    for reg in registers:
        # EN: добавляем имя только если есть EN override (key != value)
        en_tr = reg.translations.get("en") if reg.translations else None
        if en_tr and en_tr.name:
            result["en"][reg.name] = en_tr.name

        # Другие языки
        for lang in all_langs:
            tr = reg.translations.get(lang) if reg.translations else None
            if tr and tr.name:
                _set_translation(lang, reg.name, tr.name)

        # Description (только для параметров)
        if reg.description and reg.is_parameter:
            # EN: добавляем description ключ → EN текст (если есть)
            if en_tr and en_tr.description:
                result["en"][reg.description] = en_tr.description
            for lang in all_langs:
                tr = reg.translations.get(lang) if reg.translations else None
                if tr and tr.description:
                    _set_translation(lang, reg.description, tr.description)

        # Enum titles
        if reg.enum_entries:
            for entry in reg.enum_entries:
                # EN: добавляем только если есть EN override (key != value)
                en_entry_tr = entry.translations.get("en") if entry.translations else None
                if en_entry_tr:
                    result["en"][entry.title] = en_entry_tr

                for lang in all_langs:
                    entry_tr = entry.translations.get(lang) if entry.translations else None
                    if entry_tr:
                        _set_translation(lang, entry.title, entry_tr)

    # Убираем EN записи где key == value (бесполезные self-referential)
    result["en"] = {k: v for k, v in result["en"].items() if k != v}

    # Убираем языки без реальных уникальных переводов:
    # запись считается уникальной если key != value И такой записи нет в EN
    en = result["en"]
    for lang in list(result.keys()):
        if lang == "en":
            continue
        has_unique = any(
            k != v and en.get(k) != v
            for k, v in result[lang].items()
        )
        if not has_unique:
            del result[lang]

    return result, warnings


def build_template(request: BuildRequest) -> dict:
    """Собирает готовый JSON-шаблон wb-mqtt-serial из BuildRequest.

    Каналы: включаются все (disabled получают "enabled": false — драйвер не опрашивает, но можно включить).
    Параметры: только enabled (в wb-mqtt-serial нет флага enabled для параметров).
    """
    device_info = request.device_info
    request_groups = request.groups or []

    # Каналы: включаем все (disabled получат "enabled": false в шаблоне)
    # Параметры: только enabled (в wb-mqtt-serial нет enabled для параметров)
    channels_regs = [r for r in request.registers if not r.is_parameter]
    params_regs = [r for r in request.registers if r.is_parameter and r.enabled]
    registers = channels_regs + params_regs

    # Группы
    groups = _build_groups(registers, request_groups)

    # Каналы (с уникальными id)
    channels = []
    used_channel_ids: set[str] = set()
    for reg in channels_regs:
        group_id = _make_group_id(reg.group) if not request_groups else reg.group
        # Проверяем, существует ли group_id в списке групп
        group_ids = {g["id"] for g in groups}
        if group_id not in group_ids:
            group_id = _make_group_id(reg.group)
        # ID: используем оригинальный если есть, иначе генерируем
        ch_id = reg.original_channel_id or _make_channel_id(reg.name)
        original_ch_id = ch_id
        counter = 2
        while ch_id in used_channel_ids:
            ch_id = f"{original_ch_id}_{counter}"
            counter += 1
        used_channel_ids.add(ch_id)
        channels.append(_build_channel(reg, group_id, ch_id))

    # Параметры
    parameters: dict[str, dict] = {}
    for idx, reg in enumerate(params_regs):
        group_id = _make_group_id(reg.group) if not request_groups else reg.group
        group_ids = {g["id"] for g in groups}
        if group_id not in group_ids:
            group_id = _make_group_id(reg.group)
        # Используем оригинальный order если сохранён, иначе последовательный
        order = reg.param_order if reg.param_order is not None else idx
        param_id, param = _build_parameter(reg, group_id, order)
        # Уникальность id: при дубле добавляем суффикс
        original_id = param_id
        counter = 2
        while param_id in parameters:
            param_id = f"{original_id}_{counter}"
            counter += 1
        parameters[param_id] = param

    # Ключ заголовка шаблона
    device_type = device_info.id or "unknown"
    title_key = device_info.title_key or f"{device_type}_template_title"

    # Переводы
    translations, translation_warnings = _build_translations(
        registers, groups, request_groups, device_info, title_key,
    )

    # Сборка итогового шаблона
    template: dict = {
        "device_type": device_type,
        "title": title_key,
    }

    if device_info.device_group:
        template["group"] = device_info.device_group

    # hw section (для roundtrip)
    if device_info.hw:
        template["hw"] = device_info.hw

    device_dict: dict = {
        "name": device_info.name,
        "id": device_info.id,
    }

    # Device-level properties (для roundtrip)
    if device_info.max_read_registers is not None:
        device_dict["max_read_registers"] = device_info.max_read_registers
    if device_info.response_timeout_ms is not None:
        device_dict["response_timeout_ms"] = device_info.response_timeout_ms
    if device_info.frame_timeout_ms is not None:
        device_dict["frame_timeout_ms"] = device_info.frame_timeout_ms
    if device_info.enable_wb_continuous_read is not None:
        device_dict["enable_wb_continuous_read"] = device_info.enable_wb_continuous_read

    device_dict["groups"] = groups
    device_dict["channels"] = channels
    device_dict["parameters"] = parameters
    device_dict["translations"] = translations

    template["device"] = device_dict

    if translation_warnings:
        template["_warnings"] = translation_warnings

    return template
