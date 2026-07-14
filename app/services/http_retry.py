"""Повтор HTTP-запросов при rate limit и временных ошибках."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_RETRY_STATUSES = frozenset({429, 502, 503, 504})


def _retry_delay_seconds(response: httpx.Response | None, attempt: int) -> float:
    if response is not None:
        raw = response.headers.get("Retry-After")
        if raw:
            try:
                return max(float(raw), 0.5)
            except ValueError:
                pass
    return min(0.5 * (2**attempt), 30.0)


async def request_with_retry(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    max_retries: int = 4,
    retry_statuses: frozenset[int] = _RETRY_STATUSES,
    **kwargs: Any,
) -> httpx.Response:
    last_response: httpx.Response | None = None
    last_error: Exception | None = None

    for attempt in range(max_retries + 1):
        try:
            response = await client.request(method, url, **kwargs)
            if response.status_code not in retry_statuses:
                return response
            last_response = response
            if attempt >= max_retries:
                break
            delay = _retry_delay_seconds(response, attempt)
            logger.warning(
                "HTTP %s for %s %s, retry %s/%s in %.1fs",
                response.status_code,
                method,
                url,
                attempt + 1,
                max_retries,
                delay,
            )
            await asyncio.sleep(delay)
        except httpx.HTTPError as exc:
            last_error = exc
            if attempt >= max_retries:
                raise
            delay = _retry_delay_seconds(None, attempt)
            logger.warning(
                "HTTP error for %s %s, retry %s/%s in %.1fs: %s",
                method,
                url,
                attempt + 1,
                max_retries,
                delay,
                exc,
            )
            await asyncio.sleep(delay)

    if last_response is not None:
        last_response.raise_for_status()
    if last_error is not None:
        raise last_error
    raise RuntimeError(f"HTTP request failed without response: {method} {url}")
