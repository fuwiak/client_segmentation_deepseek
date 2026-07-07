"""Коннектор Мой Склад — PLACEHOLDER.

Оставлен как заглушка: интерфейс готов, реальная выгрузка/маппинг подключается
позже. Низкоуровневый HTTP-клиент уже есть в `app.services.moysklad`, здесь —
адаптация его ответов к доменным моделям.
"""

from __future__ import annotations

from typing import Any

from app.connectors.base import DataSourceConnector
from app.domain import Customer, Order, SourceType


class MoySkladConnector(DataSourceConnector):
    source_type = SourceType.MOYSKLAD

    def __init__(self, enabled: bool = False) -> None:
        self._enabled = enabled

    @property
    def available(self) -> bool:
        return self._enabled

    async def fetch_customers(self, **kwargs: Any) -> list[Customer]:
        # TODO: маппинг counterparty -> Customer через app.services.moysklad
        return []

    async def fetch_orders(self, **kwargs: Any) -> list[Order]:
        # TODO: маппинг customerorder -> Order
        return []
