# CLAUDE.md

**Язык общения: русский. Все ответы, комментарии в коде, документация — на русском языке.**

## Обзор

WB Template Generator — веб-сервис для генерации JSON-шаблонов Modbus-устройств для драйвера wb-mqtt-serial (Wiren Board).

Пользователь загружает документацию устройства (PDF, Excel, изображение), LLM извлекает регистры, детерминированный скрипт собирает валидный JSON-шаблон. Визуальный редактор позволяет доработать результат.

## Запуск и тестирование

**Все команды — только через Docker, НЕ локально.**

```bash
docker compose up --build -d          # Сборка и запуск
docker compose build --no-cache && docker compose up -d  # Без кеша
docker compose exec backend pytest tests/ -v             # Тесты
docker compose down                   # Остановка
```

Dev: `http://localhost:9080` (frontend), `http://localhost:9000` (backend).

## Стек

| Компонент | Технология |
|-----------|-----------|
| Backend | Python 3.12, FastAPI, uvicorn |
| Frontend | React 18, TypeScript, Vite, Zustand, Tailwind CSS v4 |
| LLM | OpenAI-compatible API (любой провайдер) |
| Контейнер | Docker: nginx (frontend) + uvicorn (backend) |
| PDF | pdfplumber, pdf2image + Pillow |
| Excel | openpyxl |

## Структура проекта

```
backend/
  main.py              # FastAPI: эндпоинты, middleware, lifespan
  config.py            # Настройки из .env (pydantic-settings)
  models.py            # Pydantic-модели (Register, BuildRequest и т.д.)
  llm_service.py       # LLM-интеграция: analyze_document, batch-обработка PDF
  template_builder.py  # Детерминированная сборка JSON-шаблона
  template_importer.py # Импорт существующих .json/.json.jinja шаблонов
  jinja_exporter.py    # Экспорт в .json.jinja с детекцией паттернов
  file_converter.py    # PDF→images, Excel→text, Image→base64
  prompts.py           # Системные промпты для LLM
  sse.py               # SSE-события: progress, result, done, error, keepalive
  request_context.py   # ContextVar для request_id
  queue_manager.py     # In-memory очередь на asyncio.Event
  mock_data.py         # Mock-данные для разработки без LLM
  tests/
    __init__.py
    test_template_builder.py
    test_template_importer.py
    test_jinja_exporter.py
    fixtures/
      sdm230_registers.json
      sdm230_expected.json
      config-akko.json
      config-arlight-dali-logic-lite-ps-x1.json.jinja
      config-wb-mcm8.json.jinja
      config-wb-ups-v3.json.jinja

frontend/src/
  main.tsx             # Точка входа: ReactDOM + ErrorBoundary
  App.tsx              # Главный компонент
  api.ts               # API-клиент (SSE, REST, translate, import)
  store.ts             # Zustand store — всё состояние приложения
  types.ts             # TypeScript типы (Register, WBTemplate и т.д.)
  constants.ts         # Форматы, единицы, языки, channel_types по reg_type
  components/
    RegisterTable.tsx         # Таблица регистров с inline-редактированием, DnD, CSV
    RegisterDetailPanel.tsx   # Раскрывающаяся панель деталей регистра + NormalizeToEnButton
    EnumEditor.tsx            # Редактор enum с переводами по языкам
    FormatSelect.tsx          # Dropdown формата с описаниями
    GroupManager.tsx          # Модалка управления группами
    GroupSection.tsx          # Сворачиваемая секция группы
    LanguageManager.tsx       # Модалка управления языками переводов
    ConfirmModal.tsx          # Модалка подтверждения (замена window.confirm)
    TemplatePreview.tsx       # Превью итогового JSON-шаблона
    ChannelPreview.tsx        # Превью канала wb-mqtt-serial
    ParameterPreview.tsx      # Превью параметра
    FileUpload.tsx            # Drag-n-drop загрузка файлов
    LlmImportModal.tsx        # Модалка LLM-импорта (файлы + анализ)
    LlmSettings.tsx           # Настройки LLM (URL, ключ, модель, temperature)
    AnalyzeProgress.tsx       # Прогресс-бар + очередь + подсказка
    ErrorDisplay.tsx          # Ошибка анализа + копирование лога для ТП
    ErrorBoundary.tsx         # React Error Boundary
```

## API-эндпоинты

| Метод | Путь | Назначение |
|-------|------|-----------|
| POST | `/api/analyze` | **SSE** — анализ документа через LLM |
| POST | `/api/cancel-analyze` | Отмена запроса в очереди |
| POST | `/api/build` | Сборка JSON-шаблона из регистров |
| POST | `/api/build-jinja` | Сборка Jinja-шаблона (.json.jinja) |
| POST | `/api/import-template` | Импорт .json / .json.jinja |
| POST | `/api/translate` | Перевод строк через LLM |
| POST | `/api/models` | Список моделей LLM API |
| GET | `/api/status` | Статус сервера (LLM, лимиты) |
| GET | `/api/prompts` | Сырые промпты для редактирования |
| GET | `/api/health` | Healthcheck (uptime, очереди) |
| GET | `/api/queue-status` | Состояние очередей |
| GET | `/api/metrics` | Метрики (счётчики, гистограммы) |

## SSE-события `/api/analyze`

```
event: progress   → {stage, message, current?, total?, request_id, queue_position?, queue_eta?}
event: result     → {request_id, device_info, registers}
event: done       → {message, request_id}
event: error      → {message, request_id}
```

Стадии: `queued` → `uploading` → `converting` → `analyzing` → `merging` → done/error.

## Модель данных

### DeviceInfo

- `name: str`, `id: str` — имя и идентификатор устройства
- `device_group: str | None` — группа устройства
- `hw: list[dict] | None` — аппаратные варианты (roundtrip)
- `max_read_registers: int | None` — макс. регистров за одно чтение
- `response_timeout_ms: int | None`, `frame_timeout_ms: int | None` — таймауты
- `enable_wb_continuous_read: bool | None` — непрерывное чтение WB
- `title_key: str | None`, `title_translations: dict[str, str] | None` — ключ и переводы заголовка

### Register (ключевые поля)

- `address: int | str` — число или `"109:1:2"` (register:bit_offset:bit_width)
- `name: str` — английское имя
- `reg_type`: holding, input, coil, discrete
- `format`: u16, s16, u32, s32, u64, s64, float, double, u8, s8, string
- `scale`, `offset` — final = raw * scale + offset
- `units: str | None` — единицы измерения
- `access`: read, write, readwrite
- `is_parameter: bool` — false=канал (данные/управление), true=параметр (настройки)
- `channel_type`: value, switch, wo-switch, pushbutton, range, text, alarm, rgb
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

### EnumEntry

- `value: int` — числовое значение
- `title: str` — английский заголовок
- `translations: dict[str, str] | None` — `{lang: title}`, напр. `{"ru": "Включено"}`

### RegisterGroup

- `id`, `title`, `order`, `description?`
- `translations: dict[str, GroupTranslation] | None` — переводы (title + description по языкам)
- `parent_group: str | None` — вложенная группа (для иерархии)
- `ui_options: dict | None` — визуальные настройки группы (roundtrip)

## Нормализация → EN (NormalizeToEnButton)

Кнопка `NormalizeToEnButton` в `RegisterDetailPanel.tsx` — переводит кириллицу в английский текст с помощью LLM:

- Работает для полей `name` и `description` каждого регистра
- При нажатии: текущий русский текст сохраняется в `translations.ru`, основное поле заменяется на английский перевод
- Автоматически добавляет язык `ru` в список языков, если его ещё нет

Массовая нормализация: `store.normalizeToEnglish()` — обрабатывает все регистры и группы с кириллицей, включая enum_entries. Вызывается через меню "Нормализовать → EN" в тулбаре `RegisterTable`.

## Автоперевод и языки

- **LanguageManager** — модалка для управления списком языков (сохраняется в localStorage)
- **translateAll(lang)** — пакетный перевод всех пустых полей на указанный язык через LLM
- **propagateEnumTranslation** — при изменении перевода enum-значения автоматически обновляет тот же перевод во всех регистрах с таким же enum title
- Базовый язык — English (en), всегда включён. Дополнительные языки добавляются пользователем

## CSV импорт/экспорт

`RegisterTable.tsx` поддерживает CSV-операции через меню тулбара:
- **Экспорт** — выгрузка текущих регистров в CSV
- **Импорт** — загрузка регистров из CSV (поддержка запятой и точки с запятой как разделителей)
- **Скачать шаблон** — пустой CSV с заголовками для заполнения вручную

## Drag-n-Drop

- **Перемещение между группами**: `moveRegistersToGroup(regIds, targetGroupId)` — перенос регистров в другую группу
- **Изменение порядка**: `reorderRegister(draggedId, targetId, 'before'|'after')` — перетаскивание регистров для изменения порядка внутри/между группами

## Condition-подсветка

В `RegisterTable.tsx` реализована визуальная связь между каналами и параметрами через condition:

- **При клике**: выделенный регистр — жёлтый (`bg-yellow-100`), связанные через condition — фиолетовые (`bg-purple-50`). Поиск по `name`, `id` и `original_channel_id`.
- **Постоянные бейджи**: фиолетовый бейдж с числом — параметр влияет на N каналов; янтарный `?=` — у регистра есть condition.

Condition парсится regex: `(?:^|[^a-zA-Z0-9_])([a-zA-Z_][a-zA-Z0-9_]*?)(?:==|!=|>=|<=|>|<)` — поддерживает `isDefined(param)&&param==1` и множественные условия.

## Продакшен-инфраструктура

- **Request ID**: 8 hex символов, ContextVar, заголовок X-Request-Id, во всех SSE и логах
- **Очереди**: server (max 15) + custom (max 15), asyncio.Event, позиция + ETA в SSE, антиспам-задержка
- **Rate limiter**: sliding window по IP (10 запросов/60 сек)
- **Изоляция LLM**: при серверном LLM пользовательский system_prompt игнорируется
- **Кастомный промпт**: `customSystemPrompt` хранится в localStorage, передаётся только при пользовательском LLM
- **Метрики**: in-memory счётчики и гистограммы в `/api/metrics`
- **Graceful shutdown**: отмена ожидающих запросов, ожидание активных до 30 сек
- **Автосохранение**: состояние редактора (registers, groups, deviceInfo, llmConfig) сохраняется в localStorage с debounce

## Jinja-экспорт

`jinja_exporter.py` обнаруживает повторяющиеся структуры и сворачивает в `{% for %}` циклы:

- **Числовые паттерны**: каналы/группы/параметры с числом в имени ("Input 1"..."Input 8") и арифметической прогрессией адресов
- **Строковые паттерны**: каналы с одинаковой структурой, различающиеся одним словом в имени ("Button Single Press Counter", "Button Long Press Counter"...) → `{% for val in [...] %}`
- **Вариантные каналы (sporadic)**: каналы с одинаковым именем но разными sporadic/condition → вложенный `{% for %}` по вариантам
- **Переводы (translations)**: повторяющиеся ключи в секции translations сворачиваются в for-циклы
- **Шаблонизируемые поля**: group, condition — если содержат варьирующийся номер, заменяются на `{{ i }}`

Минимум 2 элемента для паттерна. Числовые паттерны имеют приоритет над строковыми.

## Настройки (.env)

```bash
LLM_API_URL=           # URL OpenAI-совместимого API
LLM_API_KEY=           # API-ключ (необязательно для локальных LLM)
LLM_MODEL=gpt-5-mini   # Модель
LLM_MAX_TOKENS=16384
LLM_LEGACY_MAX_TOKENS=false  # true = max_tokens (старые API), false = max_completion_tokens
LLM_TEMPERATURE=       # пусто = дефолт модели, 0.0-2.0
LLM_PROXY=             # HTTP/SOCKS5 прокси для запросов к LLM API
LLM_TIMEOUT=600        # Жёсткий таймаут HTTP-запроса к LLM (сек)
LLM_SOFT_TIMEOUT=180   # Мягкий таймаут — предложить продолжить/отменить (сек)
PDF_BATCH_SIZE=0       # 0 = все страницы одним запросом
MAX_FILE_SIZE_MB=1
QUEUE_SERVER_MAX_CONCURRENT=15   # Параллельных запросов к серверному LLM
QUEUE_CUSTOM_MAX_CONCURRENT=15   # Параллельных запросов с пользовательским LLM
QUEUE_ACTIVATION_DELAY=1.0       # Задержка между запусками из очереди (сек)
RATE_LIMIT_REQUESTS=10
RATE_LIMIT_WINDOW=60
```

## Формат целевого шаблона (wb-mqtt-serial)

- **channel.type**: value, switch, wo-switch, pushbutton, range, text, alarm, rgb, temperature, voltage, current, power, ...
- **channel.format**: u16, s16, u32, s32, u64, s64, float, double, u8, s8, string
- **channel.reg_type**: holding, input, coil, discrete, holding_single, holding_multi
- **channel.units**: V, mV, A, mA, W, kWh, Hz, rpm, Ohm, mOhm, bar, mbar, Pa, deg C, %, RH, ppm, ppb, lx, dB, s, min, h, m, mm/h, m/s, m^3/h, m^3, g, kg, mol, cd, Gcal/h, cal, Gcal, deg, rad
