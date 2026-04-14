"""Центральная система метрик для мониторинга приложения."""

import hmac
import logging
from collections import deque
from typing import Any

from fastapi import HTTPException, Request

from config import get_settings

logger = logging.getLogger(__name__)


# Метрики: in-memory счётчики
_metrics: dict[str, Any] = {
    "analyze_requests": 0,
    "analyze_errors": 0,
    "rate_limit_hits": 0,
    "durations": deque(maxlen=100),  # type: ignore[arg-type]
    # LLM метрики
    "llm_requests": 0,
    "llm_errors": 0,
    "llm_retries": 0,
    "total_prompt_tokens": 0,
    "total_completion_tokens": 0,
    "total_tokens": 0,
    "llm_durations": deque(maxlen=100),  # type: ignore[arg-type]
    "registers_extracted": 0,
    "auto_fixes_applied": 0,
    # Мониторинг использования
    "monitoring_page_views": 0,
    # Статистика ошибок по категориям
    "error_categories": {
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
    },
    # Последние ошибки для диагностики
    "recent_errors": deque(maxlen=10),  # type: ignore[arg-type]
}


def check_admin_access(request: Request) -> bool:
    """Проверяет, есть ли у запроса админский доступ.

    Проверяет Authorization заголовок в формате 'Bearer <token>'.
    Возвращает True если токен правильный, False если нет доступа.
    """
    settings = get_settings()

    # Если ADMIN_TOKEN не установлен, админские функции отключены
    if not settings.ADMIN_TOKEN:
        return False

    auth_header = request.headers.get("authorization")
    if not auth_header:
        return False

    if not auth_header.startswith("Bearer "):
        return False

    token = auth_header[7:]  # Убираем "Bearer "
    return hmac.compare_digest(token, settings.ADMIN_TOKEN)


def require_admin_access(request: Request) -> None:
    """Требует админский доступ, иначе выбрасывает 403 ошибку."""
    if not check_admin_access(request):
        settings = get_settings()
        if not settings.ADMIN_TOKEN:
            raise HTTPException(
                status_code=503,
                detail="Админские функции отключены (ADMIN_TOKEN не установлен)",
            )
        else:
            raise HTTPException(
                status_code=403, detail="Доступ запрещён. Требуется админский токен"
            )


def update_basic_metrics(
    analyze_request: bool = False,
    analyze_error: bool = False,
    rate_limit_hit: bool = False,
    duration: float = 0,
) -> None:
    """Обновляет базовые метрики анализа."""

    if analyze_request:
        _metrics["analyze_requests"] += 1
    if analyze_error:
        _metrics["analyze_errors"] += 1
    if rate_limit_hit:
        _metrics["rate_limit_hits"] += 1
    if duration > 0:
        _metrics["durations"].append(duration)


def update_monitoring_metrics(
    page_view: bool = False,
) -> None:
    """Обновляет метрики мониторинга."""

    if page_view:
        _metrics["monitoring_page_views"] += 1


def update_llm_metrics(
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    total_tokens: int = 0,
    duration: float = 0,
    registers_count: int = 0,
    auto_fixes: int = 0,
    retry: bool = False,
    error: bool = False,
    error_message: str = "",
    count_request: bool = False,
) -> None:
    """Обновляет LLM метрики. Вызывается из llm_service.py.

    Args:
        count_request: Инкрементировать счётчик llm_requests.
            Передавать True только при реальном вызове LLM API.
    """  # noqa: D401
    if count_request:
        _metrics["llm_requests"] += 1
    if error:
        _metrics["llm_errors"] += 1

        # Классифицируем ошибку и обновляем статистику
        if error_message:
            import time

            from error_classifier import classify_llm_error

            error_info = classify_llm_error(error_message)
            _metrics["error_categories"][error_info.category] += 1

            # Сохраняем последнюю ошибку для диагностики
            _metrics["recent_errors"].append(
                {
                    "timestamp": time.time(),
                    "category": error_info.category,
                    "title": error_info.title,
                    "description": error_info.description,
                    "suggestion": error_info.suggestion,
                    "severity": error_info.severity,
                    "technical_details": error_message[:200],  # Ограничиваем размер
                }
            )

    if retry:
        _metrics["llm_retries"] += 1

    _metrics["total_prompt_tokens"] += prompt_tokens
    _metrics["total_completion_tokens"] += completion_tokens
    _metrics["total_tokens"] += total_tokens

    if duration > 0:
        _metrics["llm_durations"].append(duration)

    _metrics["registers_extracted"] += registers_count
    _metrics["auto_fixes_applied"] += auto_fixes


def get_public_metrics() -> dict:
    """Возвращает публичные метрики (доступные всем)."""
    durations = list(_metrics["durations"])
    avg_duration = round(sum(durations) / len(durations), 1) if durations else None

    return {
        "basic": {
            "counters": {
                "analyze_requests": _metrics["analyze_requests"],
                "analyze_errors": _metrics["analyze_errors"],
                "rate_limit_hits": _metrics["rate_limit_hits"],
                "monitoring_page_views": _metrics["monitoring_page_views"],
            },
            "histograms": {
                "analyze_duration_avg": avg_duration,
                "analyze_duration_count": len(durations),
            },
        },
        "llm": {
            "counters": {
                "llm_requests": _metrics["llm_requests"],
                "llm_errors": _metrics["llm_errors"],
                "llm_retries": _metrics["llm_retries"],
            },
            "quality": {
                "error_rate": round(
                    _metrics["llm_errors"] / max(_metrics["llm_requests"], 1) * 100, 1
                ),
                "retry_rate": round(
                    _metrics["llm_retries"] / max(_metrics["llm_requests"], 1) * 100, 1
                ),
            },
        },
    }


def get_admin_metrics() -> dict:
    """Возвращает админские метрики (требуют токен)."""
    llm_durations = list(_metrics["llm_durations"])
    avg_llm_duration = (
        round(sum(llm_durations) / len(llm_durations), 1) if llm_durations else None
    )

    # Статистика ошибок
    error_categories = dict(_metrics["error_categories"])
    recent_errors = list(_metrics["recent_errors"])

    return {
        "tokens": {
            "total_prompt_tokens": _metrics["total_prompt_tokens"],
            "total_completion_tokens": _metrics["total_completion_tokens"],
            "total_tokens": _metrics["total_tokens"],
        },
        "processing": {
            "registers_extracted": _metrics["registers_extracted"],
            "auto_fixes_applied": _metrics["auto_fixes_applied"],
            "avg_registers_per_request": round(
                _metrics["registers_extracted"] / max(_metrics["llm_requests"], 1), 1
            ),
            "auto_fix_rate": round(
                _metrics["auto_fixes_applied"]
                / max(_metrics["registers_extracted"], 1)
                * 100,
                1,
            ),
        },
        "performance": {
            "llm_duration_avg": avg_llm_duration,
            "llm_duration_count": len(llm_durations),
        },
        "errors": {
            "categories": error_categories,
            "recent": recent_errors,
            "top_category": (
                max(error_categories.items(), key=lambda x: x[1])[0]
                if any(error_categories.values())
                else None
            ),
        },
    }


def get_all_metrics() -> dict:
    """Возвращает все метрики (публичные + админские) для внутреннего использования."""
    public = get_public_metrics()
    admin = get_admin_metrics()

    # Объединяем админские метрики в публичную структуру
    result = public.copy()
    result["llm"] = {**public["llm"], **admin}

    return result


# === Интеграция с персистентностью ===


async def load_persisted_metrics() -> None:
    """Загружает метрики из файлового хранилища при старте приложения."""
    try:
        from persistence import get_persistence

        persistence = get_persistence()
        stored_data = await persistence.load_metrics()

        if stored_data:
            # Восстанавливаем базовые метрики
            if "basic" in stored_data:
                basic = stored_data["basic"]
                _metrics.update(
                    {
                        "analyze_requests": basic.get("analyze_requests", 0),
                        "analyze_errors": basic.get("analyze_errors", 0),
                        "rate_limit_hits": basic.get("rate_limit_hits", 0),
                        "monitoring_page_views": basic.get("monitoring_page_views", 0),
                    }
                )

            # Восстанавливаем LLM метрики
            if "llm" in stored_data:
                llm = stored_data["llm"]
                _metrics.update(
                    {
                        "llm_requests": llm.get("llm_requests", 0),
                        "llm_errors": llm.get("llm_errors", 0),
                        "llm_retries": llm.get("llm_retries", 0),
                        "total_prompt_tokens": llm.get("tokens", {}).get(
                            "total_prompt_tokens", 0
                        ),
                        "total_completion_tokens": llm.get("tokens", {}).get(
                            "total_completion_tokens", 0
                        ),
                        "total_tokens": llm.get("tokens", {}).get("total_tokens", 0),
                        "registers_extracted": llm.get("processing", {}).get(
                            "registers_extracted", 0
                        ),
                        "auto_fixes_applied": llm.get("processing", {}).get(
                            "auto_fixes_applied", 0
                        ),
                    }
                )

                # Восстанавливаем категории ошибок
                error_cats = llm.get("errors", {}).get("categories", {})
                for cat, count in error_cats.items():
                    if cat in _metrics["error_categories"]:
                        _metrics["error_categories"][cat] = count

            logger.info(
                f"Метрики восстановлены из хранилища: {list(stored_data.keys())}"
            )

    except Exception as e:
        logger.error(f"Ошибка загрузки сохраненных метрик: {e}")


def get_metrics_for_persistence() -> dict:
    """Возвращает метрики в формате для сохранения."""
    return {"basic": get_public_metrics()["basic"], "llm": get_admin_metrics()}


async def start_metrics_persistence() -> None:
    """Запускает автоматическое сохранение метрик."""
    try:
        from persistence import get_persistence

        persistence = get_persistence()
        await persistence.start_auto_save(get_metrics_for_persistence)
        logger.info("Автосохранение метрик запущено")

    except Exception as e:
        logger.error(f"Ошибка запуска автосохранения метрик: {e}")


async def stop_metrics_persistence() -> None:
    """Останавливает автоматическое сохранение метрик."""
    try:
        from persistence import get_persistence

        persistence = get_persistence()

        # Финальное сохранение перед остановкой
        await persistence.save_metrics(get_metrics_for_persistence())

        # Останавливаем автосохранение
        await persistence.stop_auto_save()

        logger.info("Автосохранение метрик остановлено")

    except Exception as e:
        logger.error(f"Ошибка остановки автосохранения метрик: {e}")
