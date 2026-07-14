"""Тесты маппинга API Мой Склад → Excel-формат."""

from __future__ import annotations

import json
from pathlib import Path

from app.services.export_format import MOYSKLAD_EXCEL_COLUMNS, export_columns, row_for_export
from app.services.excel_parser import ParsedWorkbook
from app.services.moysklad.mapper import (
    aggregate_client_positions,
    apply_positions_to_orders,
    counterparty_to_row,
    entity_ref_id,
    order_to_row,
    position_to_item,
    positions_label,
    resolve_counterparty_phone,
)

FIXTURE = Path(__file__).parent / "fixtures" / "moysklad_counterparty.json"


def test_counterparty_phone_from_code_when_phone_empty() -> None:
    row = counterparty_to_row(
        {
            "id": "cp-code-phone",
            "name": "sdy7DN-SGPz1f-MQIU-Umd1",
            "code": "+79991234567",
            "phone": "",
        }
    )
    assert row["Телефон"] == "+79991234567"
    assert row["Код"] == "+79991234567"


def test_resolve_counterparty_phone_prefers_phone_field() -> None:
    assert resolve_counterparty_phone({"phone": "+79991112233", "code": "+79990000000"}) == "+79991112233"


def test_entity_ref_id_uses_expanded_id() -> None:
    assert entity_ref_id({"id": "cp-uuid-1", "name": "Клиент"}) == "cp-uuid-1"
    assert entity_ref_id(
        {
            "meta": {
                "href": "https://api.moysklad.ru/api/remap/1.2/entity/counterparty/cp-from-href",
            }
        }
    ) == "cp-from-href"


def test_order_to_row_uses_expanded_agent_id() -> None:
    row = order_to_row(
        {
            "id": "order-2",
            "name": "00002",
            "sum": 100000,
            "agent": {"id": "cp-uuid-2", "name": "+79991234567", "phone": "+79991234567"},
            "state": {"name": "Новый"},
        },
        {},
    )
    assert row["_moysklad_agent_id"] == "cp-uuid-2"
    assert row["_moysklad_agent_phone"] == "+79991234567"


def test_counterparty_fixture_maps_to_excel_columns() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    row = counterparty_to_row(payload)

    assert row["UUID"] == "92887aa3-5635-11ef-0a80-089c122080a9"
    assert row["Группы"] == "букет от 10 000"
    assert row["Код"] == "+12512599293"
    assert row["Телефон"] == "+12512599293"
    assert row["Тип контрагента"] == "Физическое лицо"
    assert row["Архивный"] == "нет"
    assert row["Статус"] == "Новый"
    assert "Москва" in str(row["Фактический адрес"])


def test_bank_fields_from_accounts_meta_array() -> None:
    """accounts без expand — MetaArray dict; с expand — rows."""
    row = counterparty_to_row(
        {
            "id": "cp-1",
            "name": "ООО Ромашка",
            "accounts": {"meta": {"size": 1}},
        }
    )
    assert row["БИК"] is None
    assert row["Р/с"] is None

    row = counterparty_to_row(
        {
            "id": "cp-2",
            "name": "ООО Ромашка",
            "accounts": {
                "meta": {"size": 1},
                "rows": [
                    {
                        "bic": "044525225",
                        "bankName": "Сбербанк",
                        "correspondentAccount": "30101810400000000225",
                        "accountNumber": "40702810123456789012",
                    }
                ],
            },
        }
    )
    assert row["БИК"] == "044525225"
    assert row["Банк"] == "Сбербанк"
    assert row["К/с"] == "30101810400000000225"
    assert row["Р/с"] == "40702810123456789012"

    row = counterparty_to_row(
        {
            "id": "cp-3",
            "name": "ООО Ромашка",
            "accounts": [{"bic": "044525999", "accountNumber": "40702810999"}],
        }
    )
    assert row["БИК"] == "044525999"
    assert row["Р/с"] == "40702810999"


def test_bonus_points_from_moysklad_bonus_program() -> None:
    row = counterparty_to_row({"id": "cp-bonus", "name": "Клиент", "bonusPoints": 0})
    assert row["Баллы начисленные"] == 0

    row = counterparty_to_row({"id": "cp-bonus2", "name": "Клиент", "bonusPoints": 150})
    assert row["Баллы начисленные"] == 150


def test_display_cell_value_shows_zero() -> None:
    from app.services.export_format import display_cell_value

    assert display_cell_value(0) == 0
    assert display_cell_value(None) == "—"
    assert display_cell_value(9890.0) == 9890


def test_export_columns_for_moysklad_matches_excel_plus_ai() -> None:
    parsed = ParsedWorkbook(
        source_type="contragents",
        rows=[],
        context_columns=MOYSKLAD_EXCEL_COLUMNS,
        segment_columns=[],
        total_rows=0,
        meta={"source": "moysklad"},
    )
    cols = export_columns(parsed)
    assert cols[0] == "UUID"
    assert cols[1] == "Наименование"
    assert "Группы" in cols
    assert "Заказчик или получатель" in cols
    assert "Пол" in cols
    assert "Ник в тг/вк" in cols
    assert "История переписки" in cols


def test_row_for_export_preserves_excel_structure() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    row = counterparty_to_row(payload)
    row["Заказчик или получатель"] = "Мария"
    row["Пол"] = "Женский"
    row["ТГ ник"] = "@maria"

    parsed = ParsedWorkbook(
        source_type="contragents",
        rows=[row],
        context_columns=MOYSKLAD_EXCEL_COLUMNS,
        segment_columns=[],
        total_rows=1,
        meta={"source": "moysklad"},
    )
    cols = export_columns(parsed)
    exported = row_for_export(row, cols)

    assert exported["UUID"] == row["UUID"]
    assert exported["Группы"] == "букет от 10 000"
    assert exported["Заказчик или получатель"] == "Мария"
    assert exported["Пол"] == "Женский"
    assert exported["Ник в тг/вк"] == "@maria"


def test_position_to_item_uses_assortment_name_and_code() -> None:
    item = position_to_item(
        {
            "quantity": 2,
            "price": 150000,
            "assortment": {
                "code": "00279",
                "name": "Хамелациум белый/розовый",
            },
        }
    )
    assert item["name"] == "00279 Хамелациум белый/розовый"
    assert item["quantity"] == 2
    assert item["price"] == 1500.0


def test_apply_positions_to_orders_sets_label() -> None:
    order_rows = [{"_moysklad_id": "order-1", "№": "00001"}]
    apply_positions_to_orders(
        order_rows,
        {
            "order-1": [
                {
                    "quantity": 1,
                    "price": 50000,
                    "assortment": {"code": "00279", "name": "Хамелациум белый/розовый"},
                }
            ]
        },
    )
    assert order_rows[0]["Позиции"] == "00279 Хамелациум белый/розовый"
    assert len(order_rows[0]["_positions"]) == 1


def test_aggregate_client_positions_sums_quantities() -> None:
    orders = [
        {"_positions": [{"name": "00279 Хамелациум белый/розовый", "quantity": 1}]},
        {"_positions": [{"name": "00279 Хамелациум белый/розовый", "quantity": 2}]},
    ]
    aggregated = aggregate_client_positions(orders)
    assert aggregated == [{"name": "00279 Хамелациум белый/розовый", "quantity": 3.0}]
    assert positions_label(aggregated) == "00279 Хамелациум белый/розовый (×3)"
