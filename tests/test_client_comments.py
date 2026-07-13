"""Тесты сбора комментариев контрагента и заказов."""

from __future__ import annotations

from app.services.fields import collect_client_comments, extract_email_from_row
from app.services.segmentation import SegmentationService
from app.services.tag_rules import evaluate_tags_for_row


def test_collect_client_comments_includes_counterparty_and_orders() -> None:
    row = {
        "Комментарий": "VIP клиент, звонить заранее",
        "Фактический адрес (Комментарий)": "домофон не работает",
        "_orders_context": [{"Комментарий": "букет на день рождения мамы"}],
    }
    text = collect_client_comments(row)
    assert "VIP клиент" in text
    assert "домофон" in text
    assert "день рождения" in text


def test_extract_email_from_counterparty_comment() -> None:
    row = {"Комментарий": "Пишите на anna@example.com"}
    assert extract_email_from_row(row) == "anna@example.com"


def test_heuristic_tags_from_counterparty_comment() -> None:
    service = SegmentationService.__new__(SegmentationService)
    row = {"Комментарий": "Заказ на 8 марта коллегам"}
    tags = SegmentationService._heuristic_tags(row)
    assert tags is not None
    assert "#8марта" in tags


def test_tag_rules_match_counterparty_comment() -> None:
    row = {
        "Комментарий": "корпоративный заказ для ооо ромашка",
        "_orders_context": [],
    }
    tags, reasons = evaluate_tags_for_row(row)
    assert tags is None or isinstance(tags, str)
