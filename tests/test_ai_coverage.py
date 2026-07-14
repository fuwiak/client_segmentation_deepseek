from __future__ import annotations

from app.services.fields import (
    AI_NO_DATA_LABEL,
    empty_fillable_columns,
    finalize_ai_coverage_row,
    is_empty_cell,
)
from app.services.export_format import (
    AI_RUNNING_LABEL,
    build_clients_query,
    client_cell_state,
    client_cell_value,
    sort_client_rows,
)


def test_empty_fillable_columns_skips_filled_values() -> None:
    row = {
        "UUID": "1",
        "Наименование": "Иван",
        "Телефон": "+7999",
        "Группы": "vip",
        "Заказчик или получатель": "",
        "ТГ ник": None,
    }
    empty = empty_fillable_columns(row)
    assert "UUID" not in empty
    assert "Наименование" not in empty
    assert "Телефон" not in empty
    assert "Группы" not in empty
    assert "Заказчик или получатель" in empty
    assert "ТГ ник" in empty


def test_finalize_marks_unknown_after_ai_processing() -> None:
    row = {
        "UUID": "1",
        "Наименование": "Иван",
        "Телефон": "+7999",
        "Заказчик или получатель": "",
        "ТГ ник": "",
        "_ai_processed": True,
        "_ai_fields": ["Группы"],
        "Группы": "премиум",
    }
    result = finalize_ai_coverage_row(row)
    assert "Заказчик или получатель" in result["_ai_unknown_fields"]
    assert "ТГ ник" in result["_ai_unknown_fields"]
    assert "Группы" not in result["_ai_unknown_fields"]
    assert "Телефон" not in result["_ai_unknown_fields"]


def test_finalize_skips_when_not_processed() -> None:
    row = {"UUID": "1", "ИНН": "", "_ai_processed": False}
    result = finalize_ai_coverage_row(row)
    assert "_ai_unknown_fields" not in result


def test_client_cell_value_returns_no_data_label() -> None:
    row = {
        "ТГ ник": "",
        "_ai_unknown_fields": ["ТГ ник"],
    }
    assert client_cell_value(row, "ТГ ник") == AI_NO_DATA_LABEL


def test_client_cell_state_running_before_ai() -> None:
    row = {"ТГ ник": "", "_ai_processed": False}
    assert client_cell_state(row, "ТГ ник") == "running"
    assert client_cell_value(row, "ТГ ник") == AI_RUNNING_LABEL


def test_client_cell_state_empty_after_ai() -> None:
    row = {"Канал продаж": "Ozon", "_ai_processed": True}
    assert client_cell_state(row, "Канал продаж") == "value"


def test_is_empty_cell() -> None:
    assert is_empty_cell(None) is True
    assert is_empty_cell("") is True
    assert is_empty_cell("—") is True
    assert is_empty_cell(0) is False
    assert is_empty_cell("Иван") is False
