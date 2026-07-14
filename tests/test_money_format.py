from app.services.export_format import format_money_rub


def test_format_money_rub_uses_space_and_r_suffix() -> None:
    assert format_money_rub(5760) == "5 760 р."
    assert format_money_rub(5760.0) == "5 760 р."
    assert format_money_rub(150) == "150 р."
    assert format_money_rub(None) == "—"
