"""Тесты кэша сообщений Telegram."""

from __future__ import annotations

from app.config import Settings
from app.services.cache import InMemoryCache, CacheService
from app.services.messenger_store import MessengerMessageStore, parse_telegram_update


def test_parse_telegram_update_extracts_username_and_text() -> None:
    update = {
        "update_id": 10,
        "message": {
            "message_id": 1,
            "date": 1710000000,
            "text": "Здравствуйте, нужен букет на 8 марта",
            "from": {"id": 1, "username": "anna_flowers", "first_name": "Anna"},
            "chat": {"id": 100, "username": "anna_flowers", "type": "private"},
        },
    }
    parsed = parse_telegram_update(update)
    assert parsed is not None
    assert parsed["channel"] == "telegram"
    assert parsed["username"] == "anna_flowers"
    assert "8 марта" in parsed["text"]


def test_messages_for_row_matches_by_tg_nick() -> None:
    settings = Settings(messenger_enabled=True, telegram_enabled=True, telegram_bot_token="x")
    cache = CacheService(settings)
    cache._backend = InMemoryCache()
    store = MessengerMessageStore(settings, cache)
    store._append_message(
        {
            "channel": "telegram",
            "text": "Спасибо!",
            "username": "anna_flowers",
            "date": "1",
        }
    )
    matched = store.messages_for_row({"ТГ ник": "@anna_flowers"})
    assert len(matched) == 1
    assert matched[0]["text"] == "Спасибо!"
