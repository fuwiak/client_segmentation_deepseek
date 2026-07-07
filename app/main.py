from __future__ import annotations

import io
from typing import Any

import pandas as pd
from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import get_settings
from app.services.excel_parser import SEGMENT_COLUMNS, enrich_with_orders, parse_workbook
from app.services.moysklad import get_moysklad_client
from app.services.segmentation import SegmentationService

settings = get_settings()
app = FastAPI(title=settings.app_title)
templates = Jinja2Templates(directory="app/templates")
app.mount("/static", StaticFiles(directory="app/static"), name="static")

_store: dict[str, Any] = {"results": [], "meta": {}}


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    moysklad = get_moysklad_client(settings)
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "title": settings.app_title,
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
    parsed = parse_workbook(content)

    if orders_file and orders_file.filename:
        orders_content = await orders_file.read()
        orders_parsed = parse_workbook(orders_content)
        parsed = enrich_with_orders(parsed, orders_parsed)

    _store["parsed"] = parsed
    preview_rows = parsed.rows[:20]

    return templates.TemplateResponse(
        "partials/preview.html",
        {
            "request": request,
            "parsed": parsed,
            "preview_rows": preview_rows,
            "segment_columns": SEGMENT_COLUMNS,
        },
    )


@app.post("/segment", response_class=HTMLResponse)
async def segment(
    request: Request,
    limit: int = Form(50),
) -> HTMLResponse:
    parsed = _store.get("parsed")
    if not parsed:
        return templates.TemplateResponse(
            "partials/error.html",
            {"request": request, "message": "Сначала загрузите файл Excel."},
        )

    rows = parsed.rows[: max(1, min(limit, 500))]
    service = SegmentationService(settings)
    results = await service.segment_all(rows)

    _store["results"] = results
    _store["meta"] = {
        "processed": len(results),
        "source_type": parsed.source_type,
        "total": parsed.total_rows,
    }

    return templates.TemplateResponse(
        "partials/results.html",
        {
            "request": request,
            "results": results,
            "segment_columns": SEGMENT_COLUMNS,
            "meta": _store["meta"],
        },
    )


@app.get("/download/xlsx")
async def download_xlsx() -> StreamingResponse:
    results = _store.get("results", [])
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
