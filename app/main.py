from __future__ import annotations

import asyncio
import io
import logging
import time
import uuid
from datetime import date
from pathlib import Path
from typing import Any

import httpx
import pandas as pd
from fastapi import FastAPI, File, Form, Query, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
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
from app.services.export_format import (
  AI_RUNNING_LABEL,
  build_clients_query,
  client_cell_state,
  client_cell_value,
  compact_orders_for_display,
  display_cell_value,
  export_columns,
  format_money_rub,
  merge_enriched_rows,
  row_for_export,
)
from app.services.fields import enrich_row_computed, finalize_ai_coverage_row
from app.services.green_api import get_green_api_client
from app.services.messenger_enrichment import MessengerEnrichmentService
from app.services.moysklad import (
  get_moysklad_client,
  push_segments_to_moysklad,
  sync_moysklad_to_hub,
)
from app.services.moysklad.sync import refresh_moysklad_positions
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
from app.services.telegram_export import parse_telegram_export_file
from app.services.telegram_bot import get_telegram_client
from app.services.db_persist import get_db_persist
from app.services.background_jobs import get_background_jobs
from app.services.status_cache import get_status_cache
from app.logging_config import configure_logging, pipeline_log

configure_logging()
settings = get_settings()
cache = get_cache(settings)
db_persist = get_db_persist(settings)
status_cache = get_status_cache()
jobs = get_background_jobs()
cache.attach_db_persist(db_persist)
hub = get_data_hub()
repo = get_repository()
dashboard_svc = DashboardService()
campaign_svc = CampaignService(repo)
lead_svc = LeadService(repo)

app = FastAPI(title=settings.app_title)
perf_logger = logging.getLogger("performance")
templates = Jinja2Templates(directory="app/templates")
templates.env.globals["tag_reasons"] = explain_tags_for_row
templates.env.globals["rule_label"] = rule_label
templates.env.globals["client_cell_value"] = client_cell_value
templates.env.globals["client_cell_state"] = client_cell_state
templates.env.globals["display_cell_value"] = display_cell_value
templates.env.globals["format_money_rub"] = format_money_rub
templates.env.globals["build_clients_query"] = build_clients_query
templates.env.globals["ai_running_label"] = AI_RUNNING_LABEL
app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.middleware("http")
async def performance_middleware(request: Request, call_next):
  started = time.perf_counter()
  request_id = request.headers.get("x-railway-request-id") or uuid.uuid4().hex[:10]
  pipeline_log(
    "HTTP",
    "START id=%s method=%s path=%s query=%s htmx=%s boosted=%s ua=%s",
    request_id,
    request.method,
    request.url.path,
    request.url.query or "-",
    request.headers.get("hx-request", "false"),
    request.headers.get("hx-boosted", "false"),
    (request.headers.get("user-agent") or "-")[:90],
  )
  try:
    response = await call_next(request)
  except Exception:
    elapsed_ms = (time.perf_counter() - started) * 1000
    pipeline_log(
      "HTTP",
      "ERROR id=%s method=%s path=%s duration_ms=%.1f",
      request_id,
      request.method,
      request.url.path,
      elapsed_ms,
      level=logging.ERROR,
    )
    raise
  elapsed_ms = (time.perf_counter() - started) * 1000
  response.headers["Server-Timing"] = f"app;dur={elapsed_ms:.1f}"
  response.headers["X-Response-Time-Ms"] = f"{elapsed_ms:.1f}"
  response.headers["X-Request-Id"] = request_id
  perf_logger.info(
    "DONE id=%s method=%s path=%s status=%s duration_ms=%.1f",
    request_id,
    request.method,
    request.url.path,
    response.status_code,
    elapsed_ms,
    extra={"stage": "HTTP"},
  )
  return response


_progress: dict[str, Any] = {"status": "idle", "done": 0, "total": 0, "error": ""}
_enrich_progress: dict[str, Any] = {"status": "idle", "done": 0, "total": 0, "error": ""}
_tg_export_progress: dict[str, Any] = {"status": "idle", "done": 0, "total": 0, "error": "", "meta": {}}


async def _apply_tg_export_to_hub() -> int:
  """Привязать TG export ко всем клиентам в hub и сохранить в кэш."""
  pipeline_log("TG", "apply export to hub start rows=%s", len(hub.active_rows()))
  messenger = MessengerEnrichmentService(settings, cache)
  await messenger.load_telegram_export()
  if not messenger.export_loaded:
    pipeline_log("TG", "apply export skipped export_loaded=false")
    return 0
  rows = hub.active_rows()
  if not rows:
    pipeline_log("TG", "apply export skipped rows=0")
    return 0
  updated = await messenger.attach_tg_export_only(rows)
  matched = sum(1 for r in updated if r.get("_tg_export_context"))
  meta = {
    **(hub.meta or {}),
    "tg_export_matched": matched,
    "tg_export_meta": messenger.export_stats,
  }
  hub.set_results(updated, meta)
  payload = {"results": updated, "meta": meta}
  if hub.workbook_hash:
    await cache.save_segmentation_results(hub.workbook_hash, payload)
  else:
    await cache.save_results(payload)
  pipeline_log("TG", "apply export done matched=%s rows=%s", matched, len(updated))
  return matched


async def _import_telegram_export_from_path(path: Path) -> dict[str, Any]:
  _tg_export_progress.update(status="running", done=0, total=1, error="", meta={})
  pipeline_log("TG", "import file start path=%s", path)
  try:
    index = await asyncio.to_thread(parse_telegram_export_file, path)
    messenger = MessengerEnrichmentService(settings, cache)
    await messenger.save_telegram_export(index)
    matched = await _apply_tg_export_to_hub()
    meta = {**(index.get("meta") or {}), "matched_clients": matched}
    _tg_export_progress.update(status="done", done=1, total=1, error="", meta=meta)
    pipeline_log("TG", "import file done matched=%s meta=%s", matched, meta)
    return meta
  except Exception as exc:  # noqa: BLE001
    _tg_export_progress.update(status="error", error=str(exc))
    pipeline_log("TG", "import file failed error=%s", exc, level=logging.ERROR)
    raise


async def _save_upload_stream(upload: UploadFile, dest: Path, *, max_bytes: int) -> int:
  dest.parent.mkdir(parents=True, exist_ok=True)
  size = 0
  with dest.open("wb") as out:
    while True:
      chunk = await upload.read(1024 * 1024)
      if not chunk:
        break
      size += len(chunk)
      if size > max_bytes:
        dest.unlink(missing_ok=True)
        raise ValueError(f"Файл больше {settings.telegram_export_max_mb} МБ")
      out.write(chunk)
  return size


async def _telegram_export_import_handler(file: UploadFile) -> dict[str, Any]:
  max_bytes = settings.telegram_export_max_mb * 1024 * 1024
  filename = (file.filename or "telegram_export.json").lower()
  suffix = ".json.gz" if filename.endswith(".gz") else ".json"
  path = Path(settings.telegram_export_path).with_suffix(suffix)
  try:
    size = await _save_upload_stream(file, path, max_bytes=max_bytes)
  except ValueError as exc:
    return {"ok": False, "error": str(exc)}
  asyncio.create_task(_import_telegram_export_from_path(path))
  return {
    "ok": True,
    "status": "accepted",
    "bytes": size,
    "path": str(path),
    "message": "Импорт запущен в фоне. Обновите /clients через ~1 мин.",
  }


async def _bootstrap_telegram_export() -> None:
  messenger = MessengerEnrichmentService(settings, cache)
  cached = await messenger.load_telegram_export()
  if cached:
    _tg_export_progress.update(
      status="done",
      done=1,
      total=1,
      meta={**(cached.get("meta") or {}), "from_cache": True},
    )
    if hub.active_rows() and not any(r.get("_tg_export_context") for r in hub.active_rows()[:50]):
      asyncio.create_task(_apply_tg_export_to_hub())
    return
  if not settings.telegram_export_auto_import:
    return
  path = Path(settings.telegram_export_path)
  if not path.is_file():
    return
  asyncio.create_task(_import_telegram_export_from_path(path))


async def _hydrate_hub_from_cache(workbook_key: str | None = None) -> bool:
  """Подгрузить результаты сегментации из Redis/Postgres в hub."""
  if hub.results:
    pipeline_log("CACHE", "hydrate hub skipped already_loaded rows=%s", len(hub.results))
    return True
  key = workbook_key or hub.workbook_hash
  pipeline_log("CACHE", "hydrate hub start key=%s backend=%s", key or "-", cache.backend_kind)
  cached = await cache.get_segmentation_results_with_fallback(key)
  if not cached:
    pipeline_log("CACHE", "hydrate hub miss key=%s", key or "-")
    return False
  loaded = hub.apply_cached_results(cached)
  pipeline_log("CACHE", "hydrate hub done loaded=%s rows=%s", loaded, len(hub.results))
  return loaded


async def _backfill_postgres_from_redis() -> None:
  """Один раз перенести текущий Redis-снимок в Postgres (если БД пустая)."""
  if not db_persist.enabled:
    pipeline_log("DB", "backfill skipped db_persist=false")
    return
  pipeline_log("DB", "backfill start")
  await db_persist.init_schema()
  existing = await db_persist.load_moysklad_sync()
  if not existing:
    ms = await cache.get_moysklad_sync()
    if ms:
      await db_persist.persist_moysklad_sync(ms)
  seg = await cache.get_segmentation_results()
  if seg and not await db_persist.load_segmentation_results():
    await db_persist.persist_segmentation_results(seg)
  tag_rules = await cache.get_tag_rules()
  if tag_rules:
    await db_persist.persist_auxiliary("tag_rules:v1", tag_rules)
  tg_index = await cache.get_telegram_export_index()
  if tg_index:
    await db_persist.persist_auxiliary("telegram_export:index", tg_index)
  pipeline_log("DB", "backfill done")


async def _hydrate_moysklad_from_cache() -> bool:
  """Быстрая подгрузка МойСклад только из Redis/Postgres — без API."""
  client = get_moysklad_client(settings)
  if not client.enabled:
    pipeline_log("MS", "hydrate cache skipped enabled=false")
    return False
  if hub.parsed and hub.parsed.meta.get("source") == "moysklad" and hub.parsed.rows:
    pipeline_log("MS", "hydrate cache skipped already_loaded rows=%s", len(hub.parsed.rows))
    return True
  from app.services.moysklad.sync import _load_from_cache

  result = await _load_from_cache(
    cache,
    hub,
    max_counterparties=settings.moysklad_sync_limit,
    max_orders=settings.moysklad_sync_orders_limit,
  )
  pipeline_log("MS", "hydrate cache done success=%s rows=%s", result is not None and result.success, len(hub.active_rows()))
  return result is not None and result.success


async def _ensure_moysklad_data(*, fetch_positions: bool = False) -> None:
  """Подгрузить контрагентов Мой Склад из кэша или API."""
  client = get_moysklad_client(settings)
  if not client.enabled:
    pipeline_log("MS", "ensure skipped enabled=false")
    return

  parsed_count = len(hub.parsed.rows) if hub.parsed and hub.parsed.rows else 0
  is_moysklad = bool(hub.parsed and hub.parsed.meta.get("source") == "moysklad")
  pipeline_log(
    "MS",
    "ensure start parsed_count=%s is_moysklad=%s fetch_positions=%s",
    parsed_count,
    is_moysklad,
    fetch_positions,
  )
  if is_moysklad and parsed_count > 0:
    cached_ms = await cache.get_moysklad_sync()
    api_total = (cached_ms or {}).get("api_cp_total")
    if api_total is None:
      api_total = await client.get_entity_count("/entity/counterparty")
    if api_total and parsed_count >= api_total:
      if fetch_positions and not (cached_ms or {}).get("positions_loaded"):
        await refresh_moysklad_positions(client, hub, cache=cache)
      pipeline_log("MS", "ensure done from existing parsed_count=%s api_total=%s", parsed_count, api_total)
      return

  await sync_moysklad_to_hub(
    client,
    hub,
    max_counterparties=settings.moysklad_sync_limit,
    max_orders=settings.moysklad_sync_orders_limit,
    cache=cache,
    force_refresh=False,
    fetch_positions=fetch_positions,
  )
  pipeline_log("MS", "ensure done rows=%s", len(hub.active_rows()))


async def _fetch_moysklad_positions_background() -> None:
  client = get_moysklad_client(settings)
  if not client.enabled:
    return
  cached_ms = await cache.get_moysklad_sync()
  if (cached_ms or {}).get("positions_loaded"):
    return
  # Не конкурировать с первыми HTMX-переходами и lazy AI attach.
  await asyncio.sleep(15)
  if (await cache.get_moysklad_sync() or {}).get("positions_loaded"):
    return
  await refresh_moysklad_positions(client, hub, cache=cache)


async def _attach_messenger_for_ai(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
  messenger = MessengerEnrichmentService(settings, cache)
  await messenger.load_telegram_export()
  try:
    if messenger.export_loaded:
      return await messenger.attach_tg_export_only(rows)
    return await messenger.attach_messages(rows, sync_live=False, fetch_live=False)
  except httpx.HTTPError as exc:
    pipeline_log("AI", "messenger attach skipped: %s", exc, level=logging.WARNING)
    return rows


async def _schedule_lazy_ai(*, force: bool = False) -> None:
  if not hub.has_data():
    pipeline_log("AI", "lazy schedule skipped has_data=false force=%s", force)
    return
  started = await jobs.schedule_lazy_ai(
    hub,
    settings,
    cache=cache,
    messenger_attach=_attach_messenger_for_ai,
    force=force,
  )
  pipeline_log(
    "AI",
    "lazy schedule done started=%s force=%s pending=%s status=%s",
    started,
    force,
    len(jobs.pending_ai_rows(hub)),
    jobs.ai_snapshot().get("status"),
  )


async def _startup_background() -> None:
  """Тяжёлая инициализация в фоне — не блокирует healthcheck."""
  pipeline_log("PIPE", "startup background start")
  try:
    if settings.moysklad_auto_sync:
      await _ensure_moysklad_data(fetch_positions=False)
      asyncio.create_task(_fetch_moysklad_positions_background())
    await _hydrate_hub_from_cache()
    messenger = MessengerEnrichmentService(settings, cache)
    if messenger.telegram_enabled:
      try:
        await messenger.sync_telegram_inbox()
      except httpx.HTTPError as exc:
        pipeline_log("PIPE", "startup telegram sync skipped: %s", exc, level=logging.WARNING)
    await _bootstrap_telegram_export()
    await _schedule_lazy_ai()
  except Exception:  # noqa: BLE001 — фоновая инициализация не должна ронять процесс
    pipeline_log("PIPE", "startup background failed", level=logging.ERROR)
    logging.getLogger(__name__).exception("Startup background failed")
  else:
    pipeline_log("PIPE", "startup background done")


@app.on_event("startup")
async def startup_hydrate_cache() -> None:
  pipeline_log("PIPE", "startup event schedule")
  asyncio.create_task(_startup_all())


async def _startup_all() -> None:
  pipeline_log("PIPE", "startup all start")
  try:
    if db_persist.enabled:
      await db_persist.init_schema()
    await hydrate_tag_rules(cache)
    await _hydrate_hub_from_cache()
    await _hydrate_moysklad_from_cache()
    await _backfill_postgres_from_redis()
    await _startup_background()
  except Exception:  # noqa: BLE001
    pipeline_log("PIPE", "startup all failed", level=logging.ERROR)
    logging.getLogger(__name__).exception("Startup all failed")
  else:
    pipeline_log("PIPE", "startup all done")


@app.get("/health")
async def healthcheck() -> JSONResponse:
  postgres_ok = await db_persist.ping() if db_persist.enabled else False
  ai = jobs.ai_snapshot()
  return JSONResponse(
    {
      "status": "ok",
      "cache_backend": cache.backend_kind,
      "postgres_enabled": db_persist.enabled,
      "postgres_ok": postgres_ok,
      "ai_status": ai.get("status"),
      "ai_progress": ai,
    }
  )


@app.websocket("/ws/clients")
async def clients_websocket(websocket: WebSocket) -> None:
  await jobs.ws.connect(websocket)
  try:
    await websocket.send_json({"type": "ai_progress", **jobs.ai_snapshot()})
    while True:
      msg = await websocket.receive_text()
      if msg.strip().lower() in {"ping", "refresh"}:
        await websocket.send_json({"type": "ai_progress", **jobs.ai_snapshot()})
  except WebSocketDisconnect:
    pass
  finally:
    await jobs.ws.disconnect(websocket)


@app.get("/clients/ai/status")
async def clients_ai_status() -> JSONResponse:
  pending = len(jobs.pending_ai_rows(hub)) if hub.has_data() else 0
  return JSONResponse({**jobs.ai_snapshot(), "pending": pending})


@app.get("/clients/ai/poll")
async def clients_ai_poll(since: int = Query(0, ge=0)) -> JSONResponse:
  pending = len(jobs.pending_ai_rows(hub)) if hub.has_data() else 0
  return JSONResponse({**jobs.poll_snapshot(since), "pending": pending})


@app.post("/clients/ai/start", response_class=HTMLResponse)
async def clients_ai_start(request: Request) -> HTMLResponse:
  await _hydrate_hub_from_cache()
  await _hydrate_moysklad_from_cache()
  started = await jobs.schedule_lazy_ai(
    hub,
    settings,
    cache=cache,
    messenger_attach=_attach_messenger_for_ai,
    force=True,
  )
  if not started and not jobs.pending_ai_rows(hub):
    jobs.ai_progress.status = "done"
    jobs.ai_progress.done = jobs.ai_progress.total = len(hub.active_rows())
  return templates.TemplateResponse(
    "partials/ai_progress.html",
    _ctx(request, **jobs.ai_snapshot(), ai_started=started),
  )


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
    "postgres_enabled": db_persist.enabled,
    "results_from_cache": hub.results_from_cache,
    **_workflow_ctx(),
    **extra,
  }


async def _run_enrichment(rows: list[dict[str, Any]]) -> None:
  _enrich_progress.update(status="running", done=0, total=len(rows), error="")
  pipeline_log("AI", "enrichment start rows=%s", len(rows))
  service = MessengerEnrichmentService(settings, cache)
  if hub.parsed and hub.parsed.rows:
    all_rows = [enrich_row_computed(r) for r in hub.parsed.rows]
  else:
    all_rows = hub.active_rows()

  def _bump(n: int) -> None:
    _enrich_progress["done"] = min(_enrich_progress["total"], _enrich_progress["done"] + n)
    pipeline_log(
      "AI",
      "enrichment progress done=%s total=%s",
      _enrich_progress["done"],
      _enrich_progress["total"],
    )

  try:
    enriched = await service.enrich_all(rows, progress_cb=_bump, live=False)
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
    pipeline_log(
      "AI",
      "enrichment done rows=%s with_messages=%s ai_filled=%s",
      len(merged),
      with_messages,
      ai_filled,
    )
  except Exception as exc:  # noqa: BLE001
    _enrich_progress["status"] = "error"
    _enrich_progress["error"] = str(exc)
    pipeline_log("AI", "enrichment failed error=%s", exc, level=logging.ERROR)


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
  group: str = "",
  status: str = "",
  q: str = "",
  phone: str = "",
  sort: str = "",
  order: str = "asc",
  page: int = 1,
) -> dict[str, Any]:
  rows, group_options, groups_total = hub.filter_rows_with_groups(
    sales_filter=sales_filter,
    tag=tag,
    group=group,
    status=status,
    q=q,
    phone=phone,
    sort=sort,
    order=order,
  )
  per_page = max(1, settings.clients_page_size)
  total = len(rows)
  total_pages = max(1, (total + per_page - 1) // per_page)
  page = max(1, min(page, total_pages))
  start = (page - 1) * per_page
  end = start + per_page
  page_clients = rows[start:end]
  tg_export_ready = _tg_export_progress.get("status") == "done"
  return _ctx(
    request,
    clients=page_clients,
    total=total,
    page=page,
    per_page=per_page,
    total_pages=total_pages,
    page_start=start + 1 if total else 0,
    page_end=min(end, total),
    pagination_pages=_pagination_pages(page, total_pages),
    sales_filter=sales_filter,
    tag_filter=tag,
    group_filter=group,
    group_options=group_options,
    groups_total=groups_total,
    status_filter=status,
    q_filter=q,
    phone_filter=phone,
    sort_col=sort,
    sort_order=order if sort else "",
    data_source=hub.data_source_label(),
    messenger_available=settings.messenger_enabled and (
      get_green_api_client(settings).enabled or get_telegram_client(settings).enabled
    ),
    tg_export_ready=tg_export_ready,
    tg_export_progress=_tg_export_progress,
    ai_progress=jobs.ai_snapshot(),
  )


async def _clients_ctx_with_tg(
  request: Request,
  *,
  sales_filter: str = "direct",
  tag: str = "",
  group: str = "",
  status: str = "",
  q: str = "",
  phone: str = "",
  sort: str = "",
  order: str = "asc",
  page: int = 1,
) -> dict[str, Any]:
  return _clients_ctx(
    request,
    sales_filter=sales_filter,
    tag=tag,
    group=group,
    status=status,
    q=q,
    phone=phone,
    sort=sort,
    order=order,
    page=page,
  )


async def _run_segmentation(rows: list[dict[str, Any]], parsed: Any) -> None:
  _progress.update(status="running", done=0, total=len(rows), error="")
  pipeline_log(
    "AI",
    "segmentation start rows=%s source_type=%s workbook=%s",
    len(rows),
    getattr(parsed, "source_type", "-"),
    hub.workbook_hash or "-",
  )
  messenger = MessengerEnrichmentService(settings, cache)
  await messenger.load_telegram_export()
  if messenger.available:
    pipeline_log("AI", "segmentation attach messenger start rows=%s", len(rows))
    rows = await messenger.attach_messages(rows, sync_live=False, fetch_live=False)
    pipeline_log("AI", "segmentation attach messenger done rows=%s", len(rows))
  service = SegmentationService(settings)

  def _bump(n: int) -> None:
    _progress["done"] = min(_progress["total"], _progress["done"] + n)
    pipeline_log("AI", "segmentation progress done=%s total=%s", _progress["done"], _progress["total"])

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
    pipeline_log(
      "AI",
      "segmentation done rows=%s messenger_context=%s cached=%s",
      len(enriched),
      with_messages,
      bool(hub.workbook_hash),
    )
    asyncio.create_task(_schedule_lazy_ai(force=True))
  except Exception as exc:  # noqa: BLE001
    _progress["status"] = "error"
    _progress["error"] = str(exc)
    pipeline_log("AI", "segmentation failed error=%s", exc, level=logging.ERROR)


@app.get("/", response_class=HTMLResponse)
async def home(request: Request) -> HTMLResponse:
  pipeline_log("PIPE", "page home")
  await _hydrate_hub_from_cache()
  rows = hub.active_rows()
  dash = dashboard_svc.compute_cached(
    rows,
    hub_version=hub.version,
    period="month",
  )
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
  pipeline_log("PIPE", "page dashboard period=%s date_from=%s date_to=%s", period, date_from, date_to)
  await _hydrate_hub_from_cache()
  rows = hub.active_rows()
  parsed_from = _optional_query_date(date_from)
  parsed_to = _optional_query_date(date_to)
  dash = dashboard_svc.compute_cached(
    rows,
    hub_version=hub.version,
    period=period,
    date_from=parsed_from,
    date_to=parsed_to,
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
  group: str = Query(""),
  status: str = Query(""),
  q: str = Query(""),
  phone: str = Query(""),
  sort: str = Query(""),
  order: str = Query("asc"),
  page: int = Query(1, ge=1),
) -> HTMLResponse:
  pipeline_log(
    "PIPE",
    "page clients filter=%s tag=%s group=%s status=%s q=%s phone=%s sort=%s order=%s page=%s",
    filter,
    tag or "-",
    group or "-",
    status or "-",
    q or "-",
    phone or "-",
    sort or "-",
    order,
    page,
  )
  await _hydrate_hub_from_cache()
  await _hydrate_moysklad_from_cache()
  return templates.TemplateResponse(
    "clients.html",
    {
      **(await _clients_ctx_with_tg(
        request,
        sales_filter=filter,
        tag=tag,
        group=group,
        status=status,
        q=q,
        phone=phone,
        sort=sort,
        order=order,
        page=page,
      )),
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
  group: str = Query(""),
  status: str = Query(""),
  q: str = Query(""),
  phone: str = Query(""),
  sort: str = Query(""),
  order: str = Query("asc"),
  page: int = Query(1, ge=1),
) -> HTMLResponse:
  pipeline_log("PIPE", "partial clients_table filter=%s page=%s sort=%s order=%s", filter, page, sort or "-", order)
  await _hydrate_hub_from_cache()
  await _hydrate_moysklad_from_cache()
  return templates.TemplateResponse(
    "partials/clients_table.html",
    await _clients_ctx_with_tg(
      request,
      sales_filter=filter,
      tag=tag,
      group=group,
      status=status,
      q=q,
      phone=phone,
      sort=sort,
      order=order,
      page=page,
    ),
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


async def _ensure_hub_ready() -> None:
  """Подгрузить hub из кэша, если данных ещё нет (без relink по всей базе)."""
  if hub.has_parsed_data():
    return
  await _hydrate_hub_from_cache()
  await _ensure_moysklad_data(fetch_positions=False)


async def _ensure_hub_cache_only() -> None:
  """Быстрая подгрузка hub только из Redis/Postgres — без API МойСклад."""
  if hub.has_parsed_data() or hub.has_data():
    return
  await _hydrate_hub_from_cache()
  await _hydrate_moysklad_from_cache()


@app.get("/clients/{client_id}", response_class=HTMLResponse)
async def client_card(
  request: Request,
  client_id: str,
  drawer: bool = Query(False),
) -> HTMLResponse:
  await _ensure_hub_ready()
  client = hub.get_client(client_id)
  if not client:
    return templates.TemplateResponse(
      "partials/error.html",
      _ctx(request, message="Клиент не найден"),
    )
  orders = hub.resolve_order_entities(client.get("_orders_context") or [])
  orders_total = int(
    client.get("_orders_count") or client.get("Всего заказов") or len(orders)
  )
  template = "partials/client_card_drawer.html" if drawer else "partials/client_card.html"
  return templates.TemplateResponse(
    template,
    _ctx(request, client=client, orders=orders, orders_total=orders_total),
  )


@app.get("/clients/{client_id}/orders", response_class=HTMLResponse)
async def client_orders(
  request: Request,
  client_id: str,
  collapsed: bool = Query(False),
  modal: bool = Query(False),
) -> HTMLResponse:
  if collapsed:
    return HTMLResponse("")
  pipeline_log("PIPE", "partial client_orders client_id=%s", client_id)
  client, raw_orders, total = hub.get_client_orders(client_id)
  if client is None:
    await _ensure_hub_cache_only()
    client, raw_orders, total = hub.get_client_orders(client_id)
  if client is None:
    if modal:
      return HTMLResponse(
        '<div class="modal-overlay orders-modal-overlay" onclick="if(event.target===this) closeModal()">'
        '<div class="modal-card orders-modal">'
        '<button type="button" class="modal-close" onclick="closeModal()" aria-label="Закрыть">×</button>'
        '<p class="hint warn">Клиент не найден</p>'
        "</div></div>"
      )
    return HTMLResponse(
      '<div class="orders-nested orders-nested-empty">Клиент не найден</div>'
    )
  orders = compact_orders_for_display(raw_orders)
  template = "partials/client_orders_modal.html" if modal else "partials/client_orders.html"
  return templates.TemplateResponse(
    template,
    _ctx(
      request,
      client=client,
      orders=orders,
      orders_total=total,
      client_id=client_id,
    ),
  )


@app.get("/segment", response_class=HTMLResponse)
async def segment_page(request: Request) -> HTMLResponse:
  pipeline_log("PIPE", "page segment")
  await _hydrate_hub_from_cache()
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
  pipeline_log("PIPE", "page campaigns")
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
  pipeline_log("PIPE", "page settings")
  return templates.TemplateResponse(
    "settings.html",
    _ctx(
      request,
      active_page="settings",
      page_title="Настройки",
      subtitle="Интеграции и подключения",
    ),
  )


@app.get("/settings/communications", response_class=HTMLResponse)
async def communications_page(request: Request) -> HTMLResponse:
  pipeline_log("PIPE", "page settings/communications")
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
  pipeline_log("PIPE", "page settings/moysklad")
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
  payload = await status_cache.get_or_set(
    "messenger_health",
    90,
    _fetch_messenger_status_payload,
  )
  return templates.TemplateResponse(
    "partials/messenger_sidebar.html",
    _ctx(request, health=payload["health"]),
  )


async def _fetch_messenger_status_payload() -> dict[str, Any]:
  wa = get_green_api_client(settings)
  tg = get_telegram_client(settings)
  health = {"whatsapp": False, "telegram": False}
  wa_state: dict[str, Any] = {"enabled": False}
  tg_me: dict[str, Any] = {"enabled": False}

  if wa.enabled:
    try:
      wa_state = await wa.get_state()
      health["whatsapp"] = wa_state.get("stateInstance") in ("authorized", "sleepMode")
    except httpx.HTTPError as exc:
      wa_state = {
        "enabled": True,
        "stateInstance": "rate_limited",
        "error": str(exc),
      }

  if tg.enabled:
    try:
      tg_me = await tg.get_me()
      health["telegram"] = bool(tg_me.get("enabled") and tg_me.get("id"))
    except httpx.HTTPError:
      tg_me = {"enabled": True, "username": settings.telegram_bot_username}
      health["telegram"] = True

  enrichment = MessengerEnrichmentService(settings, cache)
  tg_stats = enrichment.stats if tg.enabled else {}
  return {
    "health": health,
    "wa_state": wa_state,
    "tg_me": tg_me,
    "tg_stats": tg_stats,
  }


@app.get("/messenger/status", response_class=HTMLResponse)
async def messenger_status(request: Request) -> HTMLResponse:
  payload = await status_cache.get_or_set(
    "messenger_health",
    90,
    _fetch_messenger_status_payload,
  )
  return templates.TemplateResponse(
    "partials/messenger_status.html",
    _ctx(
      request,
      health=payload["health"],
      wa_state=payload["wa_state"],
      tg_me=payload["tg_me"],
      tg_stats=payload["tg_stats"],
    ),
  )


async def _moysklad_status_context(
  *,
  sync_message: str | None = None,
  sync_ok: bool | None = None,
  hub_rows: int | None = None,
  hub_orders: int | None = None,
  api_cp_total: int | None = None,
  api_orders_total: int | None = None,
  from_moysklad: bool | None = None,
  from_cache: bool | None = None,
) -> dict[str, Any]:
  await _hydrate_hub_from_cache()
  await _hydrate_moysklad_from_cache()
  client = get_moysklad_client(settings)
  cached_ms = await cache.get_moysklad_sync()
  resolved_cp_total = api_cp_total
  if resolved_cp_total is None and cached_ms:
    resolved_cp_total = cached_ms.get("api_cp_total")
  resolved_orders_total = api_orders_total
  if resolved_orders_total is None and cached_ms:
    resolved_orders_total = cached_ms.get("api_orders_total")
  resolved_hub_rows = hub_rows if hub_rows is not None else len(hub.active_rows())
  resolved_hub_orders = hub_orders
  if resolved_hub_orders is None:
    resolved_hub_orders = (
      len(hub.orders_parsed.rows)
      if hub.orders_parsed and hub.orders_parsed.rows
      else 0
    )
  resolved_from_moysklad = from_moysklad
  if resolved_from_moysklad is None:
    resolved_from_moysklad = bool(
      hub.parsed and hub.parsed.meta.get("source") == "moysklad"
    )
  resolved_from_cache = from_cache
  if resolved_from_cache is None:
    resolved_from_cache = bool(cached_ms and resolved_from_moysklad)
  healthy = client.enabled and (
    resolved_from_moysklad or bool(cached_ms) or resolved_hub_rows > 0
  )
  ctx: dict[str, Any] = {
    "enabled": client.enabled,
    "healthy": healthy,
    "api_url": settings.moysklad_api_url,
    "hub_rows": resolved_hub_rows,
    "hub_orders": resolved_hub_orders,
    "api_cp_total": resolved_cp_total,
    "api_orders_total": resolved_orders_total,
    "from_moysklad": resolved_from_moysklad,
    "from_cache": resolved_from_cache,
  }
  if sync_message is not None:
    ctx["sync_message"] = sync_message
  if sync_ok is not None:
    ctx["sync_ok"] = sync_ok
  return ctx


@app.post("/upload/preview", response_class=HTMLResponse)
async def upload_preview(
  request: Request,
  contragents_file: UploadFile = File(...),
  orders_file: UploadFile | None = File(None),
) -> HTMLResponse:
  pipeline_log(
    "PIPE",
    "upload preview start contragents=%s orders=%s",
    contragents_file.filename or "-",
    orders_file.filename if orders_file and orders_file.filename else "-",
  )
  content = await contragents_file.read()
  orders_content = b""
  if orders_file and orders_file.filename:
    orders_content = await orders_file.read()

  cache_content = content + b"|orders|" + orders_content
  hub.workbook_hash = file_hash(cache_content)
  parsed = await cache.get_parsed(cache_content)
  from_cache = parsed is not None

  if parsed is None:
    pipeline_log("PIPE", "upload parse start workbook_hash=%s bytes=%s", hub.workbook_hash, len(content))
    parsed = await asyncio.to_thread(parse_workbook, content)
    orders_parsed = None
    if orders_content:
      pipeline_log("PIPE", "upload parse orders start bytes=%s", len(orders_content))
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
  pipeline_log(
    "PIPE",
    "upload preview done rows=%s from_cache=%s results_from_cache=%s source=%s",
    len(parsed.rows),
    from_cache,
    results_from_cache,
    getattr(parsed, "source_type", "-"),
  )

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
    pipeline_log("AI", "segment start rejected no parsed workbook", level=logging.WARNING)
    return templates.TemplateResponse(
      "partials/segment_modal.html",
      {"request": request, "error": "Сначала загрузите файл Excel."},
    )

  if hub.workbook_hash and not hub.results:
    pipeline_log("CACHE", "segment start cache lookup workbook=%s", hub.workbook_hash)
    cached = await cache.get_segmentation_results(hub.workbook_hash)
    if cached and cached.get("results"):
      hub.apply_cached_results(cached)
      _progress.update(
        status="done",
        done=len(hub.results),
        total=len(hub.results),
        error="",
      )
      pipeline_log("CACHE", "segment start served from cache rows=%s", len(hub.results))
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
  pipeline_log("AI", "segment start scheduled rows=%s limit=%s", len(rows), limit)
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
  pipeline_log("AI", "segment progress poll status=%s done=%s total=%s percent=%s", status, done, total, percent)

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
  pipeline_log("PIPE", "download segmentation xlsx")
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
  pipeline_log("PIPE", "download clients xlsx")
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
  group: str = Query(""),
  status: str = Query(""),
  q: str = Query(""),
  phone: str = Query(""),
  sort: str = Query(""),
  order: str = Query("asc"),
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
        group_filter=group,
        status_filter=status,
        q_filter=q,
        phone_filter=phone,
        sort_col=sort,
        sort_order=order if sort else "",
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
      group_filter=group,
      status_filter=status,
      q_filter=q,
      phone_filter=phone,
      sort_col=sort,
      sort_order=order if sort else "",
    ),
  )


@app.post("/telegram/export/import")
@app.post("/clients/telegram-import")
async def telegram_export_import(request: Request, file: UploadFile = File(...)):
  result = await _telegram_export_import_handler(file)
  if not result.get("ok"):
    if request.headers.get("accept", "").startswith("application/json"):
      return JSONResponse(result, status_code=413)
    return templates.TemplateResponse(
      "partials/error.html",
      _ctx(request, message=result.get("error", "Ошибка загрузки")),
      status_code=413,
    )
  if request.headers.get("accept", "").startswith("application/json"):
    return JSONResponse(result, status_code=202)
  return templates.TemplateResponse(
    "partials/error.html",
    _ctx(request, message=result.get("message", "Импорт запущен")),
    status_code=202,
  )


@app.get("/telegram/export/status")
async def telegram_export_status() -> JSONResponse:
  return JSONResponse(
    {
      "status": _tg_export_progress.get("status"),
      "meta": _tg_export_progress.get("meta") or {},
      "error": _tg_export_progress.get("error") or "",
    }
  )


@app.get("/enrich/progress", response_class=HTMLResponse)
async def enrich_progress(
  request: Request,
  filter: str = Query("direct"),
  tag: str = Query(""),
  group: str = Query(""),
  status: str = Query(""),
  q: str = Query(""),
  phone: str = Query(""),
  sort: str = Query(""),
  order: str = Query("asc"),
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
      group_filter=group,
      status_filter=status,
      q_filter=q,
      phone_filter=phone,
      sort_col=sort,
      sort_order=order if sort else "",
    ),
  )


@app.get("/moysklad/status", response_class=HTMLResponse)
async def moysklad_status(request: Request) -> HTMLResponse:
  ctx = await _moysklad_status_context()
  return templates.TemplateResponse(
    "partials/moysklad_status.html",
    {"request": request, **ctx},
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
    fetch_positions=True,
  )
  if result.success:
    asyncio.create_task(_schedule_lazy_ai(force=True))
  ctx = await _moysklad_status_context(
    sync_message=result.message,
    sync_ok=result.success,
    hub_rows=result.counterparties_count if result.success else 0,
    hub_orders=result.orders_count if result.success else 0,
    api_cp_total=result.api_counterparties_total,
    api_orders_total=result.api_orders_total,
    from_moysklad=result.success,
    from_cache=result.from_cache,
  )
  return templates.TemplateResponse(
    "partials/moysklad_status.html",
    {"request": request, **ctx},
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
