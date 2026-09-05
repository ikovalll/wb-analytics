"""Выгрузка отзывов в файлы и подборка для языковой модели."""

from __future__ import annotations

import csv
import json

from wb.export import write_csv, write_digest, write_json
from wb.feedbacks import Feedback, ProductFeedbacks


def feedback(feedback_id, rating, text=""):
    return Feedback(
        id=feedback_id,
        nm_id=1,
        created_at="2026-01-01",
        rating=rating,
        text=text,
        pros="",
        cons="",
        user_name="Покупатель",
        size="",
        color="",
        order_status="buyout",
        has_photo=False,
        has_video=False,
        answer="",
    )


def product(*feedbacks):
    return ProductFeedbacks(nm_id=1, feedbacks=list(feedbacks))


def test_json_содержит_отзывы_и_статистику(tmp_path):
    path = write_json(
        [product(feedback("a", 5, "Топ"), feedback("b", 1, "Брак"))],
        tmp_path / "feedbacks.json",
    )

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload[0]["total"] == 2
    assert payload[0]["average_rating"] == 3.0
    assert len(payload[0]["feedbacks"]) == 2


def test_csv_пишется_с_разделителем_точка_с_запятой(tmp_path):
    path = write_csv([product(feedback("a", 5, "Топ"))], tmp_path / "feedbacks.csv")

    with path.open(encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle, delimiter=";"))
    assert rows[0]["id"] == "a"
    assert rows[0]["rating"] == "5"


def test_csv_читается_экселем(tmp_path):
    """utf-8-sig: без BOM Excel открывает кириллицу кракозябрами."""
    path = write_csv([product(feedback("a", 5, "Тест"))], tmp_path / "feedbacks.csv")

    assert path.read_bytes().startswith(b"\xef\xbb\xbf")


def test_подборка_берёт_всю_критику(tmp_path):
    """Критики мало, и именно она отвечает на вопрос «на что жалуются»."""
    critical = [feedback(f"c{i}", 2, f"Плохо {i}") for i in range(50)]
    path = write_digest(
        [product(*critical)], tmp_path / "digest.md", positive_sample=10
    )

    text = path.read_text(encoding="utf-8")
    assert all(f"Плохо {i}" in text for i in range(50))


def test_подборка_ограничивает_похвалу(tmp_path):
    positive = [feedback(f"p{i}", 5, f"Хорошо {i}") for i in range(50)]
    path = write_digest(
        [product(*positive)], tmp_path / "digest.md", positive_sample=10
    )

    text = path.read_text(encoding="utf-8")
    assert "Хорошо 49" in text, "берутся самые свежие"
    assert "Хорошо 0" not in text


def test_подборка_объявляет_состав(tmp_path):
    """Модель должна знать про смещение, иначе завысит долю негатива."""
    items = [
        feedback("c", 1, "Плохо"),
        *(feedback(f"p{i}", 5, "Хорошо") for i in range(5)),
    ]
    path = write_digest([product(*items)], tmp_path / "digest.md", positive_sample=2)

    text = path.read_text(encoding="utf-8")
    assert "вся критика (1-3*) — 1" in text
    assert "похвала (4-5*) — 2 из 5" in text


def test_отзывы_без_текста_в_подборку_не_идут(tmp_path):
    path = write_digest(
        [product(feedback("a", 5), feedback("b", 5, "Есть текст"))],
        tmp_path / "digest.md",
        positive_sample=10,
    )

    text = path.read_text(encoding="utf-8")
    assert "Отзывов с текстом: 1" in text
    assert "Есть текст" in text


def test_товар_без_текстовых_отзывов_не_ломает_подборку(tmp_path):
    path = write_digest(
        [product(feedback("a", 5))], tmp_path / "digest.md", positive_sample=10
    )

    assert "(текстовых отзывов нет)" in path.read_text(encoding="utf-8")


def test_каталог_создаётся_при_записи(tmp_path):
    path = write_json([product(feedback("a", 5))], tmp_path / "нет" / "ещё" / "f.json")

    assert path.exists()
