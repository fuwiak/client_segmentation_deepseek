"""Агент сегментации — АКТИВЕН.

Обёртка над существующей рабочей логикой `app.services.segmentation`, приведённая
к единому интерфейсу `Agent`. Существующий UI-поток продолжает вызывать сервис
напрямую; здесь — точка входа для новой архитектуры (repository → agent).
"""

from __future__ import annotations

from typing import Any

from app.agents.base import Agent, AgentContext, AgentResult
from app.config import Settings
from app.services.segmentation import SegmentationService


class SegmentationAgent(Agent):
    name = "segmentation"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._service = SegmentationService(settings)

    @property
    def available(self) -> bool:
        return bool(self._settings.openrouter_api_key)

    async def run(self, context: AgentContext) -> AgentResult:
        rows: list[dict[str, Any]] = context.payload or []
        results = await self._service.segment_all(rows)
        processed = sum(1 for r in results if r.get("_ai_processed"))
        return AgentResult(
            data=results,
            meta={"processed": processed, "total": len(results)},
        )
