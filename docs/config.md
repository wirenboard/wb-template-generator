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
```
