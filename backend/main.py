"""Точка входа FastAPI-приложения. Эндпоинты: status, analyze (SSE), build, translate и import-template."""

import asyncio
import json
import logging
import re
import time
from collections import defaultdict, deque
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator, Optional

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse
from openai import AsyncOpenAI

import queue_manager
from config import get_settings
from jinja_exporter import build_jinja_template
from llm_errors import ALL_CATEGORIES, ErrorCategory
from llm_service import analysis_metrics, analyze_document, resolve_llm_credentials
from models import BuildRequest, TranslateRequest, ValidateRequest
from notifier import (
    init_notifier,
    register_metric_hook,
    report_llm_api_error,
    shutdown_notifier,
)
from prompts import get_raw_prompts, get_translate_prompt
from queue_manager import QueueTicket, init_queues
from request_context import generate_request_id, get_request_id, set_request_id
from sse import sse_error, sse_progress
from template_builder import build_template
from template_importer import TemplateImportError, detect_and_import
from user_errors import UserError


def get_version() -> str:
    """Парсит последнюю released-версию из CHANGELOG.md (единственный источник истины)."""
    _version_re = re.compile(r"^## \[(\d+\.\d+\.\d+)\]", re.MULTILINE)
    for candidate in (Path(__file__).resolve().parent / "../CHANGELOG.md", Path("CHANGELOG.md")):
        try:
            text = Path(candidate).resolve().read_text(encoding="utf-8")
            m = _version_re.search(text)
            if m:
                return m.group(1)
        except OSError:
            continue
    return "dev"


# Допустимые расширения загружаемых файлов
_ALLOWED_EXTENSIONS = {".pdf", ".xlsx", ".xls", ".png", ".jpg", ".jpeg", ".webp"}

# Структурированное логирование с request_id
class RequestIdFilter(logging.Filter):
    def filter(self, record):
        record.request_id = get_request_id() or "-"
        return True

def _setup_logging() -> None:
    """Настройка логирования: text (dev) или json (prod)."""
    settings = get_settings()
    handler = logging.StreamHandler()
    handler.addFilter(RequestIdFilter())

    if settings.LOG_FORMAT == "json":
        from pythonjsonlogger.json import JsonFormatter
        handler.setFormatter(JsonFormatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s %(request_id)s",
            rename_fields={"asctime": "timestamp", "levelname": "level"},
        ))
    else:
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s [%(request_id)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))

    logging.root.handlers = [handler]
    logging.root.setLevel(logging.INFO)

_setup_logging()

logger = logging.getLogger(__name__)

# Время старта для uptime
_start_time: float = time.monotonic()

# Rate limiter: sliding window по IP
_rate_limit_store: dict[str, deque[float]] = defaultdict(deque)

# Метрики: in-memory счётчики
_metrics = {
    "analyze_requests": 0,
    "analyze_errors": 0,
    "rate_limit_hits": 0,
    "durations": deque(maxlen=100),  # type: ignore[arg-type]
    # Счётчики ошибок LLM API по категориям (для мониторинга и Telegram-алертов)
    "llm_errors_by_category": {cat.value: 0 for cat in ALL_CATEGORIES},
}


def _record_llm_error_metric(category: ErrorCategory) -> None:
    """Хук для notifier: инкрементирует счётчик категории при ошибке LLM API."""
    bucket = _metrics["llm_errors_by_category"]
    bucket[category.value] = bucket.get(category.value, 0) + 1


def _check_rate_limit(ip: str, max_requests: int, window: int) -> bool:
    """Проверяет rate limit для IP. Возвращает True если лимит превышен."""
    now = time.monotonic()
    bucket = _rate_limit_store[ip]
    # Удаляем устаревшие записи
    while bucket and bucket[0] < now - window:
        bucket.popleft()
    if len(bucket) >= max_requests:
        return True
    bucket.append(now)
    return False


# ---------------------------------------------------------------------------
# Lifespan: инициализация и graceful shutdown
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Инициализация при старте, очистка при остановке."""
    global _start_time
    _start_time = time.monotonic()
    settings = get_settings()
    init_queues(
        server_max=settings.QUEUE_SERVER_MAX_CONCURRENT,
        custom_max=settings.QUEUE_CUSTOM_MAX_CONCURRENT,
        activation_delay=settings.QUEUE_ACTIVATION_DELAY,
    )
    # Telegram-уведомления о сбоях LLM API (только для серверного LLM)
    register_metric_hook(_record_llm_error_metric)
    init_notifier(settings, version=get_version())
    logger.info("Приложение запущено")
    yield
    # Graceful shutdown

    drained = 0
    if queue_manager.server_queue:
        drained += queue_manager.server_queue.drain()
    if queue_manager.custom_queue:
        drained += queue_manager.custom_queue.drain()
    if drained:
        logger.info("Снято %d ожидающих запросов при остановке", drained)
    # Ждём завершения активных запросов (до 30 сек)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        active = 0
        if queue_manager.server_queue:
            active += queue_manager.server_queue.active_count
        if queue_manager.custom_queue:
            active += queue_manager.custom_queue.active_count
        if active == 0:
            break
        await asyncio.sleep(0.5)
    await shutdown_notifier()
    logger.info("Приложение остановлено")


app = FastAPI(
    title="WB Template Generator",
    description="Генератор JSON-шаблонов Modbus-устройств для wb-mqtt-serial",
    version=get_version(),
    lifespan=lifespan,
)

# CORS — origins из переменной окружения
_cors_origins = [o.strip() for o in get_settings().CORS_ORIGINS.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-Id"],
)


# ---------------------------------------------------------------------------
# Middleware: Request ID
# ---------------------------------------------------------------------------

@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    """Генерирует request_id для каждого запроса, пробрасывает в ContextVar и заголовок."""
    rid = generate_request_id()
    set_request_id(rid)
    start = time.monotonic()
    logger.info("%s %s", request.method, request.url.path)
    response = await call_next(request)
    duration_ms = (time.monotonic() - start) * 1000
    response.headers["X-Request-Id"] = rid
    logger.info("%s %s → %d (%.0f мс)", request.method, request.url.path, response.status_code, duration_ms)
    return response


# ---------------------------------------------------------------------------
# Глобальный обработчик необработанных ошибок
# ---------------------------------------------------------------------------

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Ловит необработанные ошибки и возвращает JSON с request_id."""
    rid = get_request_id()
    logger.exception("Необработанная ошибка в %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={
            "detail": "Внутренняя ошибка сервера",
            "request_id": rid,
        },
    )


# ---------------------------------------------------------------------------
# API-эндпоинты
# ---------------------------------------------------------------------------

@app.get("/api/health")
async def health():
    """Health check — статус сервера, uptime, очереди."""

    uptime = int(time.monotonic() - _start_time)
    return {
        "status": "ok",
        "uptime_seconds": uptime,
        "queues": {
            "server": queue_manager.server_queue.get_status() if queue_manager.server_queue else None,
            "custom": queue_manager.custom_queue.get_status() if queue_manager.custom_queue else None,
        },
    }


@app.get("/api/status")
async def status():
    """Статус сервера — доступность LLM, лимиты и название модели."""
    settings = get_settings()
    result: dict = {
        "llm_available": bool(settings.LLM_API_URL),
        "max_file_size_mb": settings.MAX_FILE_SIZE_MB,
        "version": app.version,
    }
    if settings.LLM_API_URL:
        result["server_model"] = settings.LLM_MODEL
    return result


@app.get("/api/queue-status")
async def queue_status():
    """Текущее состояние очередей."""

    return {
        "server": queue_manager.server_queue.get_status() if queue_manager.server_queue else None,
        "custom": queue_manager.custom_queue.get_status() if queue_manager.custom_queue else None,
    }


@app.get("/api/metrics")
async def metrics():
    """In-memory метрики для мониторинга."""
    durations = list(_metrics["durations"])
    avg_duration = round(sum(durations) / len(durations), 1) if durations else None
    return {
        "counters": {
            "analyze_requests": _metrics["analyze_requests"],
            "analyze_errors": _metrics["analyze_errors"],
            "rate_limit_hits": _metrics["rate_limit_hits"],
        },
        "histograms": {
            "analyze_duration_avg": avg_duration,
            "analyze_duration_count": len(durations),
        },
        "llm_errors_by_category": dict(_metrics["llm_errors_by_category"]),
        # Автофикс: сколько прогонов его запускало и в скольких из них он убрал
        # все ошибки (ручная кнопка «Исправить через AI» не понадобилась).
        "analysis": dict(analysis_metrics),
    }


@app.get("/api/prompts")
async def get_prompts():
    """Возвращает сырые шаблоны промптов для отображения/редактирования на фронте."""
    return JSONResponse(content=get_raw_prompts())


@app.post("/api/models")
async def list_models(
    llm_api_url: Optional[str] = Form(None),
    llm_api_key: Optional[str] = Form(None),
):
    """Получение списка доступных моделей от LLM API провайдера."""
    settings = get_settings()

    effective_url, effective_key = resolve_llm_credentials(settings, llm_api_url, llm_api_key)

    if not effective_url:
        return JSONResponse(
            status_code=503,
            content={"detail": "LLM не настроен. Задайте LLM_API_URL или укажите URL в настройках."},
        )

    # Нормализуем base_url: убираем /v1, /v1/ и т.д.
    base_url = effective_url.rstrip("/")
    if base_url.endswith("/v1"):
        base_url = base_url[:-3]

    models_url = f"{base_url}/v1/models"

    try:
        import httpx
        http_kwargs: dict = {"timeout": 15.0}
        if not llm_api_url and settings.LLM_PROXY:
            http_kwargs["proxy"] = settings.LLM_PROXY
        headers = {}
        if effective_key:
            headers["Authorization"] = f"Bearer {effective_key}"
        async with httpx.AsyncClient(**http_kwargs) as client:
            resp = await client.get(models_url, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            models = sorted(m["id"] for m in data.get("data", []) if isinstance(m, dict) and "id" in m)
            return JSONResponse(content={"models": models})
    except Exception as e:
        logger.exception("Ошибка получения списка моделей")
        await report_llm_api_error(
            e, endpoint="list_models", request_id=get_request_id(),
            model="", is_custom_llm=bool(llm_api_url),
        )
        return JSONResponse(
            status_code=502,
            content={"detail": f"Не удалось получить список моделей: {e!s}"},
        )


@app.post("/api/analyze")
async def analyze(
    request: Request,
    files: list[UploadFile] = File(...),
    template_type: str = Form("full"),
    llm_api_url: Optional[str] = Form(None),
    llm_api_key: Optional[str] = Form(None),
    llm_model: Optional[str] = Form(None),
    llm_max_tokens: Optional[int] = Form(None),
    llm_timeout: Optional[int] = Form(None),
    llm_legacy_max_tokens: Optional[bool] = Form(None),
    llm_temperature: Optional[float] = Form(None),
    system_prompt: Optional[str] = Form(None),
    translation_languages: Optional[str] = Form(None),
):
    """Анализ загруженных файлов — SSE-поток с прогрессом и результатом.

    Требует настроенный LLM (серверный LLM_API_URL или клиентский llm_api_url).
    """
    settings = get_settings()
    request_id = get_request_id()
    is_custom_llm = bool(llm_api_url)

    # Rate limiting по IP
    client_ip = request.client.host if request.client else "unknown"
    if _check_rate_limit(client_ip, settings.RATE_LIMIT_REQUESTS, settings.RATE_LIMIT_WINDOW):
        _metrics["rate_limit_hits"] += 1
        limit_msg = (
            f"Превышен лимит запросов ({settings.RATE_LIMIT_REQUESTS} "
            f"за {settings.RATE_LIMIT_WINDOW} сек). Попробуйте позже."
        )
        return JSONResponse(
            status_code=429,
            content={"detail": limit_msg, "request_id": request_id},
        )

    _metrics["analyze_requests"] += 1

    # Проверяем доступность LLM — нужен хотя бы один URL
    if not llm_api_url and not settings.LLM_API_URL:
        return JSONResponse(
            status_code=503,
            content={
                "detail": "LLM не настроен. Задайте LLM_API_URL или укажите URL в настройках.",
                "request_id": request_id,
            },
        )

    # Проверка допустимых расширений файлов
    for f in files:
        ext = ("." + f.filename.rsplit(".", 1)[-1].lower()) if f.filename and "." in f.filename else ""
        if ext not in _ALLOWED_EXTENSIONS:
            return JSONResponse(
                status_code=400,
                content={
                    "detail": (
                        f"Неподдерживаемый формат файла: \u00ab{f.filename}\u00bb. "
                        f"Допустимые форматы: PDF, Excel (xlsx), изображения (PNG, JPG, WebP)."
                    ),
                    "request_id": request_id,
                },
            )

    # Читаем содержимое файлов и проверяем размер
    max_bytes = settings.MAX_FILE_SIZE_MB * 1024 * 1024
    file_data: list[tuple[str, bytes]] = []
    for f in files:
        content = await f.read()
        if len(content) > max_bytes:
            return JSONResponse(
                status_code=413,
                content={
                    "detail": (
                        f"Файл «{f.filename}» ({len(content) / 1024 / 1024:.1f} МБ) "
                        f"превышает лимит {settings.MAX_FILE_SIZE_MB} МБ. "
                        f"Попробуйте разделить документ на части или конвертировать в изображения."
                    ),
                    "request_id": request_id,
                },
            )
        file_data.append((f.filename or "unknown", content))

    # Парсим языки переводов из comma-separated строки
    langs: list[str] | None = None
    if translation_languages:
        langs = [lang.strip() for lang in translation_languages.split(",") if lang.strip()]

    # Выбираем очередь. None бывает, только если lifespan не выполнялся (например,
    # в тестах) — тогда анализ идёт без ограничения параллельности.
    queue = queue_manager.custom_queue if is_custom_llm else queue_manager.server_queue
    if not queue:
        logger.warning("Очередь не инициализирована, анализ без ограничения параллельности")

    def queued_event(ticket: QueueTicket) -> str:
        """SSE-событие «запрос в очереди» с текущей позицией и оценкой ожидания."""
        pos = ticket.position or 1
        eta = ticket.eta
        return sse_progress(
            "queued",
            f"Ваш запрос в очереди. Позиция: {pos}. Примерное ожидание: ~{max(1, eta // 60)} мин.",
            request_id=request_id,
            extra={"queue_position": pos, "queue_eta": eta},
        )

    async def queued_generator() -> AsyncGenerator[str, None]:
        """Обёртка: ожидание слота в очереди → выполнение analyze_document."""
        analysis_start: float | None = None

        try:
            # Выход из ticket() освобождает слот при любом исходе, включая обрыв SSE.
            async with AsyncExitStack() as stack:
                if queue:
                    ticket = await stack.enter_async_context(queue.ticket(request_id))

                    # timeout=0 — есть ли свободный слот прямо сейчас. Если нет,
                    # сообщаем позицию и ждём, обновляя её каждые 5 секунд.
                    if not await ticket.wait(timeout=0):
                        yield queued_event(ticket)
                        while not await ticket.wait(timeout=5.0):
                            if ticket.drained:
                                yield sse_error(
                                    "Сервис останавливается, попробуйте позже.",
                                    request_id=request_id,
                                )
                                return
                            yield queued_event(ticket)

                # Выполняем анализ
                analysis_start = time.monotonic()
                async for event in analyze_document(
                    files=file_data,
                    template_type=template_type,
                    settings=settings,
                    api_url=llm_api_url,
                    api_key=llm_api_key,
                    model=llm_model,
                    max_tokens=llm_max_tokens,
                    timeout=llm_timeout,
                    custom_system_prompt=system_prompt,
                    translation_languages=langs,
                    legacy_max_tokens=llm_legacy_max_tokens,
                    temperature=llm_temperature if llm_temperature is not None else -1,
                    request_id=request_id,
                    is_custom_llm=is_custom_llm,
                ):
                    yield event

        except Exception as e:
            logger.exception("Ошибка в очереди/анализе")
            _metrics["analyze_errors"] += 1
            yield sse_error(f"Ошибка: {e!s}", request_id=request_id)

        finally:
            # Ожидание в очереди в длительность анализа не входит: ETA считается из
            # среднего, а среднее росло бы от самого ожидания. Запрос, не дошедший до
            # анализа (отменён в очереди, оборван клиентом), замера не даёт вовсе.
            if analysis_start is not None:
                _metrics["durations"].append(time.monotonic() - analysis_start)

    return StreamingResponse(
        queued_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "X-Request-Id": request_id,
        },
    )


@app.post("/api/build")
async def build(request: BuildRequest):
    """Сборка JSON-шаблона из отредактированных регистров."""
    template = build_template(request)
    return JSONResponse(content=template)


@app.post("/api/validate-schema")
async def validate_schema(request: BuildRequest):
    """Валидация собранного шаблона по JSON-схеме wb-mqtt-serial."""
    from schema_validator import validate_template

    template = build_template(request)
    schema_errors = validate_template(template)
    return JSONResponse(content={
        "errors": schema_errors,
        "error_count": len(schema_errors),
    })


@app.post("/api/validate")
async def validate(request: ValidateRequest):
    """Валидация регистров по схеме wb-mqtt-serial."""
    from register_validator import validate_registers

    result = validate_registers(request.registers)
    return JSONResponse(content={
        "registers": [
            {
                "register_id": rv.register_id,
                "errors": [
                    {
                        "field": e.field,
                        "severity": e.severity.value,
                        "message_key": e.message_key,
                        "message_params": e.message_params,
                        "suggestion": e.suggestion,
                    }
                    for e in rv.errors
                ],
            }
            for rv in result.registers
            if rv.errors
        ],
        "error_count": result.error_count,
        "warning_count": result.warning_count,
    })


@app.post("/api/fix-registers")
async def fix_registers_endpoint(
    request: Request,
    body: ValidateRequest,
    llm_api_url: Optional[str] = None,
    llm_api_key: Optional[str] = None,
    llm_model: Optional[str] = None,
    llm_timeout: Optional[int] = None,
    llm_legacy_max_tokens: Optional[bool] = None,
    llm_temperature: Optional[float] = None,
):
    """Исправление регистров через AI — SSE-поток."""
    from llm_service import fix_registers
    from register_validator import (
        collect_error_registers,
        format_validation_errors,
        validate_registers,
    )

    settings = get_settings()
    request_id = get_request_id()
    is_custom_llm = bool(llm_api_url)

    effective_url, effective_key = resolve_llm_credentials(
        settings,
        llm_api_url if is_custom_llm else None,
        llm_api_key if is_custom_llm else None,
    )

    if not effective_url:
        return JSONResponse(
            status_code=503,
            content={"detail": "LLM не настроен."},
        )

    effective_model = (llm_model if is_custom_llm else None) or settings.LLM_MODEL
    effective_timeout = (llm_timeout if is_custom_llm else None) or settings.LLM_TIMEOUT
    effective_legacy = (
        llm_legacy_max_tokens if llm_legacy_max_tokens is not None else settings.LLM_LEGACY_MAX_TOKENS
    )
    effective_temperature = llm_temperature if is_custom_llm else settings.LLM_TEMPERATURE

    # Валидируем текущие регистры для получения описания ошибок
    validation = validate_registers(body.registers)
    error_desc = format_validation_errors(validation, body.registers)

    # В LLM отправляем ТОЛЬКО регистры с ошибками (не весь шаблон): иначе на
    # крупных устройствах запрос виснет и вывод обрезается по лимиту токенов.
    error_positions, error_registers = collect_error_registers(validation, body.registers)

    generator = fix_registers(
        error_registers,
        error_desc,
        all_registers=body.registers,
        error_positions=error_positions,
        effective_url=effective_url,
        effective_key=effective_key,
        effective_model=effective_model,
        effective_timeout=effective_timeout,
        max_tokens=settings.LLM_MAX_TOKENS or 16384,
        legacy_max_tokens=effective_legacy,
        temperature=effective_temperature,
        proxy=settings.LLM_PROXY if not is_custom_llm else "",
        request_id=request_id,
        is_custom_llm=is_custom_llm,
    )

    return StreamingResponse(
        generator,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/build-jinja")
async def build_jinja(request: BuildRequest):
    """Сборка Jinja-шаблона (.json.jinja) из отредактированных регистров."""
    template = build_template(request)
    jinja_text = build_jinja_template(template)
    return Response(content=jinja_text, media_type="text/plain")


@app.post("/api/translate")
async def translate(request: TranslateRequest):
    """Перевод строк через LLM."""
    settings = get_settings()
    request_id = get_request_id()

    is_custom_llm = bool(request.llm_api_url)

    # Изоляция ключей через единую функцию
    effective_url, effective_key = resolve_llm_credentials(
        settings, request.llm_api_url if is_custom_llm else None,
        request.llm_api_key if is_custom_llm else None,
    )
    if is_custom_llm:
        effective_model = request.llm_model or settings.LLM_MODEL
        effective_legacy = (
            request.llm_legacy_max_tokens if request.llm_legacy_max_tokens is not None
            else settings.LLM_LEGACY_MAX_TOKENS
        )
        effective_temperature = request.llm_temperature  # None = дефолт модели
        effective_timeout = request.llm_timeout or settings.LLM_TIMEOUT
    else:
        effective_model = settings.LLM_MODEL
        effective_legacy = settings.LLM_LEGACY_MAX_TOKENS
        effective_temperature = settings.LLM_TEMPERATURE
        effective_timeout = settings.LLM_TIMEOUT

    if not effective_url:
        return JSONResponse(
            status_code=503,
            content={
                "detail": "LLM не настроен. Задайте LLM_API_URL или укажите URL в настройках.",
                "request_id": request_id,
            },
        )

    if not request.strings:
        return JSONResponse(content={"translations": {}})

    prompt = get_translate_prompt(request.target_lang_name)
    strings_json = json.dumps(request.strings, ensure_ascii=False)

    http_client = None
    if not is_custom_llm and settings.LLM_PROXY:
        import httpx
        http_client = httpx.AsyncClient(proxy=settings.LLM_PROXY)
    # Явно предотвращаем фолбек openai-python на env OPENAI_API_KEY при api_key=None
    client = AsyncOpenAI(
        base_url=effective_url,
        api_key=effective_key or "no-key-provided",
        http_client=http_client,
    )

    try:
        # Выбираем параметр токенов в зависимости от настройки
        token_key = "max_tokens" if effective_legacy else "max_completion_tokens"
        fallback_key = "max_completion_tokens" if effective_legacy else "max_tokens"
        translate_kwargs: dict = {
            "model": effective_model,
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": strings_json},
            ],
            token_key: 4096,
            "timeout": effective_timeout,
        }
        if effective_temperature is not None:
            translate_kwargs["temperature"] = effective_temperature
        # До 3 попыток с автоудалением неподдерживаемых параметров
        for _attempt in range(3):
            try:
                response = await client.chat.completions.create(**translate_kwargs)
                break
            except Exception as e:
                err_str = str(e)
                fixed = False
                if token_key in translate_kwargs and (fallback_key in err_str or token_key in err_str):
                    logger.warning("Translate: %s → %s", token_key, fallback_key)
                    del translate_kwargs[token_key]
                    translate_kwargs[fallback_key] = 4096
                    token_key = fallback_key
                    fixed = True
                if "temperature" in err_str and "temperature" in translate_kwargs:
                    logger.warning("Translate: убираем temperature (не поддерживается моделью)")
                    del translate_kwargs["temperature"]
                    fixed = True
                if not fixed:
                    raise
        raw = response.choices[0].message.content or "{}"
        # Извлекаем JSON из ответа
        raw = raw.strip()
        json_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", raw, re.DOTALL)
        if json_match:
            raw = json_match.group(1)
        brace_start = raw.find("{")
        if brace_start > 0:
            raw = raw[brace_start:]
        brace_end = raw.rfind("}")
        if brace_end >= 0:
            raw = raw[: brace_end + 1]

        translations = json.loads(raw)
        return JSONResponse(content={"translations": translations})
    except Exception as e:
        logger.exception("Ошибка перевода через LLM")
        await report_llm_api_error(
            e, endpoint="translate", request_id=request_id,
            model=effective_model, is_custom_llm=is_custom_llm,
        )
        return JSONResponse(
            status_code=500,
            content={
                "detail": f"Ошибка перевода: {e!s}",
                "request_id": request_id,
            },
        )


@app.post("/api/import-template")
async def import_template_endpoint(file: UploadFile = File(...)):
    """Импорт существующего JSON/Jinja шаблона wb-mqtt-serial в формат редактора.

    Возвращает {device_info, registers, groups} — тот же формат что /api/analyze.
    """
    content = await file.read()
    filename = file.filename or "template.json"
    request_id = get_request_id()

    try:
        result = detect_and_import(content, filename)
    except json.JSONDecodeError as e:
        return JSONResponse(
            status_code=400,
            content=UserError("serverError.importInvalidJson", error=str(e)).payload(request_id),
        )
    except TemplateImportError as e:
        logger.warning("Импорт отклонён: %s", e)
        return JSONResponse(status_code=400, content=e.payload(request_id))
    except Exception:
        logger.exception("Ошибка импорта шаблона")
        return JSONResponse(
            status_code=422,
            content=UserError("serverError.importFailed").payload(request_id),
        )

    return JSONResponse(content=result)
