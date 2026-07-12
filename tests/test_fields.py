from app.services.fields import apply_ai_field


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
