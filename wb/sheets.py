"""Выгрузка воронки в Google Таблицу.

Скрипт пишет только числа: показатели считаются формулами внутри таблицы,
чтобы их можно было проверить и пересчитать без повторного запуска.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from contextlib import suppress
from pathlib import Path

import gspread
from google.oauth2.service_account import Credentials

from wb import styling
from wb.funnel import ProductFunnel

logger = logging.getLogger(__name__)

SCOPES = ("https://www.googleapis.com/auth/spreadsheets",)

RAW_HEADER = (
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
    "CR, %",
)

METRICS_HEADER = (
    "Артикул",
    "Товар",
    "Показы",
    "В корзину",
    "Заказы, шт",
    "Сумма заказов, ₽",
    "Выкупы, шт",
    "Сумма выкупов, ₽",
    "CR средний",
    "CR минимальный",
    "CR максимальный",
    "Средний чек по выкупам, ₽",
    "Средний чек по заказам, ₽",
)

#: Разделитель аргументов в формулах; соответствует локали, которую
#: скрипт выставляет таблице при первой записи.
SEP = ";"


def open_spreadsheet(
    credentials_path: Path, spreadsheet_id: str
) -> gspread.Spreadsheet:
    """Открыть таблицу по ключу сервисного аккаунта."""
    if not credentials_path.exists():
        raise FileNotFoundError(
            f"Не найден ключ сервисного аккаунта: {credentials_path}. "
            "Путь задаётся переменной WB_SHEETS_CREDENTIALS."
        )
    credentials = Credentials.from_service_account_file(
        str(credentials_path), scopes=list(SCOPES)
    )
    return gspread.authorize(credentials).open_by_key(spreadsheet_id)


def publish(
    spreadsheet: gspread.Spreadsheet,
    products: Sequence[ProductFunnel],
    *,
    raw_title: str,
    report_title: str,
) -> None:
    """Заполнить таблицу: лист сырых данных и лист показателей."""
    _set_locale(spreadsheet)

    ordered = sorted(products, key=_buyout_sum, reverse=True)
    raw_rows = _raw_rows(products)
    report_rows = _report_rows(ordered, raw_title, data_rows=len(raw_rows) - 1)

    raw = _write(spreadsheet, raw_title, raw_rows)
    report = _write(spreadsheet, report_title, report_rows)

    styling.apply(spreadsheet, raw, report, last_row=len(report_rows))
    _drop_stale_sheets(spreadsheet, {raw_title, report_title})


def verify(spreadsheet: gspread.Spreadsheet, report_title: str) -> list[list[str]]:
    """Прочитать посчитанный отчёт обратно, чтобы увидеть ошибки формул."""
    return spreadsheet.worksheet(report_title).get_all_values()


def _write(
    spreadsheet: gspread.Spreadsheet, title: str, rows: list[list[object]]
) -> gspread.Worksheet:
    """Создать лист ровно под данные и заполнить его.

    Размер задаётся точно: лист по умолчанию приходит с тысячей пустых
    строк, и они тянутся серой полосой под таблицей.
    """
    worksheet = _replace_worksheet(
        spreadsheet, title, rows=len(rows), cols=len(rows[0])
    )
    worksheet.update(values=rows, range_name="A1", value_input_option="USER_ENTERED")
    return worksheet


# --- содержимое листов ---------------------------------------------------


def _raw_rows(products: Sequence[ProductFunnel]) -> list[list[object]]:
    """Строки листа сырых данных: артикул × день."""
    rows: list[list[object]] = [list(RAW_HEADER)]
    line = 2  # первая строка данных в таблице

    for product in products:
        for day in product.days:
            rows.append(
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
                    f"=IFERROR(F{line}/D{line}{SEP}0)",
                ]
            )
            line += 1
    return rows


#: Строка, с которой начинаются данные на листе отчёта.
FIRST_REPORT_ROW = 2


def _report_rows(
    products: Sequence[ProductFunnel],
    raw_title: str,
    *,
    data_rows: int,
) -> list[list[object]]:
    """Показатели по артикулам — формулами по листу сырых данных.

    Товары приходят уже упорядоченными, сортировать внутри таблицы нечего.
    """
    raw = f"'{raw_title}'!"
    last = data_rows + 1
    ids = f"{raw}$A$2:$A${last}"
    cr = f"{raw}$K$2:$K${last}"

    def total(column: str, line: int) -> str:
        return f"=SUMIFS({raw}${column}$2:${column}${last}{SEP}{ids}{SEP}$A{line})"

    rows: list[list[object]] = [list(METRICS_HEADER)]
    for index, product in enumerate(products, start=FIRST_REPORT_ROW):
        rows.append(
            [
                product.nm_id,
                product.title,
                total("D", index),  # показы
                total("E", index),  # в корзину
                total("F", index),  # заказы, шт
                total("G", index),  # заказы, ₽
                total("H", index),  # выкупы, шт
                total("I", index),  # выкупы, ₽
                f"=AVERAGEIFS({cr}{SEP}{ids}{SEP}$A{index})",
                f"=MINIFS({cr}{SEP}{ids}{SEP}$A{index})",
                f"=MAXIFS({cr}{SEP}{ids}{SEP}$A{index})",
                f"=IFERROR(H{index}/G{index}{SEP}0)",
                f"=IFERROR(F{index}/E{index}{SEP}0)",
            ]
        )
    return rows


def _buyout_sum(product: ProductFunnel) -> int:
    return sum(day.buyout_sum for day in product.days)


# --- служебное -----------------------------------------------------------


def _set_locale(spreadsheet: gspread.Spreadsheet) -> None:
    """Зафиксировать локаль и часовой пояс.

    От локали зависит разделитель аргументов в формулах, поэтому её
    выставляем явно, а не наследуем от аккаунта.
    """
    spreadsheet.batch_update(
        {
            "requests": [
                {
                    "updateSpreadsheetProperties": {
                        "properties": {"locale": "ru_RU", "timeZone": "Europe/Moscow"},
                        "fields": "locale,timeZone",
                    }
                }
            ]
        }
    )


def _replace_worksheet(
    spreadsheet: gspread.Spreadsheet, title: str, *, rows: int, cols: int
) -> gspread.Worksheet:
    """Создать лист заново, чтобы не смешивать свежие данные со старыми."""
    with suppress(gspread.WorksheetNotFound):
        spreadsheet.del_worksheet(spreadsheet.worksheet(title))
    return spreadsheet.add_worksheet(title=title, rows=rows, cols=cols)


#: Листы прошлых версий скрипта — удаляются, чтобы в таблице не оставалось
#: устаревших копий тех же показателей.
OBSOLETE_TITLES = frozenset({"Показатели"})


def _drop_stale_sheets(spreadsheet: gspread.Spreadsheet, keep: set[str]) -> None:
    """Убрать пустые и устаревшие листы, не трогая чужие непустые.

    Пустым считается лист без единого непробельного значения: Google хранит
    тронутые ячейки как пустые строки.
    """
    for worksheet in spreadsheet.worksheets():
        if worksheet.title in keep:
            continue
        is_empty = not any(
            cell.strip() for row in worksheet.get_all_values() for cell in row
        )
        if is_empty or worksheet.title in OBSOLETE_TITLES:
            spreadsheet.del_worksheet(worksheet)
            logger.info("Удалён лист %r", worksheet.title)
