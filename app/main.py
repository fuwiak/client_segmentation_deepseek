from __future__ import annotations

import asyncio
import io
from typing import Any

import pandas as pd
from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import get_settings
from app.services.cache import get_cache
from app.services.excel_parser import SEGMENT_COLUMNS, enrich_with_orders, parse_workbook
from app.services.moysklad import get_moysklad_client
from app.services.segmentation import SegmentationService

settings = get_settings()
cache = get_cache(settings)
app = FastAPI(title=settings.app_title)
templates = Jinja2Templates(directory="app/templates")
app.mount("/static", StaticFiles(directory="app/static"), name="static")

_store: dict[str, Any] = {"results": [], "meta": {}}
_progress: dict[str, Any] = {"status": "idle", "done": 0, "total": 0, "error": ""}


async def _run_segmentation(rows: list[dict[str, Any]], parsed: Any) -> None:
    _progress.update(status="running", done=0, total=len(rows), error="")
    service = SegmentationService(settings)

    def _bump(n: int) -> None:
        _progress["done"] = min(_progress["total"], _progress["done"] + n)

    try:
        results = await service.segment_all(rows, progress_cb=_bump)
        meta = {
            "processed": len(results),
            "source_type": parsed.source_type,
            "total": parsed.total_rows,
        }
        _store["results"] = results
        _store["meta"] = meta
        await cache.save_results({"results": results, "meta": meta})
        _progress["done"] = _progress["total"]
        _progress["status"] = "done"
    except Exception as exc:  # noqa: BLE001 — surface any failure to the modal
        _progress["status"] = "error"
        _progress["error"] = str(exc)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    moysklad = get_moysklad_client(settings)
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "title": settings.app_title,
            "active_page": "home",
            "segment_columns": SEGMENT_COLUMNS,
            "moysklad_enabled": moysklad.enabled,
            "model": settings.openrouter_model,
            "has_api_key": bool(settings.openrouter_api_key),
        },
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
        # Parsing (pandas/openpyxl) is blocking and CPU-bound: run it off the
        # event loop so uploads don't stall the whole app.
        parsed = await asyncio.to_thread(parse_workbook, content)
        if orders_content:
            orders_parsed = await asyncio.to_thread(parse_workbook, orders_content)
            parsed = enrich_with_orders(parsed, orders_parsed)
        await cache.set_parsed(cache_content, parsed)

    _store["parsed"] = parsed
    preview_rows = parsed.rows[:20]

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
    parsed = _store.get("parsed")
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
            results=_store["results"],
            segment_columns=SEGMENT_COLUMNS,
            meta=_store["meta"],
        )
    return templates.TemplateResponse("partials/segment_progress.html", ctx)


@app.get("/download/xlsx")
async def download_xlsx() -> StreamingResponse:
    results = _store.get("results", [])
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
