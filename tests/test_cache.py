from __future__ import annotations

import asyncio

from app.config import Settings
from app.services.cache import CacheService, InMemoryCache


def _service() -> CacheService:
    # No redis_url -> in-memory backend, deterministic for tests.
    return CacheService(Settings(redis_url=""))


def test_backend_falls_back_to_memory_without_redis() -> None:
    service = _service()
    assert service.backend_kind == "memory"


def test_save_and_get_results_round_trip() -> None:
    service = _service()
    payload = {
        "results": [
            {"UUID": "1", "Группы": "премиум", "_ai_fields": ["Группы"]},
        ],
        "meta": {"processed": 1, "total": 1},
    }

    asyncio.run(service.save_segmentation_results("wb-key", payload))
    loaded = asyncio.run(service.get_segmentation_results("wb-key"))

    assert loaded == payload or loaded.get("workbook_key") == "wb-key"
    assert loaded["results"][0]["_ai_fields"] == ["Группы"]


def test_get_results_missing_key_returns_none() -> None:
    service = _service()
    assert asyncio.run(service.get_results("does-not-exist")) is None


def test_inmemory_cache_evicts_oldest() -> None:
    cache = InMemoryCache(max_items=2)

    asyncio.run(cache.set("a", 1, ttl=10))
    asyncio.run(cache.set("b", 2, ttl=10))
    asyncio.run(cache.set("c", 3, ttl=10))

    assert asyncio.run(cache.get("a")) is None
    assert asyncio.run(cache.get("b")) == 2
    assert asyncio.run(cache.get("c")) == 3
