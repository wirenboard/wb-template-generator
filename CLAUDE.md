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
docker compose exec backend pytest tests/ -v             # Бэкенд-тесты (142)
docker run --rm -v $(pwd)/frontend:/app -w /app node:20-alpine sh -c "npm ci --ignore-scripts && npx vitest run"  # Фронтенд-тесты (75)
docker compose down                   # Остановка
```

Dev: `http://localhost:9080` (frontend), `http://localhost:9000` (backend).

## Стек

| Компонент | Технология |
|-----------|-----------|
| Backend | Python 3.12, FastAPI, uvicorn |
| Frontend | React 18, TypeScript, Vite, Zustand, Tailwind CSS v4 |
| i18n | Свой лёгкий словарь (4 языка: RU, EN, KZ, IT), `useT()` хук |
| LLM | OpenAI-compatible API (любой провайдер) |
| Контейнер | Docker: nginx (frontend) + uvicorn (backend) |

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
  tests/               # pytest: builder, importer, jinja_exporter

frontend/src/
  App.tsx              # Шапка (заголовок + "by AI" + версия + язык) + layout
  store.ts             # Zustand store — всё состояние приложения
  api.ts               # API-клиент (SSE, REST, translate, import)
  i18n/                # Словари 4 языков, useT() хук, getT() для non-React
  constants.ts         # Форматы, единицы, языки, channel_types
  components/
    RegisterTable.tsx         # Таблица + тулбар + hero-блок (пустое состояние)
    RegisterDetailPanel.tsx   # Панель деталей + NormalizeToEnButton
    LlmImportModal.tsx        # Модалка AI-анализа (файлы + прогресс)
    GroupManager.tsx           # Управление группами
    LanguageManager.tsx        # Управление языками переводов
    TemplatePreview.tsx        # Превью JSON-шаблона
    EnumEditor.tsx             # Редактор enum с переводами
  __tests__/                  # Vitest: store-тесты (75 тестов)
```

## Ключевые концепции

- **Hero-блок**: при пустой таблице — 3 карточки (AI / Импорт / Вручную) с drag-n-drop роутингом по расширению файла
- **Тулбар**: скрыт при пустой таблице; при наличии регистров — только инструменты редактирования
- **i18n**: `useT()` в компонентах, `getT()` в api.ts/store.ts; ошибки бэкенда на EN, перевод на фронте
- **Нормализация → EN**: `HAS_NON_LATIN` regex — любой нелатинский текст, не только кириллица
- **Condition**: regex-парсинг, подсветка связанных регистров при клике
- **Jinja-экспорт**: автодетекция числовых/строковых/вариантных паттернов → `{% for %}` циклы

## CHANGELOG

Формат [Keep a Changelog](https://keepachangelog.com/) + [Semantic Versioning](https://semver.org/).

**При каждом PR обязательно обновлять `CHANGELOG.md`:**
- Добавлять записи в секцию `[Unreleased]`
- Категории: `Добавлено`, `Изменено`, `Исправлено`, `Удалено`
- При релизе — перенести из `[Unreleased]` в `[X.Y.Z] - YYYY-MM-DD`

## Подробная документация

- [Модель данных](docs/data-models.md) — DeviceInfo, Register, EnumEntry, RegisterGroup, формат wb-mqtt-serial
- [API и инфраструктура](docs/api.md) — эндпоинты, SSE-события, очереди, rate limiter, метрики
- [Функциональность](docs/features.md) — i18n, hero-блок, тулбар, нормализация, автоперевод, CSV, DnD, condition, jinja-экспорт
- [Настройки .env](docs/config.md) — все переменные окружения
- [План разработки](docs/development-plan.md) — бэклог идей
