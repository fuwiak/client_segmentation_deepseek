from __future__ import annotations

import asyncio

from app.config import Settings
from app.services.cache import CacheService, file_hash
from app.services.data_hub import DataHub


def test_save_segmentation_results_by_workbook_key() -> None:
    service = CacheService(Settings(redis_url=""))
    key = file_hash(b"test-workbook")
    payload = {
        "results": [{"UUID": "1", "Группы": "vip"}],
        "meta": {"processed": 1, "total": 1},
    }

    asyncio.run(service.save_segmentation_results(key, payload))
    by_key = asyncio.run(service.get_segmentation_results(key))
    latest = asyncio.run(service.get_segmentation_results())

    assert by_key is not None
    assert by_key["results"][0]["Группы"] == "vip"
    assert by_key["workbook_key"] == key
    assert latest == by_key


def test_hydrate_hub_from_cached_payload() -> None:
    hub = DataHub()
    ok = hub.apply_cached_results(
        {
            "results": [{"Наименование": "Иван", "Группы": "новый"}],
            "meta": {"processed": 1},
            "workbook_key": "abc123",
        }
    )

    assert ok is True
    assert hub.results_from_cache is True
    assert hub.workbook_hash == "abc123"
    assert hub.active_rows()[0]["Наименование"] == "Иван"
