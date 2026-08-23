"""Счётчики обращений по маршрутам в /api/metrics.

Нужны, чтобы видеть, какими действиями пользуются в UI. Ключ счётчика берётся только
из списка известных маршрутов.
"""

import pytest
from fastapi.testclient import TestClient

import main


@pytest.fixture
def client():
    """Клиент без lifespan — очереди тестам не нужны, счётчики чистые."""
    main._endpoint_hits.clear()
    main._endpoint_errors.clear()
    yield TestClient(main.app)
    main._endpoint_hits.clear()
    main._endpoint_errors.clear()


def test_known_route_counted(client):
    """Обращения к существующему маршруту суммируются."""
    client.get("/api/health")
    client.get("/api/health")

    payload = client.get("/api/metrics").json()

    assert payload["endpoints"]["GET /api/health"] == 2
    assert payload["endpoint_errors"] == {}


def test_unknown_path_not_counted(client):
    """Несуществующий путь не создаёт ключ — иначе это рост словаря по памяти."""
    for i in range(5):
        client.get(f"/api/no-such-route-{i}")

    assert main._endpoint_hits == {}
    assert main._endpoint_errors == {}, "404 наполнили бы словарь ошибок так же, как счётчик обращений"


def test_known_route_counted_on_first_request(client):
    """Список маршрутов считается лениво — первый же запрос обязан попасть в счёт.

    На импорте модуля маршруты ещё не объявлены, поэтому набор собирается при первом обращении.
    """
    main._known_routes.cache_clear()

    client.get("/api/health")

    assert main._endpoint_hits["GET /api/health"] == 1
    assert "/api/health" in main._known_routes()


def test_error_responses_counted_separately(client):
    """Ответы 4xx/5xx попадают и в общий счётчик, и в счётчик ошибок."""
    client.post("/api/build", json={"нет": "полей"})

    assert main._endpoint_hits["POST /api/build"] == 1
    assert main._endpoint_errors["POST /api/build"] == 1


def test_metrics_expose_both_counters(client):
    """Оба счётчика присутствуют в ответе.

    Обращения считаются до вызова обработчика, поэтому запрос за метриками попадает
    в собственный ответ.
    """
    payload = client.get("/api/metrics").json()

    assert payload["endpoints"] == {"GET /api/metrics": 1}
    assert payload["endpoint_errors"] == {}


class TestUnhandledErrors:
    """Падение обработчика тоже попадает в счётчики.

    Необработанное исключение уходит в ServerErrorMiddleware, а он стоит снаружи
    пользовательских middleware, поэтому до их хвоста управление не доходит.
    """

    @pytest.fixture
    def crashing_client(self, monkeypatch):
        """Существующий маршрут, обработчик которого падает."""
        def boom():
            raise RuntimeError("сломалось внутри обработчика")

        # Настройки читает сам обработчик /api/status, то есть падение
        # происходит в запросе, а не на импорте модуля
        monkeypatch.setattr(main, "get_settings", boom)
        main._endpoint_hits.clear()
        main._endpoint_errors.clear()
        # raise_server_exceptions=False — нужен ответ 500, а не проброс в тест
        yield TestClient(main.app, raise_server_exceptions=False)
        main._endpoint_hits.clear()
        main._endpoint_errors.clear()

    def test_crash_counted_as_error(self, crashing_client):
        resp = crashing_client.get("/api/status")

        assert resp.status_code == 500
        assert main._endpoint_hits["GET /api/status"] == 1
        assert main._endpoint_errors["GET /api/status"] == 1

    def test_crash_response_carries_request_id(self, crashing_client):
        """По номеру запроса падение ищут в логе, поэтому он нужен и в заголовке."""
        resp = crashing_client.get("/api/status")

        assert resp.headers["X-Request-Id"]
        assert resp.json()["request_id"] == resp.headers["X-Request-Id"]
