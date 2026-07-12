from app.services.tag_rules import (
    DEFAULT_TAG_RULES,
    evaluate_tags_for_row,
    rules_from_form,
)


def test_evaluate_vip_from_avg_check() -> None:
    tags, reasons = evaluate_tags_for_row({"Средний чек": 20000, "Всего заказов": 1})
    assert "#vip" in (tags or "")
    assert "#vip" in reasons


def test_evaluate_postoyanny_from_orders() -> None:
    tags, reasons = evaluate_tags_for_row({"Всего заказов": 5})
    assert "#постоянный" in (tags or "")
    assert "5 заказов" in reasons["#постоянный"]


def test_rules_from_form_updates_description() -> None:
    key = DEFAULT_TAG_RULES[0].key
    rules = rules_from_form(
        {
            f"rule_{key}_enabled": "on",
            f"rule_{key}_tag": "#постоянный",
            f"rule_{key}_title": "Постоянный",
            f"rule_{key}_description": "Новое правило: 3+ заказа",
            f"rule_{key}_threshold": "3",
        }
    )
    assert rules[0].description == "Новое правило: 3+ заказа"
    assert rules[0].threshold == 3
