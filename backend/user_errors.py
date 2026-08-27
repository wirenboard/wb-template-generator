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
    # --- Общие ---
    "serverError.internal": "Внутренняя ошибка сервера",
    "serverError.serviceStopping": "Сервис останавливается, попробуйте позже.",
    "serverError.rateLimit": (
        "Превышен лимит запросов ({requests} за {window} сек). Попробуйте позже."
    ),
    # --- Настройка и вызов LLM ---
    "serverError.llmNotConfigured": (
        "LLM не настроен. Задайте LLM_API_URL или укажите URL в настройках."
    ),
    "serverError.modelsFailed": "Не удалось получить список моделей — {reason}.",
    "serverError.translateFailed": "Ошибка перевода — {reason}.",
    "serverError.llmUrlScheme": "Адрес LLM должен начинаться с http:// или https://.",
    "serverError.llmUrlNoHost": "В адресе LLM не указан хост.",
    "serverError.llmUrlUnresolvable": "Не удалось разрешить имя хоста «{host}».",
    "serverError.llmUrlBadAddress": "Не удалось разобрать адрес хоста «{host}».",
    "serverError.llmUrlPrivate": (
        "Адрес LLM ведёт во внутреннюю сеть. Укажите публичный адрес провайдера."
    ),
    # --- Приём файлов ---
    "serverError.tooManyFiles": (
        "За один раз можно загрузить не больше {max} файлов. "
        "Если страниц больше, соберите их в один PDF."
    ),
    "serverError.unsupportedFormat": (
        "Неподдерживаемый формат файла: «{file}». "
        "Допустимые форматы: PDF, Excel (xlsx), изображения (PNG, JPG, WebP)."
    ),
    "serverError.requestTooLarge": (
        "Запрос ({size} МБ) превышает лимит {max} МБ. "
        "Удалите лишние файлы или оставьте только страницы с картой регистров."
    ),
    # --- Разбор файлов ---
    "serverError.excelUnreadable": (
        "Файл «{file}» не удалось прочитать как таблицу Excel. Возможно, это старый "
        "формат .xls или другой тип файла — сохраните таблицу как .xlsx и загрузите снова."
    ),
    "serverError.excelTooBig": (
        "Файл «{file}» объёмнее, чем сервис обрабатывает. Оставьте только лист "
        "с таблицей регистров или разделите документ на части."
    ),
    "serverError.imageTooLarge": (
        "Файл «{file}» имеет разрешение {width}×{height} — это больше, чем сервис "
        "обрабатывает. Уменьшите изображение или разделите его на части."
    ),
    # --- Анализ документа ---
    "serverError.noData": "Нет данных для анализа. Загрузите PDF, Excel или изображение.",
    # --- Пользовательский промпт ---
    "serverError.promptTooLarge": (
        "Системный промпт после подстановки плейсхолдеров занимает {size} символов "
        "при потолке {max} — сократите шаблон промпта в настройках LLM."
    ),
    "serverError.noRegisters": (
        "Не удалось извлечь регистры из документа. "
        "Проверьте, что документ содержит таблицу Modbus-регистров."
    ),
    "serverError.brokenImage": (
        "Файл «{file}» повреждён или не является изображением. "
        "Проверьте файл и загрузите заново."
    ),
    "serverError.modelUnsupportedFile": (
        "Модель не поддерживает переданный формат файла. Используйте модель "
        "с поддержкой PDF/Excel или конвертируйте в изображения вручную."
        "\n\nОшибка API: {reason}"
    ),
    "serverError.internalAnalyze": "Внутренняя ошибка при анализе документа. Повторите попытку.",
    "serverError.internalFix": "Внутренняя ошибка при исправлении регистров. Повторите попытку.",
    "serverError.llmNoResponse": (
        "Не удалось получить ответ от LLM API. Проверьте ключ, доступность "
        "провайдера и остаток квоты.\n\nОшибка LLM API: {reason}"
    ),
    "serverError.llmUnusableResults": "LLM не вернула пригодных результатов. Проверьте формат документа.",
    "serverError.llmUnusableResultsWithFragment": (
        "LLM не вернула пригодных результатов. Проверьте формат документа."
        "\n\nОтвет LLM (фрагмент):\n{fragment}"
    ),
    # Подставляется как {reason}, но описывает наш сбой разбора, а не отказ обращения —
    # отсюда строчная буква и отсутствие точки
    "serverError.llmUnparsableResponse": "ответ модели не удалось разобрать",
    "serverError.llmEmptyResponse": "LLM вернул пустой ответ",
    "serverError.llmNoRegisters": "LLM не вернул регистров",
    "serverError.fixFailed": "Не удалось исправить регистры — {reason}.",
    # --- Импорт шаблона ---
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
    # --- Категории сбоев провайдера LLM (подставляются как {reason}) ---
    "llmError.quota_exceeded": "у провайдера LLM закончилась квота",
    "llmError.auth": "провайдер LLM не принял ключ",
    "llmError.permission": "провайдер LLM отказал в доступе",
    "llmError.not_found": "провайдер LLM не нашёл модель или адрес",
    "llmError.bad_request": "провайдер LLM отклонил запрос",
    "llmError.rate_limit": "провайдер LLM ограничил частоту запросов",
    "llmError.timeout": "провайдер LLM не ответил за отведённое время",
    "llmError.connection": "не удалось соединиться с провайдером LLM",
    "llmError.server_error": "провайдер LLM вернул внутреннюю ошибку",
    "llmError.unknown": "обращение к провайдеру LLM не удалось",
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


def render_key(key: str) -> str:
    """Русский текст по ключу без параметров (категории сбоев LLM)."""
    return _TEXTS[key]


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
