"""AI-агенты.

Активен: SegmentationAgent. EnrichmentAgent и CampaignAgent — placeholder.
Движок — OpenRouter (DeepSeek); в будущем возможна замена на Hermes-agent
через тот же интерфейс Agent.
"""

from app.agents.base import Agent, AgentContext, AgentResult
from app.agents.campaign import CampaignAgent
from app.agents.enrichment import EnrichmentAgent
from app.agents.segmentation import SegmentationAgent

__all__ = [
    "Agent",
    "AgentContext",
    "AgentResult",
    "CampaignAgent",
    "EnrichmentAgent",
    "SegmentationAgent",
]
