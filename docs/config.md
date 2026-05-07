# Настройки (.env)

```bash
LLM_API_URL=           # URL OpenAI-совместимого API
LLM_API_KEY=           # API-ключ (необязательно для локальных LLM)
LLM_MODEL=gpt-4o       # Модель
LLM_MAX_TOKENS=16384
LLM_LEGACY_MAX_TOKENS=false  # true = max_tokens (старые API), false = max_completion_tokens
LLM_TEMPERATURE=0      # 0 = детерминированный вывод, пусто/None = дефолт модели
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
LOG_FORMAT=text              # Формат логов: text или json
CORS_ORIGINS=*               # Разрешённые CORS-источники через запятую

# Telegram-уведомления о сбоях OpenAI API (только для серверного LLM)
TELEGRAM_NOTIFY_ENABLED=false                       # Включить алерты в Telegram
TELEGRAM_BOT_TOKEN=                                 # Токен бота из @BotFather
TELEGRAM_CHAT_ID=                                   # ID чата (для групп: "-100…")
TELEGRAM_MESSAGE_THREAD_ID=                         # ID топика в супергруппе (необязательно; 0/пусто = обычный чат)
TELEGRAM_API_URL=https://api.telegram.org           # Для тестов / локального Bot API
TELEGRAM_PROXY=                                     # Отдельный прокси (Telegram заблокирован в РФ)
TELEGRAM_REQUEST_TIMEOUT=10                         # Таймаут HTTP-запроса к Bot API (сек)
TELEGRAM_NOTIFY_COOLDOWN_SECONDS=900                # CRITICAL: 1 алерт на категорию в N сек
TELEGRAM_NOTIFY_THRESHOLD_WINDOW_SECONDS=300        # WARNING: окно подсчёта событий
TELEGRAM_NOTIFY_THRESHOLD_COUNT=5                   # WARNING: триггер при N+ событий в окне
```

## Telegram-уведомления

Сервис отправляет алерты в Telegram при сбоях OpenAI API. Уведомления формируются
**только для серверного LLM** — ошибки пользовательских (custom) ключей
не репортятся (чужой ключ — наша зона ответственности нулевая).

### Категории и стратегия алертов

| Категория | Severity | Когда возникает | Стратегия |
|-----------|----------|-----------------|-----------|
| `quota_exceeded` | CRITICAL | Закончились средства / превышена квота биллинга (`insufficient_quota`, `billing_hard_limit_reached`, `billing_not_active`, `account_deactivated`) | Сразу + cooldown |
| `auth` | CRITICAL | 401, невалидный API-ключ | Сразу + cooldown |
| `permission` | CRITICAL | 403 без quota-маркеров (отозван доступ) | Сразу + cooldown |
| `not_found` | CRITICAL | 404, модель не найдена | Сразу + cooldown |
| `bad_request` | CRITICAL | 400/422, ошибка в нашем запросе | Сразу + cooldown |
| `rate_limit` | WARNING | 429 без quota-маркеров (RPM/TPM) | По порогу в окне |
| `timeout` | WARNING | `APITimeoutError` | По порогу в окне |
| `connection` | WARNING | `APIConnectionError` (сеть, прокси) | По порогу в окне |
| `server_error` | WARNING | 5xx | По порогу в окне |
| `unknown` | WARNING | Прочее | По порогу в окне |

- **CRITICAL**: алерт отправляется немедленно при первом событии категории,
  далее подавляется на `TELEGRAM_NOTIFY_COOLDOWN_SECONDS`.
- **WARNING**: алерт отправляется только если в окне
  `TELEGRAM_NOTIFY_THRESHOLD_WINDOW_SECONDS` накопилось
  ≥ `TELEGRAM_NOTIFY_THRESHOLD_COUNT` событий.
- Категории независимы (cooldown на `auth` не блокирует `quota_exceeded`).

### Настройка бота

1. Создайте бота через [@BotFather](https://t.me/BotFather), получите токен.
2. Добавьте бота в нужный чат (или напишите ему лично).
3. Узнайте `chat_id` через [@userinfobot](https://t.me/userinfobot) или
   запросом `https://api.telegram.org/bot<TOKEN>/getUpdates`.
4. Установите `TELEGRAM_NOTIFY_ENABLED=true`, `TELEGRAM_BOT_TOKEN`,
   `TELEGRAM_CHAT_ID` в `.env` и перезапустите backend.

В РФ Telegram Bot API часто блокируется — укажите `TELEGRAM_PROXY`
(`http://...` или `socks5://...`).

### Отправка в топик супергруппы

Если бот должен писать не в общий чат, а в конкретный **топик** супергруппы
с включёнными топиками (forum supergroup), задайте `TELEGRAM_MESSAGE_THREAD_ID`
— параметр `message_thread_id` будет добавлен в каждый запрос `sendMessage`.

Как узнать ID топика:

1. Откройте нужный топик в Telegram Web (`web.telegram.org`).
2. В URL после `#` будут два числа: `…#-100<chat_id>_<thread_id>` —
   первое число это `chat_id`, второе — `TELEGRAM_MESSAGE_THREAD_ID`.

Альтернатива: переслать любое сообщение из топика боту и посмотреть
`message_thread_id` в ответе `getUpdates`.

Если переменная не задана (или равна `0`), сообщения уходят в общий чат
по `TELEGRAM_CHAT_ID` — обратной совместимости с группами без топиков.

> **Важно**: бот должен быть **добавлен в супергруппу** (желательно как
> администратор с правом «Отправлять сообщения») — иначе Bot API ответит
> `400 Bad Request: chat not found` и алерт молча не уйдёт (ошибка только
> в логах backend). Проверить, видит ли бот чат, можно через
> `https://api.telegram.org/bot<TOKEN>/getChat?chat_id=<TELEGRAM_CHAT_ID>`.
