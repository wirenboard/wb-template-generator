# CLAUDE.md

**Язык общения: русский. Все ответы, комментарии в коде, документация — на русском языке.**

## Проект

**WB Template Generator** — веб-сервис для генерации JSON-шаблонов Modbus-устройств для драйвера [wb-mqtt-serial](https://github.com/wirenboard/wb-mqtt-serial) (Wiren Board).

- **Репозиторий**: https://github.com/wirenboard/wb-template-generator
- **Issues**: https://github.com/wirenboard/wb-template-generator/issues

Пользователь загружает документацию устройства (PDF, Excel, изображение), LLM извлекает регистры, детерминированный скрипт собирает валидный JSON-шаблон. Визуальный редактор позволяет доработать результат.

## Стек

| Компонент | Технология |
|-----------|-----------|
| Backend | Python 3.12, FastAPI, uvicorn |
| Frontend | React 18, TypeScript, Vite, Zustand, Tailwind CSS v4 |
| i18n | Свой лёгкий словарь (4 языка: RU, EN, KZ, IT), `useT()` хук |
| LLM | OpenAI-compatible API (любой провайдер) |
| Контейнер | Docker: nginx (frontend) + uvicorn (backend) |

## Запуск и тестирование

**Все команды — только через Docker, НЕ локально.**

```bash
docker compose up --build -d          # Сборка и запуск
docker compose build --no-cache && docker compose up -d  # Без кеша
docker compose exec --user root backend pytest tests/ -v  # Бэкенд-тесты
docker compose exec --user root backend ruff check .      # Линтер
docker compose exec --user root backend mypy --config-file pyproject.toml models.py template_builder.py jinja_exporter.py  # Типы
docker run --rm -v $(pwd)/frontend:/app -w /app node:20-alpine sh -c "npm ci --ignore-scripts && npx vitest run"  # Фронтенд-тесты
docker compose down                   # Остановка
```

**Почему `--user root`.** Образ работает под непривилегированным пользователем `app`, и `/app` для него только на чтение — приложению запись не нужна, а инструментам разработки нужна. `mypy` без права создать `.mypy_cache` падает с `INTERNAL ERROR`, `ruff` не может создать `.ruff_cache`. `pytest` работает и без флага, но флаг оставлен для единообразия. В CI флаг не нужен, там гейты идут в отдельном `python:3.12-slim` от root.

Dev: `http://localhost:9080` (frontend), `http://localhost:9000` (backend).

## Флоу разработки

1. **Ветка**: каждая задача — в отдельной ветке от `main` (напр. `fix/16-import-error-feedback`, `feat/dark-mode`)
2. **Тесты**: новые фичи и фиксы покрываются тестами. Запуск — обязательно перед коммитом
3. **CHANGELOG**: обновлять `CHANGELOG.md` при каждом PR — записи в `[Unreleased]`, при релизе — перенести в `[X.Y.Z] - YYYY-MM-DD]`
4. **Версия**: берётся из первого `## [X.Y.Z]` в CHANGELOG.md (парсит бэкенд). При релизе — поднять версию
5. **Коммит**: осмысленное сообщение с префиксом (`fix:`, `feat:`, `refactor:`, `test:`, `docs:`)
6. **PR**: пуш ветки → PR в `main` через `gh pr create`

### CHANGELOG

Формат [Keep a Changelog](https://keepachangelog.com/) + [Semantic Versioning](https://semver.org/).

- Категории: `Добавлено`, `Изменено`, `Исправлено`, `Удалено`

## Структура проекта

```
backend/
  main.py              # FastAPI: эндпоинты, middleware, lifespan
  config.py            # Настройки из .env (pydantic-settings)
  models.py            # Pydantic-модели (Register, BuildRequest и т.д.)
  llm_service.py       # LLM-интеграция: analyze_document, автофикс регистров
  template_builder.py  # Детерминированная сборка JSON-шаблона
  template_importer.py # Импорт существующих .json/.json.jinja шаблонов
  serial_values.py     # Разбор значений в записи wb-mqtt-serial — одна трактовка на весь бэкенд
  jinja_exporter.py    # Экспорт в .json.jinja с детекцией паттернов
  file_converter.py    # Excel→text, изображения→base64 с потолками на разбор
  prompts.py           # Системные промпты для LLM
  queue_manager.py     # Управление очередями анализа (server + custom)
  sse.py               # Формирование SSE-событий
  request_context.py   # Request ID через ContextVar (middleware)
  tests/               # pytest: builder, importer, jinja_exporter, key_isolation

frontend/src/
  App.tsx              # Шапка (заголовок + "by AI" + версия + язык) + layout + футер
  store.ts             # Zustand store — всё состояние приложения
  api.ts               # API-клиент (SSE, REST, translate, import)
  types.ts             # TypeScript-типы (Register, DeviceInfo, RegisterGroup и т.д.)
  i18n/                # Словари 4 языков, useT() хук, getT() для non-React
  constants.ts         # Форматы, единицы, языки, channel_types
  utils/
    conditionValidation.ts  # Валидация condition-ссылок (только на параметры)
    serialValues.ts         # Разбор адреса и полей serial_int в записи wb-mqtt-serial
    numberInput.ts          # Разбор и вывод числа для текстового поля ввода
  components/
    RegisterTable.tsx         # Таблица + тулбар + hero-блок (пустое состояние)
    RegisterDetailPanel.tsx   # Панель деталей + NormalizeToEnButton
    LlmImportModal.tsx        # Модалка AI-анализа (файлы + прогресс)
    LlmSettings.tsx           # Модалка настроек LLM (URL, ключ, модель, промпт)
    GroupManager.tsx           # Управление группами
    GroupSection.tsx           # Секция группы в таблице (заголовок + collapse)
    LanguageManager.tsx        # Управление языками переводов
    TemplatePreview.tsx        # Превью JSON-шаблона
    ChannelPreview.tsx         # Превью канала в TemplatePreview
    ParameterPreview.tsx       # Превью параметра в TemplatePreview
    EnumEditor.tsx             # Редактор enum с переводами
    FormatSelect.tsx           # Селектор форматов с подсказками
    FileUpload.tsx             # Загрузка файлов (drag-n-drop)
    AnalyzeProgress.tsx        # Прогресс AI-анализа (SSE)
    ConfirmModal.tsx           # Модалка подтверждения (сброс и т.д.)
    NumberField.tsx            # Числовое поле ввода — все числовые поля только через него
    ErrorBoundary.tsx          # Обработка ошибок React
    ErrorDisplay.tsx           # Отображение ошибок импорта
  __tests__/                  # Vitest: store, i18n, condition-validation
```

## Подробная документация

- [Модель данных](docs/data-models.md) — DeviceInfo, Register, EnumEntry, RegisterGroup, формат wb-mqtt-serial
- [API и инфраструктура](docs/api.md) — эндпоинты, SSE-события, очереди, rate limiter, метрики
- [Функциональность](docs/features.md) — i18n, hero-блок, тулбар, нормализация, автоперевод, CSV, DnD, condition, jinja-экспорт
- [Настройки .env](docs/config.md) — все переменные окружения
- [План разработки](docs/development-plan.md) — бэклог идей
