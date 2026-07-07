"""Статистика CRM — базовая реализация поверх репозитория.

Считает то, что доступно уже сейчас на XLSX-данных. Расширяется по мере
наполнения базы (заказы, лиды, кампании).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from app.repository.base import CustomerRepository


@dataclass
class CrmStats:
    total_customers: int = 0
    with_phone: int = 0
    with_telegram: int = 0
    by_gender: dict[str, int] = field(default_factory=dict)
    top_segments: list[tuple[str, int]] = field(default_factory=list)
    average_check: float | None = None


class StatsService:
    def __init__(self, repository: CustomerRepository) -> None:
        self._repo = repository

    async def compute(self) -> CrmStats:
        customers = await self._repo.list_customers(limit=10_000)
        if not customers:
            return CrmStats()

        gender = Counter(c.gender.value for c in customers)
        segments: Counter[str] = Counter()
        checks: list[float] = []
        with_phone = with_tg = 0

        for c in customers:
            for code in c.segment_codes():
                segments[code] += 1
            if c.average_check is not None:
                checks.append(c.average_check)
            if c.phone:
                with_phone += 1
            if c.telegram:
                with_tg += 1

        return CrmStats(
            total_customers=len(customers),
            with_phone=with_phone,
            with_telegram=with_tg,
            by_gender=dict(gender),
            top_segments=segments.most_common(10),
            average_check=round(sum(checks) / len(checks), 2) if checks else None,
        )
