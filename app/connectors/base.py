"""Абстракция источника данных.

Любой источник (Excel, Мой Склад, 1С, мессенджер) реализует этот интерфейс и
возвращает уже нормализованные доменные объекты, а не сырые строки. Благодаря
этому остальная система не знает, откуда пришли данные.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from app.domain import Customer, Interaction, Order, SourceType


class DataSourceConnector(ABC):
    source_type: SourceType

    @property
    @abstractmethod
    def available(self) -> bool:
        """Готов ли коннектор отдавать данные (настроен ли доступ)."""
        ...

    @abstractmethod
    async def fetch_customers(self, **kwargs: Any) -> list[Customer]:
        ...

    @abstractmethod
    async def fetch_orders(self, **kwargs: Any) -> list[Order]:
        ...

    async def fetch_interactions(self, **kwargs: Any) -> list[Interaction]:
        """Переписки/звонки. По умолчанию источник их не отдаёт."""
        return []

    async def health_check(self) -> bool:
        return self.available
