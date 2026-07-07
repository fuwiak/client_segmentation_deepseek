"""Агент обогащения — PLACEHOLDER.

Задача (по ТЗ): анализировать переписки и историю заказов клиента и дозаполнять
профиль — пол, имя получателя, предпочтения (любимые цветы/букеты), поводы,
периодичность заказов. Реализуется на этапе подключения источника переписок.
"""

from __future__ import annotations

from app.agents.base import Agent, AgentContext, AgentResult
from app.config import Settings


class EnrichmentAgent(Agent):
    name = "enrichment"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @property
    def available(self) -> bool:
        return False

    async def run(self, context: AgentContext) -> AgentResult:
        # TODO: LLM-анализ Interaction + Order -> обновление Customer
        return AgentResult(
            data=context.payload,
            reasoning="EnrichmentAgent ещё не реализован (placeholder).",
            meta={"status": "not_implemented"},
        )
