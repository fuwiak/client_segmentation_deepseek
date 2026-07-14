"""Короткий in-memory кэш для статусов интеграций (без лишних API-вызовов)."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, TypeVar

T = TypeVar("T")


@dataclass
class _CacheEntry:
    expires_at: float
    payload: Any


class StatusCache:
    def __init__(self) -> None:
        self._entries: dict[str, _CacheEntry] = {}
        self._lock = asyncio.Lock()

    async def get_or_set(
        self,
        key: str,
        ttl_seconds: float,
        factory: Callable[[], Awaitable[T]],
    ) -> T:
        now = time.monotonic()
        entry = self._entries.get(key)
        if entry and entry.expires_at > now:
            return entry.payload

        async with self._lock:
            entry = self._entries.get(key)
            if entry and entry.expires_at > now:
                return entry.payload
            payload = await factory()
            self._entries[key] = _CacheEntry(now + ttl_seconds, payload)
            return payload

    def invalidate(self, key: str) -> None:
        self._entries.pop(key, None)


_cache = StatusCache()


def get_status_cache() -> StatusCache:
    return _cache
