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

Jenkinsfile.checks      # multibranch: сторож свежести → линт → тесты → сборка образов ветки
Jenkinsfile             # выкат (привязан к main): выкат по метке → проверка живости → авто-возврат
Jenkinsfile.rollback    # кнопка отката
Makefile                # только локальные цели: lint / test / build / up / down / smoke
docker-compose.yml      # локальная разработка
docker-compose.deploy.yml  # прод: образы по ${DEPLOY_TAG}, без build:

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
