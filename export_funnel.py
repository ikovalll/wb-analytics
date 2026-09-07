#!/usr/bin/env python3
"""Забрать воронку продаж по артикулам и выгрузить сырые данные в Google Таблицу.

Показатели считаются формулами в самой таблице, скрипт пишет только числа.

Запуск:
    python export_funnel.py                 # собрать и выгрузить
    python export_funnel.py --dry-run       # только собрать, в файлы, без Google
    python export_funnel.py --days 3        # укоротить период
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

from wb.client import WildberriesClient, WildberriesError
from wb.config import ConfigError, Settings, load_settings
from wb.funnel import Period, ProductFunnel, fetch_funnel

logger = logging.getLogger("export_funnel")

#: Шапка плоского CSV. В таблице она двухуровневая, здесь — одной строкой.
CSV_HEADER = (
    "Артикул",
    "Товар",
    "Дата",
    "Показы",
    "В корзину",
    "Заказы, шт",
    "Заказы, ₽",
    "Выкупы, шт",
    "Выкупы, ₽",
    "В избранное",
)


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
        "--days",
        type=int,
        metavar="N",
        help="сколько последних дней забрать (по умолчанию — WB_FUNNEL_DAYS)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="не трогать Google Таблицу, только сохранить данные в data/",
    )
    return parser.parse_args()


def main() -> int:
    """Собрать воронку и выгрузить её в таблицу; вернуть код возврата."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )
    args = parse_args()

    try:
        settings = load_settings()
        nm_ids = tuple(args.nm_ids) or settings.nm_ids
        period = Period.last_days(args.days or settings.funnel_days)
        spreadsheet_id = None if args.dry_run else settings.require_spreadsheet()
    except (ConfigError, ValueError) as exc:
        logger.error("%s", exc)
        return 1

    logger.info("Период: %s (сегодняшний день исключён)", period)

    try:
        with WildberriesClient(
            settings.token,
            min_interval=settings.request_interval,
            max_retries=settings.max_retries,
            timeout=settings.timeout,
        ) as client:
            products = fetch_funnel(
                client, nm_ids, period, base_url=settings.analytics_api
            )
    except WildberriesError as exc:
        logger.error("Запрос к API не удался: %s", exc)
        return 1

    if not products:
        logger.error("API не вернуло ни одного товара — выгружать нечего.")
        return 1

    _dump(products, settings.data_dir)
    _report(products)

    if spreadsheet_id is None:
        logger.info("Режим --dry-run: Google Таблица не затронута.")
        return 0

    return _publish(settings, spreadsheet_id, products)


def _publish(
    settings: Settings, spreadsheet_id: str, products: Sequence[ProductFunnel]
) -> int:
    """Записать данные в таблицу и показать посчитанный отчёт."""
    # Импорт здесь, чтобы --dry-run работал без установленных Google-библиотек.
    from wb import sheets

    try:
        spreadsheet = sheets.open_spreadsheet(
            settings.sheets_credentials, spreadsheet_id
        )
        sheets.publish(
            spreadsheet,
            products,
            raw_title=settings.sheet_raw,
            report_title=settings.sheet_report,
        )
    except FileNotFoundError as exc:
        logger.error("%s", exc)
        return 1
    except Exception as exc:  # noqa: BLE001 — сообщения Google бывают невнятными
        logger.error("Не удалось записать таблицу: %s", exc)
        if "PERMISSION_DENIED" in str(exc) or "permission" in str(exc).lower():
            logger.error(
                "Похоже, таблица не расшарена на сервисный аккаунт. Откройте "
                "её настройки доступа и дайте роль «Редактор» адресу из поля "
                "client_email в ключе."
            )
        return 1

    logger.info("Таблица обновлена: %s", spreadsheet.url)
    _show_report(sheets.verify(spreadsheet, settings.sheet_report))
    return 0


def _dump(products: Sequence[ProductFunnel], data_dir: Path) -> None:
    """Сохранить ответ API и плоскую таблицу для отладки без сети."""
    data_dir.mkdir(parents=True, exist_ok=True)

    json_path = data_dir / "funnel.json"
    json_path.write_text(
        json.dumps([asdict(p) for p in products], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    csv_path = data_dir / "funnel.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle, delimiter=";")
        writer.writerow(CSV_HEADER)  # без колонки CR: она формула в таблице
        for product in products:
            for day in product.days:
                writer.writerow(
                    [
                        product.nm_id,
                        product.title,
                        day.date,
                        day.open_count,
                        day.cart_count,
                        day.order_count,
                        day.order_sum,
                        day.buyout_count,
                        day.buyout_sum,
                        day.add_to_wishlist_count,
                    ]
                )

    logger.info("Записан %s", json_path)
    logger.info("Записан %s", csv_path)


def _report(products: Sequence[ProductFunnel]) -> None:
    """Напечатать итоги по каждому товару."""
    logger.info("%s", "-" * 72)
    for product in products:
        orders = sum(d.order_sum for d in product.days)
        buyouts = sum(d.buyout_sum for d in product.days)
        logger.info(
            "%s — дней %d, заказы %s ₽, выкупы %s ₽ | %s",
            product.nm_id,
            len(product.days),
            f"{orders:,}".replace(",", " "),
            f"{buyouts:,}".replace(",", " "),
            product.title[:40],
        )


def _show_report(rows: list[list[str]]) -> None:
    """Показать отчёт из таблицы; заодно видно, не сломались ли формулы."""
    for row in rows:
        line = " | ".join(cell for cell in row if cell)
        if line:
            logger.info("  %s", line)
        if any("#" in cell for cell in row):
            logger.warning("В отчёте есть ошибки формул — проверьте лист.")


if __name__ == "__main__":
    sys.exit(main())
