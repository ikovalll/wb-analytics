"""Общие приспособления для тестов."""

from __future__ import annotations

import pytest

#: Переменные, которые проект читает из окружения. Тесты стартуют с чистого
#: листа, иначе на результат влиял бы .env разработчика.
WB_VARS = (
    "WB_TOKEN",
    "WB_NM_IDS",
    "WB_DATA_DIR",
    "WB_FEEDBACKS_API",
    "WB_ANALYTICS_API",
    "WB_PAGE_SIZE",
    "WB_REQUEST_INTERVAL",
    "WB_MAX_RETRIES",
    "WB_TIMEOUT",
    "WB_POSITIVE_SAMPLE",
    "WB_FUNNEL_DAYS",
    "WB_SPREADSHEET_ID",
    "WB_SHEETS_CREDENTIALS",
    "WB_SHEET_RAW",
    "WB_SHEET_REPORT",
)


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    """Убрать из окружения всё, что проект мог бы подхватить из .env."""
    for name in WB_VARS:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


@pytest.fixture
def minimal_env(clean_env: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    """Минимум, при котором настройки собираются успешно."""
    clean_env.setenv("WB_TOKEN", "test-token")
    clean_env.setenv("WB_NM_IDS", "1,2")
    return clean_env
