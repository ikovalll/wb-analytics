"""Период, разбор ответа воронки и запрос к аналитике."""

from __future__ import annotations

from datetime import date

import pytest

from wb.funnel import DayStats, Period, ProductFunnel, fetch_funnel

BASE = "https://analytics"


def raw_day(day="2026-09-01", **overrides):
    return {
        "date": day,
        "openCount": 100,
        "cartCount": 20,
        "orderCount": 10,
        "orderSum": 50000,
        "buyoutCount": 5,
        "buyoutSum": 25000,
        "buyoutPercent": 90,
        "addToCartConversion": 20,
        "cartToOrderConversion": 50,
        "addToWishlistCount": 3,
    } | overrides


def raw_product(nm_id=1, days=None):
    return {
        "product": {
            "nmId": nm_id,
            "title": "Товар",
            "vendorCode": "code",
            "brandName": "Бренд",
            "subjectId": 1,
            "subjectName": "Категория",
        },
        "history": days if days is not None else [raw_day()],
        "currency": "RUB",
    }


class FakeClient:
    def __init__(self, payload):
        self.payload = payload
        self.sent = None

    def post(self, url, json):
        self.sent = {"url": url, "json": json}
        return self.payload


# --- период --------------------------------------------------------------


def test_период_заканчивается_вчера():
    """Сегодня не берём: день не закрыт, цифры неполные."""
    period = Period.last_days(7, today=date(2026, 9, 5))

    assert period.start == date(2026, 8, 29)
    assert period.end == date(2026, 9, 4)


def test_период_в_один_день_это_вчера():
    period = Period.last_days(1, today=date(2026, 9, 5))

    assert period.start == period.end == date(2026, 9, 4)


def test_период_короче_дня_бессмысленен():
    with pytest.raises(ValueError):
        Period.last_days(0)


def test_период_переживает_смену_месяца():
    period = Period.last_days(7, today=date(2026, 3, 3))

    assert period.start == date(2026, 2, 24)
    assert period.end == date(2026, 3, 2)


def test_период_уходит_в_запрос_строками_дат():
    period = Period.last_days(7, today=date(2026, 9, 5))

    assert period.as_payload() == {"start": "2026-08-29", "end": "2026-09-04"}


def test_период_читаемо_печатается():
    assert str(Period.last_days(7, today=date(2026, 9, 5))) == "29.08.2026 — 04.09.2026"


# --- разбор --------------------------------------------------------------


def test_день_разбирается_из_ответа():
    day = DayStats.from_api(raw_day("2026-09-02", openCount=2530, orderSum=256852))

    assert day.date == "2026-09-02"
    assert day.open_count == 2530
    assert day.order_sum == 256852


def test_недостающие_поля_дня_становятся_нулями():
    day = DayStats.from_api({"date": "2026-09-02"})

    assert day.open_count == 0
    assert day.buyout_sum == 0


def test_дни_сортируются_по_дате():
    product = ProductFunnel.from_api(
        raw_product(days=[raw_day("2026-09-03"), raw_day("2026-09-01")])
    )

    assert [d.date for d in product.days] == ["2026-09-01", "2026-09-03"]


def test_товар_без_истории_не_ломает_разбор():
    product = ProductFunnel.from_api(raw_product(days=[]))

    assert product.days == ()


# --- запрос --------------------------------------------------------------


def test_все_артикулы_уходят_одним_запросом():
    """У аналитики лимит жёстче, чем у отзывов, — дробить незачем."""
    client = FakeClient([raw_product(1), raw_product(2), raw_product(3)])
    period = Period.last_days(7, today=date(2026, 9, 5))

    products = fetch_funnel(client, (1, 2, 3), period, base_url=BASE)

    assert len(products) == 3
    assert client.sent["json"] == {
        "nmIds": [1, 2, 3],
        "selectedPeriod": {"start": "2026-08-29", "end": "2026-09-04"},
    }


def test_пропавший_артикул_попадает_в_предупреждения(caplog):
    client = FakeClient([raw_product(1)])
    period = Period.last_days(7, today=date(2026, 9, 5))

    fetch_funnel(client, (1, 2), period, base_url=BASE)

    assert "2" in caplog.text


def test_пустой_ответ_даёт_пустой_список():
    client = FakeClient(None)

    assert fetch_funnel(client, (1,), Period.last_days(7), base_url=BASE) == []
