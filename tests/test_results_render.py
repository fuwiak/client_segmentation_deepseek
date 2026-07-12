from __future__ import annotations

from fastapi.testclient import TestClient

import app.main as m


def test_progress_endpoint_renders_ai_badge_when_done() -> None:
    client = TestClient(m.app)

    results = [
        {
            "Наименование": "Иван Петров",
            "Группы": "премиум",
            "Заказчик или получатель": "Иван Петров",
            "Пол": "Мужской",
            "ТГ ник": None,
            "_ai_processed": True,
            "_ai_fields": ["Группы", "Пол"],
            "_confidence": 0.9,
            "_reasoning": "тест",
        }
    ]
    m.hub.set_results(results, {"processed": 1, "total": 1, "source_type": "excel"})
    m._progress.update(status="done", done=1, total=1, error="")

    html = client.get("/segment/progress").text

    assert "AI" in html
    assert "ai-cell-new" in html
