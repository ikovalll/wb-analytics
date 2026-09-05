"""Поведение HTTP-клиента: конверт ответа, повторы, лимиты."""

from __future__ import annotations

import json

import pytest
import requests

from wb.client import WildberriesClient, WildberriesError


class FakeResponse:
    """Минимальная замена requests.Response."""

    def __init__(self, status_code=200, payload=None, headers=None, text=None):
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}
        self.text = text if text is not None else json.dumps(payload)

    @property
    def ok(self) -> bool:
        return self.status_code < 400

    def json(self):
        if self._payload is None:
            raise ValueError("не JSON")
        return self._payload


@pytest.fixture
def client(monkeypatch):
    """Клиент без пауз — иначе тесты ждали бы реальные секунды."""
    monkeypatch.setattr("wb.client.time.sleep", lambda _: None)
    return WildberriesClient("token", min_interval=0.0, max_retries=3)


def respond(client, *responses):
    """Подменить сессию очередью заранее заданных ответов."""
    queue = list(responses)
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        result = queue.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    client._session.request = fake_request
    return calls


def test_токен_уходит_без_префикса_bearer(client):
    assert client._session.headers["Authorization"] == "token"


def test_конверт_отзывов_распаковывается(client):
    respond(
        client, FakeResponse(payload={"data": {"feedbacks": [1, 2]}, "error": False})
    )

    assert client.get("https://example/feedbacks") == {"feedbacks": [1, 2]}


def test_ошибка_внутри_успешного_ответа_поднимает_исключение(client):
    """WB умеет вернуть HTTP 200 с error: true — статуса кода мало."""
    respond(
        client,
        FakeResponse(
            payload={
                "data": None,
                "error": True,
                "errorText": "Плохой формат isAnswered",
            }
        ),
    )

    with pytest.raises(WildberriesError, match="Плохой формат isAnswered"):
        client.get("https://example/feedbacks")


def test_массив_аналитики_возвращается_как_есть(client):
    """Аналитика отвечает без конверта — списком."""
    respond(client, FakeResponse(payload=[{"product": {}}]))

    assert client.post("https://example/funnel", json={}) == [{"product": {}}]


def test_повтор_после_429(client):
    calls = respond(
        client,
        FakeResponse(status_code=429, headers={"Retry-After": "1"}),
        FakeResponse(payload={"data": "ok", "error": False}),
    )

    assert client.get("https://example") == "ok"
    assert len(calls) == 2


def test_повтор_после_пятисотой(client):
    calls = respond(
        client,
        FakeResponse(status_code=503),
        FakeResponse(payload={"data": "ok", "error": False}),
    )

    assert client.get("https://example") == "ok"
    assert len(calls) == 2


def test_попытки_не_бесконечны(client):
    calls = respond(client, *[FakeResponse(status_code=429) for _ in range(3)])

    with pytest.raises(WildberriesError, match="3 попыток"):
        client.get("https://example")
    assert len(calls) == 3


def test_сетевая_ошибка_тоже_повторяется(client):
    calls = respond(
        client,
        requests.ConnectionError("сеть отвалилась"),
        FakeResponse(payload={"data": "ok", "error": False}),
    )

    assert client.get("https://example") == "ok"
    assert len(calls) == 2


def test_401_не_повторяется_и_подсказывает_причину(client):
    calls = respond(client, FakeResponse(status_code=401, text="unauthorized"))

    with pytest.raises(WildberriesError, match="Bearer"):
        client.get("https://example")
    assert len(calls) == 1, "проблему токена повторами не лечат"


def test_403_говорит_про_категорию_доступа(client):
    respond(client, FakeResponse(status_code=403, text="forbidden"))

    with pytest.raises(WildberriesError, match="категории доступа"):
        client.get("https://example")


def test_400_показывает_текст_ответа(client):
    respond(
        client,
        FakeResponse(
            status_code=400, payload=None, text="selectedPeriod (field required)"
        ),
    )

    with pytest.raises(WildberriesError, match="selectedPeriod"):
        client.post("https://example", json={})


def test_не_json_даёт_понятную_ошибку(client):
    respond(client, FakeResponse(payload=None, text="<html>502 Bad Gateway</html>"))

    with pytest.raises(WildberriesError, match="не является JSON"):
        client.get("https://example")


def test_retry_after_имеет_приоритет_над_задержкой(client, monkeypatch):
    delays = []
    monkeypatch.setattr("wb.client.time.sleep", delays.append)
    respond(
        client,
        FakeResponse(status_code=429, headers={"Retry-After": "7"}),
        FakeResponse(payload={"data": "ok", "error": False}),
    )

    client.get("https://example")

    assert 7.0 in delays


def test_клиент_закрывается_как_контекст(monkeypatch):
    monkeypatch.setattr("wb.client.time.sleep", lambda _: None)
    closed = []

    with WildberriesClient("token", min_interval=0.0) as client:
        client._session.close = lambda: closed.append(True)

    assert closed == [True]
