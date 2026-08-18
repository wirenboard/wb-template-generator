# WB Template Generator

Веб-сервис для создания и редактирования JSON-шаблонов Modbus-устройств для драйвера [wb-mqtt-serial](https://github.com/wirenboard/wb-mqtt-serial) (Wiren Board).

## Возможности

- **Автоматическая генерация через LLM** — загрузите документацию устройства (PDF, Excel, изображение с таблицей регистров), и LLM извлечёт все Modbus-регистры, определит типы каналов, параметры, единицы измерения и enum-значения
- **Создание шаблона вручную** — добавляйте регистры по одному через визуальный редактор: адрес, тип, формат, масштаб, группа, enum и другие свойства
- **Импорт существующих шаблонов** — загрузите готовый `.json` или `.json.jinja` шаблон wb-mqtt-serial для редактирования и доработки
- **Визуальный редактор** — таблица регистров с inline-редактированием, drag-n-drop сортировкой, группировкой, CSV импортом/экспортом
- **Превью шаблона** — интерактивное превью справа показывает как устройство будет выглядеть в интерфейсе Wiren Board (каналы, параметры, переключатели, слайдеры)
- **Мультиязычность** — переводы названий каналов и enum-значений на любые языки, автоперевод через LLM
- **Экспорт** — скачивание готового `.json` шаблона или `.json.jinja` (с автоматическим обнаружением повторяющихся паттернов и сворачиванием в `{% for %}` циклы)

## Скриншоты

### Пустой интерфейс
![Пустой интерфейс](docs/images/01-empty.png)

### Анализ документа через LLM
![Анализ LLM](docs/images/02-analyze.png)

### Таблица регистров с превью шаблона
![Таблица регистров](docs/images/03-table.png)

## Быстрый старт

```bash
cp env.example .env
# Отредактируйте .env — укажите LLM_API_KEY и LLM_API_URL

docker compose up --build -d
# Откройте http://localhost:9080
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
                │ :9080   │     │ :9000    │     │ (любой LLM) │
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
  llm_service.py       # LLM-интеграция: анализ документов, автофикс регистров
  template_builder.py  # Детерминированная сборка JSON-шаблона
  template_importer.py # Импорт существующих .json/.json.jinja шаблонов
  jinja_exporter.py    # Экспорт в .json.jinja с детекцией for-паттернов
  file_converter.py    # PDF -> images, Excel -> text, Image -> base64
  prompts.py           # Системные промпты для LLM
  sse.py               # SSE-события (progress, result, done, error)
  request_context.py   # ContextVar для request_id (трейсинг)
  queue_manager.py     # In-memory очередь на asyncio.Semaphore
  pyproject.toml       # Конфиг ruff, mypy, pytest
  tests/               # pytest-тесты + фикстуры

frontend/src/
  App.tsx              # Главный компонент (редактор)
  api.ts               # API-клиент (SSE, REST)
  store.ts             # Zustand store — всё состояние приложения
  types.ts             # TypeScript типы
  constants.ts         # Форматы, единицы, языки
  components/          # UI-компоненты редактора

Jenkinsfile.checks     # проверки: сторож свежести → lint → test → сборка образов ветки
Jenkinsfile            # выкат: по метке <ветка>-<git-SHA> → проверка живости → авто-возврат
Jenkinsfile.rollback   # кнопка отката

Makefile               # локальные команды: make lint / test / build / up / down / smoke
DEPLOYING.md           # операторская карточка: как выкатить, откатить, что делать при аварии
```

## API

| Метод | Путь | Описание |
|-------|------|----------|
| POST | `/api/analyze` | SSE — анализ документа через LLM |
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

Стадии прогресса: `queued` -> `uploading` -> `converting` -> `analyzing` -> `merging` -> `validating` -> `autofix?` -> done/error.

Стадия `slow` не звено цепочки, а замена `analyzing` после мягкого таймаута (`LLM_SOFT_TIMEOUT`, по умолчанию 3 мин): анализ продолжается, но пользователю предлагается подождать или отменить. Стадия `autofix` появляется только если валидация нашла ошибки.

## Настройки

Все настройки через переменные окружения (`.env`). См. `env.example`.

### LLM

| Переменная | По умолчанию | Описание |
|------------|-------------|----------|
| `LLM_API_URL` | _(пусто)_ | URL OpenAI-совместимого API. Пусто = анализ недоступен, пока пользователь не укажет свой LLM в настройках |
| `LLM_API_KEY` | _(пусто)_ | API-ключ |
| `LLM_MODEL` | `gpt-5.6-luna` | Модель (`gpt-5.4-mini` — ещё дешевле, `gpt-5.5` — дороже, качество то же) |
| `LLM_MAX_TOKENS` | `0` | 0 = без ограничения, >0 = лимит токенов |
| `LLM_LEGACY_MAX_TOKENS` | `false` | `true` = `max_tokens` (старые API), `false` = `max_completion_tokens` |
| `LLM_TIMEOUT` | `600` | Жёсткий таймаут HTTP-запроса к LLM (сек) |
| `LLM_SOFT_TIMEOUT` | `180` | Мягкий таймаут — предложить продлить (сек) |
| `LLM_TEMPERATURE` | _(пусто)_ | Пусто = дефолт модели (нужно для gpt-5.x); 0 = детерминизм для gpt-4o/локальных |
| `LLM_PROXY` | _(пусто)_ | HTTP/SOCKS5 прокси для запросов к LLM API |
| `LLM_ALLOW_PRIVATE_URLS` | `false` | Разрешить пользовательский адрес LLM во внутренней сети |
| `MAX_FILE_SIZE_MB` | `2` | Максимальный размер загружаемого файла (МБ) |

### Очереди и лимиты

| Переменная | По умолчанию | Описание |
|------------|-------------|----------|
| `QUEUE_SERVER_MAX_CONCURRENT` | `15` | Параллельных запросов к серверному LLM |
| `QUEUE_CUSTOM_MAX_CONCURRENT` | `15` | Параллельных запросов с пользовательским LLM |
| `QUEUE_ACTIVATION_DELAY` | `1.0` | Задержка перед стартом того, кто ждал в очереди (сек) |
| `RATE_LIMIT_REQUESTS` | `10` | Запросов за окно |
| `RATE_LIMIT_WINDOW` | `60` | Окно rate limit (сек) |

### Сервер

| Переменная | По умолчанию | Описание |
|------------|-------------|----------|
| `CORS_ORIGINS` | `*` | Разрешённые origins через запятую |
| `LOG_FORMAT` | `text` | Формат логов: `text` (dev) или `json` (prod) |

## Продакшен-инфраструктура

- **Request ID**: каждый запрос получает 8-символьный hex ID, который пробрасывается через SSE, логи и заголовок `X-Request-Id`
- **Очереди**: in-memory на `asyncio.Semaphore`, раздельные для серверного и пользовательского LLM, с задержкой перед стартом того, кто ждал
- **Rate limiter**: sliding window по IP
- **Изоляция LLM**: при серверном LLM пользовательский system_prompt игнорируется
- **Мягкий таймаут**: через 3 мин анализа пользователю предлагается продолжить или отменить
- **SSE keepalive**: каждые 15 сек отправляется прогресс с таймером, чтобы nginx не убивал соединение
- **Метрики**: in-memory счётчики и гистограммы в `/api/metrics`
- **Security headers**: `X-Content-Type-Options`, `X-Frame-Options`, `Content-Security-Policy`, `Referrer-Policy` (в prod nginx)
- **JSON-логи**: `LOG_FORMAT=json` включает структурированные логи с таймингами операций
- **CORS**: параметризован через `CORS_ORIGINS` — `*` для dev, конкретные origins для prod
- **Валидация файлов**: проверка MIME-типа и расширения загружаемых файлов (pdf, xlsx, png, jpg, jpeg, webp)

### Продакшен-деплой

Выкат автоматический и **сборки на сервере нет**: образы собираются в CI и помечаются
git-SHA, сервер только скачивает готовый образ. Поэтому любую версию можно вернуть за
секунды — она уже лежит в реестре.

- Смержил PR в `main` → джоба выката в Jenkins сама выкатывает и проверяет живость.
- Откат — **Jenkins → rollback → Build with Parameters** (пустой `TARGET_SHA` = предыдущая выкаченная версия).
- Пошагово, включая аварийные сценарии и break-glass, — в [`DEPLOYING.md`](DEPLOYING.md).
- Что сейчас в проде: имя последнего зелёного прогона джобы выката или `/api/status` (поле `revision`).

Прод-конфигурация — `docker-compose.deploy.yml` в репозитории `wirenboard/infra`
(роль `wb_template_generator`): образы по
git-SHA из `ghcr.io`, bridge-сеть, `restart: always`, healthcheck-зависимость frontend от
backend. Порт публикуется **только на `127.0.0.1:8080`** — снаружи сервис отдаёт nginx на
хосте (он держит TLS и домен), напрямую в контейнер извне не ходят. Креды (ключ на хост, push в реестр) живут в Jenkins, в папке сервиса; `Jenkinsfile`
называет их по имени. `.env` с ключами — на сервере, в репозиторий не попадает.

**Здесь лежит только `docker-compose.yml` — для локальной разработки** (`make up`): собирает образы из исходников, host networking, порты 9080/9000.

Прод-файл выката (`docker-compose.deploy.yml`) живёт в `wirenboard/infra`, роль `wb_template_generator`: скачивает готовый образ по метке из `ghcr.io`, публикует только на `127.0.0.1:8080`.

## Разработка

```bash
# Dev-режим (host networking, hot reload)
docker compose up --build -d

# Frontend: http://localhost:9080
# Backend:  http://localhost:9000

# Тесты
docker compose exec backend pytest tests/ -v

# Тесты с покрытием
docker compose exec backend pytest tests/ -v --cov=. --cov-report=term

# Линтинг
docker compose exec backend ruff check .

# Проверка типов
docker compose exec backend mypy models.py template_builder.py jinja_exporter.py

# Пересборка без кеша (при изменении зависимостей)
docker compose build --no-cache && docker compose up -d

# Логи
docker compose logs -f backend
```

### CI/CD

Один вход для всех проверок — `make`: те же команды локально и в CI.

```bash
make lint      # ruff + mypy, eslint + tsc
make test      # pytest --cov (порог 70%) + vitest
```

| Джоба | Когда | Что делает |
|---|---|---|
| `Jenkinsfile.checks` | ветки и PR | сторож свежести → `make lint` → `make test` → сборка образов ветки в реестр |
| `Jenkinsfile` | merge в `main` или кнопка | выкат по метке → проверка живости → авто-возврат при провале |
| `Jenkinsfile.rollback` | кнопка | откат на предыдущую выкаченную версию или на указанную метку |

Логика выката живёт в общей библиотеке Jenkins (`wirenboard/jenkins-pipeline-lib`),
здесь — только тонкие вызовы с настройками сервиса.

## Формат шаблона wb-mqtt-serial

Генерируемые шаблоны соответствуют формату [wb-mqtt-serial](https://github.com/wirenboard/wb-mqtt-serial).

Допустимые значения полей:

- **type**: value, switch, pushbutton, range, text, rgb, wo-switch, temperature, voltage, current, power, ...
- **format**: u16, s16, u32, s32, u64, float, string
- **reg_type**: holding, input, coil, discrete
- **units**: V, A, deg C, %, RH, Ohm, bar, ppm, W, kWh, ...

### Jinja-экспорт

При экспорте в `.json.jinja` автоматически обнаруживаются повторяющиеся структуры и сворачиваются в `{% for %}` циклы:

- **Числовые паттерны** — каналы с числом в имени ("Input 1"..."Input 8") и арифметической прогрессией адресов
- **Строковые паттерны** — каналы с одинаковой структурой, различающиеся одним словом ("Button Single Press", "Button Long Press") → `{% for val in [...] %}`
- **Вариантные каналы** — каналы с одинаковым именем но разными sporadic/condition → вложенный `{% for %}` по вариантам
- **Переводы** — повторяющиеся ключи в секции translations сворачиваются в циклы
- **Шаблонизируемые поля** — group, condition с варьирующимся номером заменяются на `{{ i }}`

Минимум 2 элемента для обнаружения паттерна. Числовые паттерны имеют приоритет над строковыми.
