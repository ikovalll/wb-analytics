"""Сбор воронки продаж по артикулам с подневной детализацией."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from wb.client import WildberriesClient

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Period:
    """Отрезок дат, включая обе границы."""

    start: date
    end: date

    @classmethod
    def last_days(cls, days: int, *, today: date | None = None) -> Period:
        """Последние ``days`` дней без сегодняшнего.

        Сегодня не берём: день не закрыт, цифры неполные.
        """
        if days < 1:
            raise ValueError("период не может быть короче одного дня")
        end = (today or date.today()) - timedelta(days=1)
        return cls(start=end - timedelta(days=days - 1), end=end)

    def as_payload(self) -> dict[str, str]:
        return {"start": self.start.isoformat(), "end": self.end.isoformat()}

    def __str__(self) -> str:
        return f"{self.start:%d.%m.%Y} — {self.end:%d.%m.%Y}"


@dataclass(frozen=True, slots=True)
class DayStats:
    """Показатели воронки за день."""

    date: str
    open_count: int
    cart_count: int
    order_count: int
    order_sum: int
    buyout_count: int
    buyout_sum: int
    add_to_wishlist_count: int

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> DayStats:
        """Собрать показатели дня из ответа API."""
        return cls(
            date=raw.get("date", ""),
            open_count=raw.get("openCount", 0),
            cart_count=raw.get("cartCount", 0),
            order_count=raw.get("orderCount", 0),
            order_sum=raw.get("orderSum", 0),
            buyout_count=raw.get("buyoutCount", 0),
            buyout_sum=raw.get("buyoutSum", 0),
            add_to_wishlist_count=raw.get("addToWishlistCount", 0),
        )


@dataclass(frozen=True, slots=True)
class ProductFunnel:
    """Воронка одного товара за период."""

    nm_id: int
    title: str
    vendor_code: str
    brand_name: str
    subject_name: str
    currency: str
    days: tuple[DayStats, ...]

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> ProductFunnel:
        """Собрать воронку товара из ответа API."""
        product = raw.get("product") or {}
        history = raw.get("history") or []
        return cls(
            nm_id=product.get("nmId", 0),
            title=(product.get("title") or "").strip(),
            vendor_code=(product.get("vendorCode") or "").strip(),
            brand_name=(product.get("brandName") or "").strip(),
            subject_name=(product.get("subjectName") or "").strip(),
            currency=raw.get("currency", "RUB"),
            days=tuple(
                DayStats.from_api(day)
                for day in sorted(history, key=lambda d: d.get("date", ""))
            ),
        )


def fetch_funnel(
    client: WildberriesClient,
    nm_ids: tuple[int, ...],
    period: Period,
    *,
    base_url: str,
) -> list[ProductFunnel]:
    """Забрать воронку по всем артикулам одним запросом.

    Лимит у аналитики жёстче, чем у отзывов, а эндпоинт принимает список —
    дробить запрос по товарам незачем.
    """
    payload = client.post(
        f"{base_url}/api/analytics/v3/sales-funnel/products/history",
        json={"nmIds": list(nm_ids), "selectedPeriod": period.as_payload()},
    )

    products = [ProductFunnel.from_api(item) for item in payload or []]
    logger.info(
        "Воронка за %s: %d товаров, дней в каждом — %s",
        period,
        len(products),
        ", ".join(str(len(p.days)) for p in products) or "нет данных",
    )

    missing = set(nm_ids) - {p.nm_id for p in products}
    if missing:
        logger.warning(
            "API не вернуло данные по артикулам: %s",
            ", ".join(str(nm_id) for nm_id in sorted(missing)),
        )
    return products
