"""Коннектор 1С — PLACEHOLDER.

1С обычно интегрируется через OData/HTTP-сервисы или промежуточные выгрузки.
Здесь только интерфейс; реализация — на будущих этапах.
"""

from __future__ import annotations

from typing import Any

from app.connectors.base import DataSourceConnector
from app.domain import Customer, Order, SourceType


class OneCConnector(DataSourceConnector):
    source_type = SourceType.ONEC

    def __init__(self, enabled: bool = False) -> None:
        self._enabled = enabled

    @property
    def available(self) -> bool:
        return self._enabled

    async def fetch_customers(self, **kwargs: Any) -> list[Customer]:
        # TODO: OData /Catalog_Контрагенты -> Customer
        return []

    async def fetch_orders(self, **kwargs: Any) -> list[Order]:
        # TODO: OData /Document_ЗаказПокупателя -> Order
        return []
