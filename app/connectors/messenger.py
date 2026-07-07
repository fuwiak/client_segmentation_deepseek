"""Коннектор мессенджеров (Telegram/WhatsApp) — PLACEHOLDER.

Самый ценный источник для AI-обогащения (пол, имя, предпочтения из переписок),
но и самый чувствительный (приватность, доступ к API). Рекомендуемый путь:
сначала экспорты переписок (файлы), затем официальные API.
"""

from __future__ import annotations

from typing import Any

from app.connectors.base import DataSourceConnector
from app.domain import Customer, Interaction, Order, SourceType


class MessengerConnector(DataSourceConnector):
    source_type = SourceType.MESSENGER

    def __init__(self, enabled: bool = False) -> None:
        self._enabled = enabled

    @property
    def available(self) -> bool:
        return self._enabled

    async def fetch_customers(self, **kwargs: Any) -> list[Customer]:
        return []

    async def fetch_orders(self, **kwargs: Any) -> list[Order]:
        return []

    async def fetch_interactions(self, **kwargs: Any) -> list[Interaction]:
        # TODO: парсинг экспортов переписок -> Interaction
        return []
