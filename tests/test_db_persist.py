"""Тесты сериализации значений для Postgres."""

import json

from app.services.db_persist import DbPersistService


def test_bind_column_jsonb_as_string():
    payload = {"UUID": "cp-1", "Наименование": "Test"}
    bound = DbPersistService._bind_column("row_data", payload, frozenset({"row_data"}))
    assert isinstance(bound, str)
    assert json.loads(bound)["UUID"] == "cp-1"


def test_bind_column_list_for_positions():
    payload = [{"name": "Розы", "quantity": 1}]
    bound = DbPersistService._bind_column("positions", payload, frozenset({"positions"}))
    assert isinstance(bound, str)
    assert json.loads(bound)[0]["name"] == "Розы"
