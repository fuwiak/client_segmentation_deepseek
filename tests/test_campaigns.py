"""Тесты Telegram-рассылок."""

from __future__ import annotations

import pytest

from app.crm.campaigns import CampaignService, resolve_telegram_chat_id


def test_resolve_telegram_chat_id_from_username_and_index() -> None:
    assert resolve_telegram_chat_id({"tg": "@alice"}) == "@alice"
    assert resolve_telegram_chat_id(
        {"tg": "bob"},
        messenger_index={
            "by_username": {"bob": [{"chat_id": 42}]},
        },
    ) == 42
    assert resolve_telegram_chat_id(
        {"phone": "+79001234567"},
        messenger_index={
            "by_phone": {"9001234567": [{"chat_id": 99}]},
        },
    ) == 99
    assert resolve_telegram_chat_id({"phone": "+79001112233"}) is None


@pytest.mark.asyncio
async def test_send_telegram_demo_when_bot_disabled() -> None:
    class FakeRepo:
        pass

    class DisabledTg:
        enabled = False

        async def send_message(self, *args, **kwargs):
            raise AssertionError("should not send when disabled")

    svc = CampaignService(FakeRepo())  # type: ignore[arg-type]
    draft = await svc.create_draft(
        title="TG test",
        mode="manual",
        channel="telegram",
        message="Привет!",
        clients=[
            {"UUID": "1", "Наименование": "Аня", "ТГ ник": "@anya", "Телефон": "+79001112233"},
        ],
    )
    result = await svc.send_telegram(
        draft["id"],
        telegram_client=DisabledTg(),
        recipient_ids=["1"],
    )
    assert result is not None
    assert result["recipients"][0]["send_status"] == "demo"
    assert result["sent_count"] == 1


@pytest.mark.asyncio
async def test_send_telegram_real_when_enabled() -> None:
    class FakeRepo:
        pass

    calls: list[tuple] = []

    class EnabledTg:
        enabled = True

        async def send_message(self, chat_id, text, *, parse_mode=None):
            calls.append((chat_id, text, parse_mode))
            return {"ok": True}

    svc = CampaignService(FakeRepo())  # type: ignore[arg-type]
    draft = await svc.create_draft(
        title="TG live",
        mode="manual",
        channel="telegram",
        message="Букет к 8 марта",
        clients=[
            {"UUID": "2", "Наименование": "Боря", "ТГ ник": "@borya", "Телефон": "+79002223344"},
        ],
        messenger_index={"by_username": {"borya": [{"chat_id": 777}]}},
    )
    result = await svc.send_telegram(
        draft["id"],
        telegram_client=EnabledTg(),
        messenger_index={"by_username": {"borya": [{"chat_id": 777}]}},
    )
    assert result is not None
    assert result["recipients"][0]["send_status"] == "sent"
    assert calls == [(777, "Букет к 8 марта", None)]


@pytest.mark.asyncio
async def test_create_draft_skips_clients_without_telegram() -> None:
    class FakeRepo:
        pass

    svc = CampaignService(FakeRepo())  # type: ignore[arg-type]
    draft = await svc.create_draft(
        title="TG only",
        mode="manual",
        channel="telegram",
        message="Hi",
        clients=[
            {"UUID": "1", "Наименование": "С TG", "ТГ ник": "@ok", "Телефон": "+79001112233"},
            {"UUID": "2", "Наименование": "Только email", "E-mail": "a@b.c", "Телефон": ""},
        ],
    )
    assert len(draft["recipients"]) == 1
    assert draft["recipients"][0]["id"] == "1"
    assert draft["skipped_no_tg"] == 1


@pytest.mark.asyncio
async def test_campaigns_persist_via_cache() -> None:
    class FakeRepo:
        pass

    class MemCache:
        def __init__(self) -> None:
            self.saved: list | None = None

        async def get_campaigns(self):
            return self.saved

        async def save_campaigns(self, payload):
            self.saved = list(payload)

    cache = MemCache()
    svc = CampaignService(FakeRepo(), cache=cache)  # type: ignore[arg-type]
    await svc.create_draft(
        title="Persist",
        mode="manual",
        channel="telegram",
        message="x",
        clients=[{"UUID": "1", "Наименование": "A", "ТГ ник": "@a", "Телефон": "+79001112233"}],
    )
    assert cache.saved is not None
    assert len(cache.saved) == 1

    svc2 = CampaignService(FakeRepo(), cache=cache)  # type: ignore[arg-type]
    listed = await svc2.list_campaigns()
    assert len(listed) == 1
    assert listed[0]["title"] == "Persist"
