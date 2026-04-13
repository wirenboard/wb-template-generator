"""Конфигурация приложения. Загрузка настроек из переменных окружения."""

from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Настройки приложения, загружаемые из переменных окружения."""

    LLM_API_URL: str = ""  # если пусто — LLM отключён, используется mock
    LLM_API_KEY: str = ""  # необязательное — для локальных LLM ключ не нужен
    LLM_MODEL: str = "gpt-4o"
    LLM_MAX_TOKENS: int = 0  # 0 = не ограничивать (модель использует свой максимум)
    LLM_LEGACY_MAX_TOKENS: bool = (
        False  # True = max_tokens (старые API), False = max_completion_tokens (OpenAI 2024+)
    )
    LLM_TEMPERATURE: float | None = (
        0  # 0 = детерминированный вывод (рекомендуется), None = дефолт модели
    )
    LLM_PROXY: str = ""  # HTTP/SOCKS5 прокси для запросов к LLM API
    LLM_TIMEOUT: int = 600  # Жёсткий таймаут HTTP-запроса к LLM API (сек)
    LLM_SOFT_TIMEOUT: int = 180  # Мягкий таймаут — предложить продолжить/отменить (сек)
    PDF_BATCH_SIZE: int = (
        0  # 0 = все страницы одним запросом (рекомендуется для облачных LLM)
    )
    MAX_FILE_SIZE_MB: int = 1  # Максимальный размер одного файла в МБ

    # Очереди
    QUEUE_SERVER_MAX_CONCURRENT: int = 15  # Параллельных запросов к серверному LLM
    QUEUE_CUSTOM_MAX_CONCURRENT: int = (
        15  # Параллельных запросов с пользовательским LLM
    )
    QUEUE_ACTIVATION_DELAY: float = 1.0  # Задержка между активациями из очереди (сек)

    # Rate limiting (sliding window по IP)
    RATE_LIMIT_REQUESTS: int = 10  # Максимум запросов за окно
    RATE_LIMIT_WINDOW: int = 60  # Окно в секундах

    # Логирование
    LOG_FORMAT: str = "text"  # text или json

    # CORS
    CORS_ORIGINS: str = (
        "*"  # Через запятую: "http://localhost:9080,https://app.example.com"
    )

    # Мониторинг и администрирование
    ADMIN_TOKEN: str = (
        ""  # Токен для доступа к админским метрикам (если пустой — админ-функции отключены)
    )

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


@lru_cache
def get_settings() -> Settings:
    """Возвращает кэшированный экземпляр настроек.

    Использует lru_cache, чтобы создать Settings() один раз при первом вызове.
    Для тестов можно подменить через app.dependency_overrides.
    """
    return Settings()
