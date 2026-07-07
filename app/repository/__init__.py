"""Хранилище клиентской базы.

Активно: InMemoryRepository. SQL/Postgres — на этапе прода (тот же интерфейс).
"""

from app.repository.base import CustomerRepository
from app.repository.memory import InMemoryRepository

__all__ = ["CustomerRepository", "InMemoryRepository"]


_default_repository: CustomerRepository | None = None


def get_repository() -> CustomerRepository:
    """Singleton текущего репозитория. Точка подмены на SQL в будущем."""
    global _default_repository
    if _default_repository is None:
        _default_repository = InMemoryRepository()
    return _default_repository
