from __future__ import annotations

import asyncio
import io
import uuid
from datetime import date
from typing import Any

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
from app.services.cache import get_cache
from app.services.data_hub import get_data_hub
from app.services.excel_parser import (
  AI_EXTRA_COLUMNS,
  CLIENT_DISPLAY_COLUMNS,
  SEGMENT_COLUMNS,
  enrich_with_orders,
  parse_workbook,
)
from app.services.fields import enrich_row_computed
from app.services.green_api import get_green_api_client
from app.services.moysklad import get_moysklad_client
from app.services.segmentation import SegmentationService
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
app.mount("/static", StaticFiles(directory="app/static"), name="static")

_progress: dict[str, Any] = {"status": "idle", "done": 0, "total": 0, "error": ""}


def _ctx(request: Request, **extra: Any) -> dict[str, Any]:
  return {
    "request": request,
    "title": settings.app_title,
    "segment_columns": SEGMENT_COLUMNS,
    "ai_extra_columns": AI_EXTRA_COLUMNS,
    "client_columns": CLIENT_DISPLAY_COLUMNS,
    "moysklad_enabled": get_moysklad_client(settings).enabled,
    "model": settings.openrouter_model,
    "has_api_key": bool(settings.openrouter_api_key),
    "wa_enabled": get_green_api_client(settings).enabled,
    "tg_enabled": get_telegram_client(settings).enabled,
    **extra,
  }


async def _run_segmentation(rows: list[dict[str, Any]], parsed: Any) -> None:
  _progress.update(status="running", done=0, total=len(rows), error="")
  service = SegmentationService(settings)

  def _bump(n: int) -> None:
    _progress["done"] = min(_progress["total"], _progress["done"] + n)

  try:
    results = await service.segment_all(rows, progress_cb=_bump)
    enriched = [enrich_row_computed(r) for r in results]
    meta = {
      "processed": len(enriched),
      "source_type": parsed.source_type,
      "total": parsed.total_rows,
    }
    hub.set_results(enriched, meta)
    await cache.save_results({"results": enriched, "meta": meta})
    _progress["done"] = _progress["total"]
    _progress["status"] = "done"
  except Exception as exc:  # noqa: BLE001
    _progress["status"] = "error"
    _progress["error"] = str(exc)


@app.get("/", response_class=HTMLResponse)
async def home(request: Request) -> HTMLResponse:
  rows = hub.active_rows()
  dash = dashboard_svc.compute(rows, period="month")
  return templates.TemplateResponse(
    "home.html",
    _ctx(
      request,
      active_page="home",
      subtitle="Основное окно — задачи, диалоги, статусы",
      dashboard=dash,
      clients=rows[:20],
      total_clients=len(rows),
    ),
  )


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(
  request: Request,
  period: str = Query("month"),
  date_from: date | None = Query(None),
  date_to: date | None = Query(None),
) -> HTMLResponse:
  rows = hub.active_rows()
  dash = dashboard_svc.compute(rows, period=period, date_from=date_from, date_to=date_to)
  return templates.TemplateResponse(
    "dashboard.html",
    _ctx(
      request,
      active_page="dashboard",
      subtitle="Дашборд — динамика и метрики",
      dashboard=dash,
      periods=PERIOD_LABELS,
      period=period,
      date_from=date_from,
      date_to=date_to,
    ),
  )


@app.get("/clients", response_class=HTMLResponse)
async def clients_page(
  request: Request,
  filter: str = Query("all"),
  tag: str = Query(""),
  status: str = Query(""),
) -> HTMLResponse:
  rows = hub.filter_rows(sales_filter=filter, tag=tag, status=status)
  return templates.TemplateResponse(
    "clients.html",
    _ctx(
      request,
      active_page="clients",
      subtitle="AI база клиентов",
      clients=rows[:200],
      total=len(rows),
      sales_filter=filter,
      tag_filter=tag,
      status_filter=status,
    ),
  )


@app.get("/clients/{client_id}", response_class=HTMLResponse)
async def client_card(request: Request, client_id: str) -> HTMLResponse:
  client = hub.get_client(client_id)
  if not client:
    return templates.TemplateResponse(
      "partials/error.html",
      _ctx(request, message="Клиент не найден"),
    )
  orders = client.get("_orders_context") or []
  return templates.TemplateResponse(
    "partials/client_card.html",
    _ctx(request, client=client, orders=orders),
  )


@app.get("/clients/{client_id}/orders", response_class=HTMLResponse)
async def client_orders(request: Request, client_id: str) -> HTMLResponse:
  client = hub.get_client(client_id)
  orders = (client or {}).get("_orders_context") or []
  return templates.TemplateResponse(
    "partials/client_orders.html",
    _ctx(request, client=client, orders=orders),
  )


@app.get("/segment", response_class=HTMLResponse)
async def segment_page(request: Request) -> HTMLResponse:
  return templates.TemplateResponse(
    "segment.html",
    _ctx(request, active_page="segment", subtitle="Загрузка и AI-сегментация"),
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
      subtitle="Маркетинговые кампании",
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
      subtitle="Настройки",
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
      subtitle="Автокоммуникация с клиентом",
      comm_rules=comm.list_rules(),
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
  wa_state = await wa.get_state() if wa.enabled else {"enabled": False}
  tg_me = await tg.get_me() if tg.enabled else {"enabled": False}
  return templates.TemplateResponse(
    "partials/messenger_status.html",
    _ctx(request, health=health, wa_state=wa_state, tg_me=tg_me),
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
    ctx.update(
      results=hub.results,
      segment_columns=SEGMENT_COLUMNS,
      ai_extra_columns=AI_EXTRA_COLUMNS,
      meta=hub.meta,
    )
  return templates.TemplateResponse("partials/segment_progress.html", ctx)


@app.get("/download/xlsx")
async def download_xlsx() -> StreamingResponse:
  results = hub.results
  if not results:
    cached = await cache.get_results()
    if cached and cached.get("results"):
      results = cached["results"]
  if not results:
    df = pd.DataFrame()
  else:
    clean = []
    for row in results:
      item = {k: v for k, v in row.items() if not str(k).startswith("_")}
      clean.append(item)
    df = pd.DataFrame(clean)

  buffer = io.BytesIO()
  df.to_excel(buffer, index=False, engine="openpyxl")
  buffer.seek(0)

  return StreamingResponse(
    buffer,
    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    headers={"Content-Disposition": 'attachment; filename="segmentation_result.xlsx"'},
  )


@app.get("/moysklad/status", response_class=HTMLResponse)
async def moysklad_status(request: Request) -> HTMLResponse:
  client = get_moysklad_client(settings)
  healthy = await client.health_check() if client.enabled else False
  return templates.TemplateResponse(
    "partials/moysklad_status.html",
    {
      "request": request,
      "enabled": client.enabled,
      "healthy": healthy,
      "api_url": settings.moysklad_api_url,
    },
  )
