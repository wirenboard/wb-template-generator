# API

## Эндпоинты

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

Стадии: `queued` → `uploading` → `converting` → `analyzing` → `merging` → done/error.

## Продакшен-инфраструктура

- **Request ID**: 8 hex символов, ContextVar, заголовок X-Request-Id, во всех SSE и логах
- **Очереди**: server (max 15) + custom (max 15), asyncio.Event, позиция + ETA в SSE, антиспам-задержка
- **Rate limiter**: sliding window по IP (10 запросов/60 сек)
- **Изоляция LLM**: при серверном LLM пользовательский system_prompt игнорируется
- **Кастомный промпт**: `customSystemPrompt` хранится в localStorage, передаётся только при пользовательском LLM
- **Метрики**: in-memory счётчики и гистограммы в `/api/metrics`
- **Graceful shutdown**: отмена ожидающих запросов, ожидание активных до 30 сек
- **Автосохранение**: состояние редактора (registers, groups, deviceInfo, llmConfig) сохраняется в localStorage с debounce
