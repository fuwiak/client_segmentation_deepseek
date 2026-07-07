"""Абстракция хранилища клиентской базы.

UI и агенты работают только через этот интерфейс. Сейчас реализация —
in-memory (для MVP на XLSX). На проде подключается SQL/Postgres без изменения
остальных слоёв.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.domain import Customer, Interaction, Order


class CustomerRepository(ABC):
    @abstractmethod
    async def upsert_customers(self, customers: list[Customer]) -> int:
        """Добавляет/обновляет клиентов, склеивая по dedup_key. Возвращает число."""
        ...

    @abstractmethod
    async def get_customer(self, customer_id: str) -> Customer | None:
        ...

    @abstractmethod
    async def list_customers(
        self, limit: int = 100, offset: int = 0
    ) -> list[Customer]:
        ...

    @abstractmethod
    async def count_customers(self) -> int:
        ...

    @abstractmethod
    async def add_orders(self, orders: list[Order]) -> int:
        ...

    @abstractmethod
    async def list_orders(self, customer_id: str | None = None) -> list[Order]:
        ...

    async def add_interactions(self, interactions: list[Interaction]) -> int:
        return 0

    @abstractmethod
    async def clear(self) -> None:
        ...
