"""Формирование SSE-событий (Server-Sent Events) для потокового ответа клиенту."""

import json

from models import AnalyzeResponse
from user_errors import UserError


def sse_progress(
    stage: str,
    message: str,
    current: int | None = None,
    total: int | None = None,
    request_id: str | None = None,
    extra: dict | None = None,
) -> str:
    """Формирует SSE-событие прогресса.

    Args:
        stage: этап обработки (uploading, converting, analyzing, merging, queued).
        message: текстовое описание текущего действия.
        current: номер текущего шага (None — indeterminate).
        total: общее количество шагов (None — indeterminate).
        request_id: идентификатор запроса для трейсинга.
        extra: дополнительные поля (queue_position, queue_eta и т.д.).

    Returns:
        Строка SSE-события в формате ``event: progress\\ndata: ...``.
    """
    data: dict = {
        "stage": stage,
        "message": message,
    }
    if current is not None:
        data["current"] = current
    if total is not None:
        data["total"] = total
    if request_id:
        data["request_id"] = request_id
    if extra:
        data.update(extra)
    return f"event: progress\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def sse_result(response: AnalyzeResponse, request_id: str | None = None) -> str:
    """Формирует SSE-событие с результатом анализа.

    Args:
        response: ответ с данными устройства и регистрами.
        request_id: идентификатор запроса для трейсинга.

    Returns:
        Строка SSE-события в формате ``event: result\\ndata: ...``.
    """
    data = response.model_dump()
    if request_id:
        data["request_id"] = request_id
    return f"event: result\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def sse_done(message: str = "Анализ завершён", request_id: str | None = None) -> str:
    """Формирует SSE-событие завершения.

    Args:
        message: текст сообщения о завершении.
        request_id: идентификатор запроса для трейсинга.

    Returns:
        Строка SSE-события в формате ``event: done\\ndata: ...``.
    """
    data: dict = {"message": message}
    if request_id:
        data["request_id"] = request_id
    return f"event: done\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def sse_keepalive() -> str:
    """SSE-комментарий для поддержания соединения (не парсится клиентом)."""
    return ": keepalive\n\n"


def sse_error(
    message: str,
    request_id: str | None = None,
    message_key: str | None = None,
    message_params: dict | None = None,
) -> str:
    """Формирует SSE-событие ошибки.

    Args:
        message: русский текст ошибки — фолбек и запись для лога.
        request_id: идентификатор запроса для трейсинга.
        message_key: ключ локализации, интерфейс рендерит его на своём языке.
        message_params: параметры подстановки для ключа.

    Returns:
        Строка SSE-события в формате ``event: error\\ndata: ...``.
    """
    data: dict = {"message": message}
    if request_id:
        data["request_id"] = request_id
    if message_key:
        data["message_key"] = message_key
        data["message_params"] = message_params or {}
    return f"event: error\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def sse_user_error(err: UserError, request_id: str | None = None) -> str:
    """SSE-событие ошибки из каталога: текст, ключ и параметры разом."""
    return sse_error(
        err.message, request_id=request_id,
        message_key=err.key, message_params=err.params,
    )
