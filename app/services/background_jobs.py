"""Фоновые задачи: lazy AI-сегментация и push-обновления через WebSocket."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from fastapi import WebSocket

from app.config import Settings
from app.services.data_hub import DataHub, _row_key
from app.services.excel_parser import AI_FILLABLE_COLUMNS, CLIENT_DISPLAY_COLUMNS
from app.services.export_format import client_cell_state, client_cell_value, display_cell_value
from app.services.fields import enrich_row_computed, finalize_ai_coverage_row
from app.logging_config import pipeline_log

logger = logging.getLogger(__name__)


@dataclass
class JobProgress:
    status: str = "idle"  # idle | running | done | error
    done: int = 0
    total: int = 0
    error: str = ""
    job: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "done": self.done,
            "total": self.total,
            "error": self.error,
            "job": self.job,
            "percent": int(self.done / self.total * 100) if self.total else 0,
        }


class ConnectionManager:
    """Подписчики WebSocket для live-обновлений таблицы клиентов."""

    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections.add(websocket)
            total = len(self._connections)
        pipeline_log("WS", "client connected total=%s", total)

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._connections.discard(websocket)
            total = len(self._connections)
        pipeline_log("WS", "client disconnected total=%s", total)

    async def broadcast(self, payload: dict[str, Any]) -> None:
        if not self._connections:
            return
        message = json.dumps(payload, default=str)
        dead: list[WebSocket] = []
        async with self._lock:
            targets = list(self._connections)
        for ws in targets:
            try:
                await ws.send_text(message)
            except Exception:  # noqa: BLE001
                dead.append(ws)
        if dead:
            async with self._lock:
                for ws in dead:
                    self._connections.discard(ws)
        pipeline_log(
            "WS",
            "broadcast type=%s targets=%s dead=%s",
            payload.get("type", "-"),
            len(targets),
            len(dead),
        )


def row_ws_patch(row: dict[str, Any]) -> dict[str, Any]:
    """Компактное представление строки для обновления ячеек в браузере."""
    client_id = str(row.get("UUID") or row.get("uuid") or row.get("Наименование") or "")
    visible_ai_cols = [c for c in CLIENT_DISPLAY_COLUMNS if c in AI_FILLABLE_COLUMNS]
    cells: dict[str, dict[str, str]] = {}
    for col in visible_ai_cols:
        state = client_cell_state(row, col)
        value = client_cell_value(row, col)
        cells[col] = {
            "state": state,
            "text": str(display_cell_value(value)),
        }
    return {
        "client_id": client_id,
        "processed": bool(row.get("_ai_processed")),
        "cells": cells,
    }


class BackgroundJobService:
    """In-process очередь фоновых задач (тонкий backend без отдельного worker)."""

    def __init__(self) -> None:
        self.ws = ConnectionManager()
        self.ai_progress = JobProgress(job="lazy_ai")
        self._ai_task: asyncio.Task[None] | None = None
        self._ai_lock = asyncio.Lock()
        self._poll_seq = 0
        self._poll_rows: list[dict[str, Any]] = []

    def ai_snapshot(self) -> dict[str, Any]:
        return self.ai_progress.to_dict()

    def poll_snapshot(self, since: int = 0) -> dict[str, Any]:
        rows = [row for seq, row in self._poll_rows if seq > since]
        return {
            **self.ai_progress.to_dict(),
            "seq": self._poll_seq,
            "rows": rows,
        }

    def _queue_row_patches(self, rows: list[dict[str, Any]]) -> None:
        for row in rows:
            self._poll_seq += 1
            self._poll_rows.append((self._poll_seq, row_ws_patch(row)))
        if len(self._poll_rows) > 2000:
            self._poll_rows = self._poll_rows[-1000:]

    async def broadcast_progress(self) -> None:
        await self.ws.broadcast({"type": "ai_progress", **self.ai_progress.to_dict()})

    async def broadcast_rows(self, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        self._queue_row_patches(rows)
        await self.ws.broadcast(
            {
                "type": "ai_rows",
                "rows": [row_ws_patch(r) for r in rows],
            }
        )

    def pending_ai_rows(self, hub: DataHub) -> list[dict[str, Any]]:
        """Строки без завершённой AI-обработки."""
        results_by_key = {_row_key(r): r for r in hub.results}
        pending: list[dict[str, Any]] = []
        base_rows = hub.parsed.rows if hub.parsed and hub.parsed.rows else hub.results
        for row in base_rows:
            key = _row_key(row)
            merged = results_by_key.get(key, row)
            if not merged.get("_ai_processed"):
                pending.append(dict(row))
        return pending

    async def schedule_lazy_ai(
        self,
        hub: DataHub,
        settings: Settings,
        *,
        cache: Any,
        messenger_attach: Callable[[list[dict[str, Any]]], Any] | None = None,
        force: bool = False,
    ) -> bool:
        """Запустить lazy AI в фоне, если есть необработанные строки."""
        if not settings.ai_auto_segment:
            pipeline_log("AI", "lazy schedule skipped ai_auto_segment=false")
            return False
        pending = self.pending_ai_rows(hub)
        if not pending:
            if self.ai_progress.status == "running":
                self.ai_progress.status = "done"
                self.ai_progress.done = self.ai_progress.total
                await self.broadcast_progress()
            pipeline_log("AI", "lazy schedule skipped pending=0 status=%s", self.ai_progress.status)
            return False
        if self._ai_task and not self._ai_task.done() and not force:
            pipeline_log("AI", "lazy schedule skipped already_running pending=%s", len(pending))
            return False
        pipeline_log("AI", "lazy schedule start pending=%s force=%s", len(pending), force)
        self._ai_task = asyncio.create_task(
            self._run_lazy_ai(hub, settings, cache, pending, messenger_attach)
        )
        return True

    async def _run_lazy_ai(
        self,
        hub: DataHub,
        settings: Settings,
        cache: Any,
        rows: list[dict[str, Any]],
        messenger_attach: Callable[[list[dict[str, Any]]], Any] | None,
    ) -> None:
        async with self._ai_lock:
            from app.services.messenger_enrichment import MessengerEnrichmentService
            from app.services.segmentation import SegmentationService

            self.ai_progress.status = "running"
            self.ai_progress.done = 0
            self.ai_progress.total = len(rows)
            self.ai_progress.error = ""
            self.ai_progress.job = "lazy_ai"
            pipeline_log("AI", "lazy run start rows=%s", len(rows))
            await self.broadcast_progress()

            try:
                if messenger_attach:
                    pipeline_log("AI", "lazy messenger attach start rows=%s", len(rows))
                    try:
                        rows = await messenger_attach(rows)
                    except Exception as attach_exc:  # noqa: BLE001
                        logger.warning(
                            "Lazy AI messenger attach failed, continuing without live sync: %s",
                            attach_exc,
                        )
                        pipeline_log(
                            "AI",
                            "lazy messenger attach failed error=%s",
                            attach_exc,
                            level=logging.WARNING,
                        )
                    pipeline_log("AI", "lazy messenger attach done rows=%s", len(rows))

                service = SegmentationService(settings)
                batch_size = max(1, settings.ai_lazy_batch_size)
                processed: list[dict[str, Any]] = []

                for i in range(0, len(rows), batch_size):
                    chunk = rows[i : i + batch_size]
                    pipeline_log(
                        "AI",
                        "lazy batch start offset=%s size=%s provider=%s",
                        i,
                        len(chunk),
                        "openrouter" if settings.openrouter_api_key else "heuristic",
                    )
                    if settings.openrouter_api_key:
                        chunk_results = await service.segment_all(chunk)
                    else:
                        chunk_results = [service._heuristic_row(r) for r in chunk]  # noqa: SLF001
                    finalized = [
                        finalize_ai_coverage_row(enrich_row_computed(r))
                        for r in chunk_results
                    ]
                    processed.extend(finalized)
                    hub.upsert_results(finalized)
                    self.ai_progress.done = min(
                        self.ai_progress.total,
                        self.ai_progress.done + len(finalized),
                    )
                    await self._persist_and_notify(hub, cache, finalized)
                    pipeline_log(
                        "AI",
                        "lazy batch done offset=%s done=%s total=%s",
                        i,
                        self.ai_progress.done,
                        self.ai_progress.total,
                    )

                meta = {
                    **(hub.meta or {}),
                    "lazy_ai": True,
                    "lazy_ai_total": len(processed),
                    "processed": len(hub.results or processed),
                }
                hub.meta = meta
                await self._save_results(hub, cache)

                self.ai_progress.status = "done"
                self.ai_progress.done = self.ai_progress.total
                await self.broadcast_progress()
                pipeline_log("AI", "lazy run done processed=%s hub_rows=%s", len(processed), len(hub.results))
            except Exception as exc:  # noqa: BLE001
                logger.exception("Lazy AI failed")
                self.ai_progress.status = "error"
                self.ai_progress.error = str(exc)
                await self.broadcast_progress()
                pipeline_log("AI", "lazy run failed error=%s", exc, level=logging.ERROR)

    async def _persist_and_notify(
        self,
        hub: DataHub,
        cache: Any,
        rows: list[dict[str, Any]],
    ) -> None:
        pipeline_log("CACHE", "lazy persist start rows=%s hub_rows=%s", len(rows), len(hub.results))
        await self._save_results(hub, cache)
        await self.broadcast_progress()
        await self.broadcast_rows(rows)
        pipeline_log("CACHE", "lazy persist done rows=%s", len(rows))

    async def _save_results(self, hub: DataHub, cache: Any) -> None:
        payload = {"results": hub.results, "meta": hub.meta or {}}
        if hub.workbook_hash:
            await cache.save_segmentation_results(hub.workbook_hash, payload)
        else:
            await cache.save_results(payload)


_jobs: BackgroundJobService | None = None


def get_background_jobs() -> BackgroundJobService:
    global _jobs
    if _jobs is None:
        _jobs = BackgroundJobService()
    return _jobs
