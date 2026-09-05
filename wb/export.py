"""Выгрузка собранных отзывов в файлы:
JSON, CSV и текст дляязыковой модели."""

from __future__ import annotations

import csv
import json
from collections.abc import Iterable
from pathlib import Path

from wb.feedbacks import Feedback, ProductFeedbacks

CSV_COLUMNS = (
    "nm_id",
    "id",
    "created_at",
    "rating",
    "text",
    "pros",
    "cons",
    "user_name",
    "size",
    "color",
    "order_status",
    "has_photo",
    "has_video",
    "answer",
)


def write_json(products: Iterable[ProductFeedbacks], path: Path) -> Path:
    """Полная выгрузка: отзывы и статистика по каждому товару."""
    payload = [
        {
            "nm_id": product.nm_id,
            "total": product.total,
            "average_rating": product.average_rating,
            "rating_distribution": product.rating_distribution,
            "feedbacks": [f.as_dict() for f in product.feedbacks],
        }
        for product in products
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def write_csv(products: Iterable[ProductFeedbacks], path: Path) -> Path:
    """Плоская таблица отзывов; кодировка с BOM, чтобы открывался Excel."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS, delimiter=";")
        writer.writeheader()
        for product in products:
            for feedback in product.feedbacks:
                writer.writerow(feedback.as_dict())
    return path


def write_digest(
    products: Iterable[ProductFeedbacks],
    path: Path,
    *,
    positive_sample: int,
) -> Path:
    """Подборка отзывов для языковой модели.

    Весь массив в контекст не помещается, поэтому выборка смещена в сторону
    сигнала: критика (1-3*) берётся целиком, похвала — свежим срезом.
    Отзывы без текста опущены, их оценки учтены в распределении звёзд.
    """
    blocks: list[str] = []

    for product in products:
        header = [
            f"## Артикул {product.nm_id}",
            f"Всего отзывов: {product.total}",
            f"Средний рейтинг: {product.average_rating}",
            "Распределение оценок: "
            + ", ".join(
                f"{star}* — {count}"
                for star, count in product.rating_distribution.items()
            ),
            f"Отзывов с текстом: {len(product.with_text)}",
            "",
        ]
        critical, positive = _split_by_sentiment(product.with_text)
        shown = critical + positive[-positive_sample:]
        header.append(
            f"В подборке ниже: вся критика (1-3*) — {len(critical)}, "
            f"похвала (4-5*) — {min(len(positive), positive_sample)} "
            f"из {len(positive)}, самые свежие."
        )
        header.append("")

        lines = [_format_feedback(f) for f in shown]
        if not lines:
            lines = ["(текстовых отзывов нет)"]
        blocks.append("\n".join(header + lines))

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n\n".join(blocks) + "\n", encoding="utf-8")
    return path


def _split_by_sentiment(
    feedbacks: list[Feedback],
) -> tuple[list[Feedback], list[Feedback]]:
    """Разложить отзывы на критику (1-3*) и похвалу (4-5*)."""
    critical = [f for f in feedbacks if f.rating <= 3]
    positive = [f for f in feedbacks if f.rating >= 4]
    return critical, positive


def _format_feedback(feedback: Feedback) -> str:
    parts = [f"[{feedback.rating}*]", feedback.created_at[:10]]
    if feedback.text:
        parts.append(_flatten(feedback.text))
    if feedback.pros:
        parts.append(f"+ {_flatten(feedback.pros)}")
    if feedback.cons:
        parts.append(f"- {_flatten(feedback.cons)}")
    return " | ".join(parts)


def _flatten(value: str) -> str:
    return " ".join(value.split())
