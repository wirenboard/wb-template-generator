"""Статистика использования: запись событий, сводка /api/stats, хранение между перезапусками."""

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

import main
import usage_stats
from usage_stats import UsageStats, open_usage_stats, parse_client_id

A = "11111111-1111-4111-8111-111111111111"
B = "22222222-2222-4222-8222-222222222222"
TODAY = date(2026, 11, 3)

TEMPLATE = b'{"device_type": "X", "device": {"name": "X", "id": "x", "channels": []}}'


@pytest.fixture
def stats(tmp_path):
    s = UsageStats(str(tmp_path / "stats.sqlite3"), retention_days=365)
    yield s
    s.close()


@pytest.fixture
def client(stats, monkeypatch):
    """Клиент без lifespan, статистика пишется во временную базу."""
    monkeypatch.setattr(main, "_usage", stats)
    return TestClient(main.app)


def test_frontend_event_recorded(client, stats):
    """Событие фронта попадает в счётчик вместе с браузером."""
    r = client.post("/api/usage", json={"event": "download_json"}, headers={"X-Client-Id": A})

    assert r.status_code == 204
    assert stats.report(1)["events"] == {"download_json": {"count": 1, "clients": 1}}


def test_frontend_rejects_backend_event(client, stats):
    """Через /api/usage нельзя накрутить события, которые бэкенд учитывает сам."""
    r = client.post("/api/usage", json={"event": "analyze_server"}, headers={"X-Client-Id": A})

    assert r.status_code == 422
    assert stats.report(1)["events"] == {}


def test_backend_event_only_on_success(client, stats):
    """Импорт шаблона учитывается при успехе и не учитывается при отказе."""
    client.post("/api/import-template", files={"file": ("t.json", TEMPLATE)}, headers={"X-Client-Id": A})
    client.post("/api/import-template", files={"file": ("t.json", b"not json")}, headers={"X-Client-Id": A})

    assert stats.report(1)["events"]["import_template"]["count"] == 1


def test_analyze_split_by_llm(client, stats, monkeypatch):
    """Анализ делится на серверный ключ и свой LLM; отказ до запуска не учитывается."""
    async def _no_analysis(**kwargs):
        return
        yield

    async def _skip_url_check(*args):
        return None

    monkeypatch.setattr(main, "analyze_document", _no_analysis)
    monkeypatch.setattr(main, "ensure_public_llm_url", _skip_url_check)
    monkeypatch.setattr(main.get_settings(), "LLM_API_URL", "https://llm.example")
    main._rate_limit_store.clear()
    file = {"files": ("a.pdf", b"x")}

    client.post("/api/analyze", files=file, headers={"X-Client-Id": A})
    client.post("/api/analyze", files=file, data={"llm_api_url": "https://my.example"}, headers={"X-Client-Id": A})
    client.post("/api/analyze", files={"files": ("a.exe", b"x")}, headers={"X-Client-Id": A})
    main._rate_limit_store.clear()

    events = stats.report(1)["events"]
    assert events["analyze_server"]["count"] == 1, "отказ по формату файла засчитан как анализ"
    assert events["analyze_custom"]["count"] == 1


def test_invalid_client_id_not_unique(client, stats):
    """Битый идентификатор не создаёт браузер, но событие в итогах остаётся."""
    client.post("/api/usage", json={"event": "page_open"}, headers={"X-Client-Id": "<script>"})
    client.post("/api/usage", json={"event": "page_open"})

    report = stats.report(1)
    assert report["events"]["page_open"] == {"count": 2, "clients": 0}
    assert report["unique_clients"] == 0


def test_parse_client_id_canonical():
    """UUID приводится к одному виду, иначе один браузер посчитался бы дважды."""
    assert parse_client_id(A.upper()) == A
    assert parse_client_id("") == ""
    assert parse_client_id("x" * 100) == ""


def test_unique_clients_distinct_over_period(stats):
    """Браузер, заходивший три дня подряд, — один уникальный и один вернувшийся."""
    for d in range(3):
        stats.record("page_open", A, today=TODAY - timedelta(days=d))
    stats.record("page_open", B, today=TODAY)

    report = stats.report(7, today=TODAY)

    assert report["unique_clients"] == 2
    assert report["returning_clients"] == 1
    assert report["clients_by_day"][TODAY.isoformat()] == 2


def test_report_period_bounds(stats):
    """Дни раньше начала периода в сводку не попадают."""
    stats.record("translate", A, today=TODAY - timedelta(days=7))
    stats.record("translate", A, today=TODAY)

    assert stats.report(7, today=TODAY)["events"]["translate"]["count"] == 1


def test_funnel_and_top(stats):
    """Доведение до результата считает браузеры; в топ не входит открытие страницы."""
    for _ in range(3):
        stats.record("page_open", A, today=TODAY)
    stats.record("analyze_server", A, today=TODAY)
    stats.record("download_json", A, today=TODAY)
    stats.record("page_open", B, today=TODAY)
    stats.record("import_csv", B, today=TODAY)

    report = stats.report(1, today=TODAY)

    assert report["funnel"] == {"opened": 2, "started": 2, "downloaded": 1}
    assert report["top_clients_actions"] == [2, 1]


def test_data_survives_reopen(tmp_path):
    """Перезапуск сервиса — новое соединение с тем же файлом, данные на месте."""
    path = str(tmp_path / "stats.sqlite3")
    first = UsageStats(path, retention_days=365)
    first.record("download_jinja", A, today=TODAY)
    first.close()

    second = UsageStats(path, retention_days=365)
    try:
        assert second.report(1, today=TODAY)["events"]["download_jinja"]["count"] == 1
    finally:
        second.close()


def test_retention_purges_old_days(tmp_path):
    """На смене суток удаляются дни старше срока хранения."""
    s = UsageStats(str(tmp_path / "stats.sqlite3"), retention_days=3)
    try:
        s.record("export_csv", A, today=TODAY - timedelta(days=3))
        s.record("export_csv", A, today=TODAY)

        rows = s._conn.execute("SELECT day FROM usage").fetchall()
        assert rows == [(TODAY.isoformat(),)]
    finally:
        s.close()


def test_new_clients_capped_per_day(stats, monkeypatch):
    """Сверх потолка новых браузеров в сутки события пишутся без идентификатора."""
    monkeypatch.setattr(usage_stats, "MAX_CLIENTS_PER_DAY", 1)

    stats.record("page_open", A, today=TODAY)
    stats.record("page_open", B, today=TODAY)
    stats.record("page_open", A, today=TODAY)

    report = stats.report(1, today=TODAY)
    assert report["unique_clients"] == 1
    assert report["events"]["page_open"] == {"count": 3, "clients": 1}


def test_disabled_when_db_unavailable(tmp_path, monkeypatch):
    """База не открылась — запросы работают, /api/stats сообщает, что статистика выключена."""
    assert open_usage_stats("", 365) is None
    assert open_usage_stats(str(tmp_path / "нет" / "stats.sqlite3"), 365) is None

    monkeypatch.setattr(main, "_usage", None)
    client = TestClient(main.app)

    assert client.post("/api/usage", json={"event": "page_open"}).status_code == 204
    assert client.get("/api/stats").json() == {"enabled": False}


def test_stats_endpoint(client, stats):
    """Эндпоинт отдаёт сводку и не раскрывает идентификаторы браузеров."""
    client.post("/api/usage", json={"event": "page_open"}, headers={"X-Client-Id": A})

    body = client.get("/api/stats?days=7").json()

    assert body["enabled"] is True
    assert body["unique_clients"] == 1
    assert A not in str(body)


def test_translate_split_from_normalize(client, stats, monkeypatch):
    """Перевод на английский учитывается как нормализация, на другие языки — как перевод."""
    async def _fake_llm(*args, **kwargs):
        return '{"a": "b"}', None

    monkeypatch.setattr(main, "call_llm", _fake_llm)
    monkeypatch.setattr(main.get_settings(), "LLM_API_URL", "https://llm.example")
    body = {"strings": {"a": "x"}, "target_lang_name": "-"}

    client.post("/api/translate", json={**body, "target_lang": "en"}, headers={"X-Client-Id": A})
    client.post("/api/translate", json={**body, "target_lang": "ru"}, headers={"X-Client-Id": A})
    client.post("/api/translate", json={**body, "strings": {}, "target_lang": "ru"}, headers={"X-Client-Id": A})

    events = stats.report(1)["events"]
    assert events["normalize_en"]["count"] == 1
    assert events["translate"]["count"] == 1, "пустой набор строк засчитан как перевод"


def test_stats_days_validated_and_clamped(client):
    """Период не меньше суток и не длиннее срока хранения."""
    assert client.get("/api/stats?days=0").status_code == 422

    body = client.get("/api/stats?days=5000").json()

    span = date.fromisoformat(body["to"]) - date.fromisoformat(body["from"])
    assert span.days == main.get_settings().STATS_RETENTION_DAYS - 1


def test_write_failure_does_not_break_request(stats, caplog):
    """Сбой записи логируется один раз за серию и не роняет запрос."""
    stats._conn.close()

    stats.record("page_open", A, today=TODAY)
    stats.record("page_open", A, today=TODAY)

    assert caplog.text.count("Статистика использования не записана") == 1


def test_report_failure_disables_stats(stats):
    """Сбой чтения сводки — ответ «выключено», а не 500."""
    stats._read.close()

    assert stats.report(1, today=TODAY) == {"enabled": False}


def test_clients_cap_survives_reopen(tmp_path, monkeypatch):
    """Счёт новых браузеров за сутки восстанавливается после перезапуска."""
    monkeypatch.setattr(usage_stats, "MAX_CLIENTS_PER_DAY", 1)
    monkeypatch.setattr(usage_stats, "_today", lambda: TODAY)
    path = str(tmp_path / "stats.sqlite3")
    first = UsageStats(path, retention_days=365)
    first.record("page_open", A)
    first.close()

    second = UsageStats(path, retention_days=365)
    try:
        second.record("page_open", B)
        assert second.report(1)["unique_clients"] == 1
    finally:
        second.close()
