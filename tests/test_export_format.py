"""Тесты формата экспорта Excel."""

from __future__ import annotations

from app.services.excel_parser import ParsedWorkbook
from app.services.export_format import (
    build_clients_query,
    client_cell_value,
    collect_group_counts,
    export_columns,
    format_messenger_history,
    row_for_export,
    row_groups,
    sort_client_rows,
)


def test_export_columns_preserves_excel_order_and_adds_ai_fields() -> None:
    parsed = ParsedWorkbook(
        source_type="contragents",
        rows=[],
        context_columns=["UUID", "Наименование", "Группы", "Телефон"],
        segment_columns=[],
        total_rows=0,
    )
    cols = export_columns(parsed)
    assert cols[:4] == ["UUID", "Наименование", "Группы", "Телефон"]
    assert "Пол" in cols
    assert "Ник в тг/вк" in cols
    assert "История переписки" in cols


def test_row_for_export_maps_tg_nick_and_history() -> None:
    row = {
        "Наименование": "Anna",
        "ТГ ник": "@anna",
        "Группы": "премиум",
        "_messenger_context": [
            {"channel": "telegram", "direction": "in", "text": "Привет"},
        ],
    }
    columns = ["Наименование", "Ник в тг/вк", "Группы", "История переписки"]
    exported = row_for_export(row, columns)
    assert exported["Ник в тг/вк"] == "@anna"
    assert exported["Группы"] == "премиум"
    assert "Привет" in exported["История переписки"]


def test_format_messenger_history_limits_lines() -> None:
    messages = [{"channel": "wa", "direction": "in", "text": f"msg{i}"} for i in range(15)]
    text = format_messenger_history(messages, limit=10)
    assert text.count("msg") == 10


def test_build_clients_query_skips_empty_params() -> None:
    query = build_clients_query(sales_filter="direct", tag="vip", group="премиум", q="", phone="7999")
    assert "filter=direct" in query
    assert "tag=vip" in query
    assert "group=" in query
    assert "phone=7999" in query
    assert "q=" not in query


def test_row_groups_splits_composite_values() -> None:
    row = {"Группы": "премиум, постоянный клиент/маркетплейс"}
    assert row_groups(row) == ["премиум", "постоянный клиент", "маркетплейс"]


def test_collect_group_counts() -> None:
    rows = [
        {"Группы": "VIP, постоянный"},
        {"Группы": "VIP"},
        {"Группы": "новый"},
    ]
    counts = collect_group_counts(rows)
    assert counts[0]["name"] == "VIP"
    assert counts[0]["count"] == 2
    names = {item["name"] for item in counts}
    assert names == {"VIP", "постоянный", "новый"}


def test_sort_client_rows_numeric() -> None:
    rows = [
        {"Наименование": "A", "Всего заказов": 5},
        {"Наименование": "B", "Всего заказов": 1},
        {"Наименование": "C", "Всего заказов": 10},
    ]
    sorted_rows = sort_client_rows(rows, "Всего заказов", "asc")
    assert [r["Наименование"] for r in sorted_rows] == ["B", "A", "C"]


def test_merge_enriched_rows_preserves_moysklad_sales_channel() -> None:
    from app.services.export_format import merge_enriched_rows

    base = [{
        "UUID": "1",
        "Наименование": "Клиент",
        "_orders_context": [{"Дата": "2026-06-23T19:04:00", "Канал продаж": "Ozon"}],
        "Канал продаж": "Ozon",
        "Тип канала продаж": "маркетплейс",
    }]
    enriched = [{
        "UUID": "1",
        "Наименование": "Клиент",
        "_ai_processed": True,
        "_ai_unknown_fields": ["Канал продаж", "Тип канала продаж", "ТГ ник"],
        "Группы": "премиум",
    }]
    merged = merge_enriched_rows(base, enriched, key_fn=lambda r: r["UUID"])
    assert merged[0]["Канал продаж"] == "Ozon"
    assert merged[0]["Тип канала продаж"] == "маркетплейс"
    assert "Канал продаж" not in (merged[0].get("_ai_unknown_fields") or [])
    assert client_cell_value(merged[0], "Канал продаж") == "Ozon"
