"""Контракт локализованных ошибок: ключ, параметры и русский фолбек.

Интерфейс говорит на четырёх языках, поэтому пользовательская ошибка несёт
`message_key` + `message_params`, а русский текст остаётся в `detail` — для
curl, интеграций и лога.
"""

import re
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Добавляем backend/ в sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

import main  # noqa: E402, I001
from user_errors import ALL_KEYS, UserError, render  # noqa: E402

TRANSLATIONS = Path(__file__).parent.parent.parent / "frontend" / "src" / "i18n" / "translations.ts"


class TestCatalog:
    """Каталог самодостаточен: опечатка видна, payload несёт ключ и текст."""

    def test_unknown_key_rejected(self):
        """Опечатка в ключе видна сразу, а не превращается в пустой текст."""
        with pytest.raises(KeyError):
            UserError("error.noSuchThing")

    def test_payload_carries_key_params_and_text(self):
        err = UserError("serverError.importJinjaTooLarge", max=1024)

        payload = err.payload("req-1")

        assert payload["message_key"] == "serverError.importJinjaTooLarge"
        assert payload["message_params"] == {"max": 1024}
        assert "1024" in payload["detail"]
        assert payload["request_id"] == "req-1"


# В контейнере бэкенда лежит только /app, фронтенда там нет — эти проверки идут
# в CI и при локальном прогоне из репозитория, где рядом есть frontend/.
@pytest.mark.skipif(not TRANSLATIONS.exists(), reason="нет frontend/ рядом с backend/")
class TestTranslationsParity:
    """Каталог бэкенда и словарь интерфейса описывают одни и те же ключи."""

    @staticmethod
    def _frontend_keys() -> set[str]:
        text = TRANSLATIONS.read_text(encoding="utf-8")
        return set(re.findall(r"'((?:serverError|llmError)\.[A-Za-z_]+)':", text))

    def test_frontend_has_every_backend_key(self):
        """Иначе интерфейс покажет сырой ключ вместо фразы."""
        missing = sorted(set(ALL_KEYS) - self._frontend_keys())

        assert missing == []

    def test_no_orphan_keys_on_frontend(self):
        """Ключ без источника на бэкенде — мёртвый перевод."""
        orphans = sorted(self._frontend_keys() - set(ALL_KEYS))

        assert orphans == []

    def test_placeholders_match(self):
        """Плейсхолдеры совпадают: иначе в интерфейсе останется «{max}».

        Сверяем с русской локалью — она единственная, где текст обязан
        совпадать с бэкендом дословно.
        """
        text = TRANSLATIONS.read_text(encoding="utf-8")
        ru_block = text[: text.index("  en: {")]
        mismatches = []

        for key in ALL_KEYS:
            match = re.search(rf"'{re.escape(key)}': (['\"])(.*?)\1,\n", ru_block, re.DOTALL)
            assert match, f"ключ {key} не найден в русской локали"
            frontend_params = set(re.findall(r"\{(\w+)\}", match.group(2)))
            backend_params = set(re.findall(r"\{(\w+)\}", render.__globals__["_TEXTS"][key]))
            if frontend_params != backend_params:
                mismatches.append(f"{key}: бэкенд {backend_params}, фронтенд {frontend_params}")

        assert mismatches == []


class TestImportEndpointCarriesKeys:
    """Ответы `/api/import-template` несут ключ, а не только русский текст."""

    @pytest.fixture
    def client(self):
        return TestClient(main.app)

    def test_not_a_template(self, client):
        """400 вместо прежних 422, в теле ключ для интерфейса."""
        resp = client.post(
            "/api/import-template",
            files=[("file", ("t.json", b'{"name": "package.json"}', "application/json"))],
        )
        body = resp.json()

        assert resp.status_code == 400
        assert body["message_key"] == "serverError.importNotTemplate"

    def test_jinja_syntax_error_carries_line(self, client):
        """Ошибка в шаблоне доходит до автора: ключ, номер строки и текст jinja2."""
        resp = client.post(
            "/api/import-template",
            files=[("file", ("t.json.jinja", b'{% for i in range(3) %}{}', "application/json"))],
        )
        body = resp.json()

        assert resp.status_code == 400
        assert body["message_key"] == "serverError.importJinjaErrorLine"
        assert "endfor" in body["message_params"]["error"]

    def test_failure_hides_raw_exception(self, client):
        """Не-utf8 тело падает в decode → общий except → detail без текста ошибки."""
        resp = client.post(
            "/api/import-template",
            files=[("file", ("t.json", b"\xff\xfe\x00\x01", "application/octet-stream"))],
        )
        body = resp.json()

        assert resp.status_code == 422
        assert body["message_key"] == "serverError.importFailed"
        assert "codec" not in body["detail"]
