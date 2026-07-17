"""Тесты сборки LLM-контента (assemble_llm_content).

Фиксируют контракт отправки файлов в модель: PDF → type:"file",
изображение → image_url, Excel-текст → text.
"""

from PIL import Image

from llm_service import assemble_llm_content


def test_empty_returns_empty_list():
    assert assemble_llm_content([], [], []) == []


def test_text_parts_joined_into_single_block():
    content = assemble_llm_content(["часть A", "часть B"], [], [])
    assert len(content) == 1
    assert content[0]["type"] == "text"
    assert content[0]["text"] == "часть A\n\nчасть B"


def test_pdf_sent_as_file_content_with_base64():
    content = assemble_llm_content([], [("map.pdf", b"%PDF-1.7 fake")], [])
    assert len(content) == 1
    block = content[0]
    assert block["type"] == "file"
    assert block["file"]["filename"] == "map.pdf"
    assert block["file"]["file_data"].startswith("data:application/pdf;base64,")


def test_image_sent_as_image_url_high_detail():
    img = Image.new("RGB", (10, 10), "white")
    content = assemble_llm_content([], [], [img])
    assert len(content) == 1
    block = content[0]
    assert block["type"] == "image_url"
    assert block["image_url"]["detail"] == "high"
    assert block["image_url"]["url"].startswith("data:image/png;base64,")


def test_order_is_text_then_files_then_images():
    img = Image.new("RGB", (4, 4), "black")
    content = assemble_llm_content(["t"], [("d.pdf", b"x")], [img])
    assert [b["type"] for b in content] == ["text", "file", "image_url"]
