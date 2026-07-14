"""Тесты обогащения из WhatsApp/Telegram."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.config import Settings
from app.services.excel_parser import ParsedWorkbook, enrich_with_orders
from app.services.messenger_enrichment import MessengerEnrichmentService


SAMPLE_ROW = {
    "UUID": "cp-1",
    "Наименование": "Анна Иванова",
    "Телефон": "+79991234567",
    "ТГ ник": "@anna_flowers",
    "_orders_context": [{"№": "001", "Сумма": 5000, "Комментарий": "день рождения мамы"}],
}


@pytest.mark.asyncio
async def test_fetch_client_messages_combines_channels() -> None:
    settings = Settings(
        messenger_enabled=True,
        green_api_enabled=True,
        green_api_id_instance="1",
        green_api_token="tok",
    )
    service = MessengerEnrichmentService(settings)

    with patch.object(
        service,
        "fetch_whatsapp_history",
        new=AsyncMock(
            return_value=[
                {
                    "channel": "whatsapp",
                    "direction": "in",
                    "text": "Спасибо, букет отличный!",
                    "date": "2025-06-01T12:00:00",
                }
            ]
        ),
    ), patch.object(service, "fetch_telegram_history", new=AsyncMock(return_value=[])):
        messages = await service.fetch_client_messages(SAMPLE_ROW)

    assert len(messages) == 1
    assert messages[0]["channel"] == "whatsapp"


def test_heuristic_from_messages_fills_tags() -> None:
    settings = Settings()
    service = MessengerEnrichmentService(settings)
    messages = [
        {"channel": "whatsapp", "direction": "in", "text": "Спасибо, всё супер!", "date": ""},
        {"channel": "whatsapp", "direction": "in", "text": "На день рождения жены", "date": ""},
    ]
    result = service._heuristic_from_messages(dict(SAMPLE_ROW), messages)
    assert "#доволен" in str(result.get("Теги"))
    assert "#деньрождения" in str(result.get("Теги"))
    assert result.get("_enrichment_source") == "messenger_heuristic"


def test_enrich_with_orders_matches_phone_in_code_field() -> None:
    contragents = ParsedWorkbook(
        source_type="contragents",
        rows=[
            {
                "UUID": "cp-other",
                "Наименование": "hash-name",
                "Код": "+79991234567",
                "Телефон": "+79991234567",
            }
        ],
        context_columns=["UUID", "Наименование", "Телефон", "Код"],
        segment_columns=[],
        total_rows=1,
    )
    orders = ParsedWorkbook(
        source_type="orders",
        rows=[
            {
                "№": "200",
                "Контрагент": "+79991234567",
                "_moysklad_agent_id": "",
                "_moysklad_agent_phone": "+79991234567",
                "Сумма": 2000,
            }
        ],
        context_columns=["№", "Контрагент"],
        segment_columns=[],
        total_rows=1,
    )
    enriched = enrich_with_orders(contragents, orders)
    row = enriched.rows[0]
    assert row["_orders_count"] == 1
    assert row["_orders_context"][0]["№"] == "200"


def test_enrich_with_orders_matches_moysklad_agent_id() -> None:
    contragents = ParsedWorkbook(
        source_type="contragents",
        rows=[{"UUID": "agent-99", "Наименование": "Клиент А"}],
        context_columns=["UUID", "Наименование"],
        segment_columns=[],
        total_rows=1,
    )
    orders = ParsedWorkbook(
        source_type="orders",
        rows=[
            {
                "№": "100",
                "Контрагент": "Другой",
                "_moysklad_agent_id": "agent-99",
                "Сумма": 1000,
            }
        ],
        context_columns=["№", "Контрагент"],
        segment_columns=[],
        total_rows=1,
    )
    enriched = enrich_with_orders(contragents, orders)
    row = enriched.rows[0]
    assert row["_orders_count"] == 1
    assert row["_orders_context"][0]["№"] == "100"


def test_enrich_with_orders_matches_normalized_phone_in_name() -> None:
    contragents = ParsedWorkbook(
        source_type="contragents",
        rows=[{
            "UUID": "cp-phone",
            "Наименование": "89603002010",
            "Телефон": "+79603002010",
        }],
        context_columns=["UUID", "Наименование", "Телефон"],
        segment_columns=[],
        total_rows=1,
    )
    orders = ParsedWorkbook(
        source_type="orders",
        rows=[{
            "№": "00042",
            "Контрагент": "Речанова Дарья",
            "_moysklad_agent_id": "cp-phone",
            "Канал продаж": "Витрина",
        }],
        context_columns=["№", "Контрагент", "Канал продаж"],
        segment_columns=[],
        total_rows=1,
    )
    enriched = enrich_with_orders(contragents, orders)
    row = enriched.rows[0]
    assert row["_orders_count"] == 1
    assert row["_orders_context"][0]["№"] == "00042"


def test_orders_for_client_row_matches_normalized_org_name() -> None:
    from app.services.excel_parser import orders_for_client_row

    client = {
        "UUID": "cp-arenda",
        "Наименование": "Аренда",
        "Тип контрагента": "Юридическое лицо",
    }
    order_rows = [{
        "№": "1001",
        "Контрагент": "ООО Аренда",
        "_moysklad_agent_id": "cp-arenda",
        "Сумма": 5000,
        "Дата": "2026-03-01",
    }]
    found = orders_for_client_row(client, order_rows)
    assert len(found) == 1
    assert found[0]["№"] == "1001"


@pytest.mark.asyncio
async def test_attach_messages_continues_when_telegram_sync_fails() -> None:
    settings = Settings(
        messenger_enabled=True,
        telegram_enabled=True,
        telegram_bot_token="123:abc",
    )
    service = MessengerEnrichmentService(settings)

    with patch.object(
        service,
        "sync_telegram_inbox",
        new=AsyncMock(side_effect=httpx.ConnectTimeout("timeout")),
    ), patch.object(
        service,
        "fetch_client_messages",
        new=AsyncMock(return_value=[]),
    ):
        rows = await service.attach_messages([dict(SAMPLE_ROW)])

    assert len(rows) == 1
    assert rows[0]["UUID"] == "cp-1"


@pytest.mark.asyncio
async def test_enrich_all_without_messengers_uses_orders_heuristic() -> None:
    settings = Settings()
    service = MessengerEnrichmentService(settings)

    with patch.object(service, "fetch_client_messages", new=AsyncMock(return_value=[])):
        results = await service.enrich_all([SAMPLE_ROW])

    assert len(results) == 1
    assert results[0].get("_enrichment_source") == "orders_only"


@pytest.mark.asyncio
async def test_clients_export_endpoint() -> None:
    from fastapi.testclient import TestClient

    import app.main as m

    hub = m.hub
    hub.set_workbook(
        ParsedWorkbook(
            source_type="contragents",
            rows=[SAMPLE_ROW],
            context_columns=["UUID", "Наименование"],
            segment_columns=[],
            total_rows=1,
            meta={"source": "moysklad"},
        ),
        None,
    )

    client = TestClient(m.app)
    response = client.get("/download/clients/xlsx")
    assert response.status_code == 200
    assert "spreadsheetml" in response.headers.get("content-type", "")
