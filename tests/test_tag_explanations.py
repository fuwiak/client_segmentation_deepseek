from app.services.tag_explanations import explain_single_tag, explain_tags_for_row


def test_explain_vip_from_avg_check() -> None:
    row = {"Теги": "#vip", "Средний чек": 18000}
    reasons = explain_tags_for_row(row)
    assert "#vip" in reasons
    assert "15 000" in reasons["#vip"]


def test_explain_postoyanny_from_orders() -> None:
    row = {"Теги": "#постоянный", "Всего заказов": 5}
    reasons = explain_tags_for_row(row)
    assert "5 заказов" in reasons["#постоянный"]


def test_explain_dovolen_from_messenger() -> None:
    row = {
        "Теги": "#доволен",
        "_messenger_context": [{"text": "Спасибо, букет отличный!"}],
    }
    reasons = explain_tags_for_row(row)
    assert "переписке" in reasons["#доволен"].lower()


def test_explain_uses_ai_reasoning_as_fallback() -> None:
    row = {
        "Теги": "#custom",
        "_reasoning": "Клиент часто заказывает к 8 марта",
    }
    reasons = explain_tags_for_row(row)
    assert reasons["#custom"] == "Клиент часто заказывает к 8 марта"


def test_explain_single_tag_denrozhdeniya_from_order() -> None:
    row = {
        "_orders_context": [{"Комментарий": "Букет на день рождения мамы"}],
    }
    reason = explain_single_tag("#деньрождения", row)
    assert reason is not None
    assert "день рождения" in reason.lower()
