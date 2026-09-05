"""HTTP-клиент Wildberries Seller API: авторизация, троттлинг, повторы."""

from __future__ import annotations

import logging
import time
from typing import Any

import requests

logger = logging.getLogger(__name__)

RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})


class WildberriesError(RuntimeError):
    """Ошибка API: неверный запрос, нет доступа или исчерпаны повторы."""


class WildberriesClient:
    """Сессия к API Wildberries.

    Токен уходит в ``Authorization`` без префикса ``Bearer``: со стандартной
    схемой WB отвечает 401.
    """

    def __init__(
        self,
        token: str,
        *,
        min_interval: float = 0.7,
        max_retries: int = 5,
        timeout: float = 30.0,
    ) -> None:
        self._session = requests.Session()
        self._session.headers.update(
            {"Authorization": token, "Accept": "application/json"}
        )
        self._min_interval = min_interval
        self._max_retries = max_retries
        self._timeout = timeout
        self._last_request_at = 0.0

    def get(self, url: str, params: dict[str, Any] | None = None) -> Any:
        """GET-запрос; возвращает распакованную полезную нагрузку."""
        return self._request("GET", url, params=params)

    def post(self, url: str, json: Any) -> Any:
        """POST-запрос с телом в JSON."""
        return self._request("POST", url, json=json)

    def close(self) -> None:
        self._session.close()

    def __enter__(self) -> WildberriesClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # --- внутреннее ----------------------------------------------------

    def _request(self, method: str, url: str, **kwargs: Any) -> Any:
        """Выполнить запрос, повторяя его при лимитах и сбоях сети."""
        backoff = 2.0
        last_error = "неизвестная ошибка"

        for attempt in range(1, self._max_retries + 1):
            self._throttle()
            try:
                response = self._session.request(
                    method, url, timeout=self._timeout, **kwargs
                )
            except requests.RequestException as exc:
                last_error = f"сетевая ошибка: {exc}"
                logger.warning(
                    "%s %s — %s, повтор %d/%d через %.0f c",
                    method,
                    url,
                    last_error,
                    attempt,
                    self._max_retries,
                    backoff,
                )
                time.sleep(backoff)
                backoff *= 2
                continue

            if response.status_code in RETRYABLE_STATUSES:
                delay = self._retry_delay(response, backoff)
                last_error = f"HTTP {response.status_code}"
                logger.warning(
                    "%s %s — %s, повтор %d/%d через %.0f c",
                    method,
                    url,
                    last_error,
                    attempt,
                    self._max_retries,
                    delay,
                )
                time.sleep(delay)
                backoff *= 2
                continue

            if response.status_code == 401:
                raise WildberriesError(
                    "401: токен не принят. Проверьте, что он передан целиком "
                    "и без префикса Bearer."
                )
            if response.status_code == 403:
                raise WildberriesError(
                    "403: у токена нет нужной категории доступа. "
                    "Это правится в личном кабинете WB, а не в коде."
                )
            if not response.ok:
                raise WildberriesError(
                    f"HTTP {response.status_code}: {response.text[:500]}"
                )

            return self._unwrap(response)

        raise WildberriesError(
            f"{method} {url}: не удалось выполнить за {self._max_retries} "
            f"попыток, последняя ошибка — {last_error}"
        )

    def _throttle(self) -> None:
        """Выдержать паузу между запросами,
        чтобы не ловить 429 на ровном месте."""
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_request_at = time.monotonic()

    @staticmethod
    def _retry_delay(response: requests.Response, fallback: float) -> float:
        """Пауза перед повтором: из Retry-After, иначе накопленная."""
        header = response.headers.get("Retry-After")
        if header and header.isdigit():
            return float(header)
        return fallback

    @staticmethod
    def _unwrap(response: requests.Response) -> Any:
        """Достать полезную нагрузку из конверта ответа.

        Отзывы отвечают объектом ``{data, error, errorText}`` и умеют вернуть
        HTTP 200 с ``error: true`` внутри; аналитика отдаёт данные как есть.
        """

        try:
            payload = response.json()
        except ValueError as exc:
            raise WildberriesError(
                f"ответ не является JSON: {response.text[:200]}"
            ) from exc

        if isinstance(payload, dict) and "error" in payload:
            if payload.get("error"):
                raise WildberriesError(
                    payload.get("errorText") or "API вернуло error: true"
                )
            return payload.get("data")
        return payload
