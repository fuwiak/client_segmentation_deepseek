"""In-memory реализация хранилища — для MVP на XLSX.

Склейка клиентов по `dedup_key` (нормализованный телефон/email). Не переживает
рестарт — для прода заменить на SQL-репозиторий (тот же интерфейс).
"""

from __future__ import annotations

from app.domain import Customer, Interaction, Order
from app.repository.base import CustomerRepository


class InMemoryRepository(CustomerRepository):
    def __init__(self) -> None:
        self._customers: dict[str, Customer] = {}
        self._dedup_index: dict[str, str] = {}
        self._orders: list[Order] = []
        self._interactions: list[Interaction] = []

    async def upsert_customers(self, customers: list[Customer]) -> int:
        for customer in customers:
            key = customer.dedup_key
            existing_id = self._dedup_index.get(key) if key else None
            if existing_id and existing_id in self._customers:
                merged = self._merge(self._customers[existing_id], customer)
                self._customers[existing_id] = merged
            else:
                self._customers[customer.id] = customer
                if key:
                    self._dedup_index[key] = customer.id
        return len(customers)

    @staticmethod
    def _merge(base: Customer, incoming: Customer) -> Customer:
        data = base.model_dump()
        for field, value in incoming.model_dump().items():
            if value in (None, "", [], {}):
                continue
            if data.get(field) in (None, "", [], {}):
                data[field] = value
        data["external_ids"] = {**base.external_ids, **incoming.external_ids}
        return Customer(**data)

    async def get_customer(self, customer_id: str) -> Customer | None:
        return self._customers.get(customer_id)

    async def list_customers(self, limit: int = 100, offset: int = 0) -> list[Customer]:
        return list(self._customers.values())[offset : offset + limit]

    async def count_customers(self) -> int:
        return len(self._customers)

    async def add_orders(self, orders: list[Order]) -> int:
        self._orders.extend(orders)
        return len(orders)

    async def list_orders(self, customer_id: str | None = None) -> list[Order]:
        if customer_id is None:
            return list(self._orders)
        return [o for o in self._orders if o.customer_id == customer_id]

    async def add_interactions(self, interactions: list[Interaction]) -> int:
        self._interactions.extend(interactions)
        return len(interactions)

    async def clear(self) -> None:
        self._customers.clear()
        self._dedup_index.clear()
        self._orders.clear()
        self._interactions.clear()
