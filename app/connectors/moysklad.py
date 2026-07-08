"""Коннектор Мой Склад — выгрузка контрагентов и заказов через Remap 1.2 API."""

from __future__ import annotations

from typing import Any

from app.config import Settings, get_settings
from app.connectors.base import DataSourceConnector
from app.domain import Customer, Order, SourceType
from app.services.moysklad import get_moysklad_client
from app.services.moysklad.mapper import (
    customer_from_counterparty,
    order_from_customerorder,
)


class MoySkladConnector(DataSourceConnector):
    source_type = SourceType.MOYSKLAD

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._client = get_moysklad_client(self._settings)

    @property
    def available(self) -> bool:
        return self._client.enabled

    async def fetch_customers(self, **kwargs: Any) -> list[Customer]:
        max_rows = int(kwargs.get("max_rows", self._settings.moysklad_sync_limit))
        rows = await self._client.fetch_all_counterparties(max_rows=max_rows)
        return [customer_from_counterparty(cp) for cp in rows]

    async def fetch_orders(self, **kwargs: Any) -> list[Order]:
        max_rows = int(kwargs.get("max_orders", self._settings.moysklad_sync_orders_limit))
        orders_raw = await self._client.fetch_all_customer_orders(max_rows=max_rows)
        counterparties = await self._client.fetch_all_counterparties(
            max_rows=self._settings.moysklad_sync_limit
        )
        agents_by_id = {
            str(cp.get("id")): str(cp.get("name") or "")
            for cp in counterparties
            if cp.get("id")
        }
        return [
            order_from_customerorder(order, agents_by_id)
            for order in orders_raw
        ]
