from __future__ import annotations

import asyncio
import io
import uuid
from datetime import date
from typing import Any

import httpx
import pandas as pd
from fastapi import FastAPI, File, Form, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import get_settings
from app.connectors.messenger import MessengerConnector
from app.crm.campaigns import CampaignService
from app.crm.communications import get_comm_settings
from app.crm.dashboard import DashboardService, PERIOD_LABELS
from app.crm.leads import LeadService
from app.domain import Campaign, CampaignStatus
from app.repository import get_repository
from app.services.cache import get_cache, file_hash
from app.services.data_hub import get_data_hub
from app.services.excel_parser import (
  AI_EXTRA_COLUMNS,
  AI_COLUMNS,
  AI_FILLABLE_COLUMNS,
  CLIENT_DISPLAY_COLUMNS,
  SEGMENT_COLUMNS,
  enrich_with_orders,
  parse_workbook,
)
from app.services.export_format import client_cell_value, export_columns, merge_enriched_rows, row_for_export
from app.services.fields import enrich_row_computed, finalize_ai_coverage_row
from app.services.green_api import get_green_api_client
from app.services.messenger_enrichment import MessengerEnrichmentService
from app.services.moysklad import get_moysklad_client, push_segments_to_moysklad, sync_moysklad_to_hub
from app.services.segmentation import SegmentationService
from app.services.tag_rules import (
  RULE_TYPE_OPTIONS,
  get_tag_rules,
  hydrate_tag_rules,
  rule_label,
  rules_from_form,
  save_tag_rules,
)
from app.services.tag_explanations import explain_tags_for_row
from app.services.telegram_bot import get_telegram_client

settings = get_settings()
cache = get_cache(settings)
hub = get_data_hub()
repo = get_repository()
dashboard_svc = DashboardService()
campaign_svc = CampaignService(repo)
lead_svc = LeadService(repo)

app = FastAPI(title=settings.app_title)
templates = Jinja2Templates(directory="app/templates")
templates.env.globals["tag_reasons"] = explain_tags_for_row
templates.env.globals["rule_label"] = rule_label
templates.env.globals["client_cell_value"] = client_cell_value
app.mount("/static", StaticFiles(directory="app/static"), name="static")

_progress: dict[str, Any] = {"status": "idle", "done": 0, "total": 0, "error": ""}
_enrich_progress: dict[str, Any] = {"status": "idle", "done": 0, "total": 0, "error": ""}


async def _hydrate_hub_from_cache(workbook_key: str | None = None) -> bool:
  """Подгрузить результаты сегментации из Redis/in-memory в hub."""
  if hub.results:
    return True
  key = workbook_key or hub.workbook_hash
  cached = await cache.get_segmentation_results(key)
  if not cached:
    return False
  return hub.apply_cached_results(cached)


async def _ensure_moysklad_data() -> None:
  """Подгрузить контрагентов Мой Склад из кэша или API."""
  client = get_moysklad_client(settings)
  if not client.enabled:
    return

  parsed_count = len(hub.parsed.rows) if hub.parsed and hub.parsed.rows else 0
  is_moysklad = bool(hub.parsed and hub.parsed.meta.get("source") == "moysklad")
  if is_moysklad and parsed_count > 0:
    cached_ms = await cache.get_moysklad_sync()
    api_total = (cached_ms or {}).get("api_cp_total")
    if api_total is None:
      api_total = await client.get_entity_count("/entity/counterparty")
    if api_total and parsed_count >= api_total:
      return

  await sync_moysklad_to_hub(
    client,
    hub,
    max_counterparties=settings.moysklad_sync_limit,
    max_orders=settings.moysklad_sync_orders_limit,
    cache=cache,
    force_refresh=False,
  )


@app.on_event("startup")
async def startup_hydrate_cache() -> None:
  await hydrate_tag_rules(cache)
  if settings.moysklad_auto_sync:
    await _ensure_moysklad_data()
  await _hydrate_hub_from_cache()
  messenger = MessengerEnrichmentService(settings, cache)
  if messenger.telegram_enabled:
    await messenger.sync_telegram_inbox()


def _workflow_ctx() -> dict[str, Any]:
  has_parsed = hub.parsed is not None and bool(hub.parsed.rows)
  has_results = bool(hub.results)
  if has_results:
    step = 3
  elif has_parsed:
    step = 2
  else:
    step = 1
  return {"has_data": has_parsed or has_results, "workflow_step": step}


def _mask_secret(value: str) -> str:
  value = value.strip()
  if not value:
    return "не задан"
  if len(value) <= 8:
    return "••••••••"
  return f"{value[:4]}…{value[-4:]}"


def _optional_query_date(value: str | None) -> date | None:
  if value is None or not str(value).strip():
    return None
  return date.fromisoformat(str(value).strip())


def _moysklad_config_ctx() -> dict[str, Any]:
  client = get_moysklad_client(settings)
  return {
    "moysklad_config": {
      "enabled": settings.moysklad_enabled,
      "token_set": bool(settings.moysklad_api_token),
      "token_masked": _mask_secret(settings.moysklad_api_token),
      "api_url": settings.moysklad_api_url,
      "sync_limit": settings.moysklad_sync_limit,
      "sync_orders_limit": settings.moysklad_sync_orders_limit,
      "client_enabled": client.enabled,
    },
  }


def _moysklad_push_available() -> bool:
  client = get_moysklad_client(settings)
  if not client.enabled or not hub.results:
    return False
  return any(
    row.get("_moysklad_id") or row.get("_source") == "moysklad"
    for row in hub.results
  )


def _segment_results_ctx() -> dict[str, Any]:
  return {"moysklad_push_available": _moysklad_push_available()}


def _ctx(request: Request, **extra: Any) -> dict[str, Any]:
  return {
    "request": request,
    "title": settings.app_title,
    "segment_columns": SEGMENT_COLUMNS,
    "ai_extra_columns": AI_EXTRA_COLUMNS,
    "ai_columns": AI_COLUMNS,
    "ai_fillable_columns": AI_FILLABLE_COLUMNS,
    "client_columns": CLIENT_DISPLAY_COLUMNS,
    "moysklad_enabled": get_moysklad_client(settings).enabled,
    "model": settings.openrouter_model,
    "has_api_key": bool(settings.openrouter_api_key),
    "wa_enabled": get_green_api_client(settings).enabled,
    "tg_enabled": get_telegram_client(settings).enabled,
    "telegram_bot_username": settings.telegram_bot_username,
    "messenger_enabled": settings.messenger_enabled,
    "cache_backend": cache.backend_kind,
    "results_from_cache": hub.results_from_cache,
    **_workflow_ctx(),
    **extra,
  }


async def _run_enrichment(rows: list[dict[str, Any]]) -> None:
  _enrich_progress.update(status="running", done=0, total=len(rows), error="")
  service = MessengerEnrichmentService(settings, cache)
  if hub.parsed and hub.parsed.rows:
    all_rows = [enrich_row_computed(r) for r in hub.parsed.rows]
  else:
    all_rows = hub.active_rows()

  def _bump(n: int) -> None:
    _enrich_progress["done"] = min(_enrich_progress["total"], _enrich_progress["done"] + n)

  try:
    enriched = await service.enrich_all(rows, progress_cb=_bump)
    enriched = [
      finalize_ai_coverage_row(enrich_row_computed(r)) for r in enriched
    ]
    merged = merge_enriched_rows(all_rows, enriched, key_fn=service._row_key)
    with_messages = sum(1 for r in merged if r.get("_messenger_context"))
    ai_filled = sum(1 for r in merged if r.get("_enrichment_fields") or r.get("_ai_processed"))
    meta = {
      **(hub.meta or {}),
      "enriched": True,
      "enrichment_total": len(merged),
      "enrichment_with_messages": with_messages,
      "enrichment_ai_filled": ai_filled,
    }
    hub.set_results(merged, meta)
    if hub.workbook_hash:
      await cache.save_segmentation_results(
        hub.workbook_hash,
        {"results": merged, "meta": meta},
      )
    _enrich_progress["done"] = _enrich_progress["total"]
    _enrich_progress["status"] = "done"
  except Exception as exc:  # noqa: BLE001
    _enrich_progress["status"] = "error"
    _enrich_progress["error"] = str(exc)


def _export_rows() -> list[dict[str, Any]]:
  rows = hub.active_rows()
  columns = export_columns(hub.parsed)
  return [row_for_export(row, columns) for row in rows]


def _pagination_pages(page: int, total_pages: int, *, radius: int = 2) -> list[int | None]:
  """Номера страниц для UI; None — многоточие."""
  if total_pages <= 1:
    return [1]
  pages: set[int] = {1, total_pages}
  for p in range(max(1, page - radius), min(total_pages, page + radius) + 1):
    pages.add(p)
  ordered = sorted(pages)
  result: list[int | None] = []
  prev = 0
  for p in ordered:
    if prev and p - prev > 1:
      result.append(None)
    result.append(p)
    prev = p
  return result


def _clients_ctx(
  request: Request,
  *,
  sales_filter: str = "direct",
  tag: str = "",
  status: str = "",
  page: int = 1,
) -> dict[str, Any]:
  rows = hub.filter_rows(sales_filter=sales_filter, tag=tag, status=status)
  per_page = max(1, settings.clients_page_size)
  total = len(rows)
  total_pages = max(1, (total + per_page - 1) // per_page)
  page = max(1, min(page, total_pages))
  start = (page - 1) * per_page
  end = start + per_page
  return _ctx(
    request,
    clients=rows[start:end],
    total=total,
    page=page,
    per_page=per_page,
    total_pages=total_pages,
    page_start=start + 1 if total else 0,
    page_end=min(end, total),
    pagination_pages=_pagination_pages(page, total_pages),
    sales_filter=sales_filter,
    tag_filter=tag,
    status_filter=status,
    data_source=hub.data_source_label(),
    messenger_available=settings.messenger_enabled and (
      get_green_api_client(settings).enabled or get_telegram_client(settings).enabled
    ),
  )


async def _run_segmentation(rows: list[dict[str, Any]], parsed: Any) -> None:
  _progress.update(status="running", done=0, total=len(rows), error="")
  messenger = MessengerEnrichmentService(settings, cache)
  if messenger.available:
    rows = await messenger.attach_messages(rows)
  service = SegmentationService(settings)

  def _bump(n: int) -> None:
    _progress["done"] = min(_progress["total"], _progress["done"] + n)

  try:
    results = await service.segment_all(rows, progress_cb=_bump)
    enriched = [
      finalize_ai_coverage_row(enrich_row_computed(r)) for r in results
    ]
    with_messages = sum(1 for r in enriched if r.get("_messenger_context"))
    meta = {
      "processed": len(enriched),
      "source_type": parsed.source_type,
      "total": parsed.total_rows,
      "messenger_context_clients": with_messages,
    }
    hub.set_results(enriched, meta)
    if hub.workbook_hash:
      await cache.save_segmentation_results(
        hub.workbook_hash,
        {"results": enriched, "meta": meta},
      )
    else:
      await cache.save_results({"results": enriched, "meta": meta})
    _progress["done"] = _progress["total"]
    _progress["status"] = "done"
  except Exception as exc:  # noqa: BLE001
    _progress["status"] = "error"
    _progress["error"] = str(exc)


@app.get("/", response_class=HTMLResponse)
async def home(request: Request) -> HTMLResponse:
  await _hydrate_hub_from_cache()
  rows = hub.active_rows()
  dash = dashboard_svc.compute(rows, period="month")
  return templates.TemplateResponse(
    "home.html",
    _ctx(
      request,
      active_page="home",
      page_title="Главная",
      subtitle="Обзор клиентской базы и быстрые действия",
      dashboard=dash,
      clients=rows[:10],
      total_clients=len(rows),
    ),
  )


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(
  request: Request,
  period: str = Query("month"),
  date_from: str = Query(""),
  date_to: str = Query(""),
) -> HTMLResponse:
  await _hydrate_hub_from_cache()
  rows = hub.active_rows()
  parsed_from = _optional_query_date(date_from)
  parsed_to = _optional_query_date(date_to)
  dash = dashboard_svc.compute(
    rows, period=period, date_from=parsed_from, date_to=parsed_to
  )
  return templates.TemplateResponse(
    "dashboard.html",
    _ctx(
      request,
      active_page="dashboard",
      page_title="Дашборд",
      subtitle="Метрики и динамика за выбранный период",
      dashboard=dash,
      periods=PERIOD_LABELS,
      period=period,
      date_from=parsed_from,
      date_to=parsed_to,
    ),
  )


@app.get("/clients", response_class=HTMLResponse)
async def clients_page(
  request: Request,
  filter: str = Query("direct"),
  tag: str = Query(""),
  status: str = Query(""),
  page: int = Query(1, ge=1),
) -> HTMLResponse:
  await _hydrate_hub_from_cache()
  await _ensure_moysklad_data()
  return templates.TemplateResponse(
    "clients.html",
    {
      **_clients_ctx(request, sales_filter=filter, tag=tag, status=status, page=page),
      "active_page": "clients",
      "page_title": "Клиенты",
      "subtitle": "AI-база с фильтрами и раскрытием заказов",
    },
  )


@app.get("/clients/table", response_class=HTMLResponse)
async def clients_table_partial(
  request: Request,
  filter: str = Query("direct"),
  tag: str = Query(""),
  status: str = Query(""),
  page: int = Query(1, ge=1),
) -> HTMLResponse:
  await _hydrate_hub_from_cache()
  await _ensure_moysklad_data()
  return templates.TemplateResponse(
    "partials/clients_table.html",
    _clients_ctx(request, sales_filter=filter, tag=tag, status=status, page=page),
  )


@app.get("/clients/tag-rules/panel", response_class=HTMLResponse)
async def tag_rules_panel(request: Request) -> HTMLResponse:
  return templates.TemplateResponse(
    "partials/tag_rules_panel.html",
    _ctx(request, tag_rules=get_tag_rules(), saved=False, rule_type_options=RULE_TYPE_OPTIONS),
  )


@app.post("/clients/tag-rules", response_class=HTMLResponse)
async def tag_rules_save(request: Request) -> HTMLResponse:
  form = dict(await request.form())
  rules = rules_from_form({k: str(v) for k, v in form.items()})
  await save_tag_rules(cache, rules)
  return templates.TemplateResponse(
    "partials/tag_rules_panel.html",
    _ctx(request, tag_rules=get_tag_rules(), saved=True, rule_type_options=RULE_TYPE_OPTIONS),
  )


@app.get("/clients/{client_id}", response_class=HTMLResponse)
async def client_card(
  request: Request,
  client_id: str,
  drawer: bool = Query(False),
) -> HTMLResponse:
  client = hub.get_client(client_id)
  if not client:
    return templates.TemplateResponse(
      "partials/error.html",
      _ctx(request, message="Клиент не найден"),
    )
  orders = client.get("_orders_context") or []
  template = "partials/client_card_drawer.html" if drawer else "partials/client_card.html"
  return templates.TemplateResponse(
    template,
    _ctx(request, client=client, orders=orders),
  )


@app.get("/clients/{client_id}/orders", response_class=HTMLResponse)
async def client_orders(
  request: Request,
  client_id: str,
  collapsed: bool = Query(False),
) -> HTMLResponse:
  if collapsed:
    return HTMLResponse("")
  client = hub.get_client(client_id)
  orders = (client or {}).get("_orders_context") or []
  return templates.TemplateResponse(
    "partials/client_orders.html",
    _ctx(request, client=client, orders=orders, client_id=client_id),
  )


@app.get("/segment", response_class=HTMLResponse)
async def segment_page(request: Request) -> HTMLResponse:
  await _hydrate_hub_from_cache()
  await _ensure_moysklad_data()
  return templates.TemplateResponse(
    "segment.html",
    _ctx(
      request,
      active_page="segment",
      page_title="Импорт данных",
      subtitle="Загрузите Excel и запустите AI-сегментацию",
    ),
  )


@app.get("/campaigns", response_class=HTMLResponse)
async def campaigns_page(request: Request) -> HTMLResponse:
  campaigns = await campaign_svc.list_campaigns()
  rows = hub.active_rows()
  return templates.TemplateResponse(
    "campaigns.html",
    _ctx(
      request,
      active_page="campaigns",
      page_title="Кампании",
      subtitle="Рассылки по сегментам клиентов",
      campaigns=campaigns,
      total_clients=len(rows),
    ),
  )


@app.post("/campaigns/create", response_class=HTMLResponse)
async def campaign_create(
  request: Request,
  title: str = Form(...),
  target_segments: str = Form(""),
  channel: str = Form("whatsapp"),
  offer: str = Form(""),
) -> HTMLResponse:
  segments = [s.strip() for s in target_segments.split(",") if s.strip()]
  campaign = Campaign(
    id=str(uuid.uuid4()),
    title=title,
    target_segments=segments,
    channel=channel,
    offer=offer,
    status=CampaignStatus.DRAFT,
  )
  await campaign_svc.create(campaign)
  campaigns = await campaign_svc.list_campaigns()
  return templates.TemplateResponse(
    "partials/campaign_list.html",
    _ctx(request, campaigns=campaigns),
  )


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request) -> HTMLResponse:
  comm = get_comm_settings()
  messenger = MessengerConnector(settings)
  health = await messenger.health()
  return templates.TemplateResponse(
    "settings.html",
    _ctx(
      request,
      active_page="settings",
      page_title="Настройки",
      subtitle="Интеграции и подключения",
      comm_rules=comm.list_rules(),
      messenger_health=health,
    ),
  )


@app.get("/settings/communications", response_class=HTMLResponse)
async def communications_page(request: Request) -> HTMLResponse:
  comm = get_comm_settings()
  return templates.TemplateResponse(
    "communications.html",
    _ctx(
      request,
      active_page="communications",
      page_title="Автокоммуникация",
      subtitle="Автоматические сообщения клиентам",
      comm_rules=comm.list_rules(),
    ),
  )


@app.get("/settings/moysklad", response_class=HTMLResponse)
async def moysklad_settings_page(request: Request) -> HTMLResponse:
  await _hydrate_hub_from_cache()
  await _ensure_moysklad_data()
  return templates.TemplateResponse(
    "moysklad_settings.html",
    _ctx(
      request,
      active_page="moysklad",
      page_title="Мой Склад",
      subtitle="Подключение, синхронизация и выгрузка сегментов",
      **_moysklad_config_ctx(),
      **_segment_results_ctx(),
    ),
  )


@app.post("/settings/communications/{rule_key}", response_class=HTMLResponse)
async def communications_update(
  request: Request,
  rule_key: str,
  enabled: bool = Form(False),
  template: str = Form(""),
  channel: str = Form("whatsapp"),
) -> HTMLResponse:
  comm = get_comm_settings()
  comm.update_rule(rule_key, enabled=enabled, template=template, channel=channel)
  return templates.TemplateResponse(
    "partials/comm_rule.html",
    _ctx(request, rule=comm._rules[rule_key]),
  )


@app.get("/messenger/sidebar", response_class=HTMLResponse)
async def messenger_sidebar(request: Request) -> HTMLResponse:
  messenger = MessengerConnector(settings)
  health = await messenger.health()
  return templates.TemplateResponse(
    "partials/messenger_sidebar.html",
    _ctx(request, health=health),
  )


@app.get("/messenger/status", response_class=HTMLResponse)
async def messenger_status(request: Request) -> HTMLResponse:
  messenger = MessengerConnector(settings)
  health = await messenger.health()
  wa = get_green_api_client(settings)
  tg = get_telegram_client(settings)
  if wa.enabled:
    try:
      wa_state = await wa.get_state()
    except httpx.HTTPError as exc:
      wa_state = {
        "enabled": True,
        "stateInstance": "rate_limited",
        "error": str(exc),
      }
  else:
    wa_state = {"enabled": False}
  if tg.enabled:
    try:
      tg_me = await tg.get_me()
    except httpx.HTTPError:
      tg_me = {"enabled": True, "username": settings.telegram_bot_username}
  else:
    tg_me = {"enabled": False}
  enrichment = MessengerEnrichmentService(settings, cache)
  tg_stats = enrichment.stats if tg.enabled else {}
  return templates.TemplateResponse(
    "partials/messenger_status.html",
    _ctx(request, health=health, wa_state=wa_state, tg_me=tg_me, tg_stats=tg_stats),
  )


@app.post("/upload/preview", response_class=HTMLResponse)
async def upload_preview(
  request: Request,
  contragents_file: UploadFile = File(...),
  orders_file: UploadFile | None = File(None),
) -> HTMLResponse:
  content = await contragents_file.read()
  orders_content = b""
  if orders_file and orders_file.filename:
    orders_content = await orders_file.read()

  cache_content = content + b"|orders|" + orders_content
  hub.workbook_hash = file_hash(cache_content)
  parsed = await cache.get_parsed(cache_content)
  from_cache = parsed is not None

  if parsed is None:
    parsed = await asyncio.to_thread(parse_workbook, content)
    orders_parsed = None
    if orders_content:
      orders_parsed = await asyncio.to_thread(parse_workbook, orders_content)
      parsed = enrich_with_orders(parsed, orders_parsed)
    hub.set_workbook(parsed, orders_parsed)
    await cache.set_parsed(cache_content, parsed)
  else:
    hub.set_workbook(parsed, None)

  results_from_cache = False
  if not hub.results:
    results_from_cache = await _hydrate_hub_from_cache(hub.workbook_hash)

  preview_rows = [enrich_row_computed(r) for r in parsed.rows[:20]]

  return templates.TemplateResponse(
    "partials/preview.html",
    {
      "request": request,
      "parsed": parsed,
      "preview_rows": preview_rows,
      "segment_columns": SEGMENT_COLUMNS,
      "from_cache": from_cache,
      "cache_backend": cache.backend_kind,
      "results_from_cache": results_from_cache,
      "has_segment_results": bool(hub.results),
      "results": hub.results,
      "meta": hub.meta,
      "ai_extra_columns": AI_EXTRA_COLUMNS,
      **_segment_results_ctx(),
    },
  )


@app.post("/segment/start", response_class=HTMLResponse)
async def segment_start(
  request: Request,
  limit: int = Form(50),
) -> HTMLResponse:
  parsed = hub.parsed
  if not parsed:
    return templates.TemplateResponse(
      "partials/segment_modal.html",
      {"request": request, "error": "Сначала загрузите файл Excel."},
    )

  if hub.workbook_hash and not hub.results:
    cached = await cache.get_segmentation_results(hub.workbook_hash)
    if cached and cached.get("results"):
      hub.apply_cached_results(cached)
      _progress.update(
        status="done",
        done=len(hub.results),
        total=len(hub.results),
        error="",
      )
      return templates.TemplateResponse(
        "partials/segment_progress.html",
        {
          "request": request,
          "status": "done",
          "done": len(hub.results),
          "total": len(hub.results),
          "percent": 100,
          "error": "",
          "results": hub.results,
          "segment_columns": SEGMENT_COLUMNS,
          "ai_extra_columns": AI_EXTRA_COLUMNS,
          "meta": hub.meta,
          "results_from_cache": True,
          "cache_backend": cache.backend_kind,
          **_segment_results_ctx(),
        },
      )

  rows = parsed.rows[: max(1, min(limit, 500))]
  _progress.update(status="running", done=0, total=len(rows), error="")
  asyncio.create_task(_run_segmentation(rows, parsed))

  return templates.TemplateResponse(
    "partials/segment_modal.html",
    {"request": request, "error": None},
  )


@app.get("/segment/progress", response_class=HTMLResponse)
async def segment_progress(request: Request) -> HTMLResponse:
  status = _progress["status"]
  total = _progress["total"]
  done = _progress["done"]
  percent = int(done / total * 100) if total else 0

  ctx: dict[str, Any] = {
    "request": request,
    "status": status,
    "done": done,
    "total": total,
    "percent": percent,
    "error": _progress["error"],
  }
  if status == "done":
    await _hydrate_hub_from_cache()
    ctx.update(
      results=hub.results,
      segment_columns=SEGMENT_COLUMNS,
      ai_extra_columns=AI_EXTRA_COLUMNS,
      meta=hub.meta,
      results_from_cache=hub.results_from_cache,
      cache_backend=cache.backend_kind,
      **_segment_results_ctx(),
    )
  return templates.TemplateResponse("partials/segment_progress.html", ctx)


@app.get("/download/xlsx")
async def download_xlsx() -> StreamingResponse:
  await _hydrate_hub_from_cache()
  rows = _export_rows()
  df = pd.DataFrame(rows) if rows else pd.DataFrame()
  buffer = io.BytesIO()
  df.to_excel(buffer, index=False, engine="openpyxl")
  buffer.seek(0)

  return StreamingResponse(
    buffer,
    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    headers={"Content-Disposition": 'attachment; filename="segmentation_result.xlsx"'},
  )


@app.get("/download/clients/xlsx")
async def download_clients_xlsx() -> StreamingResponse:
  await _hydrate_hub_from_cache()
  rows = _export_rows()
  df = pd.DataFrame(rows) if rows else pd.DataFrame()
  buffer = io.BytesIO()
  df.to_excel(buffer, index=False, engine="openpyxl")
  buffer.seek(0)
  return StreamingResponse(
    buffer,
    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    headers={"Content-Disposition": 'attachment; filename="clients_enriched.xlsx"'},
  )


@app.post("/enrich/start", response_class=HTMLResponse)
async def enrich_start(
  request: Request,
  limit: int = Form(500),
  filter: str = Query("direct"),
  tag: str = Query(""),
  status: str = Query(""),
) -> HTMLResponse:
  rows = hub.active_rows()
  if not rows:
    return templates.TemplateResponse(
      "partials/enrich_progress.html",
      _ctx(
        request,
        status="error",
        done=0,
        total=0,
        percent=0,
        error="Нет данных клиентов. Сначала синхронизируйте Мой Склад или загрузите Excel.",
        sales_filter=filter,
        tag_filter=tag,
        status_filter=status,
      ),
    )

  selected = rows[: max(1, min(limit, 500))]
  _enrich_progress.update(status="running", done=0, total=len(selected), error="")
  asyncio.create_task(_run_enrichment(selected))

  return templates.TemplateResponse(
    "partials/enrich_progress.html",
    _ctx(
      request,
      status="running",
      done=0,
      total=len(selected),
      percent=0,
      error="",
      sales_filter=filter,
      tag_filter=tag,
      status_filter=status,
    ),
  )


@app.get("/enrich/progress", response_class=HTMLResponse)
async def enrich_progress(
  request: Request,
  filter: str = Query("direct"),
  tag: str = Query(""),
  status: str = Query(""),
) -> HTMLResponse:
  enrich_status = _enrich_progress["status"]
  total = _enrich_progress["total"]
  done = _enrich_progress["done"]
  percent = int(done / total * 100) if total else 0
  return templates.TemplateResponse(
    "partials/enrich_progress.html",
    _ctx(
      request,
      status=enrich_status,
      done=done,
      total=total,
      percent=percent,
      error=_enrich_progress["error"],
      sales_filter=filter,
      tag_filter=tag,
      status_filter=status,
    ),
  )


@app.get("/moysklad/status", response_class=HTMLResponse)
async def moysklad_status(request: Request) -> HTMLResponse:
  await _ensure_moysklad_data()
  client = get_moysklad_client(settings)
  healthy = await client.health_check() if client.enabled else False
  cached_ms = await cache.get_moysklad_sync()
  api_cp_total = cached_ms.get("api_cp_total") if cached_ms else None
  api_orders_total = cached_ms.get("api_orders_total") if cached_ms else None
  if client.enabled and api_cp_total is None:
    api_cp_total = await client.get_entity_count("/entity/counterparty")
  if client.enabled and api_orders_total is None:
    api_orders_total = await client.get_entity_count("/entity/customerorder")
  hub_rows = len(hub.active_rows())
  hub_orders = (
    len(hub.orders_parsed.rows)
    if hub.orders_parsed and hub.orders_parsed.rows
    else 0
  )
  from_moysklad = bool(
    hub.parsed
    and hub.parsed.meta.get("source") == "moysklad"
  )
  from_cache = bool(cached_ms and from_moysklad)
  return templates.TemplateResponse(
    "partials/moysklad_status.html",
    {
      "request": request,
      "enabled": client.enabled,
      "healthy": healthy,
      "api_url": settings.moysklad_api_url,
      "hub_rows": hub_rows,
      "hub_orders": hub_orders,
      "api_cp_total": api_cp_total,
      "api_orders_total": api_orders_total,
      "from_moysklad": from_moysklad,
      "from_cache": from_cache,
    },
  )


@app.post("/moysklad/sync", response_class=HTMLResponse)
async def moysklad_sync(request: Request) -> HTMLResponse:
  client = get_moysklad_client(settings)
  result = await sync_moysklad_to_hub(
    client,
    hub,
    max_counterparties=settings.moysklad_sync_limit,
    max_orders=settings.moysklad_sync_orders_limit,
    cache=cache,
    force_refresh=True,
  )
  healthy = await client.health_check() if client.enabled else False
  return templates.TemplateResponse(
    "partials/moysklad_status.html",
    {
      "request": request,
      "enabled": client.enabled,
      "healthy": healthy,
      "api_url": settings.moysklad_api_url,
      "hub_rows": result.counterparties_count if result.success else 0,
      "hub_orders": result.orders_count if result.success else 0,
      "api_cp_total": result.api_counterparties_total,
      "api_orders_total": result.api_orders_total,
      "from_moysklad": result.success,
      "sync_message": result.message,
      "sync_ok": result.success,
      "from_cache": result.from_cache,
    },
  )


@app.post("/moysklad/push-tags", response_class=HTMLResponse)
async def moysklad_push_tags(request: Request) -> HTMLResponse:
  await _hydrate_hub_from_cache()
  client = get_moysklad_client(settings)
  result = await push_segments_to_moysklad(client, hub.results)
  return templates.TemplateResponse(
    "partials/moysklad_push_result.html",
    {
      "request": request,
      "result": result,
      "moysklad_push_available": _moysklad_push_available(),
    },
  )
