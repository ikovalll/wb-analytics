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

#: Шапка занимает две строки: верхняя группирует колонки, нижняя уточняет.
HEADER_ROWS = 2
FIRST_DATA_ROW = HEADER_ROWS + 1  # номер строки в таблице, считая с единицы

RAW_HEADER_TOP = (
    "Артикул",
    "Товар",
    "Дата",
    "Показы",
    "В корзину",
    "Заказы",
    "",
    "Выкупы",
    "",
    "В избранное",
    "CR",
)
RAW_HEADER_SUB = ("", "", "", "", "", "шт.", "Сумма", "шт.", "Сумма", "", "")

REPORT_HEADER_TOP = (
    "Артикул",
    "Товар",
    "Показы",
    "В корзину",
    "Заказы",
    "",
    "Выкупы",
    "",
    "CR",
    "",
    "",
    "Средний чек",
    "",
)
REPORT_HEADER_SUB = (
    "",
    "",
    "",
    "",
    "шт.",
    "Сумма",
    "шт.",
    "Сумма",
    "Средний",
    "Мин",
    "Макс",
    "Выкупы",
    "Заказы",
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
    blocks = _blocks(products)

    raw = _write(spreadsheet, raw_title, _raw_rows(products))
    report = _write(spreadsheet, report_title, _report_rows(ordered, raw_title, blocks))

    styling.apply(
        spreadsheet,
        raw,
        report,
        raw_blocks=[(start, end) for start, end in blocks.values()],
        report_rows=len(ordered),
    )
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


def _blocks(products: Sequence[ProductFunnel]) -> dict[int, tuple[int, int]]:
    """Границы строк каждого товара на листе сырых данных, считая с единицы."""
    bounds: dict[int, tuple[int, int]] = {}
    row = FIRST_DATA_ROW
    for product in products:
        bounds[product.nm_id] = (row, row + len(product.days) - 1)
        row += len(product.days)
    return bounds


def _raw_rows(products: Sequence[ProductFunnel]) -> list[list[object]]:
    """Строки листа сырых данных: артикул × день.

    Артикул и название заполняются только в первой строке блока: остальные
    ячейки колонки объединяются с ней при оформлении.
    """
    rows: list[list[object]] = [list(RAW_HEADER_TOP), list(RAW_HEADER_SUB)]
    line = FIRST_DATA_ROW

    for product in products:
        for index, day in enumerate(product.days):
            first = index == 0
            rows.append(
                [
                    product.nm_id if first else "",
                    product.title if first else "",
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


def _report_rows(
    products: Sequence[ProductFunnel],
    raw_title: str,
    blocks: dict[int, tuple[int, int]],
) -> list[list[object]]:
    """Показатели по артикулам — формулами по листу сырых данных.

    Суммы считаются по диапазону строк товара, а не через SUMIFS с отбором
    по колонке артикула: в ней объединённые ячейки, и отбор нашёл бы только
    первый день каждого блока.
    """
    rows: list[list[object]] = [list(REPORT_HEADER_TOP), list(REPORT_HEADER_SUB)]

    for index, product in enumerate(products, start=FIRST_DATA_ROW):
        block = blocks[product.nm_id]
        rows.append(
            [
                product.nm_id,
                product.title,
                _over(raw_title, "D", block),
                _over(raw_title, "E", block),
                _over(raw_title, "F", block),
                _over(raw_title, "G", block),
                _over(raw_title, "H", block),
                _over(raw_title, "I", block),
                _over(raw_title, "K", block, "AVERAGE"),
                _over(raw_title, "K", block, "MIN"),
                _over(raw_title, "K", block, "MAX"),
                f"=IFERROR(H{index}/G{index}{SEP}0)",
                f"=IFERROR(F{index}/E{index}{SEP}0)",
            ]
        )
    return rows


def _over(
    raw_title: str, column: str, block: tuple[int, int], function: str = "SUM"
) -> str:
    """Формула по колонке в пределах строк одного товара."""
    start, end = block
    return f"={function}('{raw_title}'!{column}{start}:{column}{end})"


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
