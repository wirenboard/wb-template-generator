"""Сервис для работы с LLM — отправка запросов, парсинг ответов, потоковая обработка."""

import asyncio
import base64
import ipaddress
import json
import logging
import re
import socket
import time
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx
from openai import AsyncOpenAI
from openai.types import CompletionUsage
from PIL import Image

from config import Settings
from file_converter import (
    FileParseError,
    ImageTooLargeError,
    excel_to_text,
    image_to_base64,
    is_excel_file,
    is_image_file,
    is_pdf_file,
    open_image,
)
from llm_errors import public_key
from log_utils import sanitize_for_log
from models import AnalyzeResponse, DeviceInfo, Register
from notifier import report_llm_api_error
from prompts import get_analyze_prompt, get_retry_prompt, render_custom_prompt
from serial_values import address_sort_value, canonical_address, parse_address
from sse import sse_done, sse_progress, sse_result, sse_user_error
from user_errors import UserError, render_key

# Интервал SSE keepalive (сек) — поддерживает соединение через nginx
_KEEPALIVE_INTERVAL = 15

logger = logging.getLogger(__name__)

# In-memory метрики анализа (читаются эндпоинтом /api/metrics).
# autofix_runs — прогонов, где после анализа были ERROR и запускался автофикс;
# autofix_cleared — из них тех, где автофикс убрал ВСЕ ошибки (кнопка
# «Исправить через AI» не понадобилась).
#
# ВНИМАНИЕ: main.py импортирует этот словарь по имени, поэтому его можно только
# МУТИРОВАТЬ. Переприсваивание (analysis_metrics = {...}, в том числе для сброса)
# оставит в main старый объект, и метрики перестанут обновляться — ровно так были
# сломаны очереди, где init_queues() присваивал переменные модуля.
analysis_metrics: dict[str, int] = {
    "autofix_runs": 0,
    "autofix_cleared": 0,
}


class LLMApiError(Exception):
    """Ошибка при обращении к LLM API (сеть, авторизация, модель не найдена).

    Наружу уходит только `key` — ключ локализации фразы по категории сбоя, текст собирается
    из него же. Текст провайдера лежит в `raw`, он нужен логу и эвристике
    `_is_file_unsupported`, но клиенту не уходит.
    """

    def __init__(self, key: str, *, raw: str | None = None) -> None:
        message = render_key(key)
        super().__init__(message)
        self.key = key
        self.raw = raw if raw is not None else message

    @classmethod
    def from_provider(cls, exc: Exception) -> "LLMApiError":
        """Отказ обращения к провайдеру — категория ключом, текст исключения в raw."""
        return cls(public_key(exc), raw=str(exc))


def log_llm_failure(key: str, raw: str, *, request_id: str | None, action: str) -> None:
    """Пишет отказ обращения к LLM в лог одним форматом на всех маршрутах.

    Текст провайдера идёт через санитайз — со своим адресом LLM его задаёт клиент.
    """
    logger.warning("[%s] %s (%s) — %s", request_id, action, key, sanitize_for_log(raw))


async def report_and_log_llm_failure(
    exc: Exception,
    *,
    endpoint: str,
    request_id: str | None,
    model: str,
    is_custom_llm: bool,
    action: str,
) -> None:
    """Лог плюс уведомление дежурного для маршрутов, которые зовут провайдера сами."""
    log_llm_failure(public_key(exc), str(exc), request_id=request_id, action=action)
    await report_llm_api_error(
        exc, endpoint=endpoint, request_id=request_id, model=model, is_custom_llm=is_custom_llm,
    )


# ---------------------------------------------------------------------------
# Маршрутизация LLM-ключей (изоляция серверного ключа)
# ---------------------------------------------------------------------------

def resolve_llm_credentials(
    settings: Settings,
    user_url: str | None,
    user_key: str | None,
) -> tuple[str | None, str | None]:
    """Определяет URL и API-ключ для LLM-запроса.

    Изоляция: при пользовательском URL серверный ключ НЕ подставляется.

    Returns:
        (effective_url, effective_key) — URL и ключ для использования.
    """
    if user_url:
        return user_url, user_key
    return settings.LLM_API_URL, settings.LLM_API_KEY


@dataclass(frozen=True)
class LlmTarget:
    """Куда и с какими параметрами уходит запрос к LLM."""

    url: str | None
    key: str | None
    model: str
    timeout: int
    max_tokens: int          # 0 = не задан, свой потолок выбирает вызывающий код
    legacy_max_tokens: bool
    temperature: float | None  # None = не отправлять параметр вовсе
    proxy: str | None
    is_custom: bool


def is_custom_llm_url(url: str | None) -> bool:
    """Определяет по адресу, идёт ли запрос на свой LLM пользователя.

    Ключ в критерий не входит — локальные модели авторизации не требуют, и с
    таким требованием запрос уходил бы на серверный LLM, за наш счёт.
    """
    return bool(url)


def resolve_llm_target(
    settings: Settings,
    *,
    url: str | None = None,
    key: str | None = None,
    model: str | None = None,
    timeout: int | None = None,
    max_tokens: int | None = None,
    legacy_max_tokens: bool | None = None,
    temperature: float | None = None,
) -> LlmTarget:
    """Определяет, куда и с какими параметрами уходит запрос к LLM.

    Адрес, ключ и прокси изолированы — со своим адресом серверный ключ не
    подставляется, через прокси оператора чужой адрес не гоняется. Модель,
    таймаут, лимит токенов и температура применяются и к серверному LLM, так
    задумано окно «Настройки LLM». Системный промпт в правило не входит, он
    остаётся только для своего адреса (изоляция в `analyze_document`).

    Пустое значение означает «клиент не прислал». У температуры и флага
    токенов это строго None, ноль и False значимы.

    Returns:
        Разрешённая цель со всеми параметрами запроса.
    """
    is_custom = is_custom_llm_url(url)
    effective_url, effective_key = resolve_llm_credentials(settings, url, key)

    def pick(value, fallback):
        """Для строк и чисел незаданное — это пусто или ноль."""
        return value or fallback

    def pick_exact(value, fallback):
        """Для флагов и температуры незаданное — только None."""
        return value if value is not None else fallback

    # Таймаут на серверном ключе можно опустить, но не поднять — длинный запрос
    # держит воркер, а троттлинга на исправлении регистров и переводе нет.
    effective_timeout = pick(timeout, settings.LLM_TIMEOUT)
    if not is_custom and settings.LLM_TIMEOUT > 0 and effective_timeout > settings.LLM_TIMEOUT:
        logger.warning(
            "Присланный таймаут %s с больше потолка сервера, уменьшаем до %s с.",
            effective_timeout, settings.LLM_TIMEOUT,
        )
        effective_timeout = settings.LLM_TIMEOUT

    return LlmTarget(
        url=effective_url,
        key=effective_key,
        model=pick(model, settings.LLM_MODEL),
        timeout=effective_timeout,
        max_tokens=pick(max_tokens, settings.LLM_MAX_TOKENS),
        legacy_max_tokens=pick_exact(legacy_max_tokens, settings.LLM_LEGACY_MAX_TOKENS),
        temperature=pick_exact(temperature, settings.LLM_TEMPERATURE),
        # Прокси оператора только для его же адреса
        proxy=None if is_custom else (settings.LLM_PROXY or None),
        is_custom=is_custom,
    )


# ---------------------------------------------------------------------------
# Проверка адреса пользовательского LLM
# ---------------------------------------------------------------------------

class UnsafeLLMUrlError(UserError):
    """Адрес пользовательского LLM задан неверно или ведёт во внутреннюю сеть."""


_ALLOWED_LLM_SCHEMES = frozenset({"http", "https"})

# Диапазоны, которые ведут внутрь, но под is_private попадают не всегда. 100.64.0.0/10
# это CGNAT и адреса Tailscale, fec0::/10 — site-local IPv6 (у него вдобавок
# is_global=True), 2002::/16 — 6to4, обёртка произвольного IPv4, которую приватной
# считает только Python 3.12.4+. Проверять через is_global нельзя, оно пропускает
# site-local и ловит multicast.
_EXTRA_INTERNAL_NETS = (
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("fec0::/10"),
    ipaddress.ip_network("2002::/16"),
)

# Потолок на разрешение имени. Молчащий NS в присланном адресе иначе занимает
# резолвер процесса, а /api/models и /api/translate не троттлятся.
_DNS_TIMEOUT = 5.0


async def _resolve_host(hostname: str) -> list[str]:
    """Разрешает имя хоста в список IP. Отдельной функцией — чтобы подменять в тестах."""
    loop = asyncio.get_running_loop()
    infos = await asyncio.wait_for(
        loop.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP), _DNS_TIMEOUT,
    )
    return [str(info[4][0]) for info in infos]


async def ensure_public_llm_url(url: str, allow_private: bool = False) -> None:
    """Проверяет, что адрес пользовательского LLM ведёт в публичную сеть.

    Адрес приходит в запросе и становится base_url клиента, то есть сервер идёт по
    нему сам. Адрес оператора из LLM_API_URL доверенный и сюда не попадает.

    При `allow_private` остаётся только проверка схемы и наличия хоста, имя не
    резолвится вовсе. Остаточный риск — DNS rebinding, имя проверяется до
    соединения, а резолвится ещё раз при самом запросе.

    Raises:
        UnsafeLLMUrlError: схема не http(s), адрес не разбирается, хост не указан,
            не резолвится или разрешается во внутреннюю сеть.
    """
    try:
        parts = urlsplit(url)
    except ValueError as e:
        # «[» urlsplit читает как начало IPv6-литерала и на незакрытой скобке бросает
        raise UnsafeLLMUrlError("serverError.llmUrlNoHost") from e

    if parts.scheme not in _ALLOWED_LLM_SCHEMES:
        raise UnsafeLLMUrlError("serverError.llmUrlScheme")

    hostname = parts.hostname
    if not hostname:
        raise UnsafeLLMUrlError("serverError.llmUrlNoHost")

    # Имя пришло от клиента, а urlsplit пропускает в хост что угодно, включая ESC
    safe_host = sanitize_for_log(hostname)

    if allow_private:
        return

    try:
        addresses = await _resolve_host(hostname)
    except TimeoutError as e:
        # Выше OSError — TimeoutError его подкласс, иначе ветка недостижима
        logger.warning("Имя «%s» не разрешилось за %s с, отклоняем адрес LLM", safe_host, _DNS_TIMEOUT)
        raise UnsafeLLMUrlError("serverError.llmUrlUnresolvable", host=hostname) from e
    except (OSError, UnicodeError) as e:
        logger.info("Имя «%s» не разрешилось (%s), отклоняем адрес LLM", safe_host, e)
        raise UnsafeLLMUrlError("serverError.llmUrlUnresolvable", host=hostname) from e

    for raw in addresses:
        try:
            ip = ipaddress.ip_address(raw)
        except ValueError as e:
            raise UnsafeLLMUrlError("serverError.llmUrlBadAddress", host=hostname) from e

        # ::ffff:10.0.0.1 — приватный адрес в обёртке IPv6, разворачиваем
        mapped = getattr(ip, "ipv4_mapped", None)
        if mapped is not None:
            ip = mapped

        internal = any(ip.version == net.version and ip in net for net in _EXTRA_INTERNAL_NETS)
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast or ip.is_unspecified or internal):
            logger.warning("Имя «%s» разрешилось во внутренний адрес %s, отклоняем", safe_host, ip)
            raise UnsafeLLMUrlError("serverError.llmUrlPrivate")


def build_llm_http_client(proxy: str | None = None) -> httpx.AsyncClient:
    """Создаёт httpx-клиент для обращений к LLM API.

    Свой клиент нужен всегда, а не только под прокси. openai-python поднимает
    собственный с `follow_redirects=True`, и тогда публичный адрес, отвечающий 302,
    уводит запрос во внутреннюю сеть в обход `ensure_public_llm_url`.
    """
    kwargs: dict = {"follow_redirects": False}
    if proxy:
        kwargs["proxy"] = proxy
    return httpx.AsyncClient(**kwargs)


# Клиентов ровно два — серверный и пользовательский, поэтому ключ это один флаг.
# Соединения внутри клиента переиспользуются его же пулом, за запрос ничего не
# создаётся. Закрывает клиенты lifespan.
_llm_http_clients: dict[bool, httpx.AsyncClient] = {}


def get_llm_http_client(proxy: str | None = None, *, is_custom: bool = False) -> httpx.AsyncClient:
    """Возвращает общий httpx-клиент процесса для обращений к LLM API.

    У пользовательского свой пул соединений, поэтому чужой медленный хост не
    занимает соединения серверного трафика, и прокси оператора этот клиент не
    получает ни при каких аргументах. Закрытый клиент пересоздаём — его закрывает
    lifespan на остановке, а ещё закроет AsyncOpenAI.close(), если кто-то его позовёт.
    """
    client = _llm_http_clients.get(is_custom)
    if client is None or client.is_closed:
        client = build_llm_http_client(None if is_custom else proxy)
        _llm_http_clients[is_custom] = client
    if is_custom:
        client.cookies.clear()
    return client


async def close_llm_http_clients() -> None:
    """Закрывает общие httpx-клиенты. Зовётся из lifespan при остановке."""
    for client in _llm_http_clients.values():
        if not client.is_closed:
            await client.aclose()
    _llm_http_clients.clear()


# ---------------------------------------------------------------------------
# Парсинг JSON из ответа LLM
# ---------------------------------------------------------------------------

def extract_json_from_response(text: str) -> dict:
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


def _parse_registers(raw: dict, *, preserve_id: bool = False) -> tuple[DeviceInfo, list[Register], int]:
    """Парсит ответ LLM в структуры DeviceInfo и список Register.

    Использует авто-исправление синонимов + мягкую валидацию.

    Returns:
        (DeviceInfo, список Register, количество авто-исправлений)
    """
    from register_validator import auto_fix_register

    # Парсим device_info
    raw_info = raw.get("device_info", {})
    device_info = DeviceInfo(
        name=raw_info.get("name", "Unknown Device"),
        id=raw_info.get("id", "unknown-device"),
        device_group=raw_info.get("device_group"),
    )

    # Парсим регистры с авто-фиксом и мягкой валидацией
    registers: list[Register] = []
    raw_registers = raw.get("registers", [])
    auto_fixed_count = 0

    for raw_reg in raw_registers:
        if not isinstance(raw_reg, dict):
            continue
        try:
            # По умолчанию убираем id (LLM-генерённый) — мы генерируем свои uuid.
            # preserve_id=True сохраняет id (нужно для merge-back в fix-registers).
            if not preserve_id:
                raw_reg.pop("id", None)
            # Авто-исправление синонимов (uint16→u16, holding_register→holding и т.д.)
            fixed_reg, fixes = auto_fix_register(raw_reg)
            auto_fixed_count += len(fixes)
            if fixes:
                fix_desc = ", ".join(f'{f.message_params.get("field", "")}: '
                                     f'{f.message_params.get("from", "")}→{f.message_params.get("to", "")}'
                                     for f in fixes)
                logger.info(
                    "Авто-исправление регистра «%s»: %s",
                    sanitize_for_log(raw_reg.get("name", "?")), fix_desc,
                )
            reg = Register(**fixed_reg)
            registers.append(reg)
        except Exception as e:
            # Мягкая валидация — пробуем с минимальными полями
            logger.warning("Ошибка парсинга регистра %s: %s", sanitize_for_log(raw_reg), e)
            try:
                reg = Register(
                    address=parse_address(raw_reg.get("address", 0)),
                    name=str(raw_reg.get("name", "Unknown")),
                    **({"id": raw_reg["id"]} if preserve_id and raw_reg.get("id") else {}),
                )
                registers.append(reg)
            except Exception:
                logger.error(
                    "Не удалось распарсить регистр, пропускаем: %s", sanitize_for_log(raw_reg),
                )

    return device_info, registers, auto_fixed_count


def _merge_fixed_registers(
    all_registers: list[Register],
    fixed_subset: list[Register],
    error_positions: list[int],
) -> list[Register]:
    """Вмёрдживает исправленное подмножество регистров обратно в полный список.

    Используется в fix-registers: в LLM уходят только регистры с ошибками (в порядке
    error_positions), помеченные ВРЕМЕННЫМ уникальным id `__fix_<i>`. Матчим по нему,
    а не по настоящему id, потому что id в шаблонах НЕ уникальны — у condition-gated
    пар (одна address, взаимоисключающие condition) id совпадают, и матч по id схлопнул
    бы близнецов. Восстанавливаем исходный id и ставим фикс строго на свою позицию.
    Регистры, которых LLM не вернул, остаются без изменений.
    """
    fixed_by_temp = {r.id: r for r in fixed_subset if r.id}
    merged: list[Register] = list(all_registers)
    for i, pos in enumerate(error_positions):
        fx = fixed_by_temp.get(f"__fix_{i}")
        if fx is not None:
            fx.id = all_registers[pos].id  # восстанавливаем исходный id
            merged[pos] = fx
    return merged


def _merge_batch_results(
    batches: list[tuple[DeviceInfo, list[Register], int]],
) -> tuple[DeviceInfo, list[Register], int]:
    """Мержит результаты батчей с дедупом. Побеждает первое вхождение.

    Ключ дедупа — (address, reg_type, condition). В Modbus пара (address, reg_type)
    однозначно определяет регистр, а condition в ключе сохраняет condition-gated
    пары (один адрес и тип, взаимоисключающие condition). Разные адресные
    пространства (coil и holding на одном числовом адресе) не схлопываются, у них
    разный reg_type. device_info берётся из первого непустого батча.

    Returns:
        (DeviceInfo, список Register, суммарное количество авто-исправлений)
    """
    device_info = DeviceInfo(name="Unknown Device", id="unknown-device")
    all_registers: list[Register] = []
    # Адрес в ключе канонической записью — 255 и «0xff» это один регистр
    seen: set[tuple[str, str, str | None]] = set()
    total_auto_fixed = 0

    for batch_info, batch_regs, batch_fixed in batches:
        total_auto_fixed += batch_fixed
        # Берём device_info из первого батча, где он непустой
        if device_info.name == "Unknown Device" and batch_info.name != "Unknown Device":
            device_info = batch_info

        for reg in batch_regs:
            key = (canonical_address(reg.address), reg.reg_type, reg.condition)
            if key in seen:
                continue
            seen.add(key)
            all_registers.append(reg)

    all_registers.sort(key=lambda r: (r.reg_type, address_sort_value(r.address)))
    return device_info, all_registers, total_auto_fixed


def _deterministic_fix_registers(registers: list[Register]) -> tuple[list[Register], int]:
    """Детерминированный (бесплатный) авто-фикс уже распарсенных регистров.

    Прогоняет auto_fix_register по каждому регистру (синонимы format/reg_type/… →
    канонические значения). Обычно почти всё уже поправлено при парсинге ответа LLM,
    но это дешёвый первый шаг автофикса перед платным LLM-проходом. id сохраняется.

    Returns:
        (новый список регистров, число применённых исправлений).
    """
    from register_validator import auto_fix_register

    out: list[Register] = []
    fixed_count = 0
    for reg in registers:
        raw = reg.model_dump()
        fixed_raw, fixes = auto_fix_register(raw)
        fixed_count += len(fixes)
        if not fixes:
            out.append(reg)
            continue
        try:
            out.append(Register(**fixed_raw))
        except Exception as e:  # noqa: BLE001 — оставляем оригинал, не теряем регистр
            logger.warning(
                "Детерминированный фикс не применился к «%s»: %s", sanitize_for_log(reg.name), e,
            )
            out.append(reg)
    return out, fixed_count


# ---------------------------------------------------------------------------
# Вызов LLM API (асинхронный)
# ---------------------------------------------------------------------------

async def call_llm(
    client: AsyncOpenAI,
    model: str,
    system_prompt: str,
    content: list[dict] | str,
    timeout: int,
    max_tokens: int = 16384,
    legacy_max_tokens: bool = False,
    temperature: float | None = None,
) -> tuple[str, CompletionUsage | None]:
    """Асинхронный вызов OpenAI-compatible API с vision-контентом.

    Возвращает текстовый ответ LLM и расход токенов. Расход приходит пустым, когда
    провайдер его не отдаёт.

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
    token_key_switched = False
    last_error: Exception | None = None
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
            last_error = e
            fixed = False

            # Фолбек max_tokens ↔ max_completion_tokens. Однократный: после подмены имена
            # совпадают, и повторная «правка» удаляла бы и клала обратно тот же ключ
            if not token_key_switched and primary_key in kwargs and (
                fallback_key in err_str or primary_key in err_str
            ):
                logger.warning(
                    "Модель %s не поддерживает %s, переключаемся на %s. "
                    "Совет: измените настройку «Параметр токенов» в UI.",
                    sanitize_for_log(model), primary_key, fallback_key,
                )
                del kwargs[primary_key]
                kwargs[fallback_key] = max_tokens
                primary_key = fallback_key
                token_key_switched = True
                fixed = True

            # Фолбек temperature: некоторые модели (o1, gpt-4o) не поддерживают
            if "temperature" in err_str and "temperature" in kwargs:
                logger.warning(
                    "Модель %s отвергла temperature=%s, повторяем запрос без неё.",
                    sanitize_for_log(model), kwargs["temperature"],
                )
                del kwargs["temperature"]
                fixed = True

            if not fixed:
                raise

    # Попытки кончились, а запрос так и не прошёл — отдаём последний отказ провайдера,
    # иначе вызывающий код принял бы пустой ответ за ответ модели
    raise last_error if last_error else RuntimeError("Не удалось обратиться к LLM")


def assemble_llm_content(
    text_parts: list[str],
    direct_files: list[tuple[str, bytes]],
    all_images: list["Image.Image"],
) -> list[dict]:
    """Собирает vision-контент для LLM: Excel → текст, PDF → file (base64), изображения → image_url.

    Единая точка формирования запроса — общая для analyze_document и регресс-теста,
    чтобы тест проверял ровно тот контент, что уходит в модель.
    """
    llm_content: list[dict] = []

    if text_parts:
        llm_content.append({
            "type": "text",
            "text": "\n\n".join(text_parts),
        })

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

    for img in all_images:
        b64 = image_to_base64(img)
        llm_content.append({
            "type": "image_url",
            "image_url": {
                "url": f"data:image/png;base64,{b64}",
                "detail": "high",
            },
        })

    return llm_content


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


async def _await_batch_with_progress(
    task: "asyncio.Task",
    batch_status: dict,
    *,
    request_id: str | None,
    file_names: str,
    soft_timeout: int,
    stage: str = "analyzing",
    label: str | None = None,
    slow_stage: bool = True,
) -> AsyncGenerator[str, None]:
    """SSE keepalive-цикл ожидания одной задачи LLM.

    Пока задача выполняется — периодически шлёт progress (в т.ч. soft-timeout и
    уведомление о ретрае из batch_status). Возвращается, когда задача завершена;
    результат вызывающий читает через task.result().

    Args:
        stage: стадия для промежуточных событий (по умолчанию analyzing).
        label: текст события; None — «LLM анализирует: <файлы>».
        slow_stage: переключаться на стадию slow после soft_timeout. Для этапов
            вне основного анализа выключается, иначе поверх своей стадии придёт
            чужая и лог анализа станет непонятным.
    """
    start_time = time.monotonic()
    soft_sent = False
    retry_notified = False
    text = label or f"LLM анализирует: {file_names}"
    while True:
        done, _ = await asyncio.wait({task}, timeout=_KEEPALIVE_INTERVAL)
        if done:
            return
        # Уведомляем фронт о ретрае
        if batch_status.get("retrying") and not retry_notified:
            reason = batch_status.get("retry_reason", "неизвестная ошибка")
            yield sse_progress(
                stage,
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
        if slow_stage and elapsed >= soft_timeout and not soft_sent:
            yield sse_progress(
                "slow",
                f"Анализ занимает больше времени чем обычно ({mins}:{secs:02d}){attempt_label}. "
                "Можно продолжить ожидание или отменить.",
                request_id=request_id,
            )
            soft_sent = True
        else:
            yield sse_progress(
                "slow" if soft_sent else stage,
                f"{text}...{attempt_label} ({mins}:{secs:02d})",
                request_id=request_id,
            )


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
    temperature: float | None = None,  # None = клиент не прислал, берём настройку сервера
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
                     request_id, len(files), sanitize_for_log(template_type), is_custom_llm)

        # Изоляция: при серверной модели игнорируем пользовательский промпт
        if not is_custom_llm:
            custom_system_prompt = None

        target = resolve_llm_target(
            settings,
            url=api_url if is_custom_llm else None,
            key=api_key if is_custom_llm else None,
            model=model,
            timeout=timeout,
            max_tokens=max_tokens,
            legacy_max_tokens=legacy_max_tokens,
            temperature=temperature,
        )
        effective_url, effective_key = target.url, target.key
        effective_model = target.model
        effective_max_tokens = target.max_tokens
        effective_timeout = target.timeout
        effective_legacy = target.legacy_max_tokens
        effective_temperature = target.temperature
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
                try:
                    sheet_text = excel_to_text(content_bytes)
                except FileParseError as e:
                    # Имя файла подставляем здесь, в разборе его нет
                    yield sse_user_error(
                        UserError(e.key, file=filename, **e.params), request_id=request_id,
                    )
                    return
                text_parts.append(f"--- {filename} ---\n{sheet_text}")

            elif is_image_file(filename):
                # Изображение -> PIL.Image. Битый файл прекращает анализ: пропустить его
                # молча нельзя, иначе шаблон собрался бы по части документа незаметно.
                try:
                    img = open_image(content_bytes)
                except ImageTooLargeError as e:
                    yield sse_user_error(
                        UserError(e.key, file=filename, **e.params), request_id=request_id,
                    )
                    return
                except Exception as e:  # noqa: BLE001 — любую ошибку PIL показываем понятным текстом
                    logger.warning("Битое изображение %s: %s", sanitize_for_log(filename), e)
                    yield sse_user_error(
                        UserError("serverError.brokenImage", file=filename),
                        request_id=request_id,
                    )
                    return
                all_images.append(img)

            else:
                logger.warning("Неподдерживаемый формат файла: %s", sanitize_for_log(filename))

        convert_duration = time.monotonic() - convert_start
        logger.info("[%s] Конвертация файлов: %.1f сек", request_id, convert_duration)

        # --- Этап 2: подготовка LLM-клиента ---
        try:
            if custom_system_prompt:
                system_prompt = render_custom_prompt(
                    custom_system_prompt, template_type, translation_languages,
                )
            else:
                system_prompt = get_analyze_prompt(template_type, translation_languages)
        except UserError as e:
            # Без перехвата ушла бы «внутренняя ошибка» вместо текста с числами потолка
            yield sse_user_error(e, request_id=request_id)
            return
        # Прокси только для серверного LLM: пользовательский запрос через него не гоняем
        http_client = get_llm_http_client(
            settings.LLM_PROXY if not is_custom_llm else None, is_custom=is_custom_llm,
        )
        # Явно предотвращаем фолбек openai-python на env OPENAI_API_KEY при api_key=None
        client = AsyncOpenAI(
            base_url=effective_url,
            api_key=effective_key or "no-key-provided",
            http_client=http_client,
            max_retries=2,
        )

        batch_results: list[tuple[DeviceInfo, list[Register], int]] = []
        last_parse_error: str | None = None  # фрагмент ответа LLM при неудаче парсинга
        last_api_error_key: str | None = None  # категория сбоя обращения к LLM
        unsupported_file = False

        # --- Этап 3: отправка всех файлов в LLM одним запросом ---
        # Формируем единый content: текст (Excel) + файлы (PDF) + изображения (PNG/JPG)
        llm_content = assemble_llm_content(text_parts, direct_files, all_images)

        if not llm_content:
            yield sse_user_error(UserError("serverError.noData"), request_id=request_id)
            return

        file_names = ", ".join(fn for fn, _ in files)
        yield sse_progress("analyzing", f"Отправка в LLM: {file_names}...", request_id=request_id)

        batch_status: dict = {}
        task = asyncio.create_task(_analyze_single_batch(
            client, effective_model, system_prompt, llm_content,
            effective_timeout, effective_max_tokens, effective_legacy,
            effective_temperature, status=batch_status,
            error_endpoint="analyze_document",
            error_request_id=request_id or "",
            error_model=effective_model,
            is_custom_llm=is_custom_llm,
        ))
        try:
            async for ev in _await_batch_with_progress(
                task, batch_status, request_id=request_id,
                file_names=file_names, soft_timeout=soft_timeout,
            ):
                yield ev
        finally:
            # Клиент оборвал SSE — доставить результат некуда, хранилища у нас нет,
            # поэтому не жжём квоту дальше. На нормальном пути задача уже завершена.
            if not task.done():
                task.cancel()
                logger.info("[%s] Клиент ушёл, запрос к LLM отменён", request_id)
        try:
            result = task.result()
            if isinstance(result, tuple):
                batch_results.append(result)
                logger.info("[%s] Файлы отправлены в LLM успешно", request_id)
            else:
                last_parse_error = result
        except LLMApiError as e:
            # Эвристике формата нужен текст провайдера, пользователю уйдёт категория
            last_api_error_key = e.key
            unsupported_file = _is_file_unsupported(e.raw)
            # Единственное место, где текст провайдера доходит до лога — report_llm_api_error
            # на своём ключе клиента выходит сразу
            log_llm_failure(e.key, e.raw, request_id=request_id, action="Сбой обращения к LLM")

        if unsupported_file:
            yield sse_user_error(
                UserError("serverError.modelUnsupportedFile", reasonKey=last_api_error_key),
                request_id=request_id,
            )
            return

        # --- Этап 4: мерж результатов ---
        if not batch_results:
            if last_api_error_key:
                # Запрос до модели не дошёл (ключ, квота, лимит, недоступность) —
                # с форматом документа это не связано, иначе диагностика уводится не туда.
                err = UserError("serverError.llmNoResponse", reasonKey=last_api_error_key)
            elif last_parse_error:
                err = UserError(
                    "serverError.llmUnusableResultsWithFragment", fragment=last_parse_error,
                )
            else:
                err = UserError("serverError.llmUnusableResults")
            yield sse_user_error(err, request_id=request_id)
            return

        yield sse_progress(
            "merging",
            "Объединение и классификация регистров...",
            request_id=request_id,
        )
        device_info, registers, total_auto_fixed = _merge_batch_results(batch_results)

        if not registers:
            yield sse_user_error(
                UserError("serverError.noRegisters"), request_id=request_id,
            )
            return

        from register_validator import validate_registers as _validate_regs

        # Стрипаем переводы если языки не запрошены (до автофикса — меньше токенов в фикс)
        _allowed = set(translation_languages or []) - {"en"}
        if not _allowed:
            for reg in registers:
                reg.translations = None
                reg.group_title_translations = None
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
                if reg.group_title_translations:
                    reg.group_title_translations = {
                        k: v for k, v in reg.group_title_translations.items()
                        if k in _allowed
                    } or None
                if reg.enum_entries:
                    for entry in reg.enum_entries:
                        if entry.translations:
                            entry.translations = {
                                k: v for k, v in entry.translations.items()
                                if k in _allowed
                            } or None

        # --- Этап 5: финальная валидация + автофикс (одна попытка) ---
        yield sse_progress("validating", "Проверка регистров...", request_id=request_id)
        final_validation = _validate_regs(registers)
        if total_auto_fixed:
            logger.info("[%s] Авто-исправлено %d полей при парсинге ответа", request_id, total_auto_fixed)

        if final_validation.error_count:
            errors_before = final_validation.error_count
            llm_fix_applied = False
            analysis_metrics["autofix_runs"] += 1

            # Шаг 1 — детерминированный авто-фикс (бесплатно)
            yield sse_progress("autofix", "Автоисправление: проверка полей без AI...", request_id=request_id)
            registers, det_fixed = _deterministic_fix_registers(registers)
            final_validation = _validate_regs(registers)

            # Шаг 2 — один LLM-проход по оставшимся кривым регистрам (документ НЕ передаём)
            if final_validation.error_count:
                from register_validator import collect_error_registers, format_validation_errors

                yield sse_progress(
                    "autofix", "Автоисправление: AI правит некорректные регистры...",
                    request_id=request_id,
                )
                error_positions, error_registers = collect_error_registers(final_validation, registers)
                error_desc = format_validation_errors(final_validation, registers)
                # Ждём через keepalive-цикл: без событий в потоке nginx рвёт SSE
                # по proxy_read_timeout и уже готовый анализ теряется.
                fix_task = asyncio.create_task(_fix_registers_core(
                    client, effective_model, error_registers, error_desc,
                    all_registers=registers, error_positions=error_positions,
                    timeout=effective_timeout, max_tokens=effective_max_tokens or 16384,
                    legacy_max_tokens=effective_legacy, temperature=effective_temperature,
                    request_id=request_id or "", is_custom_llm=is_custom_llm,
                    error_endpoint="analyze_document",
                ))
                try:
                    async for ev in _await_batch_with_progress(
                        fix_task, {}, request_id=request_id, file_names="",
                        soft_timeout=soft_timeout, stage="autofix",
                        label="Автоисправление: AI правит некорректные регистры",
                        slow_stage=False,
                    ):
                        yield ev
                finally:
                    if not fix_task.done():
                        fix_task.cancel()
                        logger.info("[%s] Клиент ушёл, автофикс отменён", request_id)
                try:
                    registers = fix_task.result()
                    llm_fix_applied = True
                    yield sse_progress("autofix", "Автоисправление: повторная проверка...", request_id=request_id)
                    final_validation = _validate_regs(registers)
                except Exception as fix_exc:  # noqa: BLE001 — фолбек на ручную кнопку
                    logger.warning(
                        "[%s] Автофикс (LLM) не удался, остаток ошибок под ручную кнопку: %s",
                        request_id, fix_exc,
                    )

            if final_validation.error_count == 0:
                analysis_metrics["autofix_cleared"] += 1
            logger.info(
                "[%s] Автофикс: было %d → стало %d ошибок (детерм. %d, ai=%s)",
                request_id, errors_before, final_validation.error_count,
                det_fixed, llm_fix_applied,
            )
        elif final_validation.warning_count:
            logger.info("[%s] Валидация: 0 ошибок, %d предупреждений", request_id, final_validation.warning_count)

        # --- Этап 6: формирование ответа ---
        response = AnalyzeResponse(
            device_info=device_info,
            registers=registers,
        )

        yield sse_result(response, request_id=request_id)
        yield sse_done(request_id=request_id)
        logger.info(
            "[%s] Анализ завершён: %d регистров, остаток ошибок: %d",
            request_id, len(registers), final_validation.error_count,
        )

    except Exception:
        # Текст исключения наружу не отдаём — сюда доходят и сбои обращения к LLM
        logger.exception("Ошибка при анализе документа")
        yield sse_user_error(UserError("serverError.internalAnalyze"), request_id=request_id)


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
    *,
    error_endpoint: str = "analyze_document",
    error_request_id: str = "",
    error_model: str = "",
    is_custom_llm: bool = False,
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
        raw_response, _usage = await call_llm(
            client, model, system_prompt, content, timeout, max_tokens, legacy_max_tokens, temperature,
        )
    except Exception as e:
        # Уведомление и метрики (только для серверного LLM)
        await report_llm_api_error(
            e, endpoint=error_endpoint, request_id=error_request_id,
            model=error_model, is_custom_llm=is_custom_llm,
        )
        raise LLMApiError.from_provider(e) from e

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
            raw_data = extract_json_from_response(raw_response)
            result = _parse_registers(raw_data)

            # --- Валидация: проверяем качество ответа ---
            from prompts import get_validation_retry_prompt
            from register_validator import (
                format_validation_errors,
                validate_registers,
            )

            device_info, registers, auto_fixed = result
            if registers:
                validation = validate_registers(registers)
                error_rate = validation.error_count / len(registers)
                if error_rate > 0.3:
                    # Слишком много ошибок — семантический retry
                    reason = (
                        f"Валидация: {validation.error_count} ошибок в "
                        f"{len(registers)} регистрах ({error_rate:.0%})"
                    )
                    logger.warning(
                        "Высокий процент ошибок (%.0f%%, %d из %d), семантический retry",
                        error_rate * 100, validation.error_count, len(registers),
                    )
                    error_desc = format_validation_errors(validation, registers)
                    # Переходим к retry ниже
                else:
                    if auto_fixed:
                        logger.info("Авто-исправлено %d полей", auto_fixed)
                    if validation.error_count:
                        logger.info(
                            "Валидация: %d ошибок, %d предупреждений (ниже порога retry)",
                            validation.error_count, validation.warning_count,
                        )
                    return result
            else:
                return result

        except (json.JSONDecodeError, KeyError, ValueError) as e:
            reason = f"Ошибка парсинга JSON: {e}"
            error_desc = None
            logger.warning("Ошибка парсинга JSON ответа LLM, повторная попытка: %s", e)

    # Уведомляем вызывающий код о ретрае
    status["attempt"] = 2
    status["retrying"] = True
    status["retry_reason"] = reason

    # Повторная попытка: семантический retry (с ошибками) или упрощённый промпт
    try:
        if error_desc:
            # Семантический retry — отправляем описание ошибок валидации
            retry_content = content + [
                {"type": "text", "text": get_validation_retry_prompt(error_desc)},
            ]
        else:
            # Простой retry — ошибка парсинга JSON
            retry_content = content + [
                {"type": "text", "text": get_retry_prompt()},
            ]
        raw_response, _usage = await call_llm(
            client, model, system_prompt, retry_content, timeout, max_tokens, legacy_max_tokens, temperature,
        )
    except Exception as e:
        status["failed"] = True
        await report_llm_api_error(
            e, endpoint=error_endpoint, request_id=error_request_id,
            model=error_model, is_custom_llm=is_custom_llm,
        )
        raise LLMApiError.from_provider(e) from e

    # Проверяем пустой ответ повторной попытки
    if not raw_response or not raw_response.strip():
        logger.error("Повторная попытка тоже вернула пустой ответ")
        status["failed"] = True
        return "(пустой ответ LLM — обе попытки)"

    try:
        raw_data = extract_json_from_response(raw_response)
        return _parse_registers(raw_data)
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        logger.error("Повторная попытка парсинга JSON тоже не удалась: %s", e)
        status["failed"] = True
        # Возвращаем фрагмент ответа LLM для диагностики
        snippet = raw_response[:300] if raw_response else "(пустой ответ)"
        return snippet


# ---------------------------------------------------------------------------
# Исправление регистров через AI (ядро + SSE-обёртка кнопки, + автофикс анализа)
# ---------------------------------------------------------------------------

async def _fix_registers_core(
    client: AsyncOpenAI,
    model: str,
    registers: list[Register],
    error_descriptions: str,
    *,
    all_registers: list[Register] | None = None,
    error_positions: list[int] | None = None,
    timeout: int = 600,
    max_tokens: int = 16384,
    legacy_max_tokens: bool = False,
    temperature: float | None = None,
    request_id: str = "",
    is_custom_llm: bool = False,
    error_endpoint: str = "fix_registers",
) -> list[Register]:
    """Ядро исправления: шлёт в LLM ТОЛЬКО регистры с ошибками, вмёрдживает обратно.

    Документ в контекст НЕ передаётся — фикс правит формат/диапазон/enum кривых
    регистров, но не добирает пропущенные. Общий код для кнопки «Исправить через AI»
    и автофикса после анализа.

    Returns:
        Полный список регистров с вмёрженными исправлениями, если переданы `all_registers`
        и `error_positions`, иначе только исправленное подмножество.

    Raises:
        LLMApiError: ошибка API, пустой ответ или LLM не вернул регистров.
    """
    from prompts import get_fix_registers_prompt

    # Сериализуем ТОЛЬКО регистры с ошибками. Временный уникальный id __fix_<i>:
    # настоящие id в шаблонах не уникальны (condition-gated пары), merge-back идёт
    # по позиции + этому тегу (см. _merge_fixed_registers).
    subset_payload = []
    for i, r in enumerate(registers):
        d = r.model_dump(exclude_none=True)
        d["id"] = f"__fix_{i}"
        subset_payload.append(d)
    registers_json = json.dumps(
        {"device_info": {"name": "device", "id": "device"}, "registers": subset_payload},
        ensure_ascii=False, indent=2,
    )

    prompt = get_fix_registers_prompt(registers_json, error_descriptions)
    content = [{"type": "text", "text": prompt}]

    try:
        raw_response, _usage = await call_llm(
            client, model, "You are a Modbus device template validator.",
            content, timeout, max_tokens, legacy_max_tokens, temperature,
        )
    except Exception as api_exc:
        await report_llm_api_error(
            api_exc, endpoint=error_endpoint, request_id=request_id,
            model=model, is_custom_llm=is_custom_llm,
        )
        raise LLMApiError.from_provider(api_exc) from api_exc

    if not raw_response or not raw_response.strip():
        raise LLMApiError("serverError.llmEmptyResponse")

    raw_data = extract_json_from_response(raw_response)
    # preserve_id=True — сохраняем временный id, чтобы вмёрдживать по нему.
    _device_info, fixed_registers, auto_fixed = _parse_registers(raw_data, preserve_id=True)

    if not fixed_registers:
        raise LLMApiError("serverError.llmNoRegisters")

    if all_registers is not None and error_positions is not None:
        fixed_registers = _merge_fixed_registers(all_registers, fixed_registers, error_positions)

    logger.info(
        "[%s] Fix-core: %d регистров с ошибками → %d в ответе, %d авто-исправлений",
        request_id, len(registers), len(fixed_registers), auto_fixed,
    )
    return fixed_registers


async def fix_registers(
    registers: list[Register],
    error_descriptions: str,
    *,
    all_registers: list[Register] | None = None,
    error_positions: list[int] | None = None,
    effective_url: str,
    effective_key: str | None,
    effective_model: str,
    effective_timeout: int = 600,
    max_tokens: int = 16384,
    legacy_max_tokens: bool = False,
    temperature: float | None = None,
    proxy: str = "",
    request_id: str = "",
    is_custom_llm: bool = False,
) -> AsyncGenerator[str, None]:
    """SSE-генератор: отправляет регистры с ошибками в LLM для исправления.

    В LLM уходят только `registers` (регистры с ошибками) — не весь шаблон, иначе
    на крупных устройствах запрос виснет и вывод обрезается по лимиту токенов.
    Если задан `all_registers` (полный список), исправленное подмножество
    вмёрживается обратно по позициям и возвращается полный шаблон.

    Yields SSE-события: progress, result, done, error.
    """
    from register_validator import validate_registers as _validate_regs

    try:
        # Нет регистров с ошибками — возвращаем шаблон как есть, без вызова LLM.
        if not registers:
            response = AnalyzeResponse(
                device_info=DeviceInfo(name="device", id="device"),
                registers=all_registers or [],
            )
            yield sse_result(response, request_id=request_id)
            yield sse_done(request_id=request_id)
            return

        http_client = get_llm_http_client(proxy, is_custom=is_custom_llm)
        client = AsyncOpenAI(
            base_url=effective_url,
            api_key=effective_key or "no-key-provided",
            http_client=http_client,
            max_retries=2,
        )

        yield sse_progress("analyzing", "LLM исправляет ошибки...", request_id=request_id)

        # Ждём через keepalive-цикл: молчание в потоке дольше proxy_read_timeout
        # nginx считает обрывом, и пользователь теряет исправление.
        fix_task = asyncio.create_task(_fix_registers_core(
            client, effective_model, registers, error_descriptions,
            all_registers=all_registers, error_positions=error_positions,
            timeout=effective_timeout, max_tokens=max_tokens,
            legacy_max_tokens=legacy_max_tokens, temperature=temperature,
            request_id=request_id, is_custom_llm=is_custom_llm,
            error_endpoint="fix_registers",
        ))
        try:
            async for ev in _await_batch_with_progress(
                fix_task, {}, request_id=request_id, file_names="",
                soft_timeout=0, stage="analyzing",
                label="LLM исправляет ошибки", slow_stage=False,
            ):
                yield ev
        finally:
            if not fix_task.done():
                fix_task.cancel()
                logger.info("[%s] Клиент ушёл, исправление отменено", request_id)
        try:
            fixed_registers = fix_task.result()
        except LLMApiError as e:
            log_llm_failure(
                e.key, e.raw, request_id=request_id, action="Сбой исправления регистров через LLM",
            )
            yield sse_user_error(
                UserError("serverError.fixFailed", reasonKey=e.key), request_id=request_id,
            )
            return

        # Валидация результата
        yield sse_progress("validating", "Проверка исправленных регистров...", request_id=request_id)
        validation = _validate_regs(fixed_registers)
        logger.info(
            "[%s] Fix-registers: %d регистров, %d ошибок, %d предупреждений",
            request_id, len(fixed_registers), validation.error_count, validation.warning_count,
        )

        response = AnalyzeResponse(
            device_info=DeviceInfo(name="device", id="device"),
            registers=fixed_registers,
        )
        yield sse_result(response, request_id=request_id)
        yield sse_done(request_id=request_id)

    except Exception:
        logger.exception("Ошибка при исправлении регистров через AI")
        yield sse_user_error(UserError("serverError.internalFix"), request_id=request_id)
