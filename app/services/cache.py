"""Кэш загруженных Excel-файлов.

Хранит результат разбора workbook по SHA-256 содержимого файла, чтобы повторная
загрузка того же файла не парсилась заново, а бралась из кэша (быстрее).

Backend: Redis (на Railway через REDIS_URL). Если Redis недоступен —
graceful fallback на процессный in-memory кэш, чтобы локальная разработка и
работа без Redis не ломались.
"""

from __future__ import annotations

import hashlib
import pickle
from typing import Any

from app.config import Settings

CACHE_PREFIX = "xlsx:"
RESULTS_PREFIX = "results:"
LATEST_RESULTS_KEY = "latest"


def file_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


class CacheBackend:
    async def get(self, key: str) -> Any | None:
        raise NotImplementedError

    async def set(self, key: str, value: Any, ttl: int) -> None:
        raise NotImplementedError

    @property
    def kind(self) -> str:
        return "none"


class InMemoryCache(CacheBackend):
    """Fallback-кэш в памяти процесса (без TTL-инвалидации, ограничен размером)."""

    def __init__(self, max_items: int = 32) -> None:
        self._store: dict[str, Any] = {}
        self._order: list[str] = []
        self._max = max_items

    async def get(self, key: str) -> Any | None:
        return self._store.get(key)

    async def set(self, key: str, value: Any, ttl: int) -> None:
        if key not in self._store and len(self._order) >= self._max:
            oldest = self._order.pop(0)
            self._store.pop(oldest, None)
        self._store[key] = value
        if key not in self._order:
            self._order.append(key)

    @property
    def kind(self) -> str:
        return "memory"


class RedisCache(CacheBackend):
    def __init__(self, url: str) -> None:
        import redis.asyncio as redis

        self._client = redis.from_url(url, socket_connect_timeout=5)

    async def get(self, key: str) -> Any | None:
        raw = await self._client.get(key)
        if raw is None:
            return None
        return pickle.loads(raw)

    async def set(self, key: str, value: Any, ttl: int) -> None:
        await self._client.set(key, pickle.dumps(value), ex=ttl)

    async def ping(self) -> bool:
        try:
            return bool(await self._client.ping())
        except Exception:  # noqa: BLE001 — любая ошибка соединения = недоступен
            return False

    @property
    def kind(self) -> str:
        return "redis"


class CacheService:
    """Фасад кэша: пробует Redis, иначе in-memory. Хранит разобранные workbook."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._ttl = settings.cache_ttl_seconds
        self._backend: CacheBackend = self._make_backend()

    def _make_backend(self) -> CacheBackend:
        if self._settings.redis_url:
            try:
                return RedisCache(self._settings.redis_url)
            except Exception:  # noqa: BLE001 — нет библиотеки/URL кривой -> fallback
                return InMemoryCache()
        return InMemoryCache()

    @property
    def backend_kind(self) -> str:
        return self._backend.kind

    async def get_parsed(self, content: bytes) -> Any | None:
        key = CACHE_PREFIX + file_hash(content)
        try:
            return await self._backend.get(key)
        except Exception:  # noqa: BLE001 — деградируем без кэша, не роняем аплоад
            return None

    async def set_parsed(self, content: bytes, parsed: Any) -> None:
        key = CACHE_PREFIX + file_hash(content)
        try:
            await self._backend.set(key, parsed, self._ttl)
        except Exception:  # noqa: BLE001 — запись в кэш не критична
            pass

    async def save_results(
        self, payload: Any, key: str = LATEST_RESULTS_KEY
    ) -> None:
        """Сохранить сгенерированные записи сегментации."""
        try:
            await self._backend.set(RESULTS_PREFIX + key, payload, self._ttl)
        except Exception:  # noqa: BLE001
            pass

    async def get_results(self, key: str = LATEST_RESULTS_KEY) -> Any | None:
        try:
            return await self._backend.get(RESULTS_PREFIX + key)
        except Exception:  # noqa: BLE001
            return None

    async def save_segmentation_results(
        self,
        workbook_key: str,
        payload: dict[str, Any],
    ) -> None:
        """Сохранить результаты по ключу workbook и как latest."""
        full = {**payload, "workbook_key": workbook_key}
        await self.save_results(full, key=LATEST_RESULTS_KEY)
        await self.save_results(full, key=workbook_key)

    async def get_segmentation_results(
        self, workbook_key: str | None = None
    ) -> dict[str, Any] | None:
        """Вернуть результаты для workbook или последние сохранённые."""
        if workbook_key:
            hit = await self.get_results(workbook_key)
            if hit:
                return hit
        return await self.get_results(LATEST_RESULTS_KEY)


_cache_service: CacheService | None = None


def get_cache(settings: Settings) -> CacheService:
    global _cache_service
    if _cache_service is None:
        _cache_service = CacheService(settings)
    return _cache_service
