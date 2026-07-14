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


def test_home_page_shows_title_and_active_nav() -> None:
  import app.main as m

  client = TestClient(m.app)
  response = client.get("/")
  assert response.status_code == 200
  assert "<h1>Главная</h1>" in response.text
  assert 'data-nav-path="/" class="nav-item active"' in response.text
  assert 'data-nav-path="/" class="bottom-nav-item active"' in response.text


def test_base_template_has_htmx_app_shell() -> None:
  import app.main as m

  client = TestClient(m.app)
  response = client.get("/")
  assert response.status_code == 200
  assert 'hx-boost="true"' in response.text
  assert 'hx-target="#page-content"' in response.text
  assert 'id="page-content"' in response.text
  assert "nav-progress" in response.text
  assert 'hx-get="/messenger/sidebar"' in response.text
  assert 'hx-push-url="false"' in response.text
  assert 'id="orders-modal-loading"' in response.text
  assert 'id="orders-modal-loading" class="modal-overlay orders-modal-loading-overlay" hidden' in response.text


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


def test_client_card_drawer_tolerates_non_numeric_order_count() -> None:
  import app.main as m
  from app.services.excel_parser import ParsedWorkbook

  m.hub.set_workbook(
    ParsedWorkbook(
      source_type="contragents",
      rows=[{
        "UUID": "cp-drawer",
        "Наименование": "Тест",
        "Всего заказов": "—",
        "_orders_context": [{"№": "42", "Дата": "2026-03-01", "Сумма": 1000, "Статус": "OK"}],
      }],
      context_columns=["UUID", "Наименование"],
      segment_columns=[],
      total_rows=1,
      meta={"source": "moysklad"},
    ),
    None,
  )
  with patch.object(m, "_ensure_hub_ready", new_callable=AsyncMock):
    client = TestClient(m.app)
    response = client.get(
      "/clients/cp-drawer?drawer=1",
      headers={"HX-Request": "true"},
    )
  assert response.status_code == 200
  assert "Все заказы (1)" in response.text
  assert "rules-drawer-header" in response.text


def test_client_card_drawer_shows_ai_recommendation() -> None:
  import app.main as m
  from app.services.excel_parser import ParsedWorkbook

  m.hub.set_workbook(
    ParsedWorkbook(
      source_type="contragents",
      rows=[{
        "UUID": "cp-rec",
        "Наименование": "Аренда",
        "Тип контрагента": "Юридическое лицо",
        "Телефон": "+79001234567",
        "Всего заказов": 0,
      }],
      context_columns=["UUID", "Наименование"],
      segment_columns=[],
      total_rows=1,
      meta={"source": "moysklad"},
    ),
    None,
  )
  with patch.object(m, "_ensure_hub_ready", new_callable=AsyncMock):
    client = TestClient(m.app)
    response = client.get(
      "/clients/cp-rec?drawer=1",
      headers={"HX-Request": "true"},
    )
  assert response.status_code == 200
  assert "Рекомендация AI" in response.text
  assert "ai-recommendation" in response.text


def test_client_orders_modal_returns_all_orders_from_cache() -> None:
  import app.main as m
  from app.services.excel_parser import ParsedWorkbook

  orders_rows = [
    {
      "№": str(i),
      "Дата": f"2026-0{(i % 9) + 1}-01",
      "Сумма": 1000 * i,
      "Статус": "OK",
      "Канал продаж": "Витрина",
      "_moysklad_agent_id": "cp-modal",
    }
    for i in range(1, 6)
  ]
  m.hub.set_workbook(
    ParsedWorkbook(
      source_type="contragents",
      rows=[{
        "UUID": "cp-modal",
        "Наименование": "Модалка",
        "_orders_context": orders_rows[:20],
        "_orders_count": len(orders_rows),
      }],
      context_columns=["UUID", "Наименование"],
      segment_columns=[],
      total_rows=1,
      meta={"source": "moysklad"},
    ),
    ParsedWorkbook(
      source_type="orders",
      rows=orders_rows,
      context_columns=[],
      segment_columns=[],
      total_rows=len(orders_rows),
      meta={},
    ),
  )
  with patch.object(m, "_ensure_hub_cache_only", new_callable=AsyncMock) as cache_mock, patch.object(
    m, "_ensure_moysklad_data", new_callable=AsyncMock
  ) as ensure_ms_mock:
    client = TestClient(m.app)
    response = client.get(
      "/clients/cp-modal/orders?modal=1",
      headers={"HX-Request": "true"},
    )
    assert response.status_code == 200
    assert "orders-modal-overlay" in response.text
    assert "orders-modal-progress" not in response.text
    assert "Загружаем остальные заказы" not in response.text
    assert response.text.count("orders-compact-item") == 5
    cache_mock.assert_awaited_once()
    ensure_ms_mock.assert_not_awaited()


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
  with patch.object(m, "_ensure_hub_cache_only", new_callable=AsyncMock) as cache_mock, patch.object(
    m, "_ensure_moysklad_data", new_callable=AsyncMock
  ) as ensure_ms_mock:
    client = TestClient(m.app)
    response = client.get(
      "/clients/cp-orders-endpoint/orders",
      headers={"HX-Request": "true"},
    )
    assert response.status_code == 200
    cache_mock.assert_awaited_once()
    ensure_ms_mock.assert_not_awaited()
    assert "orders-compact" in response.text
    assert "42" in response.text
