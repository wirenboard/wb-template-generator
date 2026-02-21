# Модель данных

## DeviceInfo

- `name: str`, `id: str` — имя и идентификатор устройства
- `device_group: str | None` — группа устройства
- `hw: list[dict] | None` — аппаратные варианты (roundtrip)
- `max_read_registers: int | None` — макс. регистров за одно чтение
- `response_timeout_ms: int | None`, `frame_timeout_ms: int | None` — таймауты
- `enable_wb_continuous_read: bool | None` — непрерывное чтение WB
- `title_key: str | None`, `title_translations: dict[str, str] | None` — ключ и переводы заголовка

## Register (ключевые поля)

- `address: int | str` — число или `"109:1:2"` (register:bit_offset:bit_width)
- `name: str` — английское имя
- `reg_type`: holding, input, coil, discrete
- `format`: u16, s16, u32, s32, u64, s64, float, double, u8, s8, string
- `scale`, `offset` — final = raw * scale + offset
- `units: str | None` — единицы измерения
- `access`: read, write, readwrite
- `is_parameter: bool` — false=канал (данные/управление), true=параметр (настройки)
- `channel_type`: value, switch, wo-switch, pushbutton, range, text, rgb
- `group: str` — ID группы (default: `"general"`)
- `condition: str | None` — условие показа (`"parameter_id==value"`)
- `enabled: bool` — включён/выключен в шаблоне
- `enum` + `enum_titles` — параллельные массивы значений и меток
- `enum_entries: list[EnumEntry]` — альтернатива с переводами (приоритет над enum/enum_titles)
- `translations: Record<lang, {name?, description?}>` — переводы на N языков
- `string_data_size: int | None` — размер строки (для format=string)
- `word_order`, `byte_order` — порядок байт/слов
- `error_value: str | None` — значение ошибки
- `min`, `max`, `round_to` — диапазон и округление
- `on_value`, `off_value` — значения для switch
- `default_value` — значение по умолчанию (для параметров)
- `readonly: bool | None` — только чтение

Roundtrip-поля (сохраняются при импорт/экспорт): `sporadic`, `read_only`, `required`, `fw`, `original_channel_id`, `param_order`.

При импорте шаблона `id` регистра = оригинальный ключ параметра/канала из шаблона (например `in1_mode`), не UUID. Это обеспечивает корректную работу condition-ссылок.

## EnumEntry

- `value: int` — числовое значение
- `title: str` — английский заголовок
- `translations: dict[str, str] | None` — `{lang: title}`, напр. `{"ru": "Включено"}`

## RegisterGroup

- `id`, `title`, `order`, `description?`
- `translations: dict[str, GroupTranslation] | None` — переводы (title + description по языкам)
- `parent_group: str | None` — вложенная группа (для иерархии)
- `ui_options: dict | None` — визуальные настройки группы (roundtrip)

## Формат целевого шаблона (wb-mqtt-serial)

- **channel.type**: value, switch, wo-switch, pushbutton, range, text, rgb, temperature, voltage, current, power, ...
- **channel.format**: u16, s16, u32, s32, u64, s64, float, double, u8, s8, string
- **channel.reg_type**: holding, input, coil, discrete, holding_single, holding_multi
- **channel.units**: V, mV, A, mA, W, kWh, Hz, rpm, Ohm, mOhm, bar, mbar, Pa, deg C, %, RH, ppm, ppb, lx, dB, s, min, h, m, mm/h, m/s, m^3/h, m^3, g, kg, mol, cd, Gcal/h, cal, Gcal, deg, rad
