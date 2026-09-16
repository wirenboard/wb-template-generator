"""Тесты поля `revision` в `/api/status`.

Зачем отдельный тест: по этому полю smoke-проверка конвейера сверяет, что в проде
работает именно выкаченный коммит (`EXPECT_SHA` ↔ `revision`). Если поле пропадёт,
переименуется или начнёт возвращать пустоту, smoke будет валить каждый прод-выкат
и запускать авто-откат исправной версии — то есть цена регресса тут выше обычной.
"""

import sys
from pathlib import Path

# Добавляем backend/ в sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

import main  # noqa: E402

SHA = "0123456789abcdef0123456789abcdef01234567"


def test_get_revision_returns_baked_sha(monkeypatch):
    """git-SHA запекается в образ как ENV GIT_SHA при сборке в CI."""
    monkeypatch.setenv("GIT_SHA", SHA)
    assert main.get_revision() == SHA


def test_get_revision_defaults_to_unknown(monkeypatch):
    """Локальный запуск без сборки в CI: поле есть, но честно говорит «unknown»."""
    monkeypatch.delenv("GIT_SHA", raising=False)
    assert main.get_revision() == "unknown"


async def test_status_exposes_revision(monkeypatch):
    """Контракт эндпоинта: smoke парсит именно `revision` из `/api/status`."""
    monkeypatch.setenv("GIT_SHA", SHA)
    payload = await main.status()
    assert payload["revision"] == SHA
    assert "version" in payload
