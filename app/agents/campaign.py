"""Агент кампаний/таргетинга — PLACEHOLDER.

Задача (по ТЗ): анализировать сегменты и историю заказов, предлагать офферы и
таргетинг под сегмент, генерировать сообщения для рассылок и вести
коммуникацию до момента передачи диалога живому оператору.
"""

from __future__ import annotations

from app.agents.base import Agent, AgentContext, AgentResult
from app.config import Settings


class CampaignAgent(Agent):
    name = "campaign"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @property
    def available(self) -> bool:
        return False

    async def run(self, context: AgentContext) -> AgentResult:
        # TODO: сегмент -> рекомендация оффера/канала/сообщения (Recommendation)
        return AgentResult(
            data=[],
            reasoning="CampaignAgent ещё не реализован (placeholder).",
            meta={"status": "not_implemented"},
        )
