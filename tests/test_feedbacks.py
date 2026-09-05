"""Модель отзыва и логика сбора: пагинация, два прохода, дедупликация."""

from __future__ import annotations

import pytest

from wb.feedbacks import (
    Feedback,
    ProductFeedbacks,
    fetch_feedbacks_count,
    fetch_product_feedbacks,
)

BASE = "https://feedbacks"


def raw_feedback(
    feedback_id, *, rating=5, text="", pros="", cons="", nm_id=1, answer=None
):
    """Отзыв в том виде, в каком его отдаёт API."""
    return {
        "id": feedback_id,
        "productDetails": {"nmId": nm_id},
        "createdDate": "2026-01-01T00:00:00Z",
        "productValuation": rating,
        "text": text,
        "pros": pros,
        "cons": cons,
        "userName": "Покупатель",
        "size": "",
        "answer": answer,
    }


class FakeClient:
    """Клиент, отвечающий заранее заданными страницами."""

    def __init__(self, pages_by_flag: dict[str, list[list[dict]]]):
        self._pages = {flag: list(pages) for flag, pages in pages_by_flag.items()}
        self.requests: list[dict] = []

    def get(self, url, params=None):
        self.requests.append({"url": url, **(params or {})})
        if url.endswith("/count"):
            flag = params["isAnswered"]
            total = sum(len(page) for page in self._pages.get(flag, []))
            return {"count": total}
        pages = self._pages.get(params["isAnswered"], [])
        index = params["skip"] // params["take"]
        return {"feedbacks": pages[index] if index < len(pages) else []}


# --- модель --------------------------------------------------------------


def test_отзыв_разбирается_из_ответа_api():
    feedback = Feedback.from_api(
        raw_feedback("a1", rating=4, text=" Хорошо ", pros="Цена", nm_id=777)
    )

    assert feedback.id == "a1"
    assert feedback.nm_id == 777
    assert feedback.rating == 4
    assert feedback.text == "Хорошо", "пробелы по краям убираются"
    assert feedback.is_answered is False


def test_отзыв_с_ответом_продавца_помечается():
    feedback = Feedback.from_api(raw_feedback("a1", answer={"text": "Спасибо"}))

    assert feedback.is_answered is True


def test_пустые_поля_не_ломают_разбор():
    feedback = Feedback.from_api({"id": "a1", "productValuation": 5})

    assert feedback.text == ""
    assert feedback.nm_id == 0


def test_отзыв_без_текста_считается_пустым():
    assert Feedback.from_api(raw_feedback("a1")).is_empty
    assert not Feedback.from_api(raw_feedback("a2", cons="Шумит")).is_empty


def test_статистика_считается_по_отзывам():
    product = ProductFeedbacks(
        nm_id=1,
        feedbacks=[
            Feedback.from_api(raw_feedback("a", rating=5, text="Топ")),
            Feedback.from_api(raw_feedback("b", rating=4)),
            Feedback.from_api(raw_feedback("c", rating=1, cons="Брак")),
        ],
    )

    assert product.total == 3
    assert product.average_rating == 3.33
    assert product.rating_distribution == {5: 1, 4: 1, 3: 0, 2: 0, 1: 1}
    assert len(product.with_text) == 2


def test_статистика_пустого_товара_не_делит_на_ноль():
    product = ProductFeedbacks(nm_id=1)

    assert product.total == 0
    assert product.average_rating == 0.0


# --- сбор ----------------------------------------------------------------


def test_собираются_оба_состояния_is_answered():
    """Главная ловушка API: параметр обязателен и делит выборку надвое."""
    client = FakeClient(
        {
            "false": [[raw_feedback("нов1"), raw_feedback("нов2")]],
            "true": [[raw_feedback("отв1")]],
        }
    )

    product = fetch_product_feedbacks(client, 1, base_url=BASE, page_size=100)

    assert product.total == 3
    assert {f.id for f in product.feedbacks} == {"нов1", "нов2", "отв1"}


def test_страницы_листаются_до_неполной():
    page_size = 2
    client = FakeClient(
        {
            "false": [
                [raw_feedback("a"), raw_feedback("b")],
                [raw_feedback("c")],
            ],
            "true": [],
        }
    )

    product = fetch_product_feedbacks(client, 1, base_url=BASE, page_size=page_size)

    assert product.total == 3
    skips = [r["skip"] for r in client.requests if r.get("take")]
    assert skips == [0, 2, 0], "после неполной страницы листание прекращается"


def test_дубликаты_между_страницами_отбрасываются():
    client = FakeClient(
        {
            "false": [[raw_feedback("a"), raw_feedback("b")], [raw_feedback("b")]],
            "true": [],
        }
    )

    product = fetch_product_feedbacks(client, 1, base_url=BASE, page_size=2)

    assert product.total == 2


def test_отзывы_упорядочены_по_дате():
    old = raw_feedback("старый") | {"createdDate": "2025-01-01"}
    new = raw_feedback("новый") | {"createdDate": "2026-01-01"}
    client = FakeClient({"false": [[new, old]], "true": []})

    product = fetch_product_feedbacks(client, 1, base_url=BASE, page_size=100)

    assert [f.id for f in product.feedbacks] == ["старый", "новый"]


def test_пустая_выдача_не_ломает_сбор():
    client = FakeClient({"false": [], "true": []})

    product = fetch_product_feedbacks(client, 1, base_url=BASE, page_size=100)

    assert product.total == 0


def test_счётчик_складывает_оба_состояния():
    client = FakeClient(
        {
            "false": [[raw_feedback("a"), raw_feedback("b")]],
            "true": [[raw_feedback("c")]],
        }
    )

    assert fetch_feedbacks_count(client, 1, base_url=BASE) == 3


def test_артикул_уходит_в_запрос():
    client = FakeClient({"false": [], "true": []})

    fetch_product_feedbacks(client, 386248405, base_url=BASE, page_size=100)

    assert all(r["nmId"] == 386248405 for r in client.requests)


@pytest.mark.parametrize("flag, expected", [(False, "false"), (True, "true")])
def test_булев_параметр_уходит_строкой_в_нижнем_регистре(flag, expected):
    """API ждёт true/false строкой, питоновский bool ему не подходит."""
    from wb.feedbacks import _as_flag

    assert _as_flag(flag) == expected
