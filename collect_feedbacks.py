#!/usr/bin/env python3
"""Собрать отзывы покупателей по артикулам магазина и выгрузить их в data/.

Настройки берутся из .env, артикулы — из WB_NM_IDS.

Запуск:
    python collect_feedbacks.py           # артикулы из .env
    python collect_feedbacks.py 386248405 # только указанные
    python collect_feedbacks.py --verify  # сверить полноту со счётчиком API
"""

from __future__ import annotations

import argparse
import logging
import sys

from wb.client import WildberriesClient, WildberriesError
from wb.config import ConfigError, Settings, load_settings
from wb.export import write_csv, write_digest, write_json
from wb.feedbacks import (
    ProductFeedbacks,
    fetch_feedbacks_count,
    fetch_product_feedbacks,
)

logger = logging.getLogger("collect_feedbacks")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "nm_ids",
        nargs="*",
        type=int,
        metavar="NM_ID",
        help="артикулы товаров (по умолчанию — список из WB_NM_IDS в .env)",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="сверить количество собранных отзывов со счётчиком API",
    )
    return parser.parse_args()


def main() -> int:
    """Собрать отзывы и выгрузить их в файлы; вернуть код возврата."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )
    args = parse_args()

    try:
        settings = load_settings()
    except ConfigError as exc:
        logger.error("%s", exc)
        return 1

    nm_ids = tuple(args.nm_ids) or settings.nm_ids

    try:
        products = _collect(settings, nm_ids, verify=args.verify)
    except WildberriesError as exc:
        logger.error("Запрос к API не удался: %s", exc)
        return 1

    paths = (
        write_json(products, settings.data_dir / "feedbacks.json"),
        write_csv(products, settings.data_dir / "feedbacks.csv"),
        write_digest(
            products,
            settings.data_dir / "feedbacks_digest.md",
            positive_sample=settings.positive_sample,
        ),
    )

    _report(products)
    for path in paths:
        logger.info("Записан %s", path)
    return 0


def _collect(
    settings: Settings, nm_ids: tuple[int, ...], *, verify: bool
) -> list[ProductFeedbacks]:
    products: list[ProductFeedbacks] = []

    with WildberriesClient(
        settings.token,
        min_interval=settings.request_interval,
        max_retries=settings.max_retries,
        timeout=settings.timeout,
    ) as client:
        for nm_id in nm_ids:
            products.append(
                fetch_product_feedbacks(
                    client,
                    nm_id,
                    base_url=settings.feedbacks_api,
                    page_size=settings.page_size,
                )
            )
        if verify:
            _verify(client, products, settings.feedbacks_api)

    return products


def _verify(
    client: WildberriesClient, products: list[ProductFeedbacks], base_url: str
) -> None:
    """Сверить собранное со счётчиком API."""
    for product in products:
        expected = fetch_feedbacks_count(client, product.nm_id, base_url=base_url)
        status = "совпадает" if expected == product.total else "РАСХОЖДЕНИЕ"
        logger.info(
            "Сверка %s: счётчик API — %d, собрано — %d (%s)",
            product.nm_id,
            expected,
            product.total,
            status,
        )


def _report(products: list[ProductFeedbacks]) -> None:
    """Напечатать итоги по каждому товару."""
    logger.info("%s", "-" * 62)
    for product in products:
        distribution = " ".join(
            f"{star}*:{count}" for star, count in product.rating_distribution.items()
        )
        logger.info(
            "%s — %d отзывов, рейтинг %.2f, с текстом %d  [%s]",
            product.nm_id,
            product.total,
            product.average_rating,
            len(product.with_text),
            distribution,
        )
    logger.info("Итого отзывов: %d", sum(p.total for p in products))


if __name__ == "__main__":
    sys.exit(main())
