"""Агент обогащения — анализ переписок WhatsApp/Telegram и истории заказов."""

from __future__ import annotations

from app.agents.base import Agent, AgentContext, AgentResult
from app.config import Settings
from app.services.messenger_enrichment import MessengerEnrichmentService


class EnrichmentAgent(Agent):
    name = "enrichment"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._service = MessengerEnrichmentService(settings)

    @property
    def available(self) -> bool:
        return self._service.available or bool(self._settings.openrouter_api_key)

    async def run(self, context: AgentContext) -> AgentResult:
        rows = context.payload or []
        if not isinstance(rows, list):
            return AgentResult(
                data=[],
                reasoning="Ожидался список клиентов в payload.",
                meta={"status": "error"},
            )

        limit = int(context.params.get("limit") or len(rows))
        selected = rows[: max(1, min(limit, 500))]
        enriched = await self._service.enrich_all(selected)
        with_messages = sum(1 for r in enriched if r.get("_messenger_context"))

        return AgentResult(
            data=enriched,
            reasoning=(
                f"Обогащено {len(enriched)} клиентов; "
                f"переписка найдена у {with_messages}."
            ),
            meta={
                "status": "ok",
                "total": len(enriched),
                "with_messages": with_messages,
            },
        )
