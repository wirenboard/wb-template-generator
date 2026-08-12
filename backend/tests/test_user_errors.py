"""Контракт локализованных ошибок: ключ, параметры и русский фолбек.

Интерфейс говорит на четырёх языках, поэтому пользовательская ошибка несёт
`message_key` + `message_params`, а русский текст остаётся в `detail` — для
curl, интеграций и лога.
"""

import json
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
LOCALES = ("ru", "en", "kk", "it")


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
    """Каталог бэкенда и словарь интерфейса описывают одни и те же ключи.

    Каждая локаль проверяется отдельно, а не объединение: по объединению ключ,
    заведённый только в русской, выглядел бы переведённым во всех четырёх.
    """

    @staticmethod
    def _blocks() -> dict[str, str]:
        """Текст словаря, порезанный по локалям."""
        text = TRANSLATIONS.read_text(encoding="utf-8")
        starts = sorted((text.index(f"\n  {loc}: {{"), loc) for loc in LOCALES)
        bounds = [pos for pos, _ in starts] + [len(text)]
        return {loc: text[bounds[i]:bounds[i + 1]] for i, (_, loc) in enumerate(starts)}

    @staticmethod
    def _keys(block: str) -> set[str]:
        return set(re.findall(r"'((?:serverError|llmError)\.[A-Za-z_]+)':", block))

    def test_every_locale_has_every_backend_key(self):
        """Иначе интерфейс на этом языке покажет сырой ключ вместо фразы."""
        missing = {
            loc: sorted(set(ALL_KEYS) - self._keys(block))
            for loc, block in self._blocks().items()
            if set(ALL_KEYS) - self._keys(block)
        }

        assert missing == {}

    def test_no_orphan_keys_in_any_locale(self):
        """Ключ без источника на бэкенде — мёртвый перевод."""
        orphans = {
            loc: sorted(self._keys(block) - set(ALL_KEYS))
            for loc, block in self._blocks().items()
            if self._keys(block) - set(ALL_KEYS)
        }

        assert orphans == {}

    def test_placeholders_match(self):
        """Плейсхолдеры совпадают во всех локалях: иначе останется «{max}»."""
        mismatches = []

        for loc, block in self._blocks().items():
            for key in ALL_KEYS:
                match = re.search(rf"'{re.escape(key)}': (['\"])(.*?)\1,\n", block, re.DOTALL)
                assert match, f"ключ {key} не найден в локали {loc}"
                frontend_params = set(re.findall(r"\{(\w+)\}", match.group(2)))
                backend_params = set(re.findall(r"\{(\w+)\}", render.__globals__["_TEXTS"][key]))
                if frontend_params != backend_params:
                    mismatches.append(
                        f"{loc}/{key}: бэкенд {backend_params}, фронтенд {frontend_params}"
                    )

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


class TestAnalyzeEndpointCarriesKeys:
    """HTTP-отказы `/api/analyze` несут ключ.

    Тест смотрит на маршрут, а не на хелпер: если эндпоинт перестанет класть
    ключ, каталог и словари интерфейса останутся согласованными, и остальные
    тесты этого не заметят.
    """

    @pytest.fixture
    def client(self, monkeypatch):
        # Здесь интересны отказы по самим файлам, поэтому адрес не проверяем
        async def _skip_url_check(url, allow_private=False):
            return None

        monkeypatch.setattr(main, "ensure_public_llm_url", _skip_url_check)
        # Бакет лимитера общий на процесс — чистим с двух сторон, иначе
        # запросы соседних тестов мешают проверке 429 и наоборот.
        main._rate_limit_store.clear()
        yield TestClient(main.app)
        main._rate_limit_store.clear()

    @staticmethod
    def _files(name: str, data: bytes = b"%PDF-1.4 stub"):
        return [("files", (name, data, "application/octet-stream"))]

    # Свой адрес LLM снимает проверку «LLM не настроен», сети при этом не будет —
    # отказ приходит на разборе файлов.
    _CUSTOM_LLM = {"llm_api_url": "http://llm.invalid/v1"}

    def test_unsupported_format(self, client):
        resp = client.post("/api/analyze", files=self._files("doc.txt"), data=self._CUSTOM_LLM)
        body = resp.json()

        assert resp.status_code == 400
        assert body["message_key"] == "serverError.unsupportedFormat"
        assert body["message_params"]["file"] == "doc.txt"

    def test_file_too_large(self, client):
        settings = main.get_settings()
        oversized = b"0" * (settings.MAX_FILE_SIZE_MB * 1024 * 1024 + 1024)

        resp = client.post(
            "/api/analyze", files=self._files("doc.pdf", oversized), data=self._CUSTOM_LLM,
        )
        body = resp.json()

        assert resp.status_code == 413
        assert body["message_key"] == "serverError.fileTooLarge"
        assert body["message_params"]["max"] == settings.MAX_FILE_SIZE_MB

    def test_llm_not_configured(self, client, monkeypatch):
        """Без своего адреса и без серверного LLM — 503 с ключом."""
        monkeypatch.setattr(main.get_settings(), "LLM_API_URL", "")

        resp = client.post("/api/analyze", files=self._files("doc.pdf"))
        body = resp.json()

        assert resp.status_code == 503
        assert body["message_key"] == "serverError.llmNotConfigured"

    def test_rate_limit(self, client):
        settings = main.get_settings()

        for _ in range(settings.RATE_LIMIT_REQUESTS):
            client.post("/api/analyze", files=self._files("doc.txt"), data=self._CUSTOM_LLM)
        resp = client.post("/api/analyze", files=self._files("doc.txt"), data=self._CUSTOM_LLM)
        body = resp.json()

        assert resp.status_code == 429
        assert body["message_key"] == "serverError.rateLimit"
        assert body["message_params"] == {
            "requests": settings.RATE_LIMIT_REQUESTS,
            "window": settings.RATE_LIMIT_WINDOW,
        }


class TestSseCarriesKeys:
    """SSE-события ошибок несут ключ так же, как HTTP-ответы.

    Половина ошибок анализа уходит потоком, а не ответом, и до локализации
    интерфейс показывал их русский текст независимо от выбранного языка.
    """

    def test_sse_user_error_carries_key_and_params(self):
        from sse import sse_user_error

        event = sse_user_error(
            UserError("serverError.rateLimit", requests=10, window=60), request_id="r-1",
        )

        assert event.startswith("event: error")
        payload = json.loads(event.split("data: ", 1)[1].strip())
        assert payload["message_key"] == "serverError.rateLimit"
        assert payload["message_params"] == {"requests": 10, "window": 60}
        assert payload["request_id"] == "r-1"
        # Русский текст остаётся в message — фолбек и запись для лога
        assert "10" in payload["message"]

    def test_plain_sse_error_has_no_key(self):
        """Строковая форма осталась для ошибок вне каталога — ключа быть не должно."""
        from sse import sse_error

        payload = json.loads(sse_error("что-то пошло не так").split("data: ", 1)[1].strip())

        assert "message_key" not in payload
