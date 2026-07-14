from __future__ import annotations

from app.services.fields import (
    AI_NO_DATA_LABEL,
    empty_fillable_columns,
    finalize_ai_coverage_row,
    is_empty_cell,
)
from app.services.export_format import client_cell_value


def test_empty_fillable_columns_skips_filled_values() -> None:
    row = {
        "UUID": "1",
        "Наименование": "Иван",
        "Телефон": "+7999",
        "ИНН": "",
        "E-mail": None,
    }
    empty = empty_fillable_columns(row)
    assert "UUID" not in empty
    assert "Наименование" not in empty
    assert "Телефон" not in empty
    assert "ИНН" in empty
    assert "E-mail" in empty


def test_finalize_marks_unknown_after_ai_processing() -> None:
    row = {
        "UUID": "1",
        "Наименование": "Иван",
        "Телефон": "+7999",
        "ИНН": "",
        "E-mail": "",
        "_ai_processed": True,
        "_ai_fields": ["Группы"],
        "Группы": "премиум",
    }
    result = finalize_ai_coverage_row(row)
    assert "ИНН" in result["_ai_unknown_fields"]
    assert "E-mail" in result["_ai_unknown_fields"]
    assert "Группы" not in result["_ai_unknown_fields"]
    assert "Телефон" not in result["_ai_unknown_fields"]


def test_finalize_skips_when_not_processed() -> None:
    row = {"UUID": "1", "ИНН": "", "_ai_processed": False}
    result = finalize_ai_coverage_row(row)
    assert "_ai_unknown_fields" not in result


def test_client_cell_value_returns_no_data_label() -> None:
    row = {
        "ИНН": "",
        "_ai_unknown_fields": ["ИНН"],
    }
    assert client_cell_value(row, "ИНН") == AI_NO_DATA_LABEL


def test_is_empty_cell() -> None:
    assert is_empty_cell(None) is True
    assert is_empty_cell("") is True
    assert is_empty_cell("—") is True
    assert is_empty_cell(0) is False
    assert is_empty_cell("Иван") is False
