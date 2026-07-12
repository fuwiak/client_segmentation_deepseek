"""Тесты формата экспорта Excel."""

from __future__ import annotations

from app.services.excel_parser import ParsedWorkbook
from app.services.export_format import export_columns, format_messenger_history, row_for_export


def test_export_columns_preserves_excel_order_and_adds_ai_fields() -> None:
    parsed = ParsedWorkbook(
        source_type="contragents",
        rows=[],
        context_columns=["Наименование", "Телефон", "Метки"],
        segment_columns=[],
        total_rows=0,
    )
    cols = export_columns(parsed)
    assert cols[:3] == ["Наименование", "Телефон", "Метки"]
    assert "Группы" in cols
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
