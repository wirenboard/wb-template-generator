"""Экспорт JSON-шаблона wb-mqtt-serial в .json.jinja с обнаружением паттернов.

Обнаруживает повторяющиеся структуры в channels, groups и parameters:
- Каналы (channels) — по полю name, с поддержкой шаблонизируемых полей (group, condition)
- Группы (groups) — по полю id
- Параметры (parameters) — по ключу dict

Если обнаружены паттерны с одинаковыми count и start_num — объединяет под одной
переменной Jinja (например INPUTS_NUMBER). Иначе — отдельные переменные.

Число может быть в любой позиции: "Ch 1", "Input 1 state", "DS18B20 Input 1".
Минимум 2 элемента для паттерна.
"""

import json
import re
from collections import defaultdict
from typing import Any

_PLACEHOLDER = "\x00"

# Поля, которые могут содержать варьирующийся номер и шаблонизируются
_CHANNEL_TEMPLATED_FIELDS = {"group", "condition"}
_GROUP_TEMPLATED_FIELDS = {"title", "description", "group"}
_PARAM_TEMPLATED_FIELDS = {"group", "condition", "description"}

# Поля, исключаемые из сравнения сигнатур
_CHANNEL_SKIP_FIELDS = {"name", "address", "enabled", "id"}
_PARAM_SKIP_FIELDS = {"address", "enabled", "id"}


# ---------------------------------------------------------------------------
# Обобщённая детекция паттернов
# ---------------------------------------------------------------------------

def _extract_number_variants(text: str) -> list[tuple[str, int, int, int]]:
    """Извлекает все варианты замены числа на placeholder в тексте.

    Возвращает список кортежей (шаблон, число, start_позиция, end_позиция).
    """
    variants = []
    for match in re.finditer(r"\d+", text):
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

    Возвращает dict: имя_поля → шаблон (с placeholder вместо числа).
    """
    result = {}
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


def _validate_address_progression(items: list[tuple[Any, int, dict]],
                                  address_field: str = "address") -> tuple[bool, int, int]:
    """Проверяет арифметическую прогрессию адресов.

    Возвращает (valid, base_address, step).
    """
    addresses = []
    for _, _, item in items:
        addr = item.get(address_field, 0)
        if isinstance(addr, str):
            try:
                addr = int(addr, 0)
            except (ValueError, TypeError):
                return False, 0, 0
        addresses.append(addr)

    if len(addresses) < 2:
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


def _detect_patterns_generic(
    items: list[tuple[Any, dict]],
    key_extractor: callable,
    skip_fields: set[str],
    templated_fields_candidates: set[str],
    require_address_progression: bool = True,
) -> list[dict]:
    """Обобщённая детекция паттернов.

    items — список (ключ_элемента, элемент_dict). Ключ: index для channels,
    id для groups, dict-key для params.

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

    # Сначала большие группы — приоритет у паттернов с бо́льшим числом элементов
    sorted_groups = sorted(groups.items(), key=lambda x: len(x[1]), reverse=True)

    for template, group_items in sorted_groups:
        # Убираем элементы, уже включённые в другой паттерн
        group_items = [x for x in group_items if x[0] not in used_indices]
        if len(group_items) < 2:
            continue

        # Сортируем по числовому значению
        group_items.sort(key=lambda x: x[1])

        # Проверяем последовательность номеров
        nums = [it[1] for it in group_items]
        if nums != list(range(nums[0], nums[0] + len(nums))):
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

        # Всё проверено — создаём паттерн
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

    Возвращает список паттернов:
    {
        "var_name": "INPUT_STATE_NUMBER",
        "count": 4,
        "start_num": 1,
        "base_address": 100,
        "address_step": 1,
        "name_prefix": "Input ",
        "name_suffix": " state",
        "indices": [0, 1, 2, 3],
        "prototype": {...},
        "templated_fields": {"group": "gg_in\x00_channels", ...},
    }
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
# Унификация переменных
# ---------------------------------------------------------------------------

def _unify_variables(
    channel_patterns: list[dict],
    group_patterns: list[dict],
    param_patterns: list[dict],
) -> dict[str, list[dict]]:
    """Объединяет паттерны с одинаковыми count и start_num под одной переменной.

    Возвращает dict: var_name → список всех паттернов с этой переменной.
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

    # Для каждой группы с одинаковым (count, start_num) — выбираем одно имя переменной
    used_var_names: set[str] = set()
    result: dict[str, list[dict]] = {}

    for (count, start_num), group in by_signature.items():
        if len(group) > 1:
            # Несколько паттернов с одинаковыми count/start_num — объединяем
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
        # Многострочные значения (вложенные объекты/массивы) — с отступами
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


def _render_channel_jinja(
    pattern: dict,
    indent: str = "            ",
) -> str:
    """Рендерит Jinja for-цикл для группы каналов."""
    proto = pattern["prototype"]
    var = pattern["var_name"]
    start = pattern["start_num"]
    base_addr = pattern["base_address"]
    step = pattern["address_step"]
    tpl_fields = pattern.get("templated_fields", {})

    lines = []
    lines.append(f'{{% for i in range({start}, {var} + {start}) -%}}')

    # Строим JSON канала с подстановками
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
        rendered = _render_field_value(key, value, tpl_fields, 0, start, var,
                                       indent + "    ")
        ch_fields.append(rendered)

    ch_json = ",\n".join(f"{indent}    {f}" for f in ch_fields)
    lines.append(f"{indent}{{")
    lines.append(ch_json)
    lines.append(f"{indent}}}{{% if not loop.last %}},{{% endif %}}")
    lines.append(f"{{% endfor -%}}")

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
    Если for-блок последний в массиве — последний объект на последней
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
                    # Последний объект в последнем for — условная запятая
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

    # Соединяем: между for→static и static→static ставим запятую.
    # Между for→for не ставим (for уже ставит trailing comma).
    # Между for→static: for ставит trailing comma, дополнительная не нужна.
    # Между static→static: нужна запятая.
    # Между static→for: нужна запятая.
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
                    # Последний объект в последнем for — условная запятая
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


# ---------------------------------------------------------------------------
# Основная функция
# ---------------------------------------------------------------------------

def build_jinja_template(template: dict) -> str:
    """Принимает JSON-шаблон (из build_template()), генерирует .json.jinja строку.

    Обнаруживает паттерны повторяющихся каналов, групп и параметров,
    сворачивает в for-циклы. Если паттернов нет — возвращает обычный JSON.
    """
    device = template.get("device", {})
    channels = device.get("channels", [])
    groups_list = device.get("groups", [])
    parameters = device.get("parameters", {})

    # Детекция паттернов
    channel_patterns = _detect_channel_patterns(channels)
    group_patterns = _detect_group_patterns(groups_list)
    param_patterns = _detect_param_patterns(parameters)

    all_patterns = channel_patterns + group_patterns + param_patterns

    if not all_patterns:
        # Нет паттернов — возвращаем обычный JSON
        return json.dumps(template, indent=4, ensure_ascii=False)

    # Унификация переменных с одинаковыми count/start_num
    unified = _unify_variables(channel_patterns, group_patterns, param_patterns)

    # Строим Jinja-шаблон
    lines: list[str] = []

    # Переменные (дедупликация по var_name)
    seen_vars: set[str] = set()
    for var_name, pats in unified.items():
        if var_name not in seen_vars:
            seen_vars.add(var_name)
            lines.append(f'{{% set {var_name} = {pats[0]["count"]} -%}}')

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
    index_to_pattern: dict[int, dict] = {}
    for p in channel_patterns:
        for idx in p["indices"]:
            index_to_pattern[idx] = p

    lines.append('        "channels": [')

    channel_parts: list[str] = []
    rendered_patterns: set[int] = set()  # id(pattern) — каждый паттерн свой for

    for i in range(len(channels)):
        if i in index_to_pattern:
            p = index_to_pattern[i]
            if id(p) not in rendered_patterns:
                jinja_block = _render_channel_jinja(p)
                channel_parts.append(jinja_block)
                rendered_patterns.add(id(p))
        else:
            ch_json = json.dumps(channels[i], indent=4, ensure_ascii=False)
            indented = "\n".join(
                f"            {line}" for line in ch_json.split("\n")
            )
            channel_parts.append(indented)

    lines.append(",\n".join(channel_parts))
    lines.append("        ],")

    # --- parameters ---
    if parameters:
        if param_patterns:
            lines.append('        "parameters": {')
            params_jinja, _ = _render_param_jinja(param_patterns, parameters)
            lines.append(params_jinja)
            lines.append("        },")
        else:
            lines.append(
                f'        "parameters": {json.dumps(parameters, indent=8, ensure_ascii=False)},'
            )
    else:
        lines.append('        "parameters": {},')

    # --- translations ---
    translations = device.get("translations", {})
    if translations:
        lines.append(
            f'        "translations": {json.dumps(translations, indent=8, ensure_ascii=False)}'
        )
    else:
        lines.append('        "translations": {}')

    lines.append("    }")
    lines.append("}")

    return "\n".join(lines)
