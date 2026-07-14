"""Тесты страницы дашборда."""

from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient

import app.main as m
from app.crm.dashboard import DashboardService


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


def test_dashboard_compute_cached_reuses_result() -> None:
    svc = DashboardService(cache_ttl=60.0)
    rows = [
        {
            "UUID": "1",
            "Наименование": "A",
            "Тип продаж": "прямые продажи",
            "Всего заказов": 2,
            "_orders_context": [
                {"Дата": "2026-01-15", "Сумма": 100, "Статус": "новый"},
                {"Дата": "2026-02-01", "Сумма": 200, "Статус": "в работе"},
            ],
        }
    ]
    first = svc.compute_cached(rows, hub_version=1, period="month")
    second = svc.compute_cached(rows, hub_version=1, period="month")
    assert first is second
    svc.compute_cached(
        rows,
        hub_version=1,
        period="custom",
        date_from=date(2026, 1, 1),
        date_to=date(2026, 2, 28),
    )
    third = svc.compute_cached(rows, hub_version=2, period="month")
    assert third is not first
