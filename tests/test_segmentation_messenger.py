"""Тесты сегментации с контекстом мессенджеров."""

from __future__ import annotations

from app.config import Settings
from app.services.segmentation import SegmentationService, _compact_row


def test_compact_row_includes_messenger_messages() -> None:
    row = {
        "UUID": "1",
        "Наименование": "Test",
        "_messenger_context": [
            {"channel": "telegram", "text": "Привет", "direction": "in"},
            {"channel": "whatsapp", "text": "Спасибо", "direction": "in"},
        ],
    }
    compact = _compact_row(row)
    assert compact["messages_count"] == 2
    assert len(compact["messages_sample"]) == 2


def test_heuristic_tags_use_messenger_text() -> None:
    service = SegmentationService(Settings())
    row = {
        "Наименование": "Клиент",
        "_messenger_context": [{"text": "Спасибо, всё отлично!", "channel": "whatsapp"}],
    }
    tags = service._heuristic_tags(row)
    assert tags is not None
    assert "#доволен" in tags
