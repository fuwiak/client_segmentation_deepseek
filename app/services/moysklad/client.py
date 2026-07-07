from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any

import httpx

from app.config import Settings


class MoySkladClientBase(ABC):
    """Абстракция для интеграции с API Мой Склад."""

    @abstractmethod
    async def get_counterparties(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        ...

    @abstractmethod
    async def get_customer_orders(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        ...

    @abstractmethod
    async def update_counterparty_groups(
        self, counterparty_id: str, groups: list[str]
    ) -> dict[str, Any]:
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        ...


class MoySkladClient(MoySkladClientBase):
    def __init__(self, settings: Settings) -> None:
        self._token = settings.moysklad_api_token
        self._base_url = settings.moysklad_api_url.rstrip("/")
        self._enabled = settings.moysklad_enabled and bool(self._token)

    @property
    def enabled(self) -> bool:
        return self._enabled

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
            "Accept-Encoding": "gzip",
        }

    async def get_counterparties(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        if not self._enabled:
            return []
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{self._base_url}/entity/counterparty",
                headers=self._headers(),
                params={"limit": limit, "offset": offset},
            )
            resp.raise_for_status()
            return resp.json().get("rows", [])

    async def get_customer_orders(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        if not self._enabled:
            return []
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{self._base_url}/entity/customerorder",
                headers=self._headers(),
                params={"limit": limit, "offset": offset},
            )
            resp.raise_for_status()
            return resp.json().get("rows", [])

    async def update_counterparty_groups(
        self, counterparty_id: str, groups: list[str]
    ) -> dict[str, Any]:
        if not self._enabled:
            return {"status": "disabled", "counterparty_id": counterparty_id, "groups": groups}
        payload = {"tags": groups}
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.put(
                f"{self._base_url}/entity/counterparty/{counterparty_id}",
                headers=self._headers(),
                json=payload,
            )
            resp.raise_for_status()
            return resp.json()

    async def health_check(self) -> bool:
        if not self._enabled:
            return False
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{self._base_url}/entity/counterparty",
                    headers=self._headers(),
                    params={"limit": 1},
                )
                return resp.status_code == 200
        except httpx.HTTPError:
            return False


class MoySkladStub(MoySkladClientBase):
    """Заглушка до подключения реального токена Мой Склад."""

    async def get_counterparties(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        return []

    async def get_customer_orders(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        return []

    async def update_counterparty_groups(
        self, counterparty_id: str, groups: list[str]
    ) -> dict[str, Any]:
        return {
            "status": "stub",
            "message": "Интеграция Мой Склад не настроена",
            "counterparty_id": counterparty_id,
            "groups": groups,
        }

    async def health_check(self) -> bool:
        return False


def get_moysklad_client(settings: Settings) -> MoySkladClientBase:
    if settings.moysklad_enabled and settings.moysklad_api_token:
        return MoySkladClient(settings)
    return MoySkladStub()
