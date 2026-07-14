"""Тесты Telegram Bot API."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.config import Settings
from app.services.telegram_bot import TelegramBotClient


@pytest.mark.asyncio
async def test_get_updates_returns_empty_on_connect_timeout() -> None:
    client = TelegramBotClient(
        Settings(telegram_enabled=True, telegram_bot_token="test-token")
    )
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = httpx.ConnectTimeout("timeout")
        result = await client.get_updates()
    assert result == []
