# Changelog

Все заметные изменения проекта документируются в этом файле.

Формат основан на [Keep a Changelog](https://keepachangelog.com/ru/1.1.0/),
проект придерживается [Semantic Versioning](https://semver.org/lang/ru/).

## [Unreleased]

### Добавлено
- Автоматическое версионирование: backend парсит версию из CHANGELOG.md при старте
- Отображение версии приложения в шапке UI (бейдж `vX.Y.Z`)
- CI: проверка обновления CHANGELOG.md в pull request (мягкое предупреждение)
- `.dockerignore` для оптимизации контекста сборки

### Исправлено
- Фикс `crypto.randomUUID()` в non-secure context (HTTP) (#11)
- Версия в коде (`main.py`) синхронизирована с CHANGELOG.md (была захардкожена `0.2.0`)

### Изменено
- CHANGELOG.md — единственный источник истины для версии приложения
- Docker: build context backend'а перенесён на корень проекта для доступа к CHANGELOG.md

## [0.3.0] - 2026-02-18

### Добавлено
- Фронтенд unit-тесты для Zustand store (75 тестов, Vitest)
- CI: шаг `npm test` во frontend job

## [0.2.0] - 2026-02-18

### Добавлено
- CI/CD: GitHub Actions (lint, typecheck, тесты бэкенда с покрытием ≥70%)
- Docker prod-конфигурация (`docker-compose.prod.yml`, HEALTHCHECK)
- Nginx: gzip, security headers, кеш статики
- Ruff, mypy, pytest-cov в зависимостях бэкенда
- README: возможности, настройки, скриншоты

### Исправлено
- Ошибки линтера фронтенда: `let`→`const`, неиспользуемые переменные (#8)

## [0.1.0] - 2026-02-18

### Добавлено
- Начальный релиз: загрузка PDF/Excel/изображений, анализ через LLM, визуальный редактор регистров
- Детерминированная сборка JSON-шаблона для wb-mqtt-serial
- Jinja-экспорт с детекцией паттернов (числовые, строковые, вариантные циклы)
- Импорт существующих `.json` / `.json.jinja` шаблонов
- Система переводов на N языков с автопереводом через LLM
- Нормализация кириллицы → EN с сохранением русского в translations
- DnD перемещение регистров между группами
- CSV импорт/экспорт регистров
- SSE-стриминг прогресса анализа с очередями и rate limiting
- Подсветка condition-связей между каналами и параметрами

### Исправлено
- SSE-парсер, Excel→текст конвертация, дефолты LLM (#3)
- Адреса Modbus, клик-навигация по конфликтам переводов (#4)
- Рендер параметров, удалён alarm channel_type (#5)
- Уточнение wo-switch vs switch в промпте LLM (#6)

[Unreleased]: https://github.com/wirenboard/wb-template-generator/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/wirenboard/wb-template-generator/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/wirenboard/wb-template-generator/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/wirenboard/wb-template-generator/releases/tag/v0.1.0
