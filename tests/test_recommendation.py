from app.services.segmentation import SegmentationService


def test_heuristic_recommendation_for_birthday_tag() -> None:
    service = SegmentationService.__new__(SegmentationService)
    row = {
        "Теги": "#деньрождения",
        "Саммари": "Поводы: день рождения.",
        "Телефон": "+79001234567",
        "Всего заказов": 3,
    }
    rec = SegmentationService._heuristic_recommendation(row)
    assert rec is not None
    assert "рождения" in rec.lower()
