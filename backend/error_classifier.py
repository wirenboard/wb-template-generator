"""Система классификации и человекочитаемых описаний ошибок LLM."""

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class ErrorInfo:
    """Информация об ошибке LLM."""
    category: str
    title: str
    description: str
    suggestion: str
    severity: str  # 'error', 'warning', 'info'
    technical_details: str


def classify_llm_error(error_message: str, error_context: Optional[Dict[str, Any]] = None) -> ErrorInfo:
    """Классифицирует ошибку LLM и возвращает человекочитаемое описание.

    Args:
        error_message: Сообщение об ошибке
        error_context: Дополнительный контекст (модель, timeout, токены и т.д.)

    Returns:
        ErrorInfo с категорией, описанием и предложениями по исправлению
    """
    error_lower = error_message.lower()
    # Контекст пока не используется, но может понадобиться в будущем
    _ = error_context or {}
    
    # 1. Ошибки аутентификации
    if any(keyword in error_lower for keyword in [
        'unauthorized', 'invalid api key', 'authentication', 'api_key', 'forbidden'
    ]):
        return ErrorInfo(
            category="auth",
            title="Ошибка авторизации",
            description="LLM API отклонил запрос из-за проблем с аутентификацией",
            suggestion=(
                "Проверьте правильность API ключа и его активность. "
                "Возможно, ключ истек или достигнут лимит запросов."
            ),
            severity="error",
            technical_details=error_message
        )
    
    # 2. Ошибки сети и подключения  
    if any(keyword in error_lower for keyword in [
        'connection', 'timeout', 'network', 'unreachable', 'dns', 'socket'
    ]):
        return ErrorInfo(
            category="network",
            title="Проблемы с сетью",
            description="Не удалось установить соединение с LLM API",
            suggestion=(
                "Проверьте интернет-соединение, настройки прокси и доступность API. "
                "Попробуйте повторить запрос через несколько минут."
            ),
            severity="error",
            technical_details=error_message
        )
    
    # 3. Лимиты и квоты
    if any(keyword in error_lower for keyword in [
        'rate limit', 'quota', 'billing', 'insufficient funds', 'usage limit'
    ]):
        return ErrorInfo(
            category="quota",
            title="Превышены лимиты API",
            description="Достигнут лимит запросов или исчерпана квота",
            suggestion=(
                "Подождите перед следующим запросом или обновите план подписки. "
                "Проверьте биллинг в панели провайдера."
            ),
            severity="warning",
            technical_details=error_message
        )
    
    # 4. Проблемы с моделью
    if any(keyword in error_lower for keyword in [
        'model not found', 'invalid model', 'model unavailable', 'unknown model'
    ]):
        return ErrorInfo(
            category="model",
            title="Модель недоступна",
            description="Указанная модель не найдена или недоступна",
            suggestion="Проверьте название модели в настройках. Убедитесь, что у вас есть доступ к этой модели.",
            severity="error",
            technical_details=error_message
        )
    
    # 5. Проблемы с токенами
    if any(keyword in error_lower for keyword in [
        'max_tokens', 'token limit', 'context length', 'maximum context'
    ]):
        return ErrorInfo(
            category="tokens",
            title="Превышен лимит токенов",
            description="Запрос или ответ превысил максимальное количество токенов",
            suggestion="Уменьшите размер загружаемых файлов или установите LLM_MAX_TOKENS=0 для снятия ограничения.",
            severity="warning",
            technical_details=error_message
        )
    
    # 6. Проблемы с форматом данных
    if any(keyword in error_lower for keyword in [
        'invalid_request_error', 'bad request', 'unsupported', 'invalid type'
    ]):
        return ErrorInfo(
            category="format",
            title="Неподдерживаемый формат",
            description="API не может обработать переданные данные",
            suggestion="Проверьте формат загружаемых файлов. Некоторые модели не поддерживают PDF или Excel напрямую.",
            severity="error",
            technical_details=error_message
        )
    
    # 7. Проблемы с парсингом ответа
    if any(keyword in error_lower for keyword in [
        'json', 'parse', 'invalid json', 'syntax error'
    ]):
        return ErrorInfo(
            category="parsing",
            title="Ошибка обработки ответа",
            description="LLM вернул ответ в неожиданном формате",
            suggestion="Попробуйте изменить промпт или использовать другую модель. Возможно, модель перегружена.",
            severity="warning",
            technical_details=error_message
        )
    
    # 8. Пустой ответ
    if 'пустой ответ' in error_lower or 'empty response' in error_lower:
        return ErrorInfo(
            category="empty",
            title="Пустой ответ LLM",
            description="Модель не вернула текстовый ответ",
            suggestion=(
                "Возможно, модель потратила токены на внутренние рассуждения. "
                "Попробуйте убрать лимит токенов или изменить промпт."
            ),
            severity="warning",
            technical_details=error_message
        )
    
    # 9. Общие ошибки API
    if 'api error' in error_lower or 'service unavailable' in error_lower:
        return ErrorInfo(
            category="api",
            title="Ошибка API сервиса",
            description="Внутренняя ошибка LLM провайдера",
            suggestion="Временная проблема с API. Попробуйте повторить запрос через несколько минут.",
            severity="warning",
            technical_details=error_message
        )
    
    # Неизвестная ошибка
    return ErrorInfo(
        category="unknown",
        title="Неизвестная ошибка",
        description="Произошла неожиданная ошибка при работе с LLM",
        suggestion="Обратитесь к администратору или проверьте логи для получения подробной информации.",
        severity="error",
        technical_details=error_message
    )


def get_error_statistics() -> Dict[str, int]:
    """Возвращает статистику ошибок по категориям (заглушка для будущего расширения)."""
    # TODO: В будущем можно добавить сбор статистики ошибок
    return {
        "auth": 0,
        "network": 0,
        "quota": 0,
        "model": 0,
        "tokens": 0,
        "format": 0,
        "parsing": 0,
        "empty": 0,
        "api": 0,
        "unknown": 0,
    }


def format_error_for_display(error_info: ErrorInfo) -> str:
    """Форматирует ErrorInfo для отображения пользователю."""
    severity_emoji = {
        "error": "❌",
        "warning": "⚠️", 
        "info": "ℹ️"
    }
    
    emoji = severity_emoji.get(error_info.severity, "❓")
    
    return f"""{emoji} **{error_info.title}**

{error_info.description}

**Что делать**: {error_info.suggestion}

*Категория*: {error_info.category}"""