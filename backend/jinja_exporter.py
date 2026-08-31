"""Экспорт JSON-шаблона wb-mqtt-serial в .json.jinja с обнаружением паттернов.

Обнаруживает повторяющиеся структуры в channels, groups, parameters и translations:
- Каналы (channels) — по полю name, с поддержкой шаблонизируемых полей (group, condition)
- Каналы с вариантами (sporadic) — вложенный цикл по вариантам
- Каналы со строковыми циклами — группы с одинаковой структурой, но различающимся
  словом/фрагментом в имени (например "Button Single Press Counter",
  "Button Long Press Counter"...)
- Группы (groups) — по полю id
- Параметры (parameters) — по ключу dict
- Переводы (translations) — по ключам dict внутри каждого языка

Если обнаружены паттерны с одинаковыми count и start_num — объединяет под одной
переменной Jinja (например INPUTS_NUMBER). Иначе — отдельные переменные.

Число может быть в любой позиции: "Ch 1", "Input 1 state", "DS18B20 Input 1".
Минимум 2 элемента для паттерна.
"""

import itertools
import json
import re
from collections import defaultdict
from typing import Any

from serial_values import decimal_address

_PLACEHOLDER = "\x00"

# Сколько чисел в одной строке рассматриваем как кандидаты на подстановку, см. _extract_number_variants
MAX_NUMBER_VARIANTS = 16

# Поля, которые могут содержать варьирующийся номер и шаблонизируются
_CHANNEL_TEMPLATED_FIELDS = {"group", "condition"}
_GROUP_TEMPLATED_FIELDS = {"title", "description", "group"}
_PARAM_TEMPLATED_FIELDS = {"group", "condition", "description"}

# Поля, исключаемые из сравнения сигнатур
_CHANNEL_SKIP_FIELDS = {"name", "address", "enabled", "id"}
_PARAM_SKIP_FIELDS = {"address", "enabled", "id"}

# Поля, по которым каналы могут различаться в вариантах (sporadic/condition)
_VARIANT_FIELDS = {"sporadic", "condition"}


# ---------------------------------------------------------------------------
# Обобщённая детекция паттернов
# ---------------------------------------------------------------------------

def _extract_number_variants(text: str) -> list[tuple[str, int, int, int]]:
    """Извлекает варианты замены числа на placeholder в тексте.

    Возвращает кортежи (шаблон, число, start_позиция, end_позиция), не больше
    `MAX_NUMBER_VARIANTS` штук — на каждое число копируется вся строка, и без потолка
    имя канала из одних цифр даёт квадратичный расход памяти и времени. Обрезка не портит
    результат, а лишь уменьшает шанс собрать цикл.
    """
    variants = []
    for match in itertools.islice(re.finditer(r"\d+", text), MAX_NUMBER_VARIANTS):
        num = int(match.group())
        start, end = match.start(), match.end()
        template = text[:start] + _PLACEHOLDER + text[end:]
        variants.append((template, num, start, end))
    return variants


def _make_signature(item: dict, skip_fields: set[str],
                    templated_fields: set[str], num: int) -> str | None:
    """Создаёт сигнатуру элемента для группировки.

    В шаблонизируемых полях заменяет число num на placeholder.
    Остальные поля сравниваются как есть.
    Возвращает None если структура не подходит для паттерна.
    """
    parts = []
    for key in sorted(item.keys()):
        if key in skip_fields:
            continue
        value = item[key]
        if key in templated_fields and isinstance(value, str) and str(num) in value:
            # Заменяем число на placeholder для шаблонизируемого поля
            value = value.replace(str(num), _PLACEHOLDER)
        parts.append(f"{key}={json.dumps(value, ensure_ascii=False)}")
    return "|".join(parts)


def _detect_templated_fields(items: list[tuple[Any, int, dict]],
                             templated_fields_candidates: set[str]) -> dict[str, str]:
    """Определяет какие поля содержат варьирующийся номер.

    Возвращает dict: имя_поля -> шаблон (с placeholder вместо числа).
    """
    result: dict[str, str] = {}
    if not items:
        return result

    for field_name in templated_fields_candidates:
        # Проверяем что поле есть во всех элементах и содержит соответствующий номер
        all_have_field = True
        templates_set = set()
        for _, num, item in items:
            value = item.get(field_name)
            if value is None or not isinstance(value, str):
                all_have_field = False
                break
            if str(num) not in value:
                all_have_field = False
                break
            # Заменяем число на placeholder
            tpl = value.replace(str(num), _PLACEHOLDER, 1)
            templates_set.add(tpl)

        if all_have_field and len(templates_set) == 1:
            result[field_name] = templates_set.pop()

    return result


def _progression_addresses(items: list[dict], address_field: str = "address") -> list[int] | None:
    """Адреса группы каналов для свёртки в цикл. None — хотя бы один не годится."""
    addresses: list[int] = []
    for item in items:
        addr = decimal_address(item.get(address_field, 0))
        if addr is None:
            return None
        addresses.append(addr)
    return addresses


def _validate_address_progression(items: list[tuple[Any, int, dict]],
                                  address_field: str = "address") -> tuple[bool, int, int]:
    """Проверяет арифметическую прогрессию адресов.

    Возвращает (valid, base_address, step).
    """
    addresses = _progression_addresses([item for _, _, item in items], address_field)
    if addresses is None or len(addresses) < 2:
        return False, 0, 0

    steps = [addresses[i + 1] - addresses[i] for i in range(len(addresses) - 1)]
    if len(set(steps)) != 1:
        return False, 0, 0

    return True, addresses[0], steps[0]


def _generate_var_name(template: str, used_var_names: set[str]) -> str:
    """Генерирует уникальное имя переменной Jinja из шаблона."""
    clean = template.replace(_PLACEHOLDER, " ").strip()
    var_name = re.sub(r"[^A-Z0-9]+", "_", clean.upper()).strip("_") + "_NUMBER"
    # Переменная не может начинаться с цифры
    if var_name and var_name[0].isdigit():
        var_name = "_" + var_name
    # Уникализация
    base_var = var_name
    counter = 2
    while var_name in used_var_names:
        var_name = f"{base_var}_{counter}"
        counter += 1
    used_var_names.add(var_name)
    return var_name


def _try_detect_variants(
    group_items: list[tuple[Any, int, dict, str]],
    skip_fields: set[str],
    templated_fields_candidates: set[str],
    require_address_progression: bool,
) -> dict | None:
    """Пытается обнаружить мультивариантный паттерн (sporadic каналы).

    Если для каждого num есть K одинаковых копий (K >= 2) с разными значениями
    определённых полей (variant_fields), то это вложенный цикл.

    Возвращает dict с данными паттерна или None если не подходит.
    """
    # Группируем по num
    by_num: dict[int, list[tuple[Any, int, dict, str]]] = defaultdict(list)
    for item in group_items:
        by_num[item[1]].append(item)

    # Проверяем что каждый num имеет одинаковое количество вариантов >= 2
    variant_counts = [len(items) for items in by_num.values()]
    if len(set(variant_counts)) != 1:
        return None
    k = variant_counts[0]
    if k < 2:
        return None

    # Проверяем последовательность номеров
    nums = sorted(by_num.keys())
    if len(nums) < 2:
        return None
    if nums != list(range(nums[0], nums[0] + len(nums))):
        return None

    # Для каждого num сортируем варианты по порядку появления (по индексу)
    for num in nums:
        by_num[num].sort(key=lambda x: x[0])

    # Определяем variant_fields — поля, по которым отличаются варианты одного num
    # Берём первый num как эталон
    first_num = nums[0]
    first_variants = by_num[first_num]
    variant_fields: set[str] = set()
    for field_name in first_variants[0][2].keys():
        if field_name in skip_fields or field_name == "name":
            continue
        values = [v[2].get(field_name) for v in first_variants]
        if len(set(json.dumps(val, ensure_ascii=False) for val in values)) > 1:
            variant_fields.add(field_name)

    if not variant_fields:
        return None

    # Проверяем что для каждого num набор вариантных значений одинаков
    # (с заменой num на placeholder в шаблонизируемых полях)
    def _variant_signature(item: dict, num: int) -> str:
        """Сигнатура варианта (только вариантные поля)."""
        parts = []
        for f in sorted(variant_fields):
            val = item.get(f)
            if isinstance(val, str) and str(num) in val:
                val = val.replace(str(num), _PLACEHOLDER)
            parts.append(f"{f}={json.dumps(val, ensure_ascii=False)}")
        return "|".join(parts)

    def _base_signature(item: dict, num: int, tpl_fields: dict[str, str]) -> str:
        """Сигнатура базовых полей (без вариантных и skip)."""
        parts = []
        effective_skip = skip_fields | variant_fields | set(tpl_fields.keys())
        for key in sorted(item.keys()):
            if key in effective_skip or key == "name":
                continue
            parts.append(f"{key}={json.dumps(item[key], ensure_ascii=False)}")
        return "|".join(parts)

    # Собираем сигнатуры вариантов для эталонного num
    reference_variant_sigs = [
        _variant_signature(v[2], first_num) for v in first_variants
    ]

    # Проверяем что все num имеют те же вариантные сигнатуры
    for num in nums:
        variants = by_num[num]
        if len(variants) != k:
            return None
        variant_sigs = [_variant_signature(v[2], num) for v in variants]
        if variant_sigs != reference_variant_sigs:
            return None

    # Определяем шаблонизируемые поля (берём только первый вариант каждого num)
    first_of_each = [(v[0], v[1], v[2]) for num in nums for v in [by_num[num][0]]]
    tpl_fields = _detect_templated_fields(first_of_each, templated_fields_candidates)

    # Проверяем что базовые сигнатуры совпадают
    base_sigs = set()
    for num in nums:
        for v in by_num[num]:
            base_sigs.add(_base_signature(v[2], num, tpl_fields))
    if len(base_sigs) > 1:
        return None

    # Проверяем арифметическую прогрессию адресов (по первому варианту)
    base_address = 0
    address_step = 0
    if require_address_progression:
        valid, base_address, address_step = _validate_address_progression(first_of_each)
        if not valid:
            return None

    # Собираем все индексы (для каждого num все K вариантов)
    all_indices = []
    for num in nums:
        for v in by_num[num]:
            all_indices.append(v[0])

    # Собираем данные вариантов (значения вариантных полей для каждого варианта)
    # Используем первый num как прототип — вариантные значения из первого num
    # с заменой числа на placeholder в шаблонизируемых полях
    variants_data: list[dict[str, Any]] = []
    for vi in range(k):
        variant_item = by_num[first_num][vi][2]
        variant_vals = {}
        for f in sorted(variant_fields):
            val = variant_item.get(f)
            if isinstance(val, str) and str(first_num) in val:
                val = val.replace(str(first_num), _PLACEHOLDER)
            variant_vals[f] = val
        variants_data.append(variant_vals)

    # Собираем ключи (name) из эталона
    keys = [by_num[num][0][3] for num in nums]

    return {
        "count": len(nums),
        "start_num": nums[0],
        "base_address": base_address,
        "address_step": address_step,
        "indices": all_indices,
        "prototype": by_num[first_num][0][2],
        "templated_fields": tpl_fields,
        "keys": keys,
        "variants_data": variants_data,
        "variant_fields": variant_fields,
        "variants_count": k,
    }


def _detect_patterns_generic(
    items: list[tuple[Any, dict]],
    key_extractor: Any,
    skip_fields: set[str],
    templated_fields_candidates: set[str],
    require_address_progression: bool = True,
) -> list[dict]:
    """Обобщённая детекция паттернов.

    items -- список (ключ_элемента, элемент_dict). Ключ: index для channels,
    id для groups, dict-key для params.

    Поддерживает мультивариантные паттерны: когда для каждого num есть
    K копий с разными значениями определённых полей (sporadic, condition).

    Возвращает список паттернов:
    {
        "var_name": "...",
        "count": N,
        "start_num": 1,
        "base_address": 100,
        "address_step": 1,
        "name_prefix": "...",
        "name_suffix": "...",
        "indices": [...],
        "prototype": {...},
        "templated_fields": {"group": "gg_in\x00_channels", ...},
        "key_template": "...",
        "keys": [...],
        # Для вариантных паттернов:
        "variants_data": [{...}, {...}],  # значения по вариантным полям
        "variant_fields": {"sporadic", "condition"},
        "variants_count": 2,
    }
    """
    # Группируем по шаблону ключевого поля
    groups: dict[str, list[tuple[Any, int, dict, str]]] = defaultdict(list)

    for item_key, item_dict in items:
        key_value = key_extractor(item_key, item_dict)
        for template, num, start, end in _extract_number_variants(key_value):
            groups[template].append((item_key, num, item_dict, key_value))

    patterns = []
    used_indices: set[Any] = set()
    used_var_names: set[str] = set()

    # Сначала большие группы -- приоритет у паттернов с большим числом элементов
    sorted_groups = sorted(groups.items(), key=lambda x: len(x[1]), reverse=True)

    for template, group_items in sorted_groups:
        # Убираем элементы, уже включённые в другой паттерн
        group_items = [x for x in group_items if x[0] not in used_indices]
        if len(group_items) < 2:
            continue

        # Сортируем по числовому значению, потом по индексу (для стабильного порядка вариантов)
        group_items.sort(key=lambda x: (x[1], x[0]))

        # Проверяем последовательность номеров
        nums = [it[1] for it in group_items]
        unique_nums = sorted(set(nums))

        # Проверяем: есть ли дубликаты по num (мультивариантный случай)?
        has_duplicates = len(nums) != len(unique_nums)

        if has_duplicates:
            # Пробуем мультивариантный паттерн
            variant_result = _try_detect_variants(
                group_items, skip_fields, templated_fields_candidates,
                require_address_progression,
            )
            if variant_result is not None:
                # Разбиваем шаблон на prefix + suffix
                pos = template.index(_PLACEHOLDER)
                name_prefix = template[:pos]
                name_suffix = template[pos + len(_PLACEHOLDER):]
                var_name = _generate_var_name(template, used_var_names)

                variant_result["var_name"] = var_name
                variant_result["name_prefix"] = name_prefix
                variant_result["name_suffix"] = name_suffix
                variant_result["key_template"] = template

                used_indices.update(variant_result["indices"])
                patterns.append(variant_result)
            continue

        # Простой случай: уникальные номера
        if unique_nums != list(range(unique_nums[0], unique_nums[0] + len(unique_nums))):
            continue

        # Список для сигнатурной проверки: (key, num, item_dict)
        items_for_check = [(it[0], it[1], it[2]) for it in group_items]

        # Определяем шаблонизируемые поля
        tpl_fields = _detect_templated_fields(items_for_check, templated_fields_candidates)

        # Проверяем совпадение сигнатур (все поля кроме skip + шаблонизируемые)
        effective_skip = skip_fields | set(tpl_fields.keys())
        signatures = set()
        for _, num, item in items_for_check:
            sig = _make_signature(item, effective_skip, set(), num)
            signatures.add(sig)
        if len(signatures) > 1:
            continue

        # Проверяем арифметическую прогрессию адресов (если требуется)
        base_address = 0
        address_step = 0
        if require_address_progression:
            valid, base_address, address_step = _validate_address_progression(items_for_check)
            if not valid:
                continue

        # Всё проверено -- создаём паттерн
        indices = [it[0] for it in items_for_check]
        keys = [it[3] for it in group_items]
        used_indices.update(indices)

        # Разбиваем шаблон на prefix + suffix
        pos = template.index(_PLACEHOLDER)
        name_prefix = template[:pos]
        name_suffix = template[pos + len(_PLACEHOLDER):]

        var_name = _generate_var_name(template, used_var_names)

        prototype = items_for_check[0][2]

        patterns.append({
            "var_name": var_name,
            "count": len(items_for_check),
            "start_num": nums[0],
            "base_address": base_address,
            "address_step": address_step,
            "name_prefix": name_prefix,
            "name_suffix": name_suffix,
            "indices": indices,
            "prototype": prototype,
            "templated_fields": tpl_fields,
            "key_template": template,
            "keys": keys,
        })

    return patterns


# ---------------------------------------------------------------------------
# Детекция для каждой секции
# ---------------------------------------------------------------------------

def _detect_channel_patterns(channels: list[dict]) -> list[dict]:
    """Обнаруживает группы каналов с повторяющимися паттернами.

    Ищет числа в любой позиции имени (начало, середина, конец).
    Группирует каналы по шаблону (имя с числом, заменённым на placeholder).
    Валидирует: последовательные номера, арифметическая прогрессия адресов,
    совпадение остальных полей (с учётом шаблонизируемых полей group, condition).

    Поддерживает мультивариантные каналы (sporadic): когда для каждого num
    есть K копий с разными sporadic/condition.

    Возвращает список паттернов.
    """
    items = [(idx, ch) for idx, ch in enumerate(channels)]
    return _detect_patterns_generic(
        items=items,
        key_extractor=lambda idx, ch: ch.get("name", ""),
        skip_fields=_CHANNEL_SKIP_FIELDS,
        templated_fields_candidates=_CHANNEL_TEMPLATED_FIELDS,
        require_address_progression=True,
    )


def _detect_group_patterns(groups: list[dict]) -> list[dict]:
    """Обнаруживает паттерны в группах по полю id.

    Пример: группы g_in1...g_in8 с title "Input 1"..."Input 8".
    """
    items = [(idx, g) for idx, g in enumerate(groups)]
    return _detect_patterns_generic(
        items=items,
        key_extractor=lambda idx, g: g.get("id", ""),
        skip_fields={"id"},
        templated_fields_candidates=_GROUP_TEMPLATED_FIELDS,
        require_address_progression=False,
    )


def _detect_param_patterns(parameters: dict[str, dict]) -> list[dict]:
    """Обнаруживает паттерны в параметрах по ключу dict.

    Пример: in1_mode...in8_mode с address=9...16, group="g_in1"..."g_in8".
    """
    items = [(key, param) for key, param in parameters.items()]
    return _detect_patterns_generic(
        items=items,
        key_extractor=lambda key, param: key,
        skip_fields=_PARAM_SKIP_FIELDS,
        templated_fields_candidates=_PARAM_TEMPLATED_FIELDS,
        require_address_progression=True,
    )


# ---------------------------------------------------------------------------
# Детекция строковых паттернов (каналы с варьирующимся словом в имени)
# ---------------------------------------------------------------------------


def _find_common_prefix_suffix(names: list[str]) -> tuple[str, str, list[str]] | None:
    """Находит общий prefix и suffix для списка строк.

    Ищет самый длинный общий prefix и suffix, проверяет что границы
    совпадают со словами (пробел/начало/конец строки).
    Извлекает варьирующуюся среднюю часть.

    Возвращает (prefix, suffix, [varying_parts]) или None если не удалось.
    """
    if len(names) < 2:
        return None

    # Ищем общий prefix
    prefix = ""
    min_len = min(len(n) for n in names)
    for i in range(min_len):
        chars = {n[i] for n in names}
        if len(chars) == 1:
            prefix += names[0][i]
        else:
            break

    # Ищем общий suffix (с конца)
    suffix = ""
    for i in range(1, min_len + 1):
        chars = {n[-i] for n in names}
        if len(chars) == 1:
            suffix = names[0][-i] + suffix
        else:
            break

    # Проверяем что prefix + suffix не перекрываются
    if len(prefix) + len(suffix) > min_len:
        # Обрезаем suffix чтобы не перекрывался
        max_suffix = min_len - len(prefix)
        suffix = suffix[-max_suffix:] if max_suffix > 0 else ""

    # Обрезаем prefix до границы слова (заканчивается пробелом)
    # чтобы варьирующаяся часть была целым словом/словами
    if prefix and not prefix.endswith(" ") and prefix != "":
        # Ищем последний пробел
        last_space = prefix.rfind(" ")
        if last_space >= 0:
            prefix = prefix[:last_space + 1]
        else:
            # Нет пробела в prefix -- вся строка prefix + varying, что
            # означает варьирующаяся часть начинается с начала, плохо
            prefix = ""

    # Обрезаем suffix до границы слова (начинается с пробела)
    if suffix and not suffix.startswith(" ") and suffix != "":
        first_space = suffix.find(" ")
        if first_space >= 0:
            suffix = suffix[first_space:]
        else:
            suffix = ""

    # Извлекаем варьирующиеся части
    varying = []
    for n in names:
        middle = n[len(prefix):]
        if suffix:
            middle = middle[:-len(suffix)]
        varying.append(middle)

    # Варьирующиеся части должны быть непустыми и уникальными
    if not all(v for v in varying):
        return None
    if len(set(varying)) != len(varying):
        return None

    # Prefix или suffix должны быть непустыми (иначе строки полностью разные)
    if not prefix and not suffix:
        return None

    # Prefix и suffix вместе должны составлять значимую часть имени
    # (хотя бы 30% от средней длины) для исключения ложных срабатываний
    avg_len = sum(len(n) for n in names) / len(names)
    common_len = len(prefix) + len(suffix)
    if avg_len > 0 and common_len / avg_len < 0.3:
        return None

    return prefix, suffix, varying


def _make_string_signature(item: dict, skip_fields: set[str]) -> str:
    """Создаёт сигнатуру элемента для строковой группировки.

    Все поля кроме skip_fields сравниваются как есть.
    """
    parts = []
    for key in sorted(item.keys()):
        if key in skip_fields:
            continue
        parts.append(f"{key}={json.dumps(item[key], ensure_ascii=False)}")
    return "|".join(parts)


def _detect_string_channel_patterns(
    channels: list[dict],
    already_used_indices: set[int],
) -> list[dict]:
    """Обнаруживает строковые паттерны в каналах.

    Ищет группы каналов с одинаковой сигнатурой (все поля кроме name, address,
    id, enabled), где имена отличаются одним фрагментом (общий prefix + suffix),
    и адреса в арифметической прогрессии.

    Возвращает список строковых паттернов:
    {
        "type": "string_loop",
        "var_name": "BUTTON_PRESS_VALUES",
        "string_values": ["single", "long", "double", "shortlong"],
        "name_prefix": "Button ",
        "name_suffix": " Press Counter",
        "base_address": 464,
        "address_step": 16,
        "indices": [11, 12, 13, 14],
        "prototype": {...},
        "count": 4,
    }
    """
    skip_fields = {"name", "address", "enabled", "id"}

    # Группируем каналы по сигнатуре (все поля кроме name, address, id, enabled)
    sig_groups: dict[str, list[tuple[int, dict]]] = defaultdict(list)
    for idx, ch in enumerate(channels):
        if idx in already_used_indices:
            continue
        sig = _make_string_signature(ch, skip_fields)
        sig_groups[sig].append((idx, ch))

    patterns = []
    used_indices: set[int] = set()
    used_var_names: set[str] = set()

    # Минимум 3 элемента для строкового паттерна
    # (2 элемента -- слишком мало, порождает ложные срабатывания)
    _MIN_STRING_PATTERN_SIZE = 3

    # Сортируем по размеру группы (большие сначала)
    sorted_groups = sorted(sig_groups.items(), key=lambda x: len(x[1]), reverse=True)

    for sig, group_items in sorted_groups:
        # Убираем уже использованные
        group_items = [(idx, ch) for idx, ch in group_items if idx not in used_indices]
        if len(group_items) < _MIN_STRING_PATTERN_SIZE:
            continue

        names = [ch["name"] for _, ch in group_items]

        # Ищем общий prefix/suffix
        result = _find_common_prefix_suffix(names)
        if result is None:
            continue

        prefix, suffix, varying_parts = result

        # Проверяем что варьирующиеся части не содержат чисел
        # (числовые паттерны уже обработаны)
        # НО: допускаем строковые части, даже если в них нет чисел
        # Главное — что это не просто последовательные числа
        all_numeric = all(v.strip().isdigit() for v in varying_parts)
        if all_numeric:
            # Это числовой паттерн -- пропускаем, он уже обработан
            continue

        # Проверяем арифметическую прогрессию адресов
        addresses = _progression_addresses([ch for _, ch in group_items])
        if addresses is None or len(addresses) < 2:
            continue
        steps = [addresses[i + 1] - addresses[i] for i in range(len(addresses) - 1)]
        if len(set(steps)) != 1:
            continue
        base_address = addresses[0]
        address_step = steps[0]

        # Генерируем имя переменной
        # Берём из prefix/suffix значимые слова
        clean_parts = (prefix.strip() + " " + suffix.strip()).strip()
        var_name = re.sub(r"[^A-Z0-9]+", "_", clean_parts.upper()).strip("_") + "_VALUES"
        if var_name and var_name[0].isdigit():
            var_name = "_" + var_name
        # Убираем двойные подчёркивания
        var_name = re.sub(r"_+", "_", var_name)
        # Уникализация
        base_var = var_name
        counter = 2
        while var_name in used_var_names:
            var_name = f"{base_var}_{counter}"
            counter += 1
        used_var_names.add(var_name)

        indices = [idx for idx, _ in group_items]
        used_indices.update(indices)

        # Приводим варьирующиеся части к нижнему регистру для значений списка
        # (в Jinja шаблоне используем | capitalize для отображения)
        string_values = [v.lower() for v in varying_parts]

        # Проверяем: нужен ли capitalize при рендеринге?
        # Сравниваем оригинальные части с lower().capitalize()
        # Если все части — capitalize от lower-версии, используем | capitalize
        needs_capitalize = all(
            v == v.lower().capitalize() or v == v.lower()
            for v in varying_parts
        )

        # Определяем шаблон name: как подставляются значения
        # Если в оригинале "Button Single Press Counter", prefix="Button ",
        # suffix=" Press Counter", varying="Single"
        # То шаблон: "Button {{ val | capitalize }} Press Counter"
        # Но если varying уже capitalize — используем | capitalize
        # Если varying разнорегистровые — используем как есть
        if needs_capitalize and all(v[0].isupper() for v in varying_parts if v):
            name_filter = " | capitalize"
            string_values = [v.lower() for v in varying_parts]
        else:
            name_filter = ""
            string_values = varying_parts  # как есть

        patterns.append({
            "type": "string_loop",
            "var_name": var_name,
            "string_values": string_values,
            "name_prefix": prefix,
            "name_suffix": suffix,
            "name_filter": name_filter,
            "base_address": base_address,
            "address_step": address_step,
            "indices": indices,
            "prototype": group_items[0][1],
            "count": len(group_items),
        })

    return patterns


# ---------------------------------------------------------------------------
# Детекция паттернов в translations
# ---------------------------------------------------------------------------

def _detect_translation_patterns(
    translations: dict[str, dict[str, str]],
    all_patterns: list[dict],
) -> list[dict]:
    """Обнаруживает паттерны в ключах translations.

    Для каждого языка ищет ключи с числами, группирует по шаблону.
    Если ключи образуют последовательность (как в каналах) --
    сворачивает в for-цикл.

    Использует информацию из уже найденных паттернов (all_patterns)
    для привязки переменных.

    Возвращает список translation_pattern:
    {
        "var_name": "INPUT_NUMBER",
        "count": 8,
        "start_num": 1,
        "key_templates": [
            {"key_tpl": "Input \x00", "value_tpls": {"ru": "Вход \x00", "en": None}},
            ...
        ],
        "used_keys": {"Input 1", "Input 2", ...},
    }
    """
    if not translations:
        return []

    # Собираем все ключи по всем языкам
    all_keys: set[str] = set()
    for lang_data in translations.values():
        if isinstance(lang_data, dict):
            all_keys.update(lang_data.keys())

    # Группируем ключи по шаблону
    key_groups: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for key in all_keys:
        for template, num, _, _ in _extract_number_variants(key):
            key_groups[template].append((key, num))

    # Собираем info о существующих паттернах для привязки переменных
    existing_patterns: dict[tuple[int, int], str] = {}
    for p in all_patterns:
        sig = (p["count"], p["start_num"])
        if sig not in existing_patterns:
            existing_patterns[sig] = p["var_name"]

    result_patterns = []
    used_keys: set[str] = set()
    used_var_names: set[str] = {p["var_name"] for p in all_patterns}

    # Сортируем по размеру группы (большие сначала)
    sorted_key_groups = sorted(key_groups.items(), key=lambda x: len(x[1]), reverse=True)

    for template, keys_and_nums in sorted_key_groups:
        # Убираем уже использованные ключи
        keys_and_nums = [(k, n) for k, n in keys_and_nums if k not in used_keys]
        if len(keys_and_nums) < 2:
            continue

        # Сортируем по номеру
        keys_and_nums.sort(key=lambda x: x[1])
        nums = [n for _, n in keys_and_nums]
        unique_nums = sorted(set(nums))

        # Проверяем уникальность и последовательность
        if len(nums) != len(unique_nums):
            continue
        if unique_nums != list(range(unique_nums[0], unique_nums[0] + len(unique_nums))):
            continue

        count = len(unique_nums)
        start_num = unique_nums[0]

        # Для каждого языка собираем шаблоны значений
        value_tpls: dict[str, str | None] = {}
        for lang, lang_data in translations.items():
            if not isinstance(lang_data, dict):
                continue
            # Проверяем что все ключи есть в этом языке
            all_present = all(k in lang_data for k, _ in keys_and_nums)
            if not all_present:
                value_tpls[lang] = None
                continue

            # Собираем шаблоны значений (заменяем num на placeholder)
            tpl_set_tmp: set[str] = set()
            tpl_valid = True
            for key, num in keys_and_nums:
                val = lang_data[key]
                if isinstance(val, str) and str(num) in val:
                    tpl_set_tmp.add(val.replace(str(num), _PLACEHOLDER))
                else:
                    # Значение не содержит число -- не шаблонизируем
                    tpl_valid = False
                    break
            if tpl_valid and len(tpl_set_tmp) == 1:
                value_tpls[lang] = tpl_set_tmp.pop()
            else:
                value_tpls[lang] = None

        # Привязываем переменную
        sig = (count, start_num)
        if sig in existing_patterns:
            var_name = existing_patterns[sig]
        else:
            var_name = _generate_var_name(template, used_var_names)
            existing_patterns[sig] = var_name

        actual_keys = {k for k, _ in keys_and_nums}
        used_keys.update(actual_keys)

        result_patterns.append({
            "var_name": var_name,
            "count": count,
            "start_num": start_num,
            "key_template": template,
            "value_tpls": value_tpls,
            "used_keys": actual_keys,
        })

    return result_patterns


# ---------------------------------------------------------------------------
# Унификация переменных
# ---------------------------------------------------------------------------

def _unify_variables(
    channel_patterns: list[dict],
    group_patterns: list[dict],
    param_patterns: list[dict],
) -> dict[str, list[dict]]:
    """Объединяет паттерны с одинаковыми count и start_num под одной переменной.

    Возвращает dict: var_name -> список всех паттернов с этой переменной.
    Обновляет var_name в каждом паттерне.
    """
    # Собираем все паттерны с их характеристиками (count, start_num)
    all_patterns = []
    for p in channel_patterns:
        all_patterns.append(("channel", p))
    for p in group_patterns:
        all_patterns.append(("group", p))
    for p in param_patterns:
        all_patterns.append(("param", p))

    # Группируем по (count, start_num)
    by_signature: dict[tuple[int, int], list[tuple[str, dict]]] = defaultdict(list)
    for kind, p in all_patterns:
        sig = (p["count"], p["start_num"])
        by_signature[sig].append((kind, p))

    # Для каждой группы с одинаковым (count, start_num) -- выбираем одно имя переменной
    used_var_names: set[str] = set()
    result: dict[str, list[dict]] = {}

    for (count, start_num), group in by_signature.items():
        if len(group) > 1:
            # Несколько паттернов с одинаковыми count/start_num -- объединяем
            # Берём самое короткое имя или первое из каналов
            var_names = [p["var_name"] for _, p in group]
            # Предпочитаем имя из каналов или самое короткое
            chosen = min(var_names, key=len)
            # Уникализация
            base = chosen
            counter = 2
            while chosen in used_var_names:
                chosen = f"{base}_{counter}"
                counter += 1
            used_var_names.add(chosen)
            for _, p in group:
                p["var_name"] = chosen
            result[chosen] = [p for _, p in group]
        else:
            _, p = group[0]
            var = p["var_name"]
            base = var
            counter = 2
            while var in used_var_names:
                var = f"{base}_{counter}"
                counter += 1
            used_var_names.add(var)
            p["var_name"] = var
            result[var] = [p]

    return result


# ---------------------------------------------------------------------------
# Рендеринг Jinja
# ---------------------------------------------------------------------------

def _render_field_value(key: str, value: Any, templated_fields: dict[str, str],
                        num: int, start_num: int, var_name: str,
                        indent: str) -> str:
    """Рендерит значение поля, заменяя номер на {{ i }} в шаблонизируемых полях."""
    if key in templated_fields:
        # Заменяем placeholder на {{ i }}
        tpl = templated_fields[key]
        rendered_value = tpl.replace(_PLACEHOLDER, "{{ i }}")
        return f'"{key}": "{rendered_value}"'
    else:
        dumped = json.dumps(value, ensure_ascii=False)
        # Многострочные значения (вложенные объекты/массивы) -- с отступами
        if isinstance(value, (dict, list)):
            dumped = json.dumps(value, indent=4, ensure_ascii=False)
            lines = dumped.split("\n")
            if len(lines) > 1:
                dumped = lines[0] + "\n" + "\n".join(
                    f"{indent}    {line}" for line in lines[1:]
                )
        return f'"{key}": {dumped}'


def _render_address_expr(base_address: int, step: int,
                         start_num: int, var_name: str) -> str:
    """Рендерит выражение адреса в Jinja."""
    if step == 0:
        return str(base_address)
    elif step == 1:
        return f"{{{{ {base_address} + i - {start_num} }}}}"
    else:
        return f"{{{{ {base_address} + (i - {start_num}) * {step} }}}}"


def _render_variant_value(field_name: str, value: Any, is_string: bool = False) -> str:
    """Рендерит значение вариантного поля для внутреннего цикла.

    Для строковых полей (condition) подставляет значение переменной в кавычках.
    Для нестроковых (sporadic bool) подставляет как есть.
    """
    if isinstance(value, str):
        return f'"{value}"'
    elif isinstance(value, bool):
        return "true" if value else "false"
    else:
        return json.dumps(value, ensure_ascii=False)


def _render_channel_jinja(
    pattern: dict,
    indent: str = "            ",
    is_last_in_array: bool = True,
) -> str:
    """Рендерит Jinja for-цикл для группы каналов.

    Поддерживает вариантные каналы (sporadic): если паттерн содержит
    variants_data, рендерит вложенный цикл по вариантам.

    is_last_in_array -- этот паттерн последний в массиве channels
    (влияет на trailing comma).
    """
    proto = pattern["prototype"]
    var = pattern["var_name"]
    start = pattern["start_num"]
    base_addr = pattern["base_address"]
    step = pattern["address_step"]
    tpl_fields = pattern.get("templated_fields", {})
    variants_data = pattern.get("variants_data")
    variant_fields = pattern.get("variant_fields", set())

    lines = []
    lines.append(f'{{% for i in range({start}, {var} + {start}) -%}}')

    if variants_data:
        # Сохраняем ссылку на внешний loop для условных запятых
        lines.append('{% set outer_loop = loop -%}')
        # Вложенный цикл по вариантам
        # Строим список кортежей для внутреннего for
        variant_field_names = sorted(variant_fields)

        # Определяем тип каждого вариантного поля (str/bool/other)
        # для корректного рендеринга в JSON
        variant_field_types: dict[str, str] = {}
        for fname in variant_field_names:
            sample_val = variants_data[0][fname]
            if isinstance(sample_val, bool):
                variant_field_types[fname] = "bool"
            elif isinstance(sample_val, str) or (
                isinstance(sample_val, str) or _PLACEHOLDER in str(sample_val)
            ):
                variant_field_types[fname] = "str"
            else:
                variant_field_types[fname] = "other"

        # Формируем значения для каждого варианта
        # Все значения -- строки Jinja, которые при рендере дадут нужный JSON-фрагмент
        variant_tuples: list[str] = []
        for vdata in variants_data:
            vals = []
            for fname in variant_field_names:
                raw_val = vdata[fname]
                if isinstance(raw_val, str) and _PLACEHOLDER in raw_val:
                    # Строка с placeholder: используем Jinja конкатенацию ~
                    # Пример: "cond_a\x001" -> "cond_a"~i~"1"
                    # Пример: "cond_a\x00" -> "cond_a"~i|string
                    # Пример: "\x00_mode" -> i|string~"_mode"
                    parts = raw_val.split(_PLACEHOLDER)
                    segments: list[str] = []
                    for pi, part in enumerate(parts):
                        if pi > 0:
                            # Между частями вставляем i
                            if segments:
                                # Есть предыдущий сегмент -- конкатенация через ~
                                segments.append("~i|string")
                            else:
                                # Начинаем с i
                                segments.append("i|string")
                            if part:
                                segments.append(f'~"{part}"')
                        else:
                            if part:
                                segments.append(f'"{part}"')
                    jinja_str = "".join(segments)
                    vals.append(jinja_str)
                elif isinstance(raw_val, bool):
                    # Булевое значение -- как строку "true"/"false"
                    vals.append(f'"{"true" if raw_val else "false"}"')
                elif isinstance(raw_val, str):
                    vals.append(f'"{raw_val}"')
                else:
                    vals.append(json.dumps(raw_val, ensure_ascii=False))
            variant_tuples.append(f"({', '.join(vals)})")

        var_names_str = ", ".join(f"{fn}_val" for fn in variant_field_names)
        lines.append(f'{{% for {var_names_str} in [')
        for vi, vt in enumerate(variant_tuples):
            lines.append(f'    {vt},')
        lines.append('] -%}')

        # Строим JSON канала
        ch_fields: list[str] = []
        name_tpl = f'{pattern["name_prefix"]}{{{{ i }}}}{pattern["name_suffix"]}'
        ch_fields.append(f'"name": "{name_tpl}"')

        # Адрес
        addr_expr = _render_address_expr(base_addr, step, start, var)
        ch_fields.append(f'"address": {addr_expr}')

        # Остальные поля
        skip_fields = {"name", "address", "enabled", "id"}
        for key, value in proto.items():
            if key in skip_fields:
                continue
            if key in variant_fields:
                # Подставляем переменную из внутреннего for
                field_type = variant_field_types.get(key, "other")
                if field_type == "bool":
                    # Булевое: рендерим как JSON-литерал (без кавычек)
                    ch_fields.append(f'"{key}": {{{{ {key}_val }}}}')
                elif field_type == "str":
                    # Строковое: рендерим в кавычках
                    ch_fields.append(f'"{key}": "{{{{ {key}_val }}}}"')
                else:
                    ch_fields.append(f'"{key}": {{{{ {key}_val }}}}')
            elif key in tpl_fields:
                tpl = tpl_fields[key]
                rendered_value = tpl.replace(_PLACEHOLDER, "{{ i }}")
                ch_fields.append(f'"{key}": "{rendered_value}"')
            else:
                dumped = json.dumps(value, ensure_ascii=False)
                if isinstance(value, (dict, list)):
                    dumped = json.dumps(value, indent=4, ensure_ascii=False)
                    dump_lines = dumped.split("\n")
                    if len(dump_lines) > 1:
                        dumped = dump_lines[0] + "\n" + "\n".join(
                            f"{indent}    {line}" for line in dump_lines[1:]
                        )
                ch_fields.append(f'"{key}": {dumped}')

        ch_json = ",\n".join(f"{indent}    {f}" for f in ch_fields)
        lines.append(f"{indent}{{")
        lines.append(ch_json)
        if is_last_in_array:
            # Последний паттерн в массиве -- условная запятая
            lines.append(
                f"{indent}}}{{% if not (outer_loop.last and loop.last) %}},{{% endif %}}"
            )
        else:
            # Не последний -- всегда ставим запятую
            lines.append(f"{indent}}},")

        # Закрываем внутренний цикл (по вариантам)
        lines.append("{% endfor -%}")
        # Закрываем внешний цикл (по номерам)
        lines.append("{% endfor -%}")
    else:
        # Простой случай: без вариантов
        ch_fields = []
        name_tpl = f'{pattern["name_prefix"]}{{{{ i }}}}{pattern["name_suffix"]}'
        ch_fields.append(f'"name": "{name_tpl}"')

        # Адрес
        addr_expr = _render_address_expr(base_addr, step, start, var)
        ch_fields.append(f'"address": {addr_expr}')

        # Остальные поля
        skip_fields = {"name", "address", "enabled", "id"}
        for key, value in proto.items():
            if key in skip_fields:
                continue
            rendered = _render_field_value(key, value, tpl_fields, 0, start, var,
                                           indent + "    ")
            ch_fields.append(rendered)

        ch_json = ",\n".join(f"{indent}    {f}" for f in ch_fields)
        lines.append(f"{indent}{{")
        lines.append(ch_json)
        if is_last_in_array:
            # Последний for-блок в массиве -- условная запятая
            lines.append(f"{indent}}}{{% if not loop.last %}},{{% endif %}}")
        else:
            # Не последний -- всегда ставим запятую (включая последнюю итерацию)
            lines.append(f"{indent}}},")
        lines.append("{% endfor -%}")

    return "\n".join(
        f"{indent}{line}" if not line.startswith(indent) else line
        for line in lines
    )


def _render_string_channel_jinja(
    pattern: dict,
    indent: str = "            ",
    is_last_in_array: bool = True,
) -> str:
    """Рендерит Jinja for-цикл для строкового паттерна каналов.

    Генерирует:
    {% set VAR_VALUES = ["val1", "val2", ...] -%}
    {% for val in VAR_VALUES -%}
    {
        "name": "Prefix {{ val | capitalize }} Suffix",
        "address": {{ base + loop.index0 * step }},
        ...
    }{% if not loop.last %},{% endif %}
    {% endfor -%}

    is_last_in_array -- этот паттерн последний в массиве channels.
    """
    proto = pattern["prototype"]
    var_name = pattern["var_name"]
    string_values = pattern["string_values"]
    name_prefix = pattern["name_prefix"]
    name_suffix = pattern["name_suffix"]
    name_filter = pattern.get("name_filter", "")
    base_addr = pattern["base_address"]
    address_step = pattern["address_step"]

    lines = []

    # Объявление переменной со списком строк
    values_str = ", ".join(f'"{v}"' for v in string_values)
    lines.append(f'{{% set {var_name} = [{values_str}] -%}}')

    # Открываем цикл
    lines.append(f'{{% for val in {var_name} -%}}')

    # Строим JSON канала
    ch_fields: list[str] = []

    # name с подстановкой val
    name_tpl = f'{name_prefix}{{{{ val{name_filter} }}}}{name_suffix}'
    ch_fields.append(f'"name": "{name_tpl}"')

    # Адрес через loop.index0
    if address_step == 0:
        addr_expr = str(base_addr)
    elif address_step == 1:
        addr_expr = f"{{{{ {base_addr} + loop.index0 }}}}"
    else:
        addr_expr = f"{{{{ {base_addr} + loop.index0 * {address_step} }}}}"
    ch_fields.append(f'"address": {addr_expr}')

    # Остальные поля (для строковых паттернов пропускаем только name и address --
    # enabled и id включаются, id шаблонизируется)
    skip_fields_str = {"name", "address"}
    for key, value in proto.items():
        if key in skip_fields_str:
            continue
        if key == "id" and isinstance(value, str):
            # Шаблонизируем id: находим варьирующуюся часть и заменяем на {{ val }}
            # id обычно содержит варьирующееся слово в lowercase
            # Ищем какое из string_values содержится в id
            id_val = value
            first_val = string_values[0]
            if first_val in id_val:
                id_tpl = id_val.replace(first_val, "{{ val }}", 1)
                ch_fields.append(f'"id": "{id_tpl}"')
            else:
                # Пробуем lowercase
                first_val_lower = first_val.lower()
                if first_val_lower in id_val:
                    id_tpl = id_val.replace(first_val_lower, "{{ val }}", 1)
                    ch_fields.append(f'"id": "{id_tpl}"')
                else:
                    ch_fields.append(f'"id": {json.dumps(value, ensure_ascii=False)}')
            continue
        dumped = json.dumps(value, ensure_ascii=False)
        if isinstance(value, (dict, list)):
            dumped = json.dumps(value, indent=4, ensure_ascii=False)
            dump_lines = dumped.split("\n")
            if len(dump_lines) > 1:
                dumped = dump_lines[0] + "\n" + "\n".join(
                    f"{indent}    {line}" for line in dump_lines[1:]
                )
        ch_fields.append(f'"{key}": {dumped}')

    ch_json = ",\n".join(f"{indent}    {f}" for f in ch_fields)
    lines.append(f"{indent}{{")
    lines.append(ch_json)
    if is_last_in_array:
        lines.append(f"{indent}}}{{% if not loop.last %}},{{% endif %}}")
    else:
        lines.append(f"{indent}}},")
    lines.append("{% endfor -%}")

    return "\n".join(
        f"{indent}{line}" if not line.startswith(indent) else line
        for line in lines
    )


def _render_group_object(
    pattern: dict,
    indent: str,
) -> str:
    """Рендерит один объект группы внутри for-цикла."""
    tpl_fields = pattern.get("templated_fields", {})
    proto = pattern["prototype"]
    obj_lines = []

    # title
    title_val = proto.get("title", "")
    if "title" in tpl_fields:
        title_rendered = tpl_fields["title"].replace(_PLACEHOLDER, "{{ i }}")
        obj_lines.append(f'{indent}    "title": "{title_rendered}"')
    else:
        obj_lines.append(
            f'{indent}    "title": {json.dumps(title_val, ensure_ascii=False)}'
        )

    # id
    id_tpl = f'{pattern["name_prefix"]}{{{{ i }}}}{pattern["name_suffix"]}'
    obj_lines.append(f'{indent}    "id": "{id_tpl}"')

    # group (parent)
    if "group" in tpl_fields:
        group_rendered = tpl_fields["group"].replace(_PLACEHOLDER, "{{ i }}")
        obj_lines.append(f'{indent}    "group": "{group_rendered}"')
    elif "group" in proto:
        obj_lines.append(
            f'{indent}    "group": {json.dumps(proto["group"], ensure_ascii=False)}'
        )

    # description
    if "description" in tpl_fields:
        desc_rendered = tpl_fields["description"].replace(_PLACEHOLDER, "{{ i }}")
        obj_lines.append(f'{indent}    "description": "{desc_rendered}"')
    elif "description" in proto:
        obj_lines.append(
            f'{indent}    "description": {json.dumps(proto["description"], ensure_ascii=False)}'
        )

    # ui_options и другие поля
    for key, value in proto.items():
        if key in {"title", "id", "group", "description"}:
            continue
        obj_lines.append(
            f'{indent}    "{key}": {json.dumps(value, ensure_ascii=False)}'
        )

    return f"{indent}{{\n" + ",\n".join(obj_lines) + f"\n{indent}}}"


def _render_group_jinja(
    patterns: list[dict],
    all_groups: list[dict],
    indent: str = "            ",
) -> tuple[str, set[int]]:
    """Рендерит Jinja for-циклы для групп.

    Возвращает (jinja_текст, set_использованных_индексов).
    Паттерны с одинаковой переменной объединяются в один for-цикл.

    Стратегия запятых: for-блок использует trailing comma на каждом объекте.
    Если for-блок последний в массиве -- последний объект на последней
    итерации не ставит запятую (через {% if not loop.last %},{% endif %}).
    """
    used_indices: set[int] = set()
    for p in patterns:
        used_indices.update(p["indices"])

    by_var: dict[str, list[dict]] = defaultdict(list)
    for p in patterns:
        by_var[p["var_name"]].append(p)

    # Собираем фрагменты: ("for", var, patterns_list) или ("static", group)
    fragments: list[tuple] = []
    rendered_vars: set[str] = set()

    for i, g in enumerate(all_groups):
        pattern_for_idx = None
        for p in patterns:
            if i in p["indices"]:
                pattern_for_idx = p
                break

        if pattern_for_idx:
            var = pattern_for_idx["var_name"]
            if var not in rendered_vars:
                rendered_vars.add(var)
                same_var_patterns = by_var[var]
                same_var_patterns.sort(key=lambda p: p["indices"][0])
                fragments.append(("for", var, same_var_patterns))
        else:
            fragments.append(("static", g))

    # Теперь собираем текст
    result_parts: list[str] = []

    for fi, fragment in enumerate(fragments):
        is_last = (fi == len(fragments) - 1)

        if fragment[0] == "for":
            _, var, same_var_patterns = fragment
            start = same_var_patterns[0]["start_num"]

            lines = []
            lines.append(
                f"{indent}{{% for i in range({start}, {var} + {start}) -%}}"
            )

            for pi, p in enumerate(same_var_patterns):
                obj_text = _render_group_object(p, indent)
                is_last_obj_in_for = (pi == len(same_var_patterns) - 1)

                if is_last and is_last_obj_in_for:
                    # Последний объект в последнем for -- условная запятая
                    lines.append(
                        f"{obj_text}{{% if not loop.last %}},{{% endif %}}"
                    )
                else:
                    lines.append(f"{obj_text},")

            lines.append(f"{indent}{{% endfor -%}}")
            result_parts.append("\n".join(lines))
        else:
            _, g = fragment
            g_json = json.dumps(g, indent=4, ensure_ascii=False)
            indented = "\n".join(
                f"{indent}{line}" for line in g_json.split("\n")
            )
            result_parts.append(indented)

    # Соединяем: между for->static и static->static ставим запятую.
    # Между for->for не ставим (for уже ставит trailing comma).
    # Между for->static: for ставит trailing comma, дополнительная не нужна.
    # Между static->static: нужна запятая.
    # Между static->for: нужна запятая.
    output_lines: list[str] = []
    for fi, part in enumerate(result_parts):
        if fi > 0:
            prev_type = fragments[fi - 1][0]
            if prev_type == "for":
                # for уже оставил trailing comma
                output_lines.append("\n")
            else:
                output_lines.append(",\n")
        output_lines.append(part)

    return "".join(output_lines), used_indices


def _render_param_jinja(
    patterns: list[dict],
    all_params: dict[str, dict],
    indent: str = "            ",
) -> tuple[str, set[str]]:
    """Рендерит Jinja for-циклы для параметров.

    Возвращает (jinja_текст, set_использованных_ключей).
    Аналогично группам: for-блоки ставят trailing comma, кроме
    последнего объекта на последней итерации (если for последний фрагмент).
    """
    used_keys: set[str] = set()
    for p in patterns:
        used_keys.update(p["indices"])

    by_var: dict[str, list[dict]] = defaultdict(list)
    for p in patterns:
        by_var[p["var_name"]].append(p)

    # Собираем фрагменты
    fragments: list[tuple] = []  # ("for", var, patterns) или ("static", key, value)
    rendered_vars: set[str] = set()
    all_keys = list(all_params.keys())

    i = 0
    while i < len(all_keys):
        key = all_keys[i]
        if key in used_keys:
            pattern_for_key = None
            for p in patterns:
                if key in p["indices"]:
                    pattern_for_key = p
                    break
            if pattern_for_key and pattern_for_key["var_name"] not in rendered_vars:
                var = pattern_for_key["var_name"]
                rendered_vars.add(var)
                same_var_patterns = by_var[var]
                same_var_patterns.sort(
                    key=lambda p: all_keys.index(p["indices"][0])
                    if p["indices"][0] in all_keys else 0
                )
                fragments.append(("for", var, same_var_patterns))
            i += 1
        else:
            fragments.append(("static", key, all_params[key]))
            i += 1

    # Рендерим фрагменты
    result_parts: list[str] = []

    for fi, fragment in enumerate(fragments):
        is_last = (fi == len(fragments) - 1)

        if fragment[0] == "for":
            _, var, same_var_patterns = fragment
            start = same_var_patterns[0]["start_num"]

            lines = []
            lines.append(
                f"{indent}{{% for i in range({start}, {var} + {start}) -%}}"
            )

            for pi, p in enumerate(same_var_patterns):
                tpl_fields = p.get("templated_fields", {})
                proto = p["prototype"]
                key_tpl = f'{p["name_prefix"]}{{{{ i }}}}{p["name_suffix"]}'

                obj_fields: list[str] = []
                addr_expr = _render_address_expr(
                    p["base_address"], p["address_step"], start, var
                )
                obj_fields.append(f'{indent}        "address": {addr_expr}')

                for fkey, fvalue in proto.items():
                    if fkey in {"address", "enabled", "id"}:
                        continue
                    rendered = _render_field_value(
                        fkey, fvalue, tpl_fields, 0, start, var,
                        indent + "        "
                    )
                    obj_fields.append(f"{indent}        {rendered}")

                is_last_obj_in_for = (pi == len(same_var_patterns) - 1)

                lines.append(f'{indent}"{key_tpl}": {{')
                lines.append(",\n".join(obj_fields))

                if is_last and is_last_obj_in_for:
                    # Последний объект в последнем for -- условная запятая
                    lines.append(
                        f"{indent}}}{{% if not loop.last %}},{{% endif %}}"
                    )
                else:
                    lines.append(f"{indent}}},")

            lines.append(f"{indent}{{% endfor -%}}")
            result_parts.append("\n".join(lines))
        else:
            _, key, value = fragment
            param_json = json.dumps(value, indent=4, ensure_ascii=False)
            indented_lines = param_json.split("\n")
            indented = indented_lines[0] + (
                "\n" + "\n".join(
                    f"{indent}    {line}" for line in indented_lines[1:]
                ) if len(indented_lines) > 1 else ""
            )
            result_parts.append(f'{indent}"{key}": {indented}')

    # Соединяем фрагменты
    output_lines: list[str] = []
    for fi, part in enumerate(result_parts):
        if fi > 0:
            prev_type = fragments[fi - 1][0]
            if prev_type == "for":
                # for уже оставил trailing comma
                output_lines.append("\n")
            else:
                output_lines.append(",\n")
        output_lines.append(part)

    return "".join(output_lines), used_keys


def _render_translations_jinja(
    translations: dict[str, dict[str, str]],
    translation_patterns: list[dict],
    indent: str = "            ",
) -> str:
    """Рендерит секцию translations с for-циклами для паттернов.

    Для каждого языка:
    - Статические ключи рендерятся как обычный JSON
    - Паттернные ключи сворачиваются в for-циклы
    """
    if not translations:
        return f'{indent[:-4]}"translations": {{}}'

    # Собираем все использованные ключи по паттернам
    all_pattern_keys: set[str] = set()
    for tp in translation_patterns:
        all_pattern_keys.update(tp["used_keys"])

    lang_indent = indent
    inner_indent = indent + "    "

    parts = [f'{indent[:-4]}"translations": {{']

    lang_items = list(translations.items())
    for li, (lang, lang_data) in enumerate(lang_items):
        is_last_lang = (li == len(lang_items) - 1)
        if not isinstance(lang_data, dict):
            dumped = json.dumps(lang_data, ensure_ascii=False)
            comma = "" if is_last_lang else ","
            parts.append(f'{lang_indent}"{lang}": {dumped}{comma}')
            continue

        parts.append(f'{lang_indent}"{lang}": {{')

        # Собираем фрагменты для этого языка
        # Определяем порядок: паттерны вставляются на месте первого ключа
        all_keys = list(lang_data.keys())
        fragments: list[tuple] = []  # ("static", key, value) или ("for", pattern)
        rendered_pattern_ids: set[int] = set()

        for key in all_keys:
            if key in all_pattern_keys:
                # Ищем паттерн для этого ключа
                for tp in translation_patterns:
                    if key in tp["used_keys"] and id(tp) not in rendered_pattern_ids:
                        rendered_pattern_ids.add(id(tp))
                        fragments.append(("for", tp))
                        break
            else:
                fragments.append(("static", key, lang_data[key]))

        # Рендерим фрагменты
        frag_parts: list[str] = []
        for fi, frag in enumerate(fragments):
            is_last_frag = (fi == len(fragments) - 1)

            if frag[0] == "for":
                tp = frag[1]
                var = tp["var_name"]
                start_num = tp["start_num"]
                key_tpl = tp["key_template"]
                value_tpl = tp["value_tpls"].get(lang)

                # Шаблон ключа: заменяем placeholder на {{ i }}
                key_jinja = key_tpl.replace(_PLACEHOLDER, "{{ i }}")

                flines = []
                flines.append(
                    f"{inner_indent}{{% for i in range({start_num}, {var} + {start_num}) -%}}"
                )

                if is_last_frag:
                    # Последний фрагмент -- условная trailing comma
                    comma_expr = "{% if not loop.last %},{% endif %}"
                else:
                    # Не последний -- всегда запятая
                    comma_expr = ","

                if value_tpl is not None:
                    # Значение тоже шаблонизируется
                    value_jinja = value_tpl.replace(_PLACEHOLDER, "{{ i }}")
                    flines.append(f'{inner_indent}"{key_jinja}": "{value_jinja}"{comma_expr}')
                else:
                    # Значение статическое -- берём из данных
                    # (для случая когда значение не содержит число)
                    # Используем первый ключ для получения значения
                    first_key = None
                    for k, n in sorted(
                        [(k, n) for k in tp["used_keys"]
                         for _, n, _, _ in _extract_number_variants(k)
                         if k.replace(str(n), _PLACEHOLDER) == key_tpl],
                        key=lambda x: x[1]
                    ):
                        first_key = k
                        break
                    if first_key and first_key in lang_data:
                        val = lang_data[first_key]
                        flines.append(f'{inner_indent}"{key_jinja}": {json.dumps(val, ensure_ascii=False)}{comma_expr}')
                    else:
                        flines.append(f'{inner_indent}"{key_jinja}": ""{comma_expr}')

                flines.append(f"{inner_indent}{{% endfor -%}}")
                frag_parts.append("\n".join(flines))
            else:
                _, key, value = frag
                dumped = json.dumps(value, ensure_ascii=False)
                frag_parts.append(f'{inner_indent}"{key}": {dumped}')

        # Соединяем фрагменты внутри языка
        output_frag_lines: list[str] = []
        for fi, part in enumerate(frag_parts):
            if fi > 0:
                prev_type = fragments[fi - 1][0]
                if prev_type == "for":
                    output_frag_lines.append("\n")
                else:
                    output_frag_lines.append(",\n")
            output_frag_lines.append(part)

        parts.append("".join(output_frag_lines))

        comma = "" if is_last_lang else ","
        parts.append(f'{lang_indent}}}{comma}')

    parts.append(f'{indent[:-4]}}}')
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Основная функция
# ---------------------------------------------------------------------------

def build_jinja_template(template: dict) -> str:
    """Принимает JSON-шаблон (из build_template()), генерирует .json.jinja строку.

    Обнаруживает паттерны повторяющихся каналов, групп, параметров и переводов,
    сворачивает в for-циклы. Если паттернов нет -- возвращает обычный JSON.
    """
    device = template.get("device", {})
    channels = device.get("channels", [])
    groups_list = device.get("groups", [])
    parameters = device.get("parameters", {})
    translations = device.get("translations", {})

    # Детекция паттернов
    channel_patterns = _detect_channel_patterns(channels)
    group_patterns = _detect_group_patterns(groups_list)
    # Параметры могут быть list (UPS) или dict -- обрабатываем только dict
    param_patterns = []
    if isinstance(parameters, dict):
        param_patterns = _detect_param_patterns(parameters)

    # Детекция строковых паттернов в каналах (после числовых)
    already_used_indices: set[int] = set()
    for p in channel_patterns:
        already_used_indices.update(p["indices"])
    string_channel_patterns = _detect_string_channel_patterns(
        channels, already_used_indices
    )

    all_patterns = channel_patterns + group_patterns + param_patterns

    # Детекция паттернов в translations
    translation_patterns = _detect_translation_patterns(translations, all_patterns)

    if not all_patterns and not string_channel_patterns and not translation_patterns:
        # Нет паттернов -- возвращаем обычный JSON
        return json.dumps(template, indent=4, ensure_ascii=False)

    # Унификация переменных с одинаковыми count/start_num
    unified = _unify_variables(channel_patterns, group_patterns, param_patterns)

    # Обновляем var_name в translation_patterns после унификации
    # (они ссылаются на те же переменные)
    unified_vars: dict[tuple[int, int], str] = {}
    for var_name, pats in unified.items():
        for p in pats:
            sig = (p["count"], p["start_num"])
            unified_vars[sig] = var_name

    for tp in translation_patterns:
        sig = (tp["count"], tp["start_num"])
        if sig in unified_vars:
            tp["var_name"] = unified_vars[sig]

    # Строим Jinja-шаблон
    lines: list[str] = []

    # Переменные (дедупликация по var_name)
    seen_vars: set[str] = set()
    for var_name, pats in unified.items():
        if var_name not in seen_vars:
            seen_vars.add(var_name)
            lines.append(f'{{% set {var_name} = {pats[0]["count"]} -%}}')
    # Переменные из translation_patterns, которых нет в unified
    for tp in translation_patterns:
        var = tp["var_name"]
        if var not in seen_vars:
            seen_vars.add(var)
            lines.append(f'{{% set {var} = {tp["count"]} -%}}')

    # Открываем шаблон
    lines.append("{")

    # Верхнеуровневые поля
    for key in ("device_type", "title", "group"):
        if key in template:
            lines.append(f'    "{key}": {json.dumps(template[key])},')

    lines.append('    "device": {')

    # device поля (не channels, не parameters, не translations, не groups)
    device_simple = {
        k: v for k, v in device.items()
        if k not in ("channels", "parameters", "translations", "groups")
    }
    for key, value in device_simple.items():
        lines.append(f'        "{key}": {json.dumps(value)},')

    # --- groups ---
    if groups_list:
        if group_patterns:
            lines.append('        "groups": [')
            groups_jinja, _ = _render_group_jinja(group_patterns, groups_list)
            lines.append(groups_jinja)
            lines.append("        ],")
        else:
            lines.append(
                f'        "groups": {json.dumps(groups_list, indent=12, ensure_ascii=False)},'
            )

    # --- channels ---
    # Фрагментный подход: ("for", pattern), ("string_for", pattern) или ("static", channel_dict)
    # Аналогично _render_group_jinja и _render_param_jinja
    index_to_pattern: dict[int, dict] = {}
    for p in channel_patterns:
        for idx in p["indices"]:
            index_to_pattern[idx] = p

    # Строковые паттерны
    index_to_string_pattern: dict[int, dict] = {}
    for p in string_channel_patterns:
        for idx in p["indices"]:
            index_to_string_pattern[idx] = p

    lines.append('        "channels": [')

    ch_fragments: list[tuple] = []  # ("for", pattern), ("string_for", pattern) или ("static", channel_dict)
    rendered_patterns: set[int] = set()

    for i in range(len(channels)):
        if i in index_to_pattern:
            p = index_to_pattern[i]
            if id(p) not in rendered_patterns:
                ch_fragments.append(("for", p))
                rendered_patterns.add(id(p))
        elif i in index_to_string_pattern:
            p = index_to_string_pattern[i]
            if id(p) not in rendered_patterns:
                ch_fragments.append(("string_for", p))
                rendered_patterns.add(id(p))
        else:
            ch_fragments.append(("static", channels[i]))

    # Рендерим фрагменты каналов
    ch_result_parts: list[str] = []
    ch_indent = "            "

    for fi, fragment in enumerate(ch_fragments):
        is_last = (fi == len(ch_fragments) - 1)

        if fragment[0] == "for":
            _, p = fragment
            jinja_block = _render_channel_jinja(p, indent=ch_indent, is_last_in_array=is_last)
            ch_result_parts.append(jinja_block)
        elif fragment[0] == "string_for":
            _, p = fragment
            jinja_block = _render_string_channel_jinja(
                p, indent=ch_indent, is_last_in_array=is_last
            )
            ch_result_parts.append(jinja_block)
        else:
            _, ch = fragment
            ch_json = json.dumps(ch, indent=4, ensure_ascii=False)
            indented = "\n".join(
                f"{ch_indent}{line}" for line in ch_json.split("\n")
            )
            ch_result_parts.append(indented)

    # Соединяем: for-блоки (числовые и строковые) уже управляют trailing comma,
    # статические элементы нуждаются в запятых между собой
    ch_output_lines: list[str] = []
    for fi, part in enumerate(ch_result_parts):
        if fi > 0:
            prev_type = ch_fragments[fi - 1][0]
            if prev_type in ("for", "string_for"):
                # for уже оставил trailing comma
                ch_output_lines.append("\n")
            else:
                ch_output_lines.append(",\n")
        ch_output_lines.append(part)

    lines.append("".join(ch_output_lines))
    lines.append("        ],")

    # --- parameters ---
    if isinstance(parameters, dict) and parameters:
        if param_patterns:
            lines.append('        "parameters": {')
            params_jinja, _ = _render_param_jinja(param_patterns, parameters)
            lines.append(params_jinja)
            lines.append("        },")
        else:
            lines.append(
                f'        "parameters": {json.dumps(parameters, indent=8, ensure_ascii=False)},'
            )
    elif isinstance(parameters, list) and parameters:
        lines.append(
            f'        "parameters": {json.dumps(parameters, indent=8, ensure_ascii=False)},'
        )
    else:
        lines.append('        "parameters": {},')

    # --- translations ---
    if translation_patterns:
        trans_jinja = _render_translations_jinja(
            translations, translation_patterns, indent="            "
        )
        lines.append(trans_jinja)
    elif translations:
        lines.append(
            f'        "translations": {json.dumps(translations, indent=8, ensure_ascii=False)}'
        )
    else:
        lines.append('        "translations": {}')

    lines.append("    }")
    lines.append("}")

    return "\n".join(lines)
