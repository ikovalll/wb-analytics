"""Содержимое листов Google Таблицы: строки и формулы (без обращения к Google)."""

from __future__ import annotations

from wb.funnel import DayStats, ProductFunnel
from wb.sheets import (
    FIRST_DATA_ROW,
    RAW_HEADER_SUB,
    RAW_HEADER_TOP,
    REPORT_HEADER_SUB,
    REPORT_HEADER_TOP,
    _blocks,
    _buyout_sum,
    _raw_rows,
    _report_rows,
)

RAW = "Сырые данные"


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


WEEK = [day(f"2026-09-0{n}") for n in range(1, 8)]


# --- лист сырых данных ---------------------------------------------------


def test_шапка_занимает_две_строки():
    rows = _raw_rows([product(1, day("2026-09-01"))])

    assert rows[0] == list(RAW_HEADER_TOP)
    assert rows[1] == list(RAW_HEADER_SUB)
    assert len(rows) == FIRST_DATA_ROW


def test_строка_на_каждый_день_каждого_товара():
    rows = _raw_rows(
        [
            product(1, day("2026-09-01"), day("2026-09-02")),
            product(2, day("2026-09-01")),
        ]
    )

    assert len(rows) == 2 + 3


def test_артикул_заполнен_только_в_первой_строке_блока():
    """Остальные ячейки колонки объединяются с ней при оформлении."""
    rows = _raw_rows([product(1, day("2026-09-01"), day("2026-09-02"))])

    assert rows[2][0] == 1
    assert rows[3][0] == ""
    assert rows[3][2] == "2026-09-02", "дата при этом на месте"


def test_в_сырые_данные_идут_числа_а_не_расчёты():
    rows = _raw_rows([product(1, day("2026-09-01", open_count=2530))])

    assert rows[2][3] == 2530


def test_конверсия_в_сырых_данных_это_формула():
    """ТЗ требует считать формулами в самой таблице, а не в скрипте."""
    rows = _raw_rows([product(1, day("2026-09-01"), day("2026-09-02"))])

    assert rows[2][-1] == "=IFERROR(F3/D3;0)"
    assert rows[3][-1] == "=IFERROR(F4/D4;0)"


# --- границы блоков ------------------------------------------------------


def test_блоки_идут_подряд_от_первой_строки_данных():
    products = [product(1, *WEEK), product(2, *WEEK), product(3, *WEEK)]

    assert _blocks(products) == {1: (3, 9), 2: (10, 16), 3: (17, 23)}


def test_блок_учитывает_разное_число_дней():
    products = [product(1, day("2026-09-01")), product(2, *WEEK)]

    assert _blocks(products) == {1: (3, 3), 2: (4, 10)}


# --- лист отчёта ---------------------------------------------------------


def test_отчёт_начинается_с_двухуровневой_шапки():
    products = [product(1, *WEEK)]
    rows = _report_rows(products, RAW, _blocks(products))

    assert rows[0] == list(REPORT_HEADER_TOP)
    assert rows[1] == list(REPORT_HEADER_SUB)


def test_суммы_считаются_по_диапазону_строк_товара():
    """SUMIFS по колонке артикула не подходит: в ней объединённые ячейки."""
    products = [product(1, *WEEK)]
    rows = _report_rows(products, RAW, _blocks(products))

    assert rows[2][2] == "=SUM('Сырые данные'!D3:D9)"


def test_диапазоны_подстраиваются_под_положение_блока():
    products = [product(1, *WEEK), product(2, *WEEK)]
    rows = _report_rows(products, RAW, _blocks(products))

    assert rows[3][2] == "=SUM('Сырые данные'!D10:D16)"


def test_конверсия_считается_тремя_агрегатами():
    products = [product(1, *WEEK)]
    row = _report_rows(products, RAW, _blocks(products))[2]

    assert row[8] == "=AVERAGE('Сырые данные'!K3:K9)"
    assert row[9] == "=MIN('Сырые данные'!K3:K9)"
    assert row[10] == "=MAX('Сырые данные'!K3:K9)"


def test_средний_чек_защищён_от_деления_на_ноль():
    products = [product(1, *WEEK)]
    row = _report_rows(products, RAW, _blocks(products))[2]

    assert row[11] == "=IFERROR(H3/G3;0)", "по выкупам"
    assert row[12] == "=IFERROR(F3/E3;0)", "по заказам"


def test_ширина_строки_совпадает_с_шапкой():
    products = [product(1, *WEEK)]
    rows = _report_rows(products, RAW, _blocks(products))

    assert len(rows[2]) == len(REPORT_HEADER_TOP)


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
