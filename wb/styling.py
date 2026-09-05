"""Внешний вид листов Google Таблицы: шапка, ширины, полосы, форматы чисел."""

from __future__ import annotations

import gspread

#: Ширины колонок в пикселях. Заданы явно, а не автоподбором: длинные
#: названия товаров иначе растягивают колонку на пол-экрана.
RAW_WIDTHS = (110, 300, 100, 90, 100, 100, 130, 100, 130, 110, 90)
REPORT_WIDTHS = (110, 300, 100, 110, 110, 150, 110, 150, 110, 130, 130, 170, 170)

HEADER_COLOR = {"red": 0.18, "green": 0.25, "blue": 0.33}
BAND_COLOR = {"red": 0.96, "green": 0.96, "blue": 0.97}
WHITE = {"red": 1.0, "green": 1.0, "blue": 1.0}

COUNT = "#,##0"
MONEY = "#,##0 \\₽"
PERCENT = "0.00%"


def apply(
    spreadsheet: gspread.Spreadsheet,
    raw: gspread.Worksheet,
    report: gspread.Worksheet,
    *,
    last_row: int,
) -> None:
    """Оформить оба листа одним пакетом запросов.

    Внешний вид задаётся только здесь: листы пересоздаются при каждом
    запуске, и ручные настройки следующий прогон не переживут.
    """

    def raw_columns(columns: str, pattern: str) -> dict:
        return _number_format(raw, columns, pattern, first_row=1)

    def report_columns(columns: str, pattern: str) -> dict:
        return _number_format(report, columns, pattern, first_row=1, last_row=last_row)

    requests = [
        *_layout(raw, header_row=0, widths=RAW_WIDTHS, frozen=1),
        raw_columns("D:F", COUNT),
        raw_columns("G", MONEY),
        raw_columns("H", COUNT),
        raw_columns("I", MONEY),
        raw_columns("J", COUNT),
        raw_columns("K", PERCENT),
        *_layout(report, header_row=0, widths=REPORT_WIDTHS, frozen=1),
        report_columns("C:E", COUNT),
        report_columns("F", MONEY),
        report_columns("G", COUNT),
        report_columns("H", MONEY),
        report_columns("I:K", PERCENT),
        report_columns("L:M", MONEY),
    ]

    spreadsheet.batch_update({"requests": requests})


def _layout(
    worksheet: gspread.Worksheet,
    *,
    header_row: int,
    widths: tuple[int, ...],
    frozen: int,
) -> list[dict]:
    """Шапка, закрепление, ширины колонок и чередование строк."""
    sheet_id = worksheet.id
    return [
        {
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": header_row,
                    "endRowIndex": header_row + 1,
                    "endColumnIndex": len(widths),
                },
                "cell": {
                    "userEnteredFormat": {
                        "backgroundColor": HEADER_COLOR,
                        "horizontalAlignment": "CENTER",
                        "verticalAlignment": "MIDDLE",
                        "wrapStrategy": "WRAP",
                        "textFormat": {"bold": True, "foregroundColor": WHITE},
                    }
                },
                "fields": "userEnteredFormat",
            }
        },
        {
            "updateSheetProperties": {
                "properties": {
                    "sheetId": sheet_id,
                    "gridProperties": {"frozenRowCount": frozen},
                },
                "fields": "gridProperties.frozenRowCount",
            }
        },
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
            "addBanding": {
                "bandedRange": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": header_row,
                        "endColumnIndex": len(widths),
                    },
                    "rowProperties": {
                        "headerColor": HEADER_COLOR,
                        "firstBandColor": WHITE,
                        "secondBandColor": BAND_COLOR,
                    },
                }
            }
        },
    ]


def _number_format(
    worksheet: gspread.Worksheet,
    columns: str,
    pattern: str,
    *,
    first_row: int,
    last_row: int | None = None,
) -> dict:
    """Формат чисел для колонок вида ``"G"`` или ``"D:F"``.

    Группировка разрядов — только через ``#,##0``: литеральный пробел
    в паттерне не повторяется и разваливается на миллионах.
    """
    first, _, last = columns.partition(":")
    range_ = {
        "sheetId": worksheet.id,
        "startRowIndex": first_row,
        "startColumnIndex": ord(first) - ord("A"),
        "endColumnIndex": ord(last or first) - ord("A") + 1,
    }
    if last_row is not None:
        range_["endRowIndex"] = last_row
    return {
        "repeatCell": {
            "range": range_,
            "cell": {
                "userEnteredFormat": {
                    "numberFormat": {"type": "NUMBER", "pattern": pattern}
                }
            },
            "fields": "userEnteredFormat.numberFormat",
        }
    }
