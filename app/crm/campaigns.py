"""Управление рекламными кампаниями / рассылками.

Ручной режим — по текущим фильтрам клиентов.
Авто (Demo) — по рекомендациям AI (точки касания).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from app.domain import Campaign, CampaignStatus
from app.repository.base import CustomerRepository
from app.services.fields import has_crm_contact
from app.services.segmentation import SegmentationService


class CampaignService:
    def __init__(self, repository: CustomerRepository) -> None:
        self._repo = repository
        self._campaigns: list[dict[str, Any]] = []

    async def create(self, campaign: Campaign) -> Campaign:
        self._campaigns.append(self._to_dict(campaign))
        return campaign

    async def create_draft(
        self,
        *,
        title: str,
        mode: str,
        channel: str,
        message: str,
        clients: list[dict[str, Any]],
        filters: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        item = {
            "id": str(uuid.uuid4()),
            "title": title,
            "mode": mode,  # manual | auto
            "channel": channel,
            "message": message,
            "status": CampaignStatus.DRAFT.value,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "filters": filters or {},
            "recipients": [
                {
                    "id": str(r.get("UUID") or r.get("Наименование") or ""),
                    "name": str(r.get("Наименование") or ""),
                    "phone": str(r.get("Телефон") or ""),
                    "tg": str(r.get("ТГ ник") or ""),
                    "recommendation": str(r.get("_ai_recommendation") or r.get("Рекомендация") or ""),
                }
                for r in clients
                if has_crm_contact(r)
            ],
            "sent_count": 0,
        }
        self._campaigns.insert(0, item)
        return item

    async def list_campaigns(self) -> list[dict[str, Any]]:
        return list(self._campaigns)

    async def get(self, campaign_id: str) -> dict[str, Any] | None:
        for item in self._campaigns:
            if item.get("id") == campaign_id:
                return item
        return None

    async def mark_sent(self, campaign_id: str, recipient_ids: list[str] | None = None) -> dict[str, Any] | None:
        item = await self.get(campaign_id)
        if not item:
            return None
        recipients = item.get("recipients") or []
        if recipient_ids:
            wanted = set(recipient_ids)
            sent = [r for r in recipients if r.get("id") in wanted]
        else:
            sent = recipients
        item["sent_count"] = int(item.get("sent_count") or 0) + len(sent)
        item["status"] = (
            CampaignStatus.ACTIVE.value
            if item["sent_count"] < len(recipients)
            else CampaignStatus.DONE.value
        )
        item["last_sent_at"] = datetime.now(timezone.utc).isoformat()
        return item

    @staticmethod
    def demo_ai_message(row: dict[str, Any]) -> str:
        rec = str(row.get("_ai_recommendation") or row.get("Рекомендация") or "").strip()
        if rec:
            # Короткий demo-текст для рассылки
            name = str(row.get("Наименование") or "клиент").split()[0]
            return f"Здравствуйте, {name}! {rec[:280]}"
        touch = SegmentationService._primary_touch_plan(row)
        return f"Здравствуйте! Напоминаем о касании ({touch[0]}) к поводу «{touch[1]}»."

    @staticmethod
    def _to_dict(campaign: Campaign) -> dict[str, Any]:
        return {
            "id": campaign.id,
            "title": campaign.title,
            "mode": "manual",
            "channel": campaign.channel,
            "message": campaign.offer,
            "status": campaign.status.value if hasattr(campaign.status, "value") else str(campaign.status),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "filters": {"segments": ",".join(campaign.target_segments)},
            "recipients": [],
            "sent_count": 0,
        }
