#!/usr/bin/env python3
"""Prompt regression tests — ручные тесты для LLM-промпта.

Прогоняет набор тест-кейсов (маленькие таблички регистров) через реальный LLM
и сравнивает результат с ожиданиями из expectations.yaml.

Запуск:
    docker compose exec backend python tests/prompt_regression/run.py

Требует настроенного LLM API (LLM_API_URL, LLM_API_KEY, LLM_MODEL в .env).
НЕ входит в CI-пайплайн — запускается вручную при правках промпта.
"""

import asyncio
import json
import sys
from pathlib import Path

# Добавляем корень бэкенда в sys.path (для запуска из любой директории)
_BACKEND_ROOT = str(Path(__file__).resolve().parent.parent.parent)
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

import yaml
from openai import AsyncOpenAI

from config import Settings
from llm_service import _call_llm, _extract_json_from_response, _parse_registers
from prompts import get_analyze_prompt

CASES_DIR = Path(__file__).parent / "cases"
EXPECTATIONS_FILE = Path(__file__).parent / "expectations.yaml"

# ANSI-цвета для терминала
_GREEN = "\033[92m"
_RED = "\033[91m"
_YELLOW = "\033[93m"
_BOLD = "\033[1m"
_RESET = "\033[0m"


def load_expectations() -> dict:
    """Загружает ожидания из expectations.yaml."""
    with open(EXPECTATIONS_FILE) as f:
        return yaml.safe_load(f)


def load_cases() -> list[tuple[str, str]]:
    """Загружает тест-кейсы из директории cases/."""
    cases = []
    for path in sorted(CASES_DIR.glob("*.txt")):
        case_id = path.stem
        content = path.read_text()
        cases.append((case_id, content))
    return cases


def check_register(actual_regs, expected_reg) -> tuple[bool, str]:
    """Проверяет один ожидаемый регистр в списке фактических.

    Поиск по ключу (address, reg_type). Затем проверяет channel_type,
    has_enum, format если они указаны в ожиданиях.

    Returns:
        (True, "OK") если всё совпало, (False, описание_ошибки) если нет.
    """
    addr = expected_reg["address"]
    reg_type = expected_reg["reg_type"]

    # Ищем по (address, reg_type)
    found = None
    for reg in actual_regs:
        reg_addr = reg.address
        # Сравниваем с учётом типов (int vs str для bitwise адресов)
        if str(reg_addr) == str(addr) and reg.reg_type == reg_type:
            found = reg
            break

    if not found:
        return False, f"регистр не найден в ответе LLM"

    errors = []

    # Проверяем channel_type
    if "channel_type" in expected_reg:
        if found.channel_type != expected_reg["channel_type"]:
            errors.append(
                f"channel_type: ожидали {expected_reg['channel_type']!r}, "
                f"получили {found.channel_type!r}"
            )

    # Проверяем has_enum
    if "has_enum" in expected_reg:
        actual_has_enum = bool(found.enum or found.enum_entries)
        if actual_has_enum != expected_reg["has_enum"]:
            errors.append(
                f"has_enum: ожидали {expected_reg['has_enum']}, "
                f"получили {actual_has_enum}"
            )

    # Проверяем format
    if "format" in expected_reg:
        if found.format != expected_reg["format"]:
            errors.append(
                f"format: ожидали {expected_reg['format']!r}, "
                f"получили {found.format!r}"
            )

    if errors:
        return False, "; ".join(errors)
    return True, "OK"


async def run_case(
    client: AsyncOpenAI,
    model: str,
    system_prompt: str,
    case_id: str,
    case_text: str,
    expected: dict,
    timeout: int,
    max_tokens: int,
    legacy_max_tokens: bool,
    temperature: float | None,
) -> tuple[int, int]:
    """Прогоняет один тест-кейс. Возвращает (passed, failed)."""
    print(f"\n{'='*60}")
    print(f"  {_BOLD}Кейс: {case_id}{_RESET}")
    print(f"{'='*60}")

    content = [{"type": "text", "text": case_text}]

    try:
        raw_response, _usage = await _call_llm(
            client, model, system_prompt, content,
            timeout, max_tokens, legacy_max_tokens, temperature,
        )
    except Exception as e:
        print(f"  {_RED}ОШИБКА LLM API: {e}{_RESET}")
        return 0, len(expected.get("registers", []))

    if not raw_response or not raw_response.strip():
        print(f"  {_RED}ОШИБКА: пустой ответ от LLM{_RESET}")
        return 0, len(expected.get("registers", []))

    try:
        raw_data = _extract_json_from_response(raw_response)
        _device_info, registers = _parse_registers(raw_data)
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        print(f"  {_RED}ОШИБКА парсинга: {e}{_RESET}")
        snippet = raw_response[:300] if raw_response else "(пустой ответ)"
        print(f"  Ответ LLM (фрагмент): {snippet}")
        return 0, len(expected.get("registers", []))

    # Показываем что получили от LLM
    print(f"  Получено регистров: {len(registers)}")
    for reg in registers:
        has_enum = bool(reg.enum or reg.enum_entries)
        print(
            f"    addr={reg.address}, reg_type={reg.reg_type}, "
            f"channel_type={reg.channel_type}, format={reg.format}, "
            f"has_enum={has_enum}"
        )

    # Проверяем ожидания
    print()
    passed = 0
    failed = 0

    for exp_reg in expected.get("registers", []):
        ok, msg = check_register(registers, exp_reg)
        addr = exp_reg["address"]
        reg_type = exp_reg["reg_type"]
        label = f"addr={addr}, reg_type={reg_type}"

        if ok:
            print(f"  {_GREEN}PASS{_RESET}  {label}")
            passed += 1
        else:
            print(f"  {_RED}FAIL{_RESET}  {label}: {msg}")
            failed += 1

    return passed, failed


async def main():
    """Точка входа: загружает настройки, кейсы, прогоняет через LLM."""
    settings = Settings()

    if not settings.LLM_API_URL:
        print(
            f"{_RED}ОШИБКА: LLM_API_URL не задан.{_RESET}\n"
            "Установите переменные окружения или .env файл."
        )
        sys.exit(1)

    print(f"{_BOLD}Prompt Regression Tests{_RESET}")
    print(f"LLM API: {settings.LLM_API_URL}")
    print(f"Модель:  {settings.LLM_MODEL}")

    # Загружаем кейсы и ожидания
    expectations = load_expectations()
    cases = load_cases()

    if not cases:
        print(f"{_RED}Нет тест-кейсов в директории cases/{_RESET}")
        sys.exit(1)

    print(f"Кейсов:  {len(cases)}")

    # Готовим LLM-клиент
    http_client = None
    if settings.LLM_PROXY:
        import httpx
        http_client = httpx.AsyncClient(proxy=settings.LLM_PROXY)

    client = AsyncOpenAI(
        base_url=settings.LLM_API_URL,
        api_key=settings.LLM_API_KEY or "no-key-provided",
        http_client=http_client,
        max_retries=2,
    )

    system_prompt = get_analyze_prompt("full")

    total_passed = 0
    total_failed = 0
    skipped = 0

    for case_id, case_text in cases:
        if case_id not in expectations:
            print(f"\n{_YELLOW}ПРОПУСК: {case_id} — нет ожиданий в expectations.yaml{_RESET}")
            skipped += 1
            continue

        passed, failed = await run_case(
            client=client,
            model=settings.LLM_MODEL,
            system_prompt=system_prompt,
            case_id=case_id,
            case_text=case_text,
            expected=expectations[case_id],
            timeout=settings.LLM_TIMEOUT,
            max_tokens=settings.LLM_MAX_TOKENS,
            legacy_max_tokens=settings.LLM_LEGACY_MAX_TOKENS,
            temperature=settings.LLM_TEMPERATURE,
        )

        total_passed += passed
        total_failed += failed

    # Итог
    print(f"\n{'='*60}")
    color = _GREEN if total_failed == 0 else _RED
    print(f"  {_BOLD}ИТОГО: {color}{total_passed} PASS, {total_failed} FAIL{_RESET}", end="")
    if skipped:
        print(f", {_YELLOW}{skipped} SKIP{_RESET}", end="")
    print()
    print(f"{'='*60}")

    sys.exit(1 if total_failed > 0 else 0)


if __name__ == "__main__":
    asyncio.run(main())
