"""Тесты маппинга строк CRM → колонки Postgres."""

from __future__ import annotations

from decimal import Decimal

from app.db.columns import customer_row_to_db, order_row_to_db, resolve_customer_id


def test_resolve_customer_id_prefers_uuid():
    row = {"UUID": "cp-1", "_moysklad_id": "ms-1"}
    assert resolve_customer_id(row) == "cp-1"


def test_customer_row_to_db_maps_core_fields():
    row = {
        "UUID": "cp-42",
        "_moysklad_id": "cp-42",
        "Наименование": "Антон",
        "Телефон": "+79991234567",
        "E-mail": "anton@example.com",
        "Средний чек": "15000.50",
        "Всего заказов": 12,
        "Дата последнего заказа": "2026-03-15 10:00:00",
        "Группы": "VIP",
        "Тип продаж": "прямые продажи",
        "ВИП": "да",
        "Постоянный клиент": "нет",
        "_source": "moysklad",
    }
    record = customer_row_to_db(row)

    assert record["id"] == "cp-42"
    assert record["moysklad_id"] == "cp-42"
    assert record["name"] == "Антон"
    assert record["phone"] == "+79991234567"
    assert record["email"] == "anton@example.com"
    assert record["average_check"] == Decimal("15000.50")
    assert record["total_orders"] == 12
    assert record["groups_text"] == "VIP"
    assert record["sales_type"] == "прямые продажи"
    assert record["is_vip"] is True
    assert record["is_regular"] is False
    assert record["row_data"]["Наименование"] == "Антон"


def test_order_row_to_db_maps_positions():
    row = {
        "_moysklad_id": "ord-1",
        "№": "00001",
        "Контрагент": "Антон",
        "Дата": "2026-03-01",
        "Сумма": 1000000,
        "Статус": "Доставлен",
        "Канал продаж": "Instagram",
        "_moysklad_agent_id": "cp-42",
        "_positions": [{"name": "Букет роз", "quantity": 2, "price": 5000.0}],
    }
    record = order_row_to_db(row)

    assert record["id"] == "ord-1"
    assert record["order_number"] == "00001"
    assert record["customer_name"] == "Антон"
    assert record["amount"] == Decimal("1000000")
    assert record["sales_channel"] == "Instagram"
    assert len(record["positions"]) == 1
    assert record["row_data"]["№"] == "00001"
