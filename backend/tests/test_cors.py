"""Политика CORS — пустой дефолт и запрет креденшелов.

Куки и сессии сервис не использует, а интерфейс ходит на относительные пути через тот же
origin, поэтому CORS ему не нужен. Настройка читается на импорте модуля, поэтому вариант
«origin задан» проверяется перезагрузкой модуля с восстановлением окружения.
"""

import importlib
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Добавляем backend/ в sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

import main  # noqa: E402, I001
from config import Settings, get_settings  # noqa: E402

FOREIGN = "https://evil.example"
ALLOWED = "https://app.example.com"


class TestDefaults:
    """Из коробки кросс-доменные запросы не разрешены никому."""

    def test_default_setting_is_empty(self):
        """Дефолт сменился с «*» на пустую строку."""
        assert Settings().CORS_ORIGINS == ""

    def test_foreign_origin_gets_no_allow_header(self):
        """Без заголовка браузер не отдаст ответ чужой странице."""
        resp = TestClient(main.app).get("/api/health", headers={"Origin": FOREIGN})

        assert resp.status_code == 200
        assert "access-control-allow-origin" not in resp.headers

    def test_foreign_origin_cannot_read_the_answer(self):
        """Чужой странице ответ не прочитать — нет ни allow-origin, ни allow-credentials.

        `access-control-expose-headers` middleware ставит и на чужой origin, но без
        allow-origin браузер ответ не отдаёт. Сам запрет креденшелов на разрешённом
        origin пиннит `TestConfiguredOrigin`, здесь заголовка нет по другой причине.
        """
        resp = TestClient(main.app).get("/api/health", headers={"Origin": FOREIGN})

        assert "access-control-allow-origin" not in resp.headers
        assert "access-control-allow-credentials" not in resp.headers

    def test_preflight_from_foreign_origin_not_allowed(self):
        resp = TestClient(main.app).options(
            "/api/build",
            headers={
                "Origin": FOREIGN,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )

        assert "access-control-allow-origin" not in resp.headers


class TestConfiguredOrigin:
    """Явно заданный origin работает — задаётся переменной окружения или в .env."""

    @pytest.fixture
    def reloaded_main(self, monkeypatch):
        """Перезагружает модуль с заданным CORS_ORIGINS и возвращает всё обратно."""
        monkeypatch.setenv("CORS_ORIGINS", ALLOWED)
        get_settings.cache_clear()
        reloaded = importlib.reload(main)
        yield reloaded
        monkeypatch.undo()
        get_settings.cache_clear()
        importlib.reload(main)

    def test_configured_origin_allowed(self, reloaded_main):
        resp = TestClient(reloaded_main.app).get("/api/health", headers={"Origin": ALLOWED})

        assert resp.headers["access-control-allow-origin"] == ALLOWED

    def test_other_origin_still_rejected(self, reloaded_main):
        resp = TestClient(reloaded_main.app).get("/api/health", headers={"Origin": FOREIGN})

        assert "access-control-allow-origin" not in resp.headers

    def test_credentials_still_not_allowed(self, reloaded_main):
        """Даже с разрешённым origin креденшелы остаются выключенными."""
        resp = TestClient(reloaded_main.app).get("/api/health", headers={"Origin": ALLOWED})

        assert "access-control-allow-credentials" not in resp.headers
