"""Тесты компактного отображения заказов."""

from app.services.export_format import compact_orders_for_display


def test_compact_orders_sorted_newest_first():
    orders = [
        {"№": "001", "Дата": "2026-01-10", "Сумма": 1000, "Статус": "OK"},
        {"№": "002", "Дата": "2026-03-15", "Сумма": 50000, "Статус": "OK", "Позиции": "Розы ×10"},
    ]
    compact = compact_orders_for_display(orders)
    assert compact[0]["number"] == "002"
    assert compact[0]["amount"] == "50 000 р."
    assert compact[0]["positions"] == "Розы ×10"
    assert compact[1]["number"] == "001"


def test_compact_orders_truncates_long_text():
    orders = [
        {
            "№": "003",
            "Дата": "2026-02-01",
            "Сумма": 100,
            "Комментарий": "x" * 120,
        }
    ]
    compact = compact_orders_for_display(orders)
    assert compact[0]["has_comment"] is True
    assert len(compact[0]["comment"]) <= 60
    assert compact[0]["comment"].endswith("…")


def test_compact_orders_includes_sales_channel():
    orders = [
        {
            "№": "24255345",
            "Дата": "2026-06-08",
            "Сумма": 0,
            "Статус": "Новый",
            "Канал продаж": "Flowwow",
        }
    ]
    compact = compact_orders_for_display(orders)
    assert compact[0]["channel"] == "Flowwow"
