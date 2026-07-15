from __future__ import annotations

import asyncio

from app.config import Settings
from app.services.background_jobs import BackgroundJobService, row_ws_patch
from app.services.data_hub import DataHub


def test_pending_ai_rows_without_results() -> None:
    hub = DataHub()
    hub.parsed = type("P", (), {"rows": [{"UUID": "1", "Наименование": "Антон"}]})()
    jobs = BackgroundJobService()
    pending = jobs.pending_ai_rows(hub)
    assert len(pending) == 1


def test_pending_ai_rows_skips_processed() -> None:
    hub = DataHub()
    hub.parsed = type("P", (), {"rows": [{"UUID": "1", "Наименование": "Антон"}]})()
    hub.results = [{"UUID": "1", "Наименование": "Антон", "_ai_processed": True}]
    jobs = BackgroundJobService()
    assert jobs.pending_ai_rows(hub) == []


def test_pending_ai_rows_scoped_to_page() -> None:
    hub = DataHub()
    hub.parsed = type(
        "P",
        (),
        {
            "rows": [
                {"UUID": "1", "Наименование": "А"},
                {"UUID": "2", "Наименование": "Б"},
            ]
        },
    )()
    jobs = BackgroundJobService()
    page = [{"UUID": "2", "Наименование": "Б"}]
    pending = jobs.pending_ai_rows(hub, rows=page)
    assert len(pending) == 1
    assert pending[0]["UUID"] == "2"


def test_row_ws_patch_running_state() -> None:
    row = {"UUID": "abc", "Группы": "", "_ai_processed": False}
    patch = row_ws_patch(row)
    assert patch["client_id"] == "abc"
    assert patch["cells"]["Группы"]["state"] == "running"


def test_hub_upsert_results() -> None:
    hub = DataHub()
    hub.upsert_results([{"UUID": "1", "Группы": "VIP", "_ai_processed": True}])
    hub.upsert_results([{"UUID": "1", "Группы": "VIP+", "Теги": "#vip", "_ai_processed": True}])
    assert len(hub.results) == 1
    assert hub.results[0]["Теги"] == "#vip"


def test_provider_failure_opens_circuit_for_later_batches(monkeypatch) -> None:
    import app.services.segmentation as segmentation_module

    calls = {"provider": 0, "heuristic": 0}

    async def fake_segment_all(self, rows):
        calls["provider"] += 1
        return [{**row, "_ai_processed": False, "_ai_fields": []} for row in rows]

    def fake_heuristic(self, row):
        calls["heuristic"] += 1
        return {**row, "_ai_processed": False, "_ai_fields": []}

    monkeypatch.setattr(segmentation_module.SegmentationService, "segment_all", fake_segment_all)
    monkeypatch.setattr(segmentation_module.SegmentationService, "_heuristic_row", fake_heuristic)

    hub = DataHub()
    rows = [{"UUID": str(i), "Наименование": str(i)} for i in range(3)]
    hub.parsed = type("P", (), {"rows": rows})()
    jobs = BackgroundJobService()
    settings = Settings(openrouter_api_key="broken", ai_lazy_batch_size=1)

    asyncio.run(jobs._run_lazy_ai(hub, settings, _NoopCache(), rows, None))

    assert calls["provider"] == 1
    assert calls["heuristic"] == 2
    assert jobs._ai_provider_circuit_open is True


class _NoopCache:
    async def save_segmentation_results(self, *_args, **_kwargs):
        return None

    async def save_results(self, *_args, **_kwargs):
        return None
