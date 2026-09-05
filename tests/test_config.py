"""Разбор и валидация окружения."""

from __future__ import annotations

import pytest

from wb.config import ConfigError, load_settings


def test_минимального_окружения_достаточно(minimal_env):
    settings = load_settings()

    assert settings.token == "test-token"
    assert settings.nm_ids == (1, 2)
    assert settings.page_size == 1000  # значение по умолчанию


def test_без_токена_понятная_ошибка(clean_env):
    clean_env.setenv("WB_NM_IDS", "1")

    with pytest.raises(ConfigError, match="WB_TOKEN"):
        load_settings()


def test_без_артикулов_понятная_ошибка(clean_env):
    clean_env.setenv("WB_TOKEN", "t")

    with pytest.raises(ConfigError, match="WB_NM_IDS"):
        load_settings()


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("1,2,3", (1, 2, 3)),
        ("1 2 3", (1, 2, 3)),
        ("1, 2,3 ", (1, 2, 3)),
        ("1\n2", (1, 2)),
        ("5,5,7", (5, 7)),  # дубли отбрасываются
    ],
)
def test_артикулы_принимают_любой_разделитель(clean_env, raw, expected):
    clean_env.setenv("WB_TOKEN", "t")
    clean_env.setenv("WB_NM_IDS", raw)

    assert load_settings().nm_ids == expected


def test_нечисловой_артикул_отвергается(clean_env):
    clean_env.setenv("WB_TOKEN", "t")
    clean_env.setenv("WB_NM_IDS", "123,abc")

    with pytest.raises(ConfigError, match="abc"):
        load_settings()


def test_размер_страницы_ограничен_сверху(minimal_env):
    minimal_env.setenv("WB_PAGE_SIZE", "99999")

    with pytest.raises(ConfigError, match="не может быть больше 5000"):
        load_settings()


def test_нечисловой_параметр_отвергается(minimal_env):
    minimal_env.setenv("WB_MAX_RETRIES", "много")

    with pytest.raises(ConfigError, match="ожидается целое число"):
        load_settings()


def test_дробное_значение_принимает_запятую(minimal_env):
    minimal_env.setenv("WB_REQUEST_INTERVAL", "1,5")

    assert load_settings().request_interval == 1.5


def test_относительный_путь_считается_от_корня_проекта(minimal_env):
    minimal_env.setenv("WB_DATA_DIR", "выгрузка")

    assert load_settings().data_dir.name == "выгрузка"
    assert load_settings().data_dir.is_absolute()


def test_без_id_таблицы_выгрузка_невозможна(minimal_env):
    settings = load_settings()

    with pytest.raises(ConfigError, match="WB_SPREADSHEET_ID"):
        settings.require_spreadsheet()


def test_id_таблицы_возвращается_как_есть(minimal_env):
    minimal_env.setenv("WB_SPREADSHEET_ID", "abc123")

    assert load_settings().require_spreadsheet() == "abc123"
