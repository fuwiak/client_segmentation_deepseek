from __future__ import annotations

from app.config import Settings
from app.services.segmentation import SegmentationService
from app.services.fields import guess_gender


def _service() -> SegmentationService:
    # No API key -> heuristic path; tracking logic under test is backend-agnostic.
    return SegmentationService(Settings(openrouter_api_key=""))


def test_parse_ai_response_marks_only_newly_filled_fields() -> None:
    service = _service()
    rows = [
        {"UUID": "1", "Наименование": "Иван Петров", "Группы": None},
    ]
    content = (
        '{"results": [{"uuid": "1", "Группы": "премиум", '
        '"Заказчик или получатель": "Иван Петров", "Пол": "Мужской", '
        '"ТГ ник": null, "reasoning": "test", "confidence": 0.9}]}'
    )

    result = service._parse_ai_response(content, rows)[0]

    assert result["_ai_processed"] is True
    ai_fields = result["_ai_fields"]
    assert "Группы" in ai_fields
    assert "Заказчик или получатель" in ai_fields
    assert "Пол" in ai_fields
    # null value must not be marked as AI-added
    assert "ТГ ник" not in ai_fields


def test_parse_ai_response_fills_segment_columns_only() -> None:
    service = _service()
    rows = [
        {
            "UUID": "5",
            "Наименование": "ООО Ромашка",
            "ИНН": "",
            "Комментарий": "ИНН 7701234567",
        },
    ]
    content = (
        '{"results": [{"uuid": "5", "Группы": "корпоративный", '
        '"ИНН": "7701234567", "reasoning": "из комментария", "confidence": 0.8}]}'
    )

    result = service._parse_ai_response(content, rows)[0]

    assert result["Группы"] == "корпоративный"
    assert "Группы" in result["_ai_fields"]
    assert result.get("ИНН") in ("", None)
    assert "ИНН" not in result["_ai_fields"]


def test_parse_ai_response_marks_ai_returned_fields() -> None:
    service = _service()
    rows = [{"UUID": "2", "Группы": "новый", "Пол": "Женский"}]
    content = (
        '{"results": [{"uuid": "2", "Группы": "постоянный клиент", '
        '"Пол": "Женский", "reasoning": "x", "confidence": 0.5}]}'
    )

    result = service._parse_ai_response(content, rows)[0]

    assert result["Группы"] == "постоянный клиент"
    assert "Группы" in result["_ai_fields"]
    assert "Пол" in result["_ai_fields"]
    assert result["_ai_original"]["Группы"] == "новый"
    assert "Пол" not in result.get("_ai_original", {})


def test_parse_ai_response_invalid_json_falls_back_to_heuristic() -> None:
    service = _service()
    rows = [{"UUID": "3", "Наименование": "Мария"}]

    result = service._parse_ai_response("not a json", rows)[0]

    assert result["_ai_processed"] is False
    assert "_ai_fields" in result


def test_heuristic_row_tracks_added_fields() -> None:
    service = _service()
    row = {"UUID": "4", "Наименование": "Ольга Иванова"}

    result = service._heuristic_row(row)

    assert result["_ai_processed"] is False
    assert "Пол" in result["_ai_fields"]
    assert result["Пол"] == "Женский"


def test_heuristic_intent_summary_from_order_comment() -> None:
    service = _service()
    row = {
        "UUID": "6",
        "Наименование": "Дмитрий",
        "_orders_context": [{"Комментарий": "Букет на день рождения мамы"}],
    }
    summary = service._heuristic_intent_summary(row)
    assert summary is not None
    assert "день рождения" in summary
    assert "подарок маме" in summary


def test_heuristic_intent_summary_unknown_occasion() -> None:
    service = _service()
    row = {
        "UUID": "7",
        "_orders_context": [{"Комментарий": "стандартная доставка"}],
        "_messenger_context": [{"text": "здравствуйте", "channel": "telegram"}],
    }
    summary = service._heuristic_intent_summary(row)
    assert summary is not None
    assert "не определён" in summary


def test_apply_resolved_gender_prefers_ai_over_heuristic() -> None:
    from app.services.fields import apply_resolved_gender

    row = {
        "Заказчик или получатель": "Иван Петров",
        "_messenger_context": [{"display_name": "Иван", "text": "привет"}],
    }
    ai_fields: list[str] = []
    apply_resolved_gender(row, "Женский", ai_fields)
    assert row["Пол"] == "Женский"
    assert "Пол" in ai_fields


def test_guess_gender() -> None:
    assert guess_gender("Иван Петров") == "Мужской"
    assert guess_gender("Ольга") == "Женский"
    assert guess_gender("Саша") is None
    assert guess_gender(None) is None
