"""Каталог ошибок, которые видит пользователь, с ключами локализации.

Интерфейс говорит на четырёх языках, а тексты бэкенда только русские, поэтому
каждая пользовательская ошибка несёт ключ и параметры: `message_key` +
`message_params`. Тот же контракт, что у валидатора регистров (`FieldError`),
только там ключ идёт без текста — валидация это данные успешного ответа, а
здесь ошибка HTTP, и текст нужен ещё двум потребителям.

Русский текст остаётся в поле `detail`: его читают curl и интеграции, и он же
уходит в лог. Хранится здесь, рядом с ключом, — иначе они разойдутся при первой
же правке, а `ALL_KEYS` позволяет тесту сверить каталог со словарём интерфейса.

Параметр с именем на `Key` — вложенный ключ: значение переводится, а в шаблон
подставляется под именем без суффикса. Фронтенд делает то же самое, см.
`resolveMessage` в `frontend/src/api.ts`.
"""

from __future__ import annotations

# Плейсхолдеры совпадают с теми, что лежат в `frontend/src/i18n/translations.ts`
# под тем же ключом. Расхождение ловит тест паритета.
_TEXTS: dict[str, str] = {
    "serverError.importInvalidJson": "Невалидный JSON: {error}",
    "serverError.importFailed": (
        "Не удалось импортировать шаблон. Проверьте, что файл — корректный JSON "
        "или .json.jinja шаблона wb-mqtt-serial."
    ),
    "serverError.importNotTemplate": (
        "Файл не похож на шаблон wb-mqtt-serial: не найдены каналы, параметры "
        "или тип устройства."
    ),
    "serverError.importJinjaTooLarge": "Jinja-шаблон больше {max} МБ и не будет обработан.",
    "serverError.importJinjaUnsafe": (
        "Шаблон содержит конструкции, запрещённые при импорте. "
        "Допустимы только циклы, условия, макросы и фильтры."
    ),
    "serverError.importJinjaError": "Ошибка в Jinja-шаблоне: {error}",
    "serverError.importJinjaErrorLine": "Ошибка в Jinja-шаблоне (строка {line}): {error}",
    "serverError.importJinjaLimit": "Шаблон упирается в ограничение песочницы: {error}",
}


def render(key: str, params: dict) -> str:
    """Русский текст ошибки по ключу и параметрам.

    Параметры с именем на `Key` считаются вложенными ключами: значение
    переводится, а подставляется под именем без суффикса.
    """
    resolved: dict = {}
    for name, value in params.items():
        if name.endswith("Key") and isinstance(value, str):
            resolved[name[:-3]] = _TEXTS.get(value, value)
        else:
            resolved[name] = value
    # Шаблоны наши, от пользователя приходят только значения — подстановка безопасна
    return _TEXTS[key].format(**resolved)


class UserError(Exception):
    """Ошибка, предназначенная пользователю: несёт ключ, параметры и русский текст."""

    def __init__(self, key: str, **params: object) -> None:
        if key not in _TEXTS:
            raise KeyError(f"Нет текста для ключа ошибки {key!r}")
        self.key = key
        self.params = params
        super().__init__(render(key, params))

    @property
    def message(self) -> str:
        """Русский текст — он же `detail` в ответе и запись в логе."""
        return str(self)

    def payload(self, request_id: str | None = None) -> dict:
        """Тело JSON-ответа: русский текст плюс ключ с параметрами для интерфейса."""
        body: dict = {
            "detail": self.message,
            "message_key": self.key,
            "message_params": self.params,
        }
        if request_id:
            body["request_id"] = request_id
        return body


ALL_KEYS: tuple[str, ...] = tuple(_TEXTS)
