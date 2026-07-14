from __future__ import annotations

from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient


def test_performance_headers_on_page_get() -> None:
  import app.main as m

  client = TestClient(m.app)
  response = client.get("/settings")
  assert response.status_code == 200
  assert "Server-Timing" in response.headers
  assert response.headers["Server-Timing"].startswith("app;dur=")
  assert "X-Response-Time-Ms" in response.headers


def test_settings_page_renders_without_blocking_health() -> None:
  import app.main as m

  with patch.object(m.MessengerConnector, "health", new_callable=AsyncMock) as health_mock:
    client = TestClient(m.app)
    response = client.get("/settings")
    assert response.status_code == 200
    health_mock.assert_not_called()
    assert "Проверяем подключения" in response.text


def test_segment_page_does_not_sync_moysklad() -> None:
  import app.main as m

  with patch.object(m, "_ensure_moysklad_data", new_callable=AsyncMock) as ensure_mock:
    client = TestClient(m.app)
    response = client.get("/segment")
    assert response.status_code == 200
    ensure_mock.assert_not_called()
    assert 'id="page-content"' in response.text


def test_base_template_has_htmx_app_shell() -> None:
  import app.main as m

  client = TestClient(m.app)
  response = client.get("/")
  assert response.status_code == 200
  assert 'hx-boost="true"' in response.text
  assert 'hx-target="#page-content"' in response.text
  assert 'id="page-content"' in response.text
  assert "nav-progress" in response.text


def test_clients_page_skips_relink_and_lazy_ai() -> None:
  import app.main as m

  with patch.object(m.hub, "relink_orders") as relink_mock, patch.object(
    m, "_schedule_lazy_ai", new_callable=AsyncMock
  ) as lazy_ai_mock:
    client = TestClient(m.app)
    response = client.get("/clients")
    assert response.status_code == 200
    relink_mock.assert_not_called()
    lazy_ai_mock.assert_not_called()


def test_client_orders_uses_cache_only_hydrate() -> None:
  import app.main as m
  from app.services.excel_parser import ParsedWorkbook

  hub = m.hub
  hub.set_workbook(
    ParsedWorkbook(
      source_type="contragents",
      rows=[{
        "UUID": "cp-orders-endpoint",
        "Наименование": "Тест",
        "_orders_context": [{"№": "42", "Дата": "2026-03-01", "Сумма": 1000, "Статус": "OK"}],
        "_orders_count": 1,
      }],
      context_columns=["UUID", "Наименование"],
      segment_columns=[],
      total_rows=1,
      meta={"source": "moysklad"},
    ),
    None,
  )
  with patch.object(m, "_ensure_hub_ready", new_callable=AsyncMock) as ready_mock, patch.object(
    m, "_ensure_moysklad_data", new_callable=AsyncMock
  ) as ensure_ms_mock:
    client = TestClient(m.app)
    response = client.get(
      "/clients/cp-orders-endpoint/orders",
      headers={"HX-Request": "true"},
    )
    assert response.status_code == 200
    ready_mock.assert_not_called()
    ensure_ms_mock.assert_not_called()
    assert "orders-compact" in response.text
    assert "42" in response.text
