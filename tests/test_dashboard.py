"""Тесты страницы дашборда."""

from __future__ import annotations

from fastapi.testclient import TestClient

import app.main as m


def test_dashboard_accepts_empty_date_query_params() -> None:
    client = TestClient(m.app)
    response = client.get("/dashboard?period=month&date_from=&date_to=")
    assert response.status_code == 200
    assert "Дашборд" in response.text or "Клиенты" in response.text


def test_dashboard_accepts_valid_custom_dates() -> None:
    client = TestClient(m.app)
    response = client.get(
        "/dashboard?period=custom&date_from=2025-01-01&date_to=2025-06-30"
    )
    assert response.status_code == 200
