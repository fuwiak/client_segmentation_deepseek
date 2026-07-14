from app.services.fields import (
    apply_ai_field,
    enrich_row_computed,
    is_direct_sales_channel,
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


def test_direct_sales_channels() -> None:
    for channel in (
        "Витрина",
        "Прямые продажи",
        "Telegram",
        "WhatsApp",
        "WhatsApp/MAX",
        "https://vereskflowers.ru/",
        "Сайт vereskflowers.ru",
    ):
        assert is_direct_sales_channel(channel) is True
        assert sales_type_from_channel(channel) == "прямые продажи"


def test_marketplace_sales_channels() -> None:
    for channel in ("Яндекс.Маркет", "Ozon", "Wildberries", "Авито", "Flowwow"):
        assert is_direct_sales_channel(channel) is False
        assert sales_type_from_channel(channel) == "маркетплейс"


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
    assert enriched["Тип карала продаж"] == "маркетплейс"
    assert enriched["Тип продаж"] == "маркетплейс"


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
