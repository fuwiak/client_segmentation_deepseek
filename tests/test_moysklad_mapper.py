"""Тесты маппинга API Мой Склад → Excel-формат."""

from __future__ import annotations

import json
from pathlib import Path

from app.services.export_format import MOYSKLAD_EXCEL_COLUMNS, export_columns, row_for_export
from app.services.excel_parser import ParsedWorkbook
from app.services.moysklad.mapper import counterparty_to_row

FIXTURE = Path(__file__).parent / "fixtures" / "moysklad_counterparty.json"


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
