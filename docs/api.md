# API

## Эндпоинты

| Метод | Путь | Назначение |
|-------|------|-----------|
| POST | `/api/analyze` | **SSE** — анализ документа через LLM |
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

### Параметры `/api/analyze` (multipart/form-data)

| Параметр | Тип | По умолчанию | Описание |
|----------|-----|-------------|----------|
| `files` | File[] | — | Файлы документации (PDF, Excel, изображения) |
| `template_type` | str | `"full"` | Тип шаблона: `small`, `medium`, `full` |
| `translation_languages` | str | `null` | Языки переводов через запятую, напр. `"ru,kz"` |
| `custom_llm_url` | str | `null` | URL пользовательского LLM API |
| `custom_llm_key` | str | `null` | Ключ пользовательского LLM API |
| `custom_llm_model` | str | `null` | Модель пользовательского LLM |
| `custom_system_prompt` | str | `null` | Кастомный промпт (только для пользовательского LLM) |

## SSE-события `/api/analyze`

```
event: progress   → {stage, message, current?, total?, request_id, queue_position?, queue_eta?}
event: result     → {request_id, device_info, registers}
event: done       → {message, request_id}
event: error      → {message, request_id}
```

Стадии: `queued` → `uploading` → `converting` → `analyzing` → `merging` → `validating` → `autofix?` → done/error.

- **Мягкий таймаут (`slow`)**: не звено цепочки, а замена `analyzing` после `LLM_SOFT_TIMEOUT` (по умолчанию 3 мин). Анализ продолжается, клиенту предлагается подождать или отменить.
- **Автофикс (`autofix`)**: если после валидации остались ERROR — `детерминированный auto_fix → один LLM-фикс кривых регистров → повторная валидация`. Документ в фикс не передаётся. Остаток ошибок — под ручной кнопкой «Исправить через AI». Шаги видны в прогрессе, итог (было/стало) пишется в лог сервера, счётчики — в `/api/metrics`.

## Продакшен-инфраструктура

- **Request ID**: 8 hex символов, ContextVar, заголовок X-Request-Id, во всех SSE и логах
- **Очереди**: server (max 15) + custom (max 15), asyncio.Semaphore, позиция + ETA в SSE, антиспам-задержка. Отмена ожидания отдельного эндпоинта не требует — клиент рвёт SSE, и сервер снимает ожидание сам
- **Rate limiter**: sliding window по IP (10 запросов/60 сек)
- **Изоляция LLM**: при серверном LLM пользовательский system_prompt игнорируется
- **Кастомный промпт**: `customSystemPrompt` хранится в localStorage, передаётся только при пользовательском LLM
- **Метрики**: in-memory счётчики и гистограммы в `/api/metrics`. В ответе:
  - `analyze_total`, `analyze_errors`, `rate_limit_hits`,
  - `analyze_duration_avg`, `analyze_duration_count` — только время самого анализа,
    без ожидания слота в очереди. Запросы, не дошедшие до анализа (отменены в очереди,
    оборваны клиентом, отбиты по размеру), в гистограмму не попадают, поэтому
    `analyze_duration_count` меньше `analyze_total`,
  - `llm_errors_by_category` — словарь `{category: count}` по категориям
    ошибок OpenAI API (см. [docs/config.md](config.md) — `quota_exceeded`,
    `auth`, `permission`, `not_found`, `bad_request`, `rate_limit`,
    `timeout`, `connection`, `server_error`, `unknown`). Считается
    только для серверного LLM.
  - `analysis` — `{autofix_runs, autofix_cleared}`: прогонов, где запускался
    автофикс; из них тех, где автофикс убрал все ошибки (ручная кнопка не
    понадобилась).
- **Telegram-алерты**: при сбоях серверного OpenAI API (квота, auth, 5xx и т. п.)
  бэкенд шлёт уведомления в Telegram-чат (см. [docs/config.md](config.md) →
  «Telegram-уведомления»). Антиспам: CRITICAL — cooldown по категории,
  WARNING — порог событий в окне.
- **Graceful shutdown**: отмена ожидающих запросов, ожидание активных до 30 сек
- **Автосохранение**: состояние редактора (registers, groups, deviceInfo, llmConfig) сохраняется в localStorage с debounce
