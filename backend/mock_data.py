"""Mock-данные для разработки — используются когда LLM_API_KEY == 'test'."""

import asyncio

from models import AnalyzeResponse, DeviceInfo, Register
from sse import sse_done, sse_progress, sse_result


def mock_registers() -> list[Register]:
    """Тестовые регистры SDM-230 для mock-ответа."""
    return [
        Register(
            address=0,
            name="Voltage",
            reg_type="input",
            format="float",
            scale=1,
            units="V",
            access="read",
            description="Line voltage",
            channel_type="value",
            group="power_meters",
            group_title="Power Meters",
            translations={"ru": {"name": "Напряжение"}},
        ),
        Register(
            address=6,
            name="Current",
            reg_type="input",
            format="float",
            scale=1,
            units="A",
            access="read",
            description="Line current",
            channel_type="value",
            group="power_meters",
            group_title="Power Meters",
            translations={"ru": {"name": "Ток"}},
        ),
        Register(
            address=12,
            name="Active Power",
            reg_type="input",
            format="float",
            scale=1,
            units="W",
            access="read",
            description="Active power",
            channel_type="value",
            group="power_meters",
            group_title="Power Meters",
            translations={"ru": {"name": "Активная мощность"}},
        ),
        Register(
            address=28,
            name="Baud Rate",
            reg_type="holding",
            format="u16",
            scale=1,
            access="readwrite",
            description="Serial port baud rate",
            channel_type="value",
            group="general",
            group_title="General",
            is_parameter=True,
            enum=[0, 1, 2, 5],
            enum_titles=["2400", "4800", "9600", "1200"],
            translations={
                "ru": {
                    "name": "Скорость обмена",
                    "description": "Скорость порта: 0=2400, 1=4800, 2=9600, 5=1200",
                }
            },
        ),
    ]


async def sse_analyze_mock(template_type: str):
    """Генератор SSE-событий для mock-ответа analyze.

    Имитирует процесс анализа с задержками для отладки фронтенда.

    Args:
        template_type: тип шаблона (не используется в mock, но сохраняет сигнатуру).

    Yields:
        SSE-строки с событиями прогресса, результата и завершения.
    """
    # Прогресс-события с задержкой
    progress_messages = [
        ("uploading", "Загрузка и распознавание файлов...", 1, 3),
        ("analyzing", "Извлечение регистров из документа...", 2, 3),
        ("merging", "Классификация и группировка регистров...", 3, 3),
    ]

    for stage, message, current, total in progress_messages:
        yield sse_progress(stage, message, current, total)
        await asyncio.sleep(0.5)

    # Результат — mock-данные SDM-230
    result = AnalyzeResponse(
        device_info=DeviceInfo(
            name="Eastron SDM-230",
            id="eastron-sdm230",
            device_group="power_meters",
        ),
        registers=mock_registers(),
    )

    yield sse_result(result)
    yield sse_done("Анализ завершён (mock)")


def use_mock(llm_api_url: str | None, settings_api_url: str) -> bool:
    """Определяет, нужно ли использовать mock вместо реального LLM.

    Mock используется если LLM_API_URL не задан — ни клиентом, ни в настройках.

    Args:
        llm_api_url: URL API от клиента (может быть None).
        settings_api_url: URL API из настроек приложения.

    Returns:
        True если нужно использовать mock.
    """
    # Если клиент передал свой URL — используем реальный LLM
    if llm_api_url:
        return False
    # Иначе проверяем серверный URL — mock если не задан
    return not settings_api_url
