from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any

import httpx

from app.config import Settings


class MoySkladClientBase(ABC):
    """Абстракция для интеграции с API Мой Склад."""

    @property
    def enabled(self) -> bool:
        return False

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

    @abstractmethod
    async def get_entity_count(self, path: str) -> int | None:
        ...

    @abstractmethod
    async def fetch_all_counterparties(self, max_rows: int = 500) -> list[dict[str, Any]]:
        ...

    @abstractmethod
    async def fetch_all_customer_orders(self, max_rows: int = 2000) -> list[dict[str, Any]]:
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

    async def _get_page(
        self,
        path: str,
        *,
        limit: int,
        offset: int,
        extra_params: dict[str, Any] | None = None,
        timeout: float = 30,
    ) -> tuple[list[dict[str, Any]], int | None]:
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if extra_params:
            params.update(extra_params)
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(
                f"{self._base_url}{path}",
                headers=self._headers(),
                params=params,
            )
            resp.raise_for_status()
            payload = resp.json()
            total = payload.get("meta", {}).get("size")
            return payload.get("rows", []), total

    async def _fetch_all(
        self,
        path: str,
        *,
        max_rows: int,
        page_size: int = 1000,
        extra_params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        offset = 0
        unlimited = max_rows <= 0
        while unlimited or len(rows) < max_rows:
            batch_limit = page_size if unlimited else min(page_size, max_rows - len(rows))
            batch, _ = await self._get_page(
                path,
                limit=batch_limit,
                offset=offset,
                extra_params=extra_params,
                timeout=60,
            )
            if not batch:
                break
            rows.extend(batch)
            if len(batch) < page_size:
                break
            offset += len(batch)
        return rows

    async def get_counterparties(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        if not self._enabled:
            return []
        rows, _ = await self._get_page("/entity/counterparty", limit=limit, offset=offset)
        return rows

    async def get_entity_count(self, path: str) -> int | None:
        if not self._enabled:
            return None
        _, total = await self._get_page(path, limit=1, offset=0)
        return total

    async def get_customer_orders(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        if not self._enabled:
            return []
        rows, _ = await self._get_page(
            "/entity/customerorder",
            limit=limit,
            offset=offset,
            extra_params={"expand": "agent,state,salesChannel"},
        )
        return rows

    async def fetch_all_counterparties(self, max_rows: int = 500) -> list[dict[str, Any]]:
        if not self._enabled:
            return []
        return await self._fetch_all("/entity/counterparty", max_rows=max_rows)

    async def fetch_all_customer_orders(self, max_rows: int = 2000) -> list[dict[str, Any]]:
        if not self._enabled:
            return []
        return await self._fetch_all(
            "/entity/customerorder",
            max_rows=max_rows,
            extra_params={"expand": "agent,state,salesChannel"},
        )

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

    async def get_entity_count(self, path: str) -> int | None:
        return None

    async def fetch_all_counterparties(self, max_rows: int = 500) -> list[dict[str, Any]]:
        return []

    async def fetch_all_customer_orders(self, max_rows: int = 2000) -> list[dict[str, Any]]:
        return []


def get_moysklad_client(settings: Settings) -> MoySkladClientBase:
    if settings.moysklad_enabled and settings.moysklad_api_token:
        return MoySkladClient(settings)
    return MoySkladStub()
