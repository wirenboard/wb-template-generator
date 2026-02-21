"""Сервис для работы с LLM — отправка запросов, парсинг ответов, потоковая обработка."""

import asyncio
import base64
import io
import json
import logging
import re
import time
from collections.abc import AsyncGenerator

from openai import AsyncOpenAI
from PIL import Image

from config import Settings
from file_converter import (
    excel_to_text,
    image_to_base64,
    is_excel_file,
    is_image_file,
    is_pdf_file,
)
from models import AnalyzeResponse, DeviceInfo, Register
from prompts import get_analyze_prompt, get_retry_prompt, render_custom_prompt
from sse import sse_done, sse_error, sse_progress, sse_result

# Интервал SSE keepalive (сек) — поддерживает соединение через nginx
_KEEPALIVE_INTERVAL = 15

logger = logging.getLogger(__name__)


class LLMApiError(Exception):
    """Ошибка при обращении к LLM API (сеть, авторизация, модель не найдена)."""


# ---------------------------------------------------------------------------
# Парсинг JSON из ответа LLM
# ---------------------------------------------------------------------------

def _extract_json_from_response(text: str) -> dict:
    """Извлекает JSON из ответа LLM.

    Ответ может быть чистым JSON или обёрнут в ```json ... ```.
    """
    # Убираем markdown-обёртку если есть
    json_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
    if json_match:
        text = json_match.group(1)

    # Ищем JSON-объект в тексте (на случай если перед/после есть текст)
    text = text.strip()
    # Пробуем найти начало JSON-объекта
    brace_start = text.find("{")
    if brace_start > 0:
        text = text[brace_start:]

    # Ищем конец JSON-объекта — последняя закрывающая скобка
    brace_end = text.rfind("}")
    if brace_end >= 0:
        text = text[: brace_end + 1]

    return json.loads(text)


def _parse_registers(raw: dict) -> tuple[DeviceInfo, list[Register]]:
    """Парсит ответ LLM в структуры DeviceInfo и список Register.

    Использует мягкую валидацию — невалидные поля заменяются дефолтами.
    """
    # Парсим device_info
    raw_info = raw.get("device_info", {})
    device_info = DeviceInfo(
        name=raw_info.get("name", "Unknown Device"),
        id=raw_info.get("id", "unknown-device"),
        device_group=raw_info.get("device_group"),
    )

    # Парсим регистры с мягкой валидацией
    registers: list[Register] = []
    raw_registers = raw.get("registers", [])

    for raw_reg in raw_registers:
        if not isinstance(raw_reg, dict):
            continue
        try:
            # Убираем поле id если LLM его сгенерировала (мы генерируем свои uuid)
            raw_reg.pop("id", None)
            reg = Register(**raw_reg)
            registers.append(reg)
        except Exception as e:
            # Мягкая валидация — пробуем с минимальными полями
            logger.warning("Ошибка парсинга регистра %s: %s", raw_reg, e)
            try:
                reg = Register(
                    address=int(raw_reg.get("address", 0)),
                    name=str(raw_reg.get("name", "Unknown")),
                )
                registers.append(reg)
            except Exception:
                logger.error("Не удалось распарсить регистр, пропускаем: %s", raw_reg)

    return device_info, registers


def _merge_batch_results(
    batches: list[tuple[DeviceInfo, list[Register]]],
) -> tuple[DeviceInfo, list[Register]]:
    """Мержит результаты из нескольких батчей.

    Дедупликация по ключу (address, reg_type) — побеждает первое вхождение.
    device_info берётся из первого непустого батча.
    """
    device_info = DeviceInfo(name="Unknown Device", id="unknown-device")
    all_registers: list[Register] = []
    seen: set[tuple[int, str]] = set()

    for batch_info, batch_regs in batches:
        # Берём device_info из первого батча, где он непустой
        if device_info.name == "Unknown Device" and batch_info.name != "Unknown Device":
            device_info = batch_info

        for reg in batch_regs:
            key = (reg.address, reg.reg_type)
            if key not in seen:
                seen.add(key)
                all_registers.append(reg)

    # Сортируем по адресу (address может быть int или str "109:1:2")
    def _sort_key(r):
        addr = r.address
        if isinstance(addr, str):
            # "109:1:2" → сортируем по первому числу
            try:
                addr = int(addr.split(":")[0])
            except (ValueError, IndexError):
                addr = 0
        return (r.reg_type, addr)

    all_registers.sort(key=_sort_key)
    return device_info, all_registers


# ---------------------------------------------------------------------------
# Вызов LLM API (асинхронный)
# ---------------------------------------------------------------------------

async def _call_llm(
    client: AsyncOpenAI,
    model: str,
    system_prompt: str,
    content: list[dict],
    timeout: int,
    max_tokens: int = 16384,
    legacy_max_tokens: bool = False,
    temperature: float | None = None,
) -> str:
    """Асинхронный вызов OpenAI-compatible API с vision-контентом.

    Возвращает текстовый ответ LLM.

    При ошибке «Unsupported parameter» автоматически:
    - переключает max_tokens ↔ max_completion_tokens;
    - убирает temperature, если модель не поддерживает.
    """
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": content},
    ]
    # Выбираем имя параметра: legacy (max_tokens) или новый (max_completion_tokens)
    primary_key = "max_tokens" if legacy_max_tokens else "max_completion_tokens"
    fallback_key = "max_completion_tokens" if legacy_max_tokens else "max_tokens"

    kwargs: dict = {
        "model": model,
        "messages": messages,
        "timeout": timeout,
    }
    # max_tokens=0 означает «не ограничивать» — не передаём параметр
    if max_tokens and max_tokens > 0:
        kwargs[primary_key] = max_tokens
    if temperature is not None:
        kwargs["temperature"] = temperature

    # До 3 попыток: каждая убирает/заменяет один неподдерживаемый параметр
    for attempt in range(3):
        try:
            llm_start = time.monotonic()
            response = await client.chat.completions.create(**kwargs)
            # Логируем расход токенов и finish_reason
            usage = response.usage
            finish_reason = response.choices[0].finish_reason if response.choices else None
            if usage:
                logger.info(
                    "Токены: prompt=%d, completion=%d, total=%d, finish_reason=%s",
                    usage.prompt_tokens or 0,
                    usage.completion_tokens or 0,
                    usage.total_tokens or 0,
                    finish_reason,
                )
            if finish_reason == "length":
                logger.warning(
                    "Ответ LLM обрезан по лимиту токенов (finish_reason=length). "
                    "Увеличьте LLM_MAX_TOKENS или уберите ограничение (0)."
                )
            llm_duration = time.monotonic() - llm_start
            logger.info("LLM-запрос: %.1f сек", llm_duration)
            text = response.choices[0].message.content or ""
            return text, usage
        except Exception as e:
            err_str = str(e)
            fixed = False

            # Фолбек max_tokens ↔ max_completion_tokens
            if primary_key in kwargs and (fallback_key in err_str or primary_key in err_str):
                logger.warning(
                    "Модель %s не поддерживает %s, переключаемся на %s. "
                    "Совет: измените настройку «Параметр токенов» в UI.",
                    model, primary_key, fallback_key,
                )
                del kwargs[primary_key]
                kwargs[fallback_key] = max_tokens
                primary_key = fallback_key  # Запоминаем, чтобы не циклить
                fixed = True

            # Фолбек temperature: некоторые модели (o1, gpt-4o) не поддерживают
            if "temperature" in err_str and "temperature" in kwargs:
                logger.warning(
                    "Модель %s не поддерживает temperature=0.1, убираем параметр.",
                    model,
                )
                del kwargs["temperature"]
                fixed = True

            if not fixed:
                raise

    # Сюда не должны попасть, но на всякий случай
    return "", None


def _get_file_mime(filename: str) -> str:
    """Определяет MIME-тип файла по расширению."""
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    mimes = {
        "pdf": "application/pdf",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "xls": "application/vnd.ms-excel",
    }
    return mimes.get(ext, "application/octet-stream")


def _is_file_unsupported(error_msg: str) -> bool:
    """Проверяет, связана ли ошибка LLM с неподдержкой file-контента.

    Возвращает True, если ошибка указывает на то, что API не поддерживает
    прямую отправку файлов (type: "file"), и нужно откатиться на конвертацию.
    """
    lower = error_msg.lower()
    keywords = [
        "invalid_content_type",
        "content type",
        "unsupported",
        "not supported",
        "invalid type",
        "unrecognized content",
    ]
    has_keyword = any(kw in lower for kw in keywords)
    has_context = "file" in lower or "pdf" in lower or "type" in lower or "xlsx" in lower
    return has_keyword and has_context


# ---------------------------------------------------------------------------
# Основная функция анализа документа
# ---------------------------------------------------------------------------

async def analyze_document(
    files: list[tuple[str, bytes]],
    template_type: str,
    settings: Settings,
    api_url: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
    max_tokens: int | None = None,
    timeout: int | None = None,
    custom_system_prompt: str | None = None,
    translation_languages: list[str] | None = None,
    legacy_max_tokens: bool | None = None,
    temperature: float | None = -1,  # -1 = использовать настройки сервера
    request_id: str | None = None,
    is_custom_llm: bool = False,
) -> AsyncGenerator[str, None]:
    """Анализирует загруженные документы с помощью LLM.

    Принимает список файлов (имя, содержимое), конвертирует в формат
    пригодный для vision API, отправляет на анализ, парсит результат.
    Генерирует SSE-события прогресса и результата.

    Args:
        files: список кортежей (имя_файла, содержимое_в_байтах).
        template_type: тип шаблона — "small", "medium", "full".
        settings: настройки приложения.
        api_url: URL LLM API (переопределяет настройки).
        api_key: API-ключ (переопределяет настройки).
        model: модель LLM (переопределяет настройки).
        custom_system_prompt: кастомный шаблон промпта (переопределяет дефолтный).
        translation_languages: список кодов языков для переводов (напр. ["ru", "de"]).

    Yields:
        SSE-строки с событиями прогресса, результата, завершения или ошибки.
    """
    try:
        logger.info("[%s] Начало анализа: %d файл(ов), тип=%s, custom_llm=%s",
                     request_id, len(files), template_type, is_custom_llm)

        # Изоляция: при серверной модели игнорируем пользовательский промпт
        if not is_custom_llm:
            custom_system_prompt = None

        # Изоляция ключей: при пользовательском LLM НЕ фолбечим на серверный ключ
        if is_custom_llm:
            effective_url = api_url  # всегда truthy (is_custom_llm = bool(api_url))
            effective_key = api_key  # может быть None — не подставляем серверный
        else:
            effective_url = settings.LLM_API_URL
            effective_key = settings.LLM_API_KEY
        effective_model = model or settings.LLM_MODEL
        effective_max_tokens = max_tokens or settings.LLM_MAX_TOKENS
        effective_timeout = timeout or settings.LLM_TIMEOUT
        effective_legacy = legacy_max_tokens if legacy_max_tokens is not None else settings.LLM_LEGACY_MAX_TOKENS
        effective_temperature = temperature if temperature != -1 else settings.LLM_TEMPERATURE
        soft_timeout = settings.LLM_SOFT_TIMEOUT

        # --- Этап 1: загрузка и классификация файлов ---
        yield sse_progress(
            "uploading",
            "Загрузка и распознавание файлов...",
            current=0,
            total=len(files),
            request_id=request_id,
        )

        all_images: list[Image.Image] = []
        direct_files: list[tuple[str, bytes]] = []  # PDF — отправляем файлом
        text_parts: list[str] = []  # Excel — конвертируем в текст

        convert_start = time.monotonic()
        for idx, (filename, content_bytes) in enumerate(files):
            if is_pdf_file(filename):
                # PDF — отправляем файлом напрямую
                yield sse_progress(
                    "uploading",
                    f"Загрузка: {filename}...",
                    current=idx + 1,
                    total=len(files),
                    request_id=request_id,
                )
                direct_files.append((filename, content_bytes))

            elif is_excel_file(filename):
                # Excel — конвертируем в текст (LLM API не поддерживает Excel как файл)
                yield sse_progress(
                    "converting",
                    f"Конвертация Excel: {filename}...",
                    current=idx + 1,
                    total=len(files),
                    request_id=request_id,
                )
                text_parts.append(f"--- {filename} ---\n{excel_to_text(content_bytes)}")

            elif is_image_file(filename):
                # Изображение -> PIL.Image
                img = Image.open(io.BytesIO(content_bytes))
                all_images.append(img)

            else:
                logger.warning("Неподдерживаемый формат файла: %s", filename)

        convert_duration = time.monotonic() - convert_start
        logger.info("[%s] Конвертация файлов: %.1f сек", request_id, convert_duration)

        # --- Этап 2: подготовка LLM-клиента ---
        if custom_system_prompt:
            system_prompt = render_custom_prompt(
                custom_system_prompt, template_type, translation_languages,
            )
        else:
            system_prompt = get_analyze_prompt(template_type, translation_languages)
        http_client = None
        if not is_custom_llm and settings.LLM_PROXY:
            import httpx
            http_client = httpx.AsyncClient(proxy=settings.LLM_PROXY)
        # Явно предотвращаем фолбек openai-python на env OPENAI_API_KEY при api_key=None
        client = AsyncOpenAI(
            base_url=effective_url,
            api_key=effective_key or "no-key-provided",
            http_client=http_client,
            max_retries=2,
        )

        batch_results: list[tuple[DeviceInfo, list[Register]]] = []
        last_parse_error: str | None = None  # фрагмент ответа LLM при неудаче парсинга

        # --- Этап 3: отправка всех файлов в LLM одним запросом ---
        # Формируем единый content: текст (Excel) + файлы (PDF) + изображения (PNG/JPG)
        llm_content: list[dict] = []

        # Excel-данные как текст
        if text_parts:
            llm_content.append({
                "type": "text",
                "text": "\n\n".join(text_parts),
            })

        # PDF как file-content
        for filename, file_bytes in direct_files:
            mime = _get_file_mime(filename)
            b64_data = base64.b64encode(file_bytes).decode("ascii")
            llm_content.append({
                "type": "file",
                "file": {
                    "filename": filename,
                    "file_data": f"data:{mime};base64,{b64_data}",
                },
            })

        # Изображения как image_url
        for img in all_images:
            b64 = image_to_base64(img)
            llm_content.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/png;base64,{b64}",
                    "detail": "high",
                },
            })

        if not llm_content:
            yield sse_error("Нет данных для анализа. Загрузите PDF, Excel или изображение.", request_id=request_id)
            return

        file_names = ", ".join(fn for fn, _ in files)
        yield sse_progress("analyzing", f"Отправка в LLM: {file_names}...", request_id=request_id)

        batch_status: dict = {}
        task = asyncio.create_task(_analyze_single_batch(
            client, effective_model, system_prompt, llm_content,
            effective_timeout, effective_max_tokens, effective_legacy,
            effective_temperature, status=batch_status,
        ))
        start_time = time.monotonic()
        soft_sent = False
        retry_notified = False
        while True:
            done, _ = await asyncio.wait({task}, timeout=_KEEPALIVE_INTERVAL)
            if done:
                break
            # Уведомляем фронт о ретрае
            if batch_status.get("retrying") and not retry_notified:
                reason = batch_status.get("retry_reason", "неизвестная ошибка")
                yield sse_progress(
                    "analyzing",
                    f"Ответ LLM не удалось распарсить: {reason}. Повторная попытка...",
                    request_id=request_id,
                )
                retry_notified = True
                start_time = time.monotonic()
                soft_sent = False
                continue
            elapsed = int(time.monotonic() - start_time)
            mins, secs = divmod(elapsed, 60)
            attempt_label = " (попытка 2)" if retry_notified else ""
            if elapsed >= soft_timeout and not soft_sent:
                yield sse_progress(
                    "slow",
                    f"Анализ занимает больше времени чем обычно ({mins}:{secs:02d}){attempt_label}. "
                    "Можно продолжить ожидание или отменить.",
                    request_id=request_id,
                )
                soft_sent = True
            else:
                yield sse_progress(
                    "slow" if soft_sent else "analyzing",
                    f"LLM анализирует: {file_names}...{attempt_label} ({mins}:{secs:02d})",
                    request_id=request_id,
                )

        try:
            result = task.result()
            if isinstance(result, tuple):
                batch_results.append(result)
                logger.info("Файлы отправлены в LLM успешно")
            else:
                last_parse_error = result
        except LLMApiError as e:
            err_msg = str(e)
            if _is_file_unsupported(err_msg):
                yield sse_error(
                    f"Модель не поддерживает переданный формат файла. "
                    f"Используйте модель с поддержкой PDF/Excel или конвертируйте в изображения вручную.\n\n"
                    f"Ошибка API: {err_msg}",
                    request_id=request_id,
                )
            else:
                yield sse_error(f"Ошибка LLM API: {e}", request_id=request_id)
            return

        # --- Этап 5: мерж результатов ---
        if not batch_results:
            msg = "LLM не вернула пригодных результатов. Проверьте формат документа."
            if last_parse_error:
                msg += f"\n\nОтвет LLM (фрагмент):\n{last_parse_error}"
            yield sse_error(msg, request_id=request_id)
            return

        yield sse_progress(
            "merging",
            "Объединение и классификация регистров...",
            request_id=request_id,
        )

        device_info, registers = _merge_batch_results(batch_results)

        # Стрипаем переводы если языки не запрошены
        _allowed = set(translation_languages or []) - {"en"}
        if not _allowed:
            for reg in registers:
                reg.translations = None
                if reg.enum_entries:
                    for entry in reg.enum_entries:
                        entry.translations = None
        elif translation_languages:
            # Оставляем только запрошенные языки
            for reg in registers:
                if reg.translations:
                    reg.translations = {
                        k: v for k, v in reg.translations.items()
                        if k in _allowed
                    } or None
                if reg.enum_entries:
                    for entry in reg.enum_entries:
                        if entry.translations:
                            entry.translations = {
                                k: v for k, v in entry.translations.items()
                                if k in _allowed
                            } or None

        if not registers:
            yield sse_error(
                "Не удалось извлечь регистры из документа. "
                "Проверьте, что документ содержит таблицу Modbus-регистров.",
                request_id=request_id,
            )
            return

        # --- Этап 6: формирование ответа ---
        response = AnalyzeResponse(
            device_info=device_info,
            registers=registers,
        )

        yield sse_result(response, request_id=request_id)
        yield sse_done(request_id=request_id)
        logger.info("[%s] Анализ завершён: %d регистров", request_id, len(registers))

    except Exception as e:
        logger.exception("Ошибка при анализе документа")
        yield sse_error(f"Ошибка анализа: {e!s}", request_id=request_id)


async def _analyze_single_batch(
    client: AsyncOpenAI,
    model: str,
    system_prompt: str,
    content: list[dict],
    timeout: int,
    max_tokens: int = 16384,
    legacy_max_tokens: bool = False,
    temperature: float | None = None,
    status: dict | None = None,
) -> tuple[DeviceInfo, list[Register]] | str:
    """Анализирует один батч данных через LLM.

    При ошибке парсинга JSON делает одну повторную попытку
    с упрощённым промптом. Обновляет status-dict для уведомления
    вызывающего кода (keepalive-loop) о состоянии.

    status-dict:
        attempt: номер текущей попытки (1 или 2)
        retrying: True если идёт повторная попытка
        retry_reason: причина ретрая (текст ошибки)
        failed: True если все попытки провалились

    Returns:
        Кортеж (DeviceInfo, список Register) при успехе,
        или строку с фрагментом ответа LLM при неудаче парсинга.

    Raises:
        LLMApiError: при ошибках API (сеть, авторизация, модель не найдена).
    """
    if status is None:
        status = {}
    status["attempt"] = 1
    status["retrying"] = False

    try:
        # Первая попытка
        raw_response, _usage = await _call_llm(
            client, model, system_prompt, content, timeout, max_tokens, legacy_max_tokens, temperature,
        )
    except Exception as e:
        raise LLMApiError(str(e)) from e

    # Проверяем пустой ответ
    if not raw_response or not raw_response.strip():
        completion_tokens = _usage.completion_tokens if _usage else 0
        if completion_tokens and completion_tokens > 1000:
            reason = (
                f"LLM потратил {completion_tokens} токенов на reasoning, но не выдал текст. "
                f"Уберите ограничение LLM_MAX_TOKENS (установите 0)."
            )
        else:
            reason = "LLM вернул пустой ответ"
        logger.warning("Пустой ответ от LLM (completion_tokens=%d), повторная попытка", completion_tokens)
    else:
        try:
            raw_data = _extract_json_from_response(raw_response)
            return _parse_registers(raw_data)
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            reason = f"Ошибка парсинга JSON: {e}"
            logger.warning("Ошибка парсинга JSON ответа LLM, повторная попытка: %s", e)

    # Уведомляем вызывающий код о ретрае
    status["attempt"] = 2
    status["retrying"] = True
    status["retry_reason"] = reason

    # Повторная попытка с упрощённым промптом
    try:
        retry_content = content + [
            {"type": "text", "text": get_retry_prompt()},
        ]
        raw_response, _usage = await _call_llm(
            client, model, system_prompt, retry_content, timeout, max_tokens, legacy_max_tokens, temperature,
        )
    except Exception as e:
        status["failed"] = True
        raise LLMApiError(str(e)) from e

    # Проверяем пустой ответ повторной попытки
    if not raw_response or not raw_response.strip():
        logger.error("Повторная попытка тоже вернула пустой ответ")
        status["failed"] = True
        return "(пустой ответ LLM — обе попытки)"

    try:
        raw_data = _extract_json_from_response(raw_response)
        return _parse_registers(raw_data)
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        logger.error("Повторная попытка парсинга JSON тоже не удалась: %s", e)
        status["failed"] = True
        # Возвращаем фрагмент ответа LLM для диагностики
        snippet = raw_response[:300] if raw_response else "(пустой ответ)"
        return snippet
