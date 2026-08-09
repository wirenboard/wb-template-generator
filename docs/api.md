# API

## Эндпоинты

| Метод | Путь | Назначение |
|-------|------|-----------|
| POST | `/api/analyze` | **SSE** — анализ документа через LLM |
| POST | `/api/build` | Сборка JSON-шаблона из регистров |
| POST | `/api/build-jinja` | Сборка Jinja-шаблона (.json.jinja) |
| POST | `/api/import-template` | Импорт .json / .json.jinja |
| POST | `/api/fix-registers` | **SSE** — исправление ошибочных регистров через LLM |
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
| `system_prompt` | str | `null` | Кастомный промпт (только для своего LLM) |
| `llm_*` | — | `null` | Настройки LLM, см. таблицу ниже |

### Настройки LLM

Одинаковый набор полей у `/api/analyze` (частями multipart-формы), `/api/fix-registers`
и `/api/translate` (полями JSON-тела), у `/api/models` только адрес и ключ. В строку
запроса они не выносятся — ключ попал бы в access-логи nginx и uvicorn.

| Поле | Тип | Описание |
|------|-----|----------|
| `llm_api_url` | str | Адрес своего LLM. Задан — серверный ключ не подставляется, прокси оператора не используется |
| `llm_api_key` | str | Ключ своего LLM |
| `llm_model` | str | Модель. Применяется и к серверному LLM |
| `llm_timeout` | int | Таймаут запроса, сек |
| `llm_legacy_max_tokens` | bool | Старое имя параметра токенов (`max_tokens` вместо `max_completion_tokens`) |
| `llm_temperature` | float | Температура. Ноль значим, не передано — берётся настройка сервера |
| `llm_max_tokens` | int | Потолок ответа. **Только `/api/analyze`** |

Пустое поле означает «клиент не прислал» — подставляется настройка сервера. Правило
приоритета живёт в одном месте, `resolve_llm_target` в `backend/llm_service.py`.

## SSE-события `/api/analyze`

```
event: progress   → {stage, message, current?, total?, request_id, queue_position?, queue_eta?}
event: result     → {request_id, device_info, registers}
event: done       → {message, request_id}
event: error      → {message, request_id, message_key?, message_params?}
```

Ошибки, у которых есть ключ локализации, несут `message_key` и `message_params` — интерфейс рендерит фразу на своём языке, а `message` остаётся русским фолбеком для незнакомого ключа и записью для лога. Тот же контракт у HTTP-отказов, только поле там называется `detail`. Каталог ключей с русскими текстами — `backend/user_errors.py`.

Стадии: `queued` → `uploading` → `converting` → `analyzing` → `merging` → `validating` → `autofix?` → done/error.

- **Мягкий таймаут (`slow`)**: не звено цепочки, а замена `analyzing` после `LLM_SOFT_TIMEOUT` (по умолчанию 3 мин). Анализ продолжается, клиенту предлагается подождать или отменить.
- **Автофикс (`autofix`)**: если после валидации остались ERROR — `детерминированный auto_fix → один LLM-фикс кривых регистров → повторная валидация`. Документ в фикс не передаётся. Остаток ошибок — под ручной кнопкой «Исправить через AI». Шаги видны в прогрессе, итог (было/стало) пишется в лог сервера, счётчики — в `/api/metrics`.

## Продакшен-инфраструктура

- **Request ID**: 8 hex символов, ContextVar, заголовок X-Request-Id, во всех SSE и логах
- **Очереди**: server (max 15) + custom (max 15), asyncio.Semaphore, позиция + ETA в SSE, антиспам-задержка. Отмена ожидания отдельного эндпоинта не требует — клиент рвёт SSE, и сервер снимает ожидание сам
- **Rate limiter**: sliding window (10 запросов/60 сек), только на `/api/analyze`. Ключ бакета — `request.client.host`, то есть за обратным прокси это адрес прокси, и бакет получается общий на всех клиентов. Пер-пользовательский лимит требует доверенного `X-Forwarded-For` на входном nginx
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
