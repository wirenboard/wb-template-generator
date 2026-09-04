"""Отказы по потолкам разбора внутри анализа доходят до клиента событием error.

Здесь `analyze_document` превращает отказ разбора в SSE-событие, подставляет имя файла
и останавливает анализ. Файлы настоящие, конвертация не подменяется.
"""

import io
import json
import sys
import zipfile
from pathlib import Path

import pytest
from openpyxl import Workbook
from PIL import Image

# Добавляем backend/ в sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

import file_converter  # noqa: E402, I001
from config import Settings  # noqa: E402
from llm_service import analyze_document  # noqa: E402
from prompts import MAX_RENDERED_PROMPT_CHARS  # noqa: E402


def _settings() -> Settings:
    return Settings(
        LLM_API_URL="https://api.server.example/v1",
        LLM_API_KEY="sk-server",
        LLM_MODEL="gpt-4o",
        LLM_TIMEOUT=60,
        LLM_SOFT_TIMEOUT=30,
        LLM_PROXY="",
    )


def _xlsx(rows: int = 5) -> bytes:
    wb = Workbook(write_only=True)
    ws = wb.create_sheet()
    for _ in range(rows):
        ws.append(["value"] * 3)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _png(width: int, height: int) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), (7, 7, 7)).save(buf, format="PNG")
    return buf.getvalue()


async def _error_event(files: list[tuple[str, bytes]]) -> dict:
    """Прогоняет анализ и возвращает данные первого события error."""
    events = [
        event async for event in analyze_document(
            files=files, template_type="full", settings=_settings(), request_id="req-1",
        )
    ]
    for event in events:
        if event.startswith("event: error"):
            return json.loads(event.split("data: ", 1)[1].strip())
    raise AssertionError(f"события error нет, пришло: {[e[:40] for e in events]}")


class TestExcelRejection:
    """Таблица за потолком прекращает анализ понятной ошибкой."""

    async def test_zip_bomb_rejected_with_filename(self):
        """Имя файла подставляет анализ, в разборе его нет."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("xl/worksheets/sheet1.xml", b"0" * (12 * 1024 * 1024))

        data = await _error_event([("registers.xlsx", buf.getvalue())])

        assert data["message_key"] == "serverError.excelTooBig"
        assert data["message_params"] == {"file": "registers.xlsx"}
        assert "registers.xlsx" in data["message"]

    async def test_not_a_zip_explained(self):
        """Файл с расширением .xlsx, который не архив, объясняется, а не падает."""
        data = await _error_event([("table.xlsx", b"\xd0\xcf\x11\xe0" + b"\x00" * 512)])

        assert data["message_key"] == "serverError.excelUnreadable"

    async def test_analysis_stops_on_bad_file(self):
        """Остальные файлы не разбираются — шаблон по части документа хуже отказа."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("xl/worksheets/sheet1.xml", b"0" * (12 * 1024 * 1024))

        events = [
            event async for event in analyze_document(
                files=[("bad.xlsx", buf.getvalue()), ("good.xlsx", _xlsx())],
                template_type="full", settings=_settings(), request_id="req-1",
            )
        ]

        assert "good.xlsx" not in "".join(events)
        assert sum(e.startswith("event: error") for e in events) == 1


class TestImageRejection:
    """Картинка за потолком пикселей прекращает анализ до декодирования."""

    async def test_too_large_image_rejected(self, monkeypatch):
        # Потолок опускаем, чтобы не генерировать в тесте картинку на 25 Мпикс
        monkeypatch.setattr(file_converter, "MAX_IMAGE_PIXELS", 100_000)

        data = await _error_event([("scan.png", _png(500, 500))])

        assert data["message_key"] == "serverError.imageTooLarge"
        assert data["message_params"] == {"file": "scan.png", "width": 500, "height": 500}

    async def test_broken_image_rejected(self):
        """Битый файл прекращает анализ, а не пропускается молча."""
        data = await _error_event([("scan.png", b"not an image at all")])

        assert data["message_key"] == "serverError.brokenImage"
        assert data["message_params"] == {"file": "scan.png"}


class TestPromptRejection:
    """Шаблон промпта за потолком прекращает анализ до обращения к модели."""

    async def test_too_large_prompt_rejected(self):
        """Отказ приходит своим ключом, а не «внутренней ошибкой при анализе».

        Рендер стоит до создания клиента, поэтому ни сети, ни мока LLM тут не нужно.
        """
        events = [
            event async for event in analyze_document(
                files=[("scan.png", _png(10, 10))],
                template_type="full",
                settings=_settings(),
                custom_system_prompt="x" * (MAX_RENDERED_PROMPT_CHARS + 1),
                is_custom_llm=True,
                request_id="req-1",
            )
        ]
        errors = [e for e in events if e.startswith("event: error")]
        data = json.loads(errors[0].split("data: ", 1)[1].strip())

        assert data["message_key"] == "serverError.promptTooLarge"
        assert not [e for e in events if e.startswith("event: result")]


class TestNoUsableData:
    """Формат, который сервис не берёт, отсекается до обращения к модели."""

    async def test_unsupported_extension_gives_no_data(self):
        data = await _error_event([("readme.txt", b"nothing useful")])

        assert data["message_key"] == "serverError.noData"


@pytest.mark.parametrize("filename,payload", [
    ("registers.xlsx", b"\xd0\xcf\x11\xe0"),
    ("scan.png", b"not an image"),
])
async def test_rejection_carries_request_id(filename, payload):
    """Номер запроса нужен в событии, по нему ищут подробности в логе."""
    data = await _error_event([(filename, payload)])

    assert data["request_id"] == "req-1"
