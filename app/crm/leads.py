"""Управление лидами и воронкой — PLACEHOLDER.

Задача (по ТЗ): приём входящих лидов из разных каналов, квалификация,
привязка к клиенту, движение по воронке, передача оператору.
"""

from __future__ import annotations

from app.domain import Lead, LeadStatus
from app.repository.base import CustomerRepository


class LeadService:
    def __init__(self, repository: CustomerRepository) -> None:
        self._repo = repository
        self._leads: list[Lead] = []

    async def intake(self, lead: Lead) -> Lead:
        # TODO: матчинг с существующим клиентом, назначение оператора
        self._leads.append(lead)
        return lead

    async def list_leads(self, status: LeadStatus | None = None) -> list[Lead]:
        if status is None:
            return list(self._leads)
        return [lead for lead in self._leads if lead.status == status]
