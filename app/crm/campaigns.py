"""Управление рекламными кампаниями — PLACEHOLDER.

Задача (по ТЗ): создание кампаний под сегменты, генерация офферов с помощью
CampaignAgent, запуск рассылок по каналам, сбор метрик.
"""

from __future__ import annotations

from app.domain import Campaign
from app.repository.base import CustomerRepository


class CampaignService:
    def __init__(self, repository: CustomerRepository) -> None:
        self._repo = repository
        self._campaigns: list[Campaign] = []

    async def create(self, campaign: Campaign) -> Campaign:
        # TODO: валидация сегментов, привязка CampaignAgent для оффера
        self._campaigns.append(campaign)
        return campaign

    async def list_campaigns(self) -> list[Campaign]:
        return list(self._campaigns)
