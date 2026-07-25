"""Тесты логина и Telegram-канала."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.auth import auth_required, is_public_path, verify_credentials
from app.config import Settings, get_settings
from app.crm.campaigns import CampaignService


def test_verify_credentials() -> None:
    settings = Settings(
        auth_enabled=True,
        auth_username="admin",
        auth_password="secret",
    )
    assert verify_credentials(settings, "admin", "secret") is True
    assert verify_credentials(settings, "admin", "wrong") is False
    assert auth_required(settings) is True
    assert auth_required(Settings(auth_enabled=True, auth_password="")) is False


def test_public_paths() -> None:
    assert is_public_path("/login") is True
    assert is_public_path("/health") is True
    assert is_public_path("/health/ready") is True
    assert is_public_path("/static/style.css") is True
    assert is_public_path("/clients") is False


def test_login_page_renders() -> None:
    get_settings.cache_clear()
    from fastapi.testclient import TestClient
    import app.main as m

    client = TestClient(m.app)
    resp = client.get("/login")
    assert resp.status_code == 200
    assert "password" in resp.text.lower() or "Пароль" in resp.text


@pytest.mark.asyncio
async def test_send_telegram_channel_post() -> None:
    class FakeRepo:
        pass

    calls: list[str] = []

    class Tg:
        enabled = True
        channel_configured = True
        channel_id = "@iris_news"

        async def send_to_channel(self, text, *, parse_mode=None, channel_id=None):
            calls.append(text)
            return {"ok": True}

    svc = CampaignService(FakeRepo())  # type: ignore[arg-type]
    draft = await svc.create_draft(
        title="Канал",
        mode="manual",
        channel="telegram_channel",
        message="Акция 8 марта",
        clients=[],
    )
    result = await svc.send_telegram(draft["id"], telegram_client=Tg())
    assert result is not None
    assert result["channel_post_status"] == "sent"
    assert calls == ["Акция 8 марта"]


@pytest.mark.asyncio
async def test_telegram_get_chat_and_channel_send() -> None:
    from app.services.telegram_bot import TelegramBotClient

    settings = Settings(
        telegram_enabled=True,
        telegram_bot_token="123:abc",
        telegram_channel_id="@test_channel",
    )
    client = TelegramBotClient(settings)
    assert client.channel_configured is True

    with patch("httpx.AsyncClient") as mock_cls:
        instance = mock_cls.return_value
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=None)
        mock_resp = AsyncMock(status_code=200)
        mock_resp.json = lambda: {
            "ok": True,
            "result": {"id": -1001, "title": "News", "username": "test_channel"},
        }
        instance.get = AsyncMock(return_value=mock_resp)
        post_resp = AsyncMock(status_code=200)
        post_resp.json = lambda: {"ok": True, "result": {"message_id": 1}}
        instance.post = AsyncMock(return_value=post_resp)
        chat = await client.get_chat("@test_channel")
        assert chat["ok"] is True
        sent = await client.send_to_channel("hello")
        assert sent["ok"] is True
