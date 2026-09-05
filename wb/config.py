"""Настройки проекта.

Всё, что меняется между запусками, живёт в ``.env`` и превращается здесь
в один объект :class:`Settings`. Модули получают его аргументом и в
окружение сами не заглядывают.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent

load_dotenv(PROJECT_ROOT / ".env")


class ConfigError(RuntimeError):
    """Окружение задано неверно или неполно."""


@dataclass(frozen=True, slots=True)
class Settings:
    """Разобранное окружение проекта."""

    token: str
    nm_ids: tuple[int, ...]
    data_dir: Path
    feedbacks_api: str
    analytics_api: str
    page_size: int
    request_interval: float
    max_retries: int
    timeout: float
    positive_sample: int
    funnel_days: int
    spreadsheet_id: str
    sheets_credentials: Path
    sheet_raw: str
    sheet_report: str

    def require_spreadsheet(self) -> str:
        """ID таблицы; без него выгружать некуда."""
        if not self.spreadsheet_id:
            raise ConfigError(
                "Не задан WB_SPREADSHEET_ID. Это идентификатор таблицы из её "
                "адреса: docs.google.com/spreadsheets/d/<ID>/edit"
            )
        return self.spreadsheet_id


def load_settings() -> Settings:
    """Собрать настройки из окружения."""
    return Settings(
        token=_required_str("WB_TOKEN", "токен из личного кабинета WB"),
        nm_ids=_nm_ids("WB_NM_IDS"),
        data_dir=_path("WB_DATA_DIR", PROJECT_ROOT / "data"),
        feedbacks_api=_str("WB_FEEDBACKS_API", "https://feedbacks-api.wildberries.ru"),
        analytics_api=_str(
            "WB_ANALYTICS_API", "https://seller-analytics-api.wildberries.ru"
        ),
        page_size=_int("WB_PAGE_SIZE", 1000, minimum=1, maximum=5000),
        request_interval=_float("WB_REQUEST_INTERVAL", 0.7, minimum=0.0),
        max_retries=_int("WB_MAX_RETRIES", 5, minimum=1),
        timeout=_float("WB_TIMEOUT", 30.0, minimum=1.0),
        positive_sample=_int("WB_POSITIVE_SAMPLE", 300, minimum=0),
        funnel_days=_int("WB_FUNNEL_DAYS", 7, minimum=1, maximum=7),
        spreadsheet_id=_str("WB_SPREADSHEET_ID", ""),
        sheets_credentials=_path(
            "WB_SHEETS_CREDENTIALS", PROJECT_ROOT / "service_account.json"
        ),
        sheet_raw=_str("WB_SHEET_RAW", "Сырые данные"),
        sheet_report=_str("WB_SHEET_REPORT", "Отчёт"),
    )


# --- разбор отдельных значений ------------------------------------------


def _str(name: str, default: str) -> str:
    return os.getenv(name, "").strip() or default


def _required_str(name: str, hint: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ConfigError(f"Не задан {name}. Добавьте в .env строку {name}=<{hint}>.")
    return value


def _path(name: str, default: Path) -> Path:
    """Путь из окружения; относительный отсчитывается от корня проекта."""
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    path = Path(raw).expanduser()
    return path if path.is_absolute() else PROJECT_ROOT / path


def _int(
    name: str, default: int, *, minimum: int | None = None, maximum: int | None = None
) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ConfigError(f"{name}: {raw!r} — ожидается целое число.") from None
    return _in_range(name, value, minimum, maximum)


def _float(
    name: str,
    default: float,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw.replace(",", "."))
    except ValueError:
        raise ConfigError(f"{name}: {raw!r} — ожидается число.") from None
    return _in_range(name, value, minimum, maximum)


def _in_range(name, value, minimum, maximum):
    if minimum is not None and value < minimum:
        raise ConfigError(f"{name}: {value} — значение не может быть меньше {minimum}.")
    if maximum is not None and value > maximum:
        raise ConfigError(f"{name}: {value} — значение не может быть больше {maximum}.")
    return value


def _nm_ids(name: str) -> tuple[int, ...]:
    """Артикулы товаров; разделитель любой — запятая, пробел, перенос строки."""
    tokens = [chunk for chunk in os.getenv(name, "").replace(",", " ").split() if chunk]
    if not tokens:
        raise ConfigError(
            f"Не задан {name}. Добавьте в .env строку с артикулами через "
            f"запятую, например {name}=386248405,147866642."
        )

    nm_ids: list[int] = []
    for token in tokens:
        if not token.isdigit():
            raise ConfigError(
                f"{name}: {token!r} не похож на артикул — ожидается целое число."
            )
        value = int(token)
        if value not in nm_ids:
            nm_ids.append(value)
    return tuple(nm_ids)
