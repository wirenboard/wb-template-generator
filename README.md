# WB Template Generator

Веб-сервис для генерации JSON-шаблонов Modbus-устройств для драйвера [wb-mqtt-serial](https://github.com/wirenboard/wb-mqtt-serial) (Wiren Board).

Пользователь загружает документацию устройства (PDF, Excel, изображение), LLM извлекает и классифицирует регистры, детерминированный скрипт собирает валидный JSON-шаблон. Визуальный редактор позволяет доработать результат перед экспортом.

## Быстрый старт

```bash
cp env.example .env
# Отредактируйте .env — укажите LLM_API_KEY и LLM_API_URL

docker compose up --build -d
# Откройте http://localhost:8080
```

## Как это работает

1. Загрузите PDF / Excel / изображение с таблицей Modbus-регистров
2. Выберите тип шаблона (Small / Medium / Full)
3. LLM проанализирует документ и извлечёт регистры
4. Доработайте результат в визуальном редакторе
5. Скачайте готовый `.json` или `.json.jinja` шаблон

### Типы шаблонов

| Тип | Описание |
|-----|----------|
| **Small** | 10-30 основных каналов для измерений и управления |
| **Medium** | Каналы + параметры конфигурации устройства |
| **Full** | Все регистры устройства без фильтрации |

## Архитектура

```
                ┌─────────┐     ┌─────────┐     ┌─────────────┐
 Браузер ──────>│  nginx  │────>│ FastAPI  │────>│ OpenAI API  │
                │ :8080   │     │ :8000    │     │ (любой LLM) │
                └─────────┘     └─────────┘     └─────────────┘
                 frontend        backend
```

- **Frontend**: React 18 + TypeScript + Vite + Zustand + Tailwind CSS v4
- **Backend**: Python 3.12 + FastAPI + uvicorn
- **LLM**: Любой OpenAI-совместимый API (OpenAI, Anthropic, локальный)
- **PDF**: pdfplumber + pdf2image + Pillow
- **Excel**: openpyxl
- **Контейнеризация**: Docker Compose (nginx + uvicorn)

## Структура проекта

```
backend/
  main.py              # FastAPI: эндпоинты, middleware, очереди, rate limiting
  config.py            # Настройки из .env (pydantic-settings)
  models.py            # Pydantic-модели (Register, BuildRequest и т.д.)
  llm_service.py       # LLM-интеграция: анализ документов, батчинг PDF
  template_builder.py  # Детерминированная сборка JSON-шаблона
  template_importer.py # Импорт существующих .json/.json.jinja шаблонов
  jinja_exporter.py    # Экспорт в .json.jinja с детекцией for-паттернов
  file_converter.py    # PDF -> images, Excel -> text, Image -> base64
  prompts.py           # Системные промпты для LLM
  sse.py               # SSE-события (progress, result, done, error)
  request_context.py   # ContextVar для request_id (трейсинг)
  queue_manager.py     # In-memory очередь на asyncio.Event
  mock_data.py         # Mock-данные для разработки без LLM
  tests/               # pytest-тесты + фикстуры

frontend/src/
  App.tsx              # Главный компонент (редактор)
  api.ts               # API-клиент (SSE, REST)
  store.ts             # Zustand store — всё состояние приложения
  types.ts             # TypeScript типы
  constants.ts         # Форматы, единицы, языки
  components/          # UI-компоненты редактора
```

## API

| Метод | Путь | Описание |
|-------|------|----------|
| POST | `/api/analyze` | SSE — анализ документа через LLM |
| POST | `/api/cancel-analyze` | Отмена запроса в очереди |
| POST | `/api/build` | Сборка JSON-шаблона из регистров |
| POST | `/api/build-jinja` | Сборка Jinja-шаблона (.json.jinja) |
| POST | `/api/import-template` | Импорт .json / .json.jinja |
| POST | `/api/translate` | Перевод строк через LLM |
| POST | `/api/models` | Список моделей LLM API |
| GET | `/api/status` | Статус сервера (LLM, лимиты) |
| GET | `/api/health` | Healthcheck (uptime, очереди) |
| GET | `/api/queue-status` | Состояние очередей |
| GET | `/api/metrics` | Метрики (счётчики, гистограммы) |

### SSE-события `/api/analyze`

```
event: progress  ->  {stage, message, current?, total?, request_id, queue_position?, queue_eta?}
event: result    ->  {request_id, device_info, registers}
event: done      ->  {message, request_id}
event: error     ->  {message, request_id}
```

Стадии прогресса: `queued` -> `uploading` -> `converting` -> `analyzing` -> `slow` -> `merging` -> done/error.

Стадия `slow` — мягкий таймаут (по умолчанию 3 мин), анализ продолжается, но пользователю предлагается подождать или отменить.

## Настройки

Все настройки через переменные окружения (`.env`). См. `env.example`.

### LLM

| Переменная | По умолчанию | Описание |
|------------|-------------|----------|
| `LLM_API_URL` | _(пусто)_ | URL OpenAI-совместимого API. Пусто = mock-режим |
| `LLM_API_KEY` | _(пусто)_ | API-ключ |
| `LLM_MODEL` | `gpt-5-mini` | Модель |
| `LLM_MAX_TOKENS` | `16384` | Максимум токенов в ответе |
| `LLM_TIMEOUT` | `600` | Жёсткий таймаут HTTP-запроса к LLM (сек) |
| `LLM_SOFT_TIMEOUT` | `180` | Мягкий таймаут — предложить продлить (сек) |
| `LLM_TEMPERATURE` | _(пусто)_ | Температура (пусто = дефолт модели) |
| `PDF_BATCH_SIZE` | `0` | Страниц на батч (0 = все одним запросом) |

### Очереди и лимиты

| Переменная | По умолчанию | Описание |
|------------|-------------|----------|
| `QUEUE_SERVER_MAX_CONCURRENT` | `15` | Параллельных запросов к серверному LLM |
| `QUEUE_CUSTOM_MAX_CONCURRENT` | `15` | Параллельных запросов с пользовательским LLM |
| `QUEUE_ACTIVATION_DELAY` | `1.0` | Задержка между запусками из очереди (сек) |
| `RATE_LIMIT_REQUESTS` | `10` | Запросов за окно |
| `RATE_LIMIT_WINDOW` | `60` | Окно rate limit (сек) |

## Продакшен-инфраструктура

- **Request ID**: каждый запрос получает 8-символьный hex ID, который пробрасывается через SSE, логи и заголовок `X-Request-Id`
- **Очереди**: in-memory на `asyncio.Event`, раздельные для серверного и пользовательского LLM, с задержкой между активациями
- **Rate limiter**: sliding window по IP
- **Изоляция LLM**: при серверном LLM пользовательский system_prompt игнорируется
- **Мягкий таймаут**: через 3 мин анализа пользователю предлагается продолжить или отменить
- **SSE keepalive**: каждые 15 сек отправляется прогресс с таймером, чтобы nginx не убивал соединение
- **Метрики**: in-memory счётчики и гистограммы в `/api/metrics`

## Разработка

```bash
# Dev-режим (host networking, hot reload)
docker compose up --build -d

# Frontend: http://localhost:9080
# Backend:  http://localhost:9000

# Тесты
docker compose exec backend pytest tests/ -v

# Пересборка без кеша (при изменении зависимостей)
docker compose build --no-cache && docker compose up -d

# Логи
docker compose logs -f backend
```

### Mock-режим

Если `LLM_API_URL` не задан — backend работает в mock-режиме с тестовыми данными SDM-230. Удобно для разработки фронтенда без реального LLM.

## Формат шаблона wb-mqtt-serial

Генерируемые шаблоны соответствуют формату [wb-mqtt-serial](https://github.com/wirenboard/wb-mqtt-serial).

Допустимые значения полей:

- **type**: value, switch, pushbutton, range, text, alarm, rgb, wo-switch, temperature, voltage, current, power, ...
- **format**: u16, s16, u32, s32, u64, float, string
- **reg_type**: holding, input, coil, discrete
- **units**: V, A, deg C, %, RH, Ohm, bar, ppm, W, kWh, ...

### Jinja-экспорт

Экспорт в `.json.jinja` автоматически обнаруживает повторяющиеся каналы с числом в имени и арифметической прогрессией адресов, сворачивая их в `{% for %}` циклы.
