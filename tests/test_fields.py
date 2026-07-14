import pytest

from app.services.fields import (
    SALES_CHANNEL_TYPE_DIRECT,
    SALES_CHANNEL_TYPE_HYBRID,
    SALES_CHANNEL_TYPE_MARKETPLACE,
    apply_ai_field,
    channel_type_from_channel,
    client_status_from_orders,
    enrich_row_computed,
    is_direct_sales_channel,
    is_marketplace_channel,
    order_count_for_row,
    sales_channel_type_for_row,
    sales_type_from_channel,
)
from app.services.moysklad.mapper import order_to_row


def test_apply_ai_field_stores_original_when_changed() -> None:
    row: dict = {"Группы": "старый"}
    ai_fields: list[str] = []
    apply_ai_field(row, "Группы", "новый", ai_fields)
    assert row["Группы"] == "новый"
    assert row["_ai_original"]["Группы"] == "старый"
    assert ai_fields == ["Группы"]


def test_apply_ai_field_skips_original_when_empty_before() -> None:
    row: dict = {"Группы": None}
    ai_fields: list[str] = []
    apply_ai_field(row, "Группы", "новый", ai_fields)
    assert row["Группы"] == "новый"
    assert "_ai_original" not in row


def test_marketplace_channels() -> None:
    for channel in (
        "Яндекс.Маркет",
        "Ozon",
        "Flowwow",
        "FLOW WOW",
        "Flawery",
        "Флавери",
        "Wildberries",
        "Авито",
    ):
        assert is_marketplace_channel(channel) is True
        assert is_direct_sales_channel(channel) is False
        assert channel_type_from_channel(channel) == SALES_CHANNEL_TYPE_MARKETPLACE
        assert sales_type_from_channel(channel) == SALES_CHANNEL_TYPE_MARKETPLACE


def test_direct_sales_channels() -> None:
    for channel in (
        "Витрина",
        "Telegram",
        "WhatsApp",
        "WhatsApp/MAX",
        "Прямые продажи",
        "Сайт vereskflowers.ru",
        "https://vereskflowers.ru/",
    ):
        assert is_direct_sales_channel(channel) is True
        assert is_marketplace_channel(channel) is False
        assert channel_type_from_channel(channel) == SALES_CHANNEL_TYPE_DIRECT
        assert sales_type_from_channel(channel) == SALES_CHANNEL_TYPE_DIRECT


def test_sales_channel_type_marketplace_if_any_order_not_direct() -> None:
    row = {
        "UUID": "1",
        "_orders_context": [
            {"Канал продаж": "Ozon"},
            {"Канал продаж": "Витрина"},
        ],
        "_order_channels_all": ["Ozon", "Витрина"],
    }
    assert sales_channel_type_for_row(row) == SALES_CHANNEL_TYPE_MARKETPLACE


def test_sales_channel_type_direct_only_for_whitelist_channels() -> None:
    row = {
        "UUID": "2",
        "_order_channels_all": [
            "Telegram",
            "WhatsApp/MAX",
            "Витрина",
            "Прямые продажи",
            "Сайт vereskflowers.ru",
        ],
    }
    assert sales_channel_type_for_row(row) == SALES_CHANNEL_TYPE_DIRECT


def test_sales_channel_type_marketplace_for_missing_channel() -> None:
    row = {
        "UUID": "3",
        "_order_channels_all": ["Витрина", ""],
    }
    assert sales_channel_type_for_row(row) == SALES_CHANNEL_TYPE_MARKETPLACE


@pytest.mark.parametrize(
    ("orders", "expected"),
    [
        (0, "новый"),
        (1, "новый"),
        (2, "повторный"),
        (3, "постоянный"),
        (10, "постоянный"),
    ],
)
def test_client_status_from_orders(orders: int, expected: str) -> None:
    row = {"Всего заказов": orders}
    assert client_status_from_orders(row) == expected
    assert order_count_for_row(row) == orders


def test_order_count_prefers_orders_context_over_zero_stored() -> None:
    row = {"_orders_count": 0, "Всего заказов": 0, "_orders_context": [{"№": "1"}]}
    assert order_count_for_row(row) == 1


def test_enrich_row_computed_sets_client_status() -> None:
    row = {"UUID": "1", "_orders_count": 5, "Статус": "Новый"}
    enriched = enrich_row_computed(row)
    assert enriched["Статус"] == "постоянный"
    assert enriched["Постоянный клиент"] == "да"


def test_enrich_row_computed_uses_order_sales_channel() -> None:
    row = {
        "UUID": "1",
        "_orders_context": [
            {
                "Дата": "2026-06-23T19:04:00",
                "Канал продаж": "Ozon",
            }
        ],
    }
    enriched = enrich_row_computed(row)
    assert enriched["Канал продаж"] == "Ozon"
    assert enriched["Тип канала продаж"] == SALES_CHANNEL_TYPE_MARKETPLACE
    assert enriched["Тип продаж"] == SALES_CHANNEL_TYPE_MARKETPLACE


def test_order_to_row_maps_sales_channel() -> None:
    row = order_to_row(
        {
            "id": "43e4bf7d-3961-11ef-0a80-09d400192095",
            "name": "00011",
            "moment": "2025-06-01T12:00:00.000",
            "sum": 150000,
            "salesChannel": {"name": "Витрина"},
            "agent": {"meta": {"href": "https://api.moysklad.ru/api/remap/1.2/entity/counterparty/cp-1"}},
        },
        {"cp-1": "Клиент"},
    )
    assert row["№"] == "00011"
    assert row["Канал продаж"] == "Витрина"


def test_order_to_row_resolves_sales_channel_by_id() -> None:
    channel_id = "61d6519a-ec0b-11ee-0a80-1751000827ea"
    row = order_to_row(
        {
            "id": "order-1",
            "name": "24255345",
            "sum": 0,
            "salesChannel": {
                "meta": {
                    "href": f"https://api.moysklad.ru/api/remap/1.2/entity/saleschannel/{channel_id}",
                }
            },
            "agent": {"id": "cp-1", "name": "Клиент"},
        },
        {"cp-1": "Клиент"},
        {channel_id: "Flowwow"},
    )
    assert row["Канал продаж"] == "Flowwow"
