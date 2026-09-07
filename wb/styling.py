"""Внешний вид листов Google Таблицы: шапка, ширины, объединения, рамки."""

from __future__ import annotations

import gspread

HEADER_ROWS = 2

#: Ширины колонок в пикселях. Заданы явно, а не автоподбором: длинные
#: названия товаров иначе растягивают колонку на пол-экрана.
RAW_WIDTHS = (110, 432, 73, 71, 100, 100, 102, 100, 88, 102, 90)
REPORT_WIDTHS = (85, 293, 85, 85, 85, 85, 85, 85, 85, 85, 85, 85, 85)

#: Колонки верхней шапки, объединённые по горизонтали: (первая, последняя+1).
RAW_GROUPS = ((5, 7), (7, 9))
REPORT_GROUPS = ((4, 6), (6, 8), (8, 11), (11, 13))

#: Колонки без подзаголовка — их шапка объединяется по вертикали.
RAW_SINGLE = (0, 1, 2, 3, 4, 9, 10)
REPORT_SINGLE = (0, 1, 2, 3)

HEADER_HEIGHT = 38
ROW_HEIGHT = 21

HEADER_COLOR = {"red": 0.176, "green": 0.247, "blue": 0.329}
BAND_COLOR = {"red": 0.957, "green": 0.957, "blue": 0.969}
WHITE = {"red": 1.0, "green": 1.0, "blue": 1.0}

FONT = "Arial"
COUNT = "#,##0"
MONEY = "#,##0 \\₽"
PERCENT = "0.00%"
DATE = "yyyy-mm-dd"


def apply(
    spreadsheet: gspread.Spreadsheet,
    raw: gspread.Worksheet,
    report: gspread.Worksheet,
    *,
    raw_blocks: list[tuple[int, int]],
    report_rows: int,
) -> None:
    """Оформить оба листа одним пакетом запросов.

    Внешний вид задаётся только здесь: листы пересоздаются при каждом
    запуске, и ручные настройки следующий прогон не переживут.
    """
    raw_rows = sum(end - start + 1 for start, end in raw_blocks)

    requests = [
        *_sheet(
            raw,
            widths=RAW_WIDTHS,
            data_rows=raw_rows,
            groups=RAW_GROUPS,
            single=RAW_SINGLE,
        ),
        *_raw_columns(raw, raw_rows),
        *_product_merges(raw, raw_blocks),
        *_sheet(
            report,
            widths=REPORT_WIDTHS,
            data_rows=report_rows,
            groups=REPORT_GROUPS,
            single=REPORT_SINGLE,
        ),
        *_report_columns(report, report_rows),
    ]
    spreadsheet.batch_update({"requests": requests})


# --- общая разметка листа ------------------------------------------------


def _sheet(
    worksheet: gspread.Worksheet,
    *,
    widths: tuple[int, ...],
    data_rows: int,
    groups: tuple[tuple[int, int], ...],
    single: tuple[int, ...],
) -> list[dict]:
    """Шапка, объединения, ширины, высоты, рамки и чередование строк."""
    sheet_id = worksheet.id
    columns = len(widths)
    last_row = HEADER_ROWS + data_rows

    return [
        _cells(
            sheet_id,
            0,
            1,
            0,
            columns,
            {
                "backgroundColor": HEADER_COLOR,
                "horizontalAlignment": "CENTER",
                "verticalAlignment": "MIDDLE",
                "wrapStrategy": "WRAP",
                "textFormat": {
                    "fontFamily": FONT,
                    "fontSize": 11,
                    "bold": True,
                    "foregroundColor": WHITE,
                },
            },
        ),
        _cells(
            sheet_id,
            1,
            HEADER_ROWS,
            0,
            columns,
            {
                "backgroundColor": HEADER_COLOR,
                "horizontalAlignment": "CENTER",
                "verticalAlignment": "MIDDLE",
                "wrapStrategy": "WRAP",
                "textFormat": {
                    "fontFamily": FONT,
                    "fontSize": 10,
                    "bold": False,
                    "foregroundColor": WHITE,
                },
            },
        ),
        _cells(
            sheet_id,
            HEADER_ROWS,
            last_row,
            0,
            columns,
            {
                "horizontalAlignment": "CENTER",
                "verticalAlignment": "MIDDLE",
                "textFormat": {"fontFamily": FONT, "fontSize": 10, "bold": False},
            },
        ),
        # Название товара — единственная колонка с текстом, ей нужен перенос.
        _cells(
            sheet_id,
            HEADER_ROWS,
            last_row,
            1,
            2,
            {
                "horizontalAlignment": "LEFT",
                "verticalAlignment": "MIDDLE",
                "wrapStrategy": "WRAP",
            },
        ),
        *(_merge(sheet_id, 0, HEADER_ROWS, column, column + 1) for column in single),
        *(_merge(sheet_id, 0, 1, first, last) for first, last in groups),
        *_dimensions(sheet_id, widths, last_row),
        _borders(sheet_id, 0, HEADER_ROWS, columns, bottom="SOLID_MEDIUM"),
        _borders(sheet_id, HEADER_ROWS, last_row, columns, bottom="SOLID_MEDIUM"),
        _banding(sheet_id, last_row, columns),
    ]


def _dimensions(sheet_id: int, widths: tuple[int, ...], last_row: int) -> list[dict]:
    return [
        *(
            {
                "updateDimensionProperties": {
                    "range": {
                        "sheetId": sheet_id,
                        "dimension": "COLUMNS",
                        "startIndex": index,
                        "endIndex": index + 1,
                    },
                    "properties": {"pixelSize": width},
                    "fields": "pixelSize",
                }
            }
            for index, width in enumerate(widths)
        ),
        {
            "updateDimensionProperties": {
                "range": {
                    "sheetId": sheet_id,
                    "dimension": "ROWS",
                    "startIndex": 0,
                    "endIndex": 1,
                },
                "properties": {"pixelSize": HEADER_HEIGHT},
                "fields": "pixelSize",
            }
        },
        {
            "updateDimensionProperties": {
                "range": {
                    "sheetId": sheet_id,
                    "dimension": "ROWS",
                    "startIndex": 1,
                    "endIndex": last_row,
                },
                "properties": {"pixelSize": ROW_HEIGHT},
                "fields": "pixelSize",
            }
        },
    ]


# --- форматы чисел по колонкам -------------------------------------------


def _raw_columns(worksheet: gspread.Worksheet, data_rows: int) -> list[dict]:
    last = HEADER_ROWS + data_rows
    sheet_id = worksheet.id
    return [
        _number(sheet_id, HEADER_ROWS, last, 2, 3, DATE, align="RIGHT"),
        _number(sheet_id, HEADER_ROWS, last, 3, 6, COUNT),
        _number(sheet_id, HEADER_ROWS, last, 6, 7, MONEY),
        _number(sheet_id, HEADER_ROWS, last, 7, 8, COUNT),
        _number(sheet_id, HEADER_ROWS, last, 8, 9, MONEY),
        _number(sheet_id, HEADER_ROWS, last, 9, 10, COUNT),
        _number(sheet_id, HEADER_ROWS, last, 10, 11, PERCENT),
    ]


def _report_columns(worksheet: gspread.Worksheet, data_rows: int) -> list[dict]:
    last = HEADER_ROWS + data_rows
    sheet_id = worksheet.id
    return [
        _number(sheet_id, HEADER_ROWS, last, 2, 5, COUNT),
        _number(sheet_id, HEADER_ROWS, last, 5, 6, MONEY),
        _number(sheet_id, HEADER_ROWS, last, 6, 7, COUNT),
        _number(sheet_id, HEADER_ROWS, last, 7, 8, MONEY),
        _number(sheet_id, HEADER_ROWS, last, 8, 11, PERCENT),
        _number(sheet_id, HEADER_ROWS, last, 11, 13, MONEY),
    ]


# --- элементарные запросы -------------------------------------------------


def _cells(sheet_id, first_row, last_row, first_col, last_col, fmt) -> dict:
    return {
        "repeatCell": {
            "range": {
                "sheetId": sheet_id,
                "startRowIndex": first_row,
                "endRowIndex": last_row,
                "startColumnIndex": first_col,
                "endColumnIndex": last_col,
            },
            "cell": {"userEnteredFormat": fmt},
            "fields": ",".join(f"userEnteredFormat.{key}" for key in fmt),
        }
    }


def _number(
    sheet_id,
    first_row,
    last_row,
    first_col,
    last_col,
    pattern,
    *,
    align: str = "CENTER",
) -> dict:
    """Формат чисел для диапазона колонок.

    Группировка разрядов — только через ``#,##0``: литеральный пробел
    в паттерне не повторяется и разваливается на миллионах.
    """
    return _cells(
        sheet_id,
        first_row,
        last_row,
        first_col,
        last_col,
        {
            "numberFormat": {"type": "NUMBER", "pattern": pattern},
            "horizontalAlignment": align,
        },
    )


def _merge(sheet_id, first_row, last_row, first_col, last_col) -> dict:
    return {
        "mergeCells": {
            "range": {
                "sheetId": sheet_id,
                "startRowIndex": first_row,
                "endRowIndex": last_row,
                "startColumnIndex": first_col,
                "endColumnIndex": last_col,
            },
            "mergeType": "MERGE_ALL",
        }
    }


def _product_merges(
    worksheet: gspread.Worksheet, blocks: list[tuple[int, int]]
) -> list[dict]:
    """Склеить артикул и название по всем дням товара."""
    return [
        _merge(worksheet.id, start - 1, end, column, column + 1)
        for start, end in blocks
        for column in (0, 1)
    ]


def _borders(sheet_id, first_row, last_row, columns, *, bottom: str) -> dict:
    line = {"style": "SOLID_MEDIUM"}
    return {
        "updateBorders": {
            "range": {
                "sheetId": sheet_id,
                "startRowIndex": first_row,
                "endRowIndex": last_row,
                "startColumnIndex": 0,
                "endColumnIndex": columns,
            },
            "top": line,
            "bottom": {"style": bottom},
            "left": line,
            "right": line,
            "innerVertical": {"style": "SOLID"},
        }
    }


def _banding(sheet_id, last_row, columns) -> dict:
    """Чередование строк только под шапкой.

    Полосы перекрывают заливку ячеек, поэтому диапазон начинается с данных:
    иначе вторая строка шапки становится белой, а текст на ней белый.
    """
    return {
        "addBanding": {
            "bandedRange": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": HEADER_ROWS,
                    "endRowIndex": last_row,
                    "startColumnIndex": 0,
                    "endColumnIndex": columns,
                },
                "rowProperties": {
                    "firstBandColor": BAND_COLOR,
                    "secondBandColor": WHITE,
                },
            }
        }
    }
