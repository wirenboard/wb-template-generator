"""Конвертация загруженных файлов — изображения, PDF, Excel."""

import base64
import io

from openpyxl import load_workbook
from pdf2image import convert_from_bytes
from PIL import Image


def image_to_base64(img: Image.Image, max_size: int = 2048) -> str:
    """Конвертирует PIL.Image в base64-строку PNG.

    Уменьшает изображение если оно больше max_size по любой стороне,
    чтобы не превышать лимиты LLM на размер изображений.
    Не мутирует входной объект — работает с копией при необходимости.

    Args:
        img: исходное изображение.
        max_size: максимальный размер стороны в пикселях.

    Returns:
        Base64-строка PNG-изображения.
    """
    if img.width > max_size or img.height > max_size:
        img = img.copy()
        img.thumbnail((max_size, max_size), Image.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def pdf_to_images(pdf_bytes: bytes) -> list[Image.Image]:
    """Конвертирует PDF в список PIL.Image (по одному на страницу).

    Args:
        pdf_bytes: содержимое PDF-файла в байтах.

    Returns:
        Список изображений страниц PDF.
    """
    return convert_from_bytes(pdf_bytes, dpi=200)


def excel_to_text(excel_bytes: bytes) -> str:
    """Конвертирует Excel-файл в текстовое представление таблицы.

    Формирует читаемую таблицу с ячейками, разделёнными ``|``.

    Args:
        excel_bytes: содержимое Excel-файла в байтах.

    Returns:
        Текстовое представление всех листов Excel-файла.
    """
    wb = load_workbook(io.BytesIO(excel_bytes), read_only=True, data_only=True)
    parts: list[str] = []

    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            continue

        parts.append(f"=== Sheet: {sheet_name} ===")

        for row in rows:
            cells = [str(cell) if cell is not None else "" for cell in row]
            parts.append(" | ".join(cells))

        parts.append("")  # пустая строка между листами

    wb.close()
    return "\n".join(parts)


def is_image_file(filename: str) -> bool:
    """Проверяет, является ли файл изображением по расширению.

    Args:
        filename: имя файла.

    Returns:
        True если расширение соответствует изображению.
    """
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    return ext in ("png", "jpg", "jpeg", "webp", "bmp")


def is_pdf_file(filename: str) -> bool:
    """Проверяет, является ли файл PDF.

    Args:
        filename: имя файла.

    Returns:
        True если расширение ``.pdf``.
    """
    return filename.lower().endswith(".pdf")


def is_excel_file(filename: str) -> bool:
    """Проверяет, является ли файл Excel.

    Args:
        filename: имя файла.

    Returns:
        True если расширение ``.xlsx`` или ``.xls``.
    """
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    return ext in ("xlsx", "xls")
