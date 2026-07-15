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


def test_dynamic_pages_disable_browser_cache() -> None:
  import app.main as m

  client = TestClient(m.app)
  response = client.get("/settings", headers={"HX-Request": "true"})
  assert response.status_code == 200
  assert response.headers["Cache-Control"] == "no-store, max-age=0"
  assert response.headers["Pragma"] == "no-cache"
  assert response.headers["Expires"] == "0"
  assert "HX-Request" in response.headers["Vary"]


def test_primary_htmx_navigation_is_short_cached_for_preload() -> None:
  import app.main as m

  client = TestClient(m.app)
  for path in ("/clients", "/dashboard"):
    response = client.get(
      path,
      headers={"HX-Request": "true", "HX-Boosted": "true", "HX-Preloaded": "true"},
    )
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "private, max-age=20, stale-while-revalidate=30"
    assert "HX-Request" in response.headers["Vary"]


def test_clients_page_partial_is_short_cached_for_preload() -> None:
  import app.main as m
  from app.services.excel_parser import ParsedWorkbook

  m.hub.set_workbook(
    ParsedWorkbook(
      source_type="contragents",
      rows=[{
        "UUID": f"page-{i}",
        "Наименование": f"Клиент {i}",
        "Тип продаж": "прямые продажи",
      } for i in range(30)],
      context_columns=["UUID", "Наименование"],
      segment_columns=[],
      total_rows=30,
      meta={"source": "moysklad"},
    ),
    None,
  )

  client = TestClient(m.app)
  response = client.get(
    "/clients/page?filter=direct&page=2",
    headers={"HX-Request": "true", "HX-Preloaded": "true"},
  )
  assert response.status_code == 200
  assert response.headers["Cache-Control"] == "private, max-age=20, stale-while-revalidate=30"
  assert response.text.lstrip().startswith('<div id="clients-page-frame"')
  assert 'id="clients-live-region"' not in response.text
  assert 'hx-sync="#clients-page-frame:replace"' in response.text
  assert 'hx-get="/clients/page?' in response.text
  assert 'hx-push-url="/clients?' in response.text


def test_static_assets_can_be_cached_with_versioned_urls() -> None:
  import app.main as m

  client = TestClient(m.app)
  response = client.get(m.static_asset("app.js"))
  assert response.status_code == 200
  assert response.headers["Cache-Control"] == "public, max-age=31536000, immutable"
  vendor_response = client.get(m.static_asset("vendor/htmx.min.js"))
  assert vendor_response.status_code == 200
  assert vendor_response.headers["Cache-Control"] == "public, max-age=31536000, immutable"
  preload_response = client.get(m.static_asset("vendor/htmx-ext-preload.js"))
  assert preload_response.status_code == 200
  assert preload_response.headers["Cache-Control"] == "public, max-age=31536000, immutable"


def test_large_static_assets_are_gzipped() -> None:
  import app.main as m

  client = TestClient(m.app)
  response = client.get(m.static_asset("style.css"), headers={"Accept-Encoding": "gzip"})
  assert response.status_code == 200
  assert response.headers["Content-Encoding"] == "gzip"


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


def test_home_page_shows_title_and_nav_without_extra_tabs() -> None:
  import app.main as m

  client = TestClient(m.app)
  response = client.get("/")
  assert response.status_code == 200
  assert "<h1>Главная</h1>" in response.text
  assert 'data-nav-path="/clients"' in response.text
  assert 'data-nav-path="/dashboard"' in response.text
  # Desktop + mobile nav_items: только Клиенты и Дашборд (по 2 = 4 nav-item).
  assert response.text.count('class="nav-item') == 4
  assert response.text.count('class="bottom-nav-item') == 2


def test_home_page_shows_diag_panel_for_import_and_settings() -> None:
  import app.main as m

  client = TestClient(m.app)
  response = client.get("/")
  assert response.status_code == 200
  assert 'id="diag-panel"' in response.text
  assert "Импорт Excel" in response.text
  assert "Настройки" in response.text
  assert 'data-nav-path="/segment"' in response.text
  assert "Импорт</a>" not in response.text.split("diag-panel-nav")[0]


def test_health_liveness_is_lightweight() -> None:
  import app.main as m

  with patch.object(m.db_persist, "ping", new_callable=AsyncMock) as db_ping:
    client = TestClient(m.app)
    response = client.get("/health")
  assert response.status_code == 200
  body = response.json()
  assert body["status"] == "ok"
  db_ping.assert_not_called()


def test_compute_home_kpis_skips_order_scan() -> None:
  from app.crm.dashboard import DashboardService

  rows = [
    {"Наименование": "A", "Всего заказов": 3, "ТГ ник": "@a"},
    {"Наименование": "B", "Всего заказов": 1},
    {"Наименование": "C", "_orders_count": 2, "ТГ ник": "@c"},
  ]
  svc = DashboardService()
  data = svc.compute_home_kpis(rows, hub_version=1)
  assert data.repeat_clients.total == 2
  assert data.open_dialogs == 2
  assert data.open_tasks == 0


def test_apply_cached_results_does_not_bulk_enrich() -> None:
  from unittest.mock import patch

  from app.services.data_hub import DataHub
  hub = DataHub()
  with patch("app.services.data_hub.enrich_row_computed") as enrich_mock:
    ok = hub.apply_cached_results(
      {
        "results": [{"Наименование": "Иван", "Группы": "новый"}],
        "meta": {"processed": 1},
        "workbook_key": "abc123",
      }
    )
  assert ok is True
  enrich_mock.assert_not_called()
  assert hub.results[0]["Наименование"] == "Иван"


def test_home_recent_clients_open_uses_drawer() -> None:
  import app.main as m
  from app.services.excel_parser import ParsedWorkbook

  m.hub.set_workbook(
    ParsedWorkbook(
      source_type="contragents",
      rows=[{
        "Наименование": "+12512569353",
        "Тип продаж": "маркетплейс",
        "Теги": "#vip",
      }],
      context_columns=["Наименование"],
      segment_columns=[],
      total_rows=1,
      meta={"source": "moysklad"},
    ),
    None,
  )
  with patch.object(m, "_hydrate_hub_from_cache", new_callable=AsyncMock, return_value=False):
    client = TestClient(m.app)
    response = client.get("/")
  assert response.status_code == 200
  assert 'hx-get="/clients/%2B12512569353?drawer=1"' in response.text
  assert 'hx-target="#client-drawer-panel"' in response.text
  assert 'hx-boost="false"' in response.text


def test_client_card_drawer_resolves_encoded_phone_name() -> None:
  import app.main as m
  from app.services.excel_parser import ParsedWorkbook

  m.hub.set_workbook(
    ParsedWorkbook(
      source_type="contragents",
      rows=[{
        "Наименование": "+1 305 6455530",
        "Тип продаж": "маркетплейс",
        "Всего заказов": 0,
      }],
      context_columns=["Наименование"],
      segment_columns=[],
      total_rows=1,
      meta={"source": "moysklad"},
    ),
    None,
  )
  with patch.object(m, "_ensure_hub_ready", new_callable=AsyncMock):
    client = TestClient(m.app)
    response = client.get(
      "/clients/%2B1%20305%206455530?drawer=1",
      headers={"HX-Request": "true"},
    )
  assert response.status_code == 200
  assert "+1 305 6455530" in response.text
  assert "rules-drawer-header" in response.text


def test_base_template_has_htmx_app_shell() -> None:
  import app.main as m

  client = TestClient(m.app)
  response = client.get("/")
  assert response.status_code == 200
  assert '<meta name="htmx-config" content=\'{"historyCacheSize":6}\'>' in response.text
  assert '/static/vendor/htmx.min.js?v=' in response.text
  assert '/static/vendor/htmx-ext-preload.js?v=' in response.text
  assert "unpkg.com/htmx" not in response.text
  assert '/static/app.js?v=' in response.text
  assert '/static/clients_ws.js?v=' in response.text
  assert '/static/style.css?v=' in response.text
  assert 'hx-boost="true"' in response.text
  assert 'hx-ext="preload"' in response.text
  assert 'preload="mouseover always"' in response.text
  assert 'hx-sync="#page-content:replace"' in response.text
  assert 'hx-target="#page-content"' in response.text
  assert 'id="page-content"' in response.text
  assert "nav-progress" in response.text
  assert 'hx-get="/messenger/sidebar"' in response.text
  assert 'hx-push-url="false"' in response.text
  assert 'id="orders-modal-loading"' in response.text
  assert 'id="orders-modal-loading" class="modal-overlay orders-modal-loading-overlay" hidden' in response.text


def test_boosted_navigation_returns_page_content_fragment() -> None:
  import app.main as m

  client = TestClient(m.app)
  response = client.get("/dashboard", headers={"HX-Boosted": "true", "HX-Request": "true"})
  assert response.status_code == 200
  assert response.text.lstrip().startswith('<main id="page-content"')
  assert 'class="site-header"' not in response.text
  assert '<script src=' not in response.text
  assert "<h1>Дашборд</h1>" in response.text


def test_htmx_navigation_request_without_boost_header_returns_fragment() -> None:
  import app.main as m

  client = TestClient(m.app)
  response = client.get("/clients", headers={"HX-Request": "true"})
  assert response.status_code == 200
  assert response.text.lstrip().startswith('<main id="page-content"')
  assert 'class="site-header"' not in response.text
  assert '<script src=' not in response.text


def test_clients_page_skips_relink_and_schedules_page_ai() -> None:
  import app.main as m

  with patch.object(m.hub, "relink_orders") as relink_mock, patch.object(
    m, "_schedule_page_lazy_ai", new_callable=AsyncMock
  ) as page_ai_mock:
    client = TestClient(m.app)
    response = client.get("/clients")
    assert response.status_code == 200
    relink_mock.assert_not_called()
    page_ai_mock.assert_called()


def test_clients_toolbar_buttons_have_click_feedback_markup() -> None:
  import app.main as m
  from app.services.excel_parser import ParsedWorkbook

  m.hub.set_workbook(
    ParsedWorkbook(
      source_type="contragents",
      rows=[{"UUID": "cp-toolbar", "Наименование": "Тест"}],
      context_columns=["UUID", "Наименование"],
      segment_columns=[],
      total_rows=1,
      meta={"source": "moysklad"},
    ),
    None,
  )
  with patch.object(m, "_hydrate_hub_from_cache", new_callable=AsyncMock, return_value=False):
    client = TestClient(m.app)
    response = client.get("/clients")
  assert response.status_code == 200
  assert "toolbar-action-btn" in response.text
  assert "export-xlsx-btn" in response.text
  assert "btn-action-icon" in response.text
  assert "openTagRulesDrawer(event)" in response.text


def test_tag_rules_panel_has_content_and_diagnostic_headers() -> None:
  import app.main as m

  client = TestClient(m.app)
  response = client.get(
    "/clients/tag-rules/panel?ui_request_id=browser-test",
    headers={"HX-Request": "true"},
  )
  assert response.status_code == 200
  assert response.headers["X-Tag-Rules-Count"] == str(len(m.get_tag_rules()))
  assert "rules-drawer-header" in response.text
  assert "tag-rules-form" in response.text


def test_tag_rules_browser_diagnostic_accepts_event() -> None:
  import app.main as m

  client = TestClient(m.app)
  response = client.post(
    "/diagnostics/tag-rules",
    json={"event": "rendered", "ui_request_id": "browser-test", "details": "bytes=123"},
  )
  assert response.status_code == 204
  assert response.content == b""


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
  assert 'hx-get="/clients/cp-drawer/orders?modal=1"' in response.text
  assert "orders-modal-btn" in response.text
  assert "rules-drawer-header" in response.text


def test_client_card_drawer_shows_ai_summary_and_recommendation() -> None:
  import app.main as m
  from app.services.excel_parser import ParsedWorkbook

  m.hub.set_workbook(
    ParsedWorkbook(
      source_type="contragents",
      rows=[{
        "UUID": "cp-rec",
        "Наименование": "Султанова Лилия",
        "Тип контрагента": "Физическое лицо",
        "Телефон": "+79001234567",
        "Всего заказов": 3,
        "_orders_count": 3,
        "Средний чек": 10000,
        "Группы": "премиум",
        "Теги": "#vip",
        "Саммари": "Поводы: 8 марта. Intent: подарок.",
        "_orders_context": [{"№": "1", "Дата": "2026-03-01", "Сумма": 10000, "Статус": "OK"}],
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
  assert "Саммари AI" in response.text
  assert "ai-client-summary" in response.text
  assert "История и профиль клиента" in response.text
  assert "Повод и intent покупки" in response.text
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
    assert response.text.count("orders-compact-item") == 1


def test_client_orders_expand_shows_all_cached_orders() -> None:
  import app.main as m
  from app.services.excel_parser import ParsedWorkbook

  orders_rows = [
    {
      "№": f"{i:05d}",
      "Контрагент": "VIP",
      "_moysklad_agent_id": "cp-expand",
      "Дата": f"2026-01-{(i % 28) + 1:02d}",
      "Сумма": 1000 * i,
      "Статус": "OK",
    }
    for i in range(1, 28)
  ]
  m.hub.set_workbook(
    ParsedWorkbook(
      source_type="contragents",
      rows=[{
        "UUID": "cp-expand",
        "Наименование": "VIP",
        "Всего заказов": 27,
        "_orders_context": orders_rows[:1],
        "_orders_count": 27,
      }],
      context_columns=["UUID", "Наименование"],
      segment_columns=[],
      total_rows=1,
      meta={"source": "moysklad"},
    ),
    ParsedWorkbook(
      source_type="orders",
      rows=orders_rows,
      context_columns=["№", "Контрагент"],
      segment_columns=[],
      total_rows=len(orders_rows),
      meta={},
    ),
  )
  with patch.object(m, "_ensure_hub_cache_only", new_callable=AsyncMock):
    client = TestClient(m.app)
    response = client.get(
      "/clients/cp-expand/orders",
      headers={"HX-Request": "true"},
    )
  assert response.status_code == 200
  assert response.text.count("orders-compact-item") == 27
