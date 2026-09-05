"""Формирование строк и формул для Google Таблицы (без обращения к Google)."""

from __future__ import annotations

from datetime import date

from wb.funnel import DayStats, Period, ProductFunnel
from wb.sheets import (
    FIRST_REPORT_ROW,
    METRICS_HEADER,
    RAW_HEADER,
    _buyout_sum,
    _raw_rows,
    _report_rows,
)


def day(date_str, **overrides):
    values = {
        "date": date_str,
        "open_count": 100,
        "cart_count": 20,
        "order_count": 10,
        "order_sum": 50_000,
        "buyout_count": 5,
        "buyout_sum": 25_000,
        "add_to_wishlist_count": 3,
    } | overrides
    return DayStats(**values)


def product(nm_id, *days, title="Товар"):
    return ProductFunnel(
        nm_id=nm_id,
        title=title,
        vendor_code="c",
        brand_name="b",
        subject_name="s",
        currency="RUB",
        days=tuple(days),
    )


PERIOD = Period.last_days(7, today=date(2026, 9, 5))


# --- лист сырых данных ---------------------------------------------------


def test_строка_на_каждый_день_каждого_товара():
    rows = _raw_rows(
        [
            product(1, day("2026-09-01"), day("2026-09-02")),
            product(2, day("2026-09-01")),
        ]
    )

    assert rows[0] == list(RAW_HEADER)
    assert len(rows) == 1 + 3


def test_в_сырые_данные_идут_числа_а_не_расчёты():
    rows = _raw_rows([product(1, day("2026-09-01", open_count=2530))])

    assert rows[1][3] == 2530


def test_конверсия_в_сырых_данных_это_формула():
    """ТЗ требует считать формулами в самой таблице, а не в скрипте."""
    rows = _raw_rows([product(1, day("2026-09-01"))])

    assert rows[1][-1] == "=IFERROR(F2/D2;0)"


def test_формулы_ссылаются_на_свою_строку():
    rows = _raw_rows([product(1, day("2026-09-01"), day("2026-09-02"))])

    assert rows[1][-1].endswith("F2/D2;0)")
    assert rows[2][-1].endswith("F3/D3;0)")


# --- лист отчёта ---------------------------------------------------------


def test_отчёт_начинается_с_шапки():
    rows = _report_rows([product(1, day("2026-09-01"))], "Сырые данные", data_rows=1)

    assert rows[0] == list(METRICS_HEADER)


def test_строки_отчёта_идут_сразу_после_шапки():
    rows = _report_rows([product(1, day("2026-09-01"))], "Сырые данные", data_rows=1)

    assert len(rows) == FIRST_REPORT_ROW
    assert rows[-1][0] == 1


def test_суммы_считаются_формулой_sumifs():
    rows = _report_rows([product(1, day("2026-09-01"))], "Сырые данные", data_rows=21)

    показы = rows[FIRST_REPORT_ROW - 1][2]
    assert показы == (
        "=SUMIFS('Сырые данные'!$D$2:$D$22;'Сырые данные'!$A$2:$A$22;$A2)"
    )


def test_диапазоны_подстраиваются_под_объём_данных():
    rows = _report_rows([product(1, day("2026-09-01"))], "Сырые данные", data_rows=9)

    assert "$D$2:$D$10" in rows[FIRST_REPORT_ROW - 1][2]


def test_конверсия_считается_тремя_агрегатами():
    rows = _report_rows([product(1, day("2026-09-01"))], "Сырые данные", data_rows=21)
    row = rows[FIRST_REPORT_ROW - 1]

    assert row[8].startswith("=AVERAGEIFS(")
    assert row[9].startswith("=MINIFS(")
    assert row[10].startswith("=MAXIFS(")


def test_средний_чек_защищён_от_деления_на_ноль():
    rows = _report_rows([product(1, day("2026-09-01"))], "Сырые данные", data_rows=21)
    row = rows[FIRST_REPORT_ROW - 1]

    assert row[11] == "=IFERROR(H2/G2;0)", "по выкупам"
    assert row[12] == "=IFERROR(F2/E2;0)", "по заказам"


def test_ширина_строки_совпадает_с_шапкой():
    rows = _report_rows([product(1, day("2026-09-01"))], "Сырые данные", data_rows=21)

    assert len(rows[FIRST_REPORT_ROW - 1]) == len(METRICS_HEADER)


# --- сортировка ----------------------------------------------------------


def test_сумма_выкупов_складывается_по_дням():
    assert (
        _buyout_sum(
            product(
                1, day("2026-09-01", buyout_sum=100), day("2026-09-02", buyout_sum=50)
            )
        )
        == 150
    )


def test_товары_упорядочены_по_сумме_выкупов_по_убыванию():
    products = [
        product(1, day("2026-09-01", buyout_sum=100)),
        product(2, day("2026-09-01", buyout_sum=900)),
        product(3, day("2026-09-01", buyout_sum=500)),
    ]

    ordered = sorted(products, key=_buyout_sum, reverse=True)

    assert [p.nm_id for p in ordered] == [2, 3, 1]
