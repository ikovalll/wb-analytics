"""Оркестрация записи в таблицу — на подставных объектах вместо Google."""

from __future__ import annotations

from datetime import date

import gspread
import pytest

from wb.funnel import DayStats, Period, ProductFunnel
from wb.sheets import publish
from wb.styling import RAW_WIDTHS, REPORT_WIDTHS

PERIOD = Period.last_days(7, today=date(2026, 9, 5))


class FakeWorksheet:
    _next_id = 0

    def __init__(self, title: str, values: list[list[str]] | None = None):
        FakeWorksheet._next_id += 1
        self.id = FakeWorksheet._next_id
        self.title = title
        self.values = values or []
        self.written: list[list[object]] = []
        self.size: tuple[int, int] | None = None

    def update(self, values, range_name, value_input_option):
        self.written = values
        self.range_name = range_name
        self.value_input_option = value_input_option

    def get_all_values(self):
        return self.written or self.values


class FakeSpreadsheet:
    url = "https://docs.google.com/spreadsheets/d/fake"

    def __init__(self, existing: list[FakeWorksheet] | None = None):
        self.sheets = list(existing or [])
        self.requests: list[dict] = []
        self.deleted: list[str] = []

    def worksheets(self):
        return list(self.sheets)

    def worksheet(self, title):
        for sheet in self.sheets:
            if sheet.title == title:
                return sheet
        raise gspread.WorksheetNotFound(title)

    def add_worksheet(self, title, rows, cols):
        sheet = FakeWorksheet(title)
        sheet.size = (rows, cols)
        self.sheets.append(sheet)
        return sheet

    def del_worksheet(self, worksheet):
        self.sheets.remove(worksheet)
        self.deleted.append(worksheet.title)

    def batch_update(self, body):
        self.requests.extend(body["requests"])


def day(date_str, buyout_sum=25_000):
    return DayStats(
        date=date_str,
        open_count=100,
        cart_count=20,
        order_count=10,
        order_sum=50_000,
        buyout_count=5,
        buyout_sum=buyout_sum,
        add_to_wishlist_count=3,
    )


def product(nm_id, buyout_sum=25_000, days=2):
    return ProductFunnel(
        nm_id=nm_id,
        title=f"Товар {nm_id}",
        vendor_code="c",
        brand_name="b",
        subject_name="s",
        currency="RUB",
        days=tuple(day(f"2026-09-0{n + 1}", buyout_sum) for n in range(days)),
    )


@pytest.fixture
def published():
    spreadsheet = FakeSpreadsheet([FakeWorksheet("Лист1")])
    publish(
        spreadsheet,
        [product(1, 100), product(2, 900), product(3, 500)],
        raw_title="Сырые данные",
        report_title="Отчёт",
    )
    return spreadsheet


def sheet(spreadsheet, title):
    return next(s for s in spreadsheet.sheets if s.title == title)


def test_создаются_ровно_два_листа(published):
    assert [s.title for s in published.sheets] == ["Сырые данные", "Отчёт"]


def test_локаль_выставляется_явно(published):
    """От локали зависит разделитель аргументов в формулах."""
    locale = next(
        request["updateSpreadsheetProperties"]["properties"]
        for request in published.requests
        if "updateSpreadsheetProperties" in request
    )

    assert locale["locale"] == "ru_RU"


def test_формулы_пишутся_как_формулы(published):
    assert sheet(published, "Отчёт").value_input_option == "USER_ENTERED"


def test_строки_отчёта_отсортированы_по_сумме_выкупов(published):
    rows = sheet(published, "Отчёт").written

    assert [row[0] for row in rows[2:]] == [2, 3, 1]


def test_сырые_данные_идут_в_порядке_запроса(published):
    """Сырьё не переставляем: это снимок ответа API, а не отчёт."""
    rows = sheet(published, "Сырые данные").written

    assert [row[0] for row in rows[2:] if row[0]] == [1, 2, 3]


def test_листы_создаются_ровно_под_данные(published):
    """Лист по умолчанию приходит с тысячей пустых строк под таблицей."""
    assert sheet(published, "Сырые данные").size == (2 + 6, 11), "шапка и 3×2 дня"
    assert sheet(published, "Отчёт").size == (2 + 3, 13)


def test_шапка_занимает_две_строки(published):
    rows = sheet(published, "Отчёт").written

    assert rows[0][0] == "Артикул"
    assert rows[1][4] == "шт."


def test_ячейки_артикула_объединяются_по_дням(published):
    """Каждый товар занимает несколько строк, артикул показан один раз."""
    merges = [
        request["mergeCells"]["range"]
        for request in published.requests
        if "mergeCells" in request
    ]
    product_merges = [
        m for m in merges if m["startColumnIndex"] == 0 and m["startRowIndex"] >= 2
    ]

    assert len(product_merges) == 3, "по одному объединению на товар"
    assert all(m["endRowIndex"] - m["startRowIndex"] == 2 for m in product_merges)


def test_у_таблиц_есть_рамки(published):
    borders = [r for r in published.requests if "updateBorders" in r]

    assert len(borders) == 4, "шапка и данные на каждом из двух листов"


def test_пустой_лист_удаляется(published):
    assert "Лист1" in published.deleted


def test_устаревший_лист_прошлой_версии_удаляется():
    stale = FakeWorksheet("Показатели", values=[["Артикул", "Показы"]])
    spreadsheet = FakeSpreadsheet([stale])

    publish(spreadsheet, [product(1)], raw_title="Сырые данные", report_title="Отчёт")

    assert "Показатели" in spreadsheet.deleted


def test_чужой_непустой_лист_не_трогаем():
    mine = FakeWorksheet("Мои заметки", values=[["не удаляй"]])
    spreadsheet = FakeSpreadsheet([mine])

    publish(spreadsheet, [product(1)], raw_title="Сырые данные", report_title="Отчёт")

    assert "Мои заметки" not in spreadsheet.deleted


def test_суммы_форматируются_с_разделителями(published):
    """Без группировки миллион нечитаем: 1843 650 вместо 1 843 650."""
    patterns = {
        request["repeatCell"]["cell"]["userEnteredFormat"]["numberFormat"]["pattern"]
        for request in published.requests
        if "numberFormat" in str(request.get("repeatCell", {}))
    }

    assert patterns == {"#,##0", "#,##0 \\₽", "0.00%", "yyyy-mm-dd"}


def test_ширины_колонок_задаются_явно(published):
    """Автоподбор растянул бы колонку с названием товара на пол-экрана."""
    widths = [
        request["updateDimensionProperties"]
        for request in published.requests
        if request.get("updateDimensionProperties", {})
        .get("range", {})
        .get("dimension")
        == "COLUMNS"
    ]

    assert len(widths) == len(RAW_WIDTHS) + len(REPORT_WIDTHS)


def test_строки_чередуются_подсветкой(published):
    banding = [request for request in published.requests if "addBanding" in request]

    assert len(banding) == 2, "по одному диапазону на лист"


def test_подсветка_не_заходит_на_шапку(published):
    """Полосы перекрывают заливку: под ними шапка стала бы белой на белом."""
    ranges = [
        request["addBanding"]["bandedRange"]["range"]
        for request in published.requests
        if "addBanding" in request
    ]

    assert all(r["startRowIndex"] == 2 for r in ranges)


def test_повторная_публикация_не_плодит_листы(published):
    publish(published, [product(1)], raw_title="Сырые данные", report_title="Отчёт")

    assert [s.title for s in published.sheets] == ["Сырые данные", "Отчёт"]
