"""Сбор отзывов покупателей по артикулам."""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Iterator
from dataclasses import asdict, dataclass, field
from typing import Any

from wb.client import WildberriesClient

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Feedback:
    """Отзыв покупателя."""

    id: str
    nm_id: int
    created_at: str
    rating: int
    text: str
    pros: str
    cons: str
    user_name: str
    size: str
    color: str
    order_status: str
    has_photo: bool
    has_video: bool
    answer: str

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> Feedback:
        """Собрать отзыв из ответа API."""
        details = raw.get("productDetails") or {}
        answer = raw.get("answer") or {}
        return cls(
            id=raw.get("id", ""),
            nm_id=details.get("nmId", 0),
            created_at=raw.get("createdDate", ""),
            rating=raw.get("productValuation", 0),
            text=(raw.get("text") or "").strip(),
            pros=(raw.get("pros") or "").strip(),
            cons=(raw.get("cons") or "").strip(),
            user_name=(raw.get("userName") or "").strip(),
            # Размер лежит внутри productDetails, на верхнем уровне его нет.
            size=(details.get("size") or "").strip(),
            color=(raw.get("color") or "").strip(),
            order_status=(raw.get("orderStatus") or "").strip(),
            has_photo=bool(raw.get("photoLinks")),
            has_video=bool(raw.get("video")),
            answer=(answer.get("text") or "").strip(),
        )

    @property
    def is_empty(self) -> bool:
        """Оценка есть, текста нет."""
        return not (self.text or self.pros or self.cons)

    @property
    def is_answered(self) -> bool:
        """Продавец ответил на отзыв."""
        return bool(self.answer)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ProductFeedbacks:
    """Отзывы товара и статистика по ним."""

    nm_id: int
    feedbacks: list[Feedback] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.feedbacks)

    @property
    def average_rating(self) -> float:
        if not self.feedbacks:
            return 0.0
        return round(sum(f.rating for f in self.feedbacks) / self.total, 2)

    @property
    def rating_distribution(self) -> dict[int, int]:
        counter = Counter(f.rating for f in self.feedbacks)
        return {star: counter.get(star, 0) for star in range(5, 0, -1)}

    @property
    def with_text(self) -> list[Feedback]:
        """Отзывы, в которых есть что читать."""
        return [f for f in self.feedbacks if not f.is_empty]


def fetch_product_feedbacks(
    client: WildberriesClient,
    nm_id: int,
    *,
    base_url: str,
    page_size: int,
) -> ProductFeedbacks:
    """Забрать все отзывы по артикулу.

    Параметр ``isAnswered`` обязателен и делит выборку надвое: значения
    «оба сразу» нет, поэтому проходим дважды. Иначе половина отзывов
    потеряется молча, без ошибки.
    """
    collected: dict[str, Feedback] = {}

    for is_answered in (False, True):
        for raw in _iter_pages(client, nm_id, is_answered, base_url, page_size):
            feedback = Feedback.from_api(raw)
            collected[feedback.id] = feedback

    result = ProductFeedbacks(
        nm_id=nm_id,
        feedbacks=sorted(collected.values(), key=lambda f: f.created_at),
    )
    logger.info(
        "Артикул %s: собрано %d отзывов, средний рейтинг %.2f",
        nm_id,
        result.total,
        result.average_rating,
    )
    return result


def fetch_feedbacks_count(
    client: WildberriesClient, nm_id: int, *, base_url: str
) -> int:
    """Счётчик отзывов по артикулу для сверки полноты выгрузки."""
    total = 0
    for is_answered in (False, True):
        payload = client.get(
            f"{base_url}/api/v1/feedbacks/count",
            params={"isAnswered": _as_flag(is_answered), "nmId": nm_id},
        )
        total += _extract_count(payload)
    return total


def _iter_pages(
    client: WildberriesClient,
    nm_id: int,
    is_answered: bool,
    base_url: str,
    page_size: int,
) -> Iterator[dict[str, Any]]:
    """Листать выдачу, пока страницы приходят полными."""
    skip = 0
    while True:
        payload = client.get(
            f"{base_url}/api/v1/feedbacks",
            params={
                "isAnswered": _as_flag(is_answered),
                "nmId": nm_id,
                "take": page_size,
                "skip": skip,
            },
        )
        page = (payload or {}).get("feedbacks") or []
        yield from page

        if len(page) < page_size:
            return
        skip += page_size


def _as_flag(value: bool) -> str:
    """API ждёт булев параметр строкой в нижнем регистре."""
    return "true" if value else "false"


def _extract_count(payload: Any) -> int:
    if isinstance(payload, dict):
        return int(payload.get("count", 0))
    return int(payload or 0)
