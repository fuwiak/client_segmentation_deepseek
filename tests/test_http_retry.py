"""Тесты retry для HTTP-клиентов."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from app.services.http_retry import request_with_retry


@pytest.mark.asyncio
async def test_request_with_retry_on_429() -> None:
    client = AsyncMock()
    ok = MagicMock(spec=httpx.Response)
    ok.status_code = 200
    ok.json.return_value = {"ok": True}

    rate_limited = MagicMock(spec=httpx.Response)
    rate_limited.status_code = 429
    rate_limited.headers = {"Retry-After": "0.01"}

    client.request = AsyncMock(side_effect=[rate_limited, ok])

    response = await request_with_retry(client, "GET", "https://example.test", max_retries=2)
    assert response.status_code == 200
    assert client.request.await_count == 2
