"""Общие фикстуры pytest."""

from __future__ import annotations

import pytest

from app.config import get_settings


@pytest.fixture(autouse=True)
def _disable_auth_in_tests(monkeypatch: pytest.MonkeyPatch) -> None:
    """В тестах логин выключен, чтобы не ломать HTTP-сценарии."""
    monkeypatch.setenv("AUTH_ENABLED", "false")
    monkeypatch.setenv("AUTH_PASSWORD", "")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
