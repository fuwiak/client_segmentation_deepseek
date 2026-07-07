from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi.testclient import TestClient

import app.main as m
from app.config import Settings
from app.services.cache import CacheService
from app.services.excel_parser import parse_workbook

XLSX = Path("Контрагенты V2 эксель.xlsx")


def test_parse_workbook_reads_contragents_file() -> None:
    if not XLSX.exists():
        return
    content = XLSX.read_bytes()
    parsed = parse_workbook(content)
    assert parsed.source_type == "contragents"
    assert parsed.total_rows > 0
    assert any(r.get("Наименование") for r in parsed.rows)


def test_upload_cache_round_trip() -> None:
    if not XLSX.exists():
        return
    content = XLSX.read_bytes()
    cache = CacheService(Settings(redis_url=""))
    key_content = content + b"|orders|"

    assert asyncio.run(cache.get_parsed(key_content)) is None
    parsed = parse_workbook(content)
    asyncio.run(cache.set_parsed(key_content, parsed))
    cached = asyncio.run(cache.get_parsed(key_content))

    assert cached is not None
    assert cached.total_rows == parsed.total_rows


def test_upload_preview_uses_cache_on_second_request() -> None:
    if not XLSX.exists():
        return
    # Isolate from other tests sharing the process-wide in-memory cache.
    backend = m.cache._backend
    if hasattr(backend, "_store"):
        backend._store.clear()
        backend._order.clear()

    client = TestClient(m.app)
    files = {
        "contragents_file": (
            "c.xlsx",
            XLSX.read_bytes(),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    }

    first = client.post("/upload/preview", files=files)
    second = client.post("/upload/preview", files=files)

    assert first.status_code == 200
    assert second.status_code == 200
    assert "из кэша" not in first.text
    assert "из кэша" in second.text
