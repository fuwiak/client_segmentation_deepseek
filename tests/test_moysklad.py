"""Тесты интеграции Мой Склад."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import Response

from app.config import Settings
from app.services.data_hub import DataHub
from app.services.moysklad.client import MoySkladClient
from app.services.moysklad.mapper import (
    counterparty_to_row,
    customer_from_counterparty,
    order_to_row,
)
from app.services.moysklad.push import (
    build_ai_tags,
    merge_counterparty_tags,
    push_segments_to_moysklad,
)
from app.services.moysklad.sync import sync_moysklad_to_hub


SAMPLE_CP = {
    "id": "cp-uuid-1",
    "name": "Иван Петров",
    "phone": "+79991234567",
    "email": "ivan@example.com",
    "tags": ["VIP", "Розница"],
    "archived": False,
    "externalCode": "001",
}

SAMPLE_ORDER = {
    "id": "order-uuid-1",
    "name": "00001",
    "moment": "2025-06-01T12:00:00.000",
    "sum": 150000,
    "description": "Букет роз",
    "agent": {
        "meta": {"href": "https://api.moysklad.ru/api/remap/1.2/entity/counterparty/cp-uuid-1"},
        "name": "Иван Петров",
    },
    "state": {"name": "Новый"},
}


def test_counterparty_to_row_maps_fields() -> None:
    row = counterparty_to_row(SAMPLE_CP)
    assert row["UUID"] == "cp-uuid-1"
    assert row["Наименование"] == "Иван Петров"
    assert row["Телефон"] == "+79991234567"
    assert row["Группы"] == "VIP, Розница"
    assert row["_moysklad_id"] == "cp-uuid-1"
    assert row["_moysklad_tags"] == ["VIP", "Розница"]


def test_build_ai_tags_from_segmentation_row() -> None:
    tags = build_ai_tags(
        {
            "Группы": "премиум",
            "Теги": "#vip #деньрождения",
        }
    )
    assert tags == ["crm:премиум", "crm:vip", "crm:деньрождения"]


def test_merge_counterparty_tags_preserves_existing() -> None:
    merged = merge_counterparty_tags(
        ["VIP", "crm:старый"],
        {"Группы": "постоянный клиент", "Теги": "#доволен"},
    )
    assert merged == ["VIP", "crm:постоянный клиент", "crm:доволен"]


def test_order_to_row_converts_sum_from_kopecks() -> None:
    row = order_to_row(SAMPLE_ORDER, {"cp-uuid-1": "Иван Петров"})
    assert row["№"] == "00001"
    assert row["Контрагент"] == "Иван Петров"
    assert row["Сумма"] == 1500.0
    assert row["Статус"] == "Новый"
    assert row["_moysklad_agent_id"] == "cp-uuid-1"


def test_customer_from_counterparty() -> None:
    customer = customer_from_counterparty(SAMPLE_CP)
    assert customer.id == "cp-uuid-1"
    assert customer.phone == "+79991234567"
    assert customer.source.value == "moysklad"
    assert "VIP" in customer.preferences


@pytest.mark.asyncio
async def test_push_segments_to_moysklad_updates_counterparties() -> None:
    client = MagicMock()
    client.enabled = True
    client.update_counterparty_groups = AsyncMock(return_value={"id": "cp-uuid-1"})

    results = [
        {
            "UUID": "cp-uuid-1",
            "Наименование": "Иван Петров",
            "_moysklad_id": "cp-uuid-1",
            "_moysklad_tags": ["VIP"],
            "Группы": "премиум",
            "Теги": "#доволен",
        },
        {
            "UUID": "excel-only",
            "Наименование": "Без МС",
            "Группы": "новый",
            "_source": "excel",
        },
    ]

    result = await push_segments_to_moysklad(client, results)

    assert result.success is True
    assert result.updated == 1
    assert result.skipped == 1
    client.update_counterparty_groups.assert_awaited_once_with(
        "cp-uuid-1",
        ["VIP", "crm:премиум", "crm:доволен"],
    )


@pytest.mark.asyncio
async def test_sync_moysklad_to_hub_populates_data_hub() -> None:
    client = MagicMock()
    client.enabled = True
    client.get_entity_count = AsyncMock(return_value=1)
    client.fetch_all_counterparties = AsyncMock(return_value=[SAMPLE_CP])
    client.fetch_all_customer_orders = AsyncMock(return_value=[SAMPLE_ORDER])

    hub = DataHub()
    result = await sync_moysklad_to_hub(client, hub, max_counterparties=10, max_orders=10)

    assert result.success is True
    assert result.counterparties_count == 1
    assert result.orders_count == 1
    assert hub.parsed is not None
    assert len(hub.parsed.rows) == 1
    assert hub.parsed.rows[0]["Наименование"] == "Иван Петров"
    assert hub.parsed.rows[0]["Всего заказов"] == 1
    assert hub.parsed.rows[0]["Средний чек"] == 1500.0
    assert hub.parsed.meta["source"] == "moysklad"
    assert hub.orders_parsed is not None
    assert len(hub.orders_parsed.rows) == 1


@pytest.mark.asyncio
async def test_moysklad_settings_page_renders() -> None:
    from fastapi.testclient import TestClient

    import app.main as m

    client = TestClient(m.app)
    response = client.get("/settings/moysklad")
    assert response.status_code == 200
    html = response.text
    assert "Мой Склад" in html
    assert "MOYSKLAD_API_TOKEN" in html
    assert "MOYSKLAD_SYNC_LIMIT" in html
    assert 'hx-get="/moysklad/status"' in html


@pytest.mark.asyncio
async def test_moysklad_client_pagination() -> None:
    settings = Settings(
        moysklad_api_token="test-token",
        moysklad_enabled=True,
    )
    client = MoySkladClient(settings)

    responses = [
        {"rows": [{"id": "1", "name": "A"}, {"id": "2", "name": "B"}], "meta": {"size": 2}},
        {"rows": [{"id": "1", "name": "A"}], "meta": {"size": 2}},
    ]
    call_idx = {"n": 0}

    async def fake_get(url: str, **kwargs):  # noqa: ANN003
        payload = responses[call_idx["n"]]
        call_idx["n"] += 1
        mock_resp = MagicMock(spec=Response)
        mock_resp.status_code = 200
        mock_resp.json.return_value = payload
        mock_resp.raise_for_status = MagicMock()
        return mock_resp

    with patch("app.services.moysklad.client.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get = fake_get
        mock_client_cls.return_value = mock_client

        rows = await client.fetch_all_counterparties(max_rows=200)
        assert len(rows) == 2
        assert rows[0]["id"] == "1"
        assert rows[1]["id"] == "2"
        count = await client.get_entity_count("/entity/counterparty")
        assert count == 2
