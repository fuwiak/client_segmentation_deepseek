"""Управление рекламными кампаниями / рассылками.

Ручной режим — по текущим фильтрам клиентов.
Авто (Demo) — по рекомендациям AI (точки касания).
Канал Telegram — реальная отправка через Bot API (если TELEGRAM_ENABLED).
"""

from __future__ import annotations

import asyncio
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from app.domain import Campaign, CampaignStatus
from app.repository.base import CustomerRepository
from app.services.fields import has_crm_contact
from app.services.segmentation import SegmentationService

logger = logging.getLogger(__name__)


def _normalize_tg(value: str | None) -> str:
    if not value:
        return ""
    text = str(value).strip()
    if text.startswith("@"):
        text = text[1:]
    return text.strip()


def resolve_telegram_chat_id(
    recipient: dict[str, Any],
    *,
    messenger_index: dict[str, Any] | None = None,
) -> str | int | None:
    """chat_id для Bot API: явный id, @username или индекс getUpdates."""
    explicit = recipient.get("tg_chat_id") or recipient.get("chat_id")
    if explicit is not None and str(explicit).strip():
        raw = str(explicit).strip()
        return int(raw) if raw.lstrip("-").isdigit() else raw

    tg = _normalize_tg(recipient.get("tg") or recipient.get("ТГ ник"))
    index = messenger_index or {}
    if tg:
        by_user = index.get("by_username") or {}
        msgs = by_user.get(tg.lower()) or by_user.get(tg) or []
        for msg in reversed(msgs):
            cid = msg.get("chat_id")
            if cid is not None and str(cid).strip():
                return cid
        # Bot API принимает @username, если пользователь уже писал боту.
        return f"@{tg}"

    phone_digits = re.sub(r"\D", "", str(recipient.get("phone") or recipient.get("Телефон") or ""))
    if phone_digits.startswith("8") and len(phone_digits) == 11:
        phone_digits = "7" + phone_digits[1:]
    phone_key = phone_digits[-10:] if len(phone_digits) >= 10 else phone_digits
    if phone_key:
        by_phone = index.get("by_phone") or {}
        msgs = by_phone.get(phone_key) or []
        for msg in reversed(msgs):
            cid = msg.get("chat_id")
            if cid is not None and str(cid).strip():
                return cid
    return None


class CampaignService:
    def __init__(
        self,
        repository: CustomerRepository,
        *,
        cache: Any | None = None,
    ) -> None:
        self._repo = repository
        self._cache = cache
        self._campaigns: list[dict[str, Any]] = []
        self._loaded = False

    async def _ensure_loaded(self) -> None:
        if self._loaded or self._cache is None:
            self._loaded = True
            return
        try:
            stored = await self._cache.get_campaigns()
            if isinstance(stored, list):
                self._campaigns = stored
        except Exception:  # noqa: BLE001
            logger.warning("Failed to load campaigns from cache", exc_info=True)
        self._loaded = True

    async def _persist(self) -> None:
        if self._cache is None:
            return
        try:
            await self._cache.save_campaigns(list(self._campaigns))
        except Exception:  # noqa: BLE001
            logger.warning("Failed to persist campaigns", exc_info=True)

    async def create(self, campaign: Campaign) -> Campaign:
        await self._ensure_loaded()
        self._campaigns.append(self._to_dict(campaign))
        await self._persist()
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
        messenger_index: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        await self._ensure_loaded()
        recipients: list[dict[str, Any]] = []
        skipped_no_tg = 0
        channel_l = str(channel or "").lower()
        for r in clients:
            if not has_crm_contact(r):
                continue
            tg = str(r.get("ТГ ник") or "").strip()
            phone = str(r.get("Телефон") or "").strip()
            rec = {
                "id": str(r.get("UUID") or r.get("Наименование") or ""),
                "name": str(r.get("Наименование") or ""),
                "phone": phone,
                "tg": tg,
                "recommendation": str(
                    r.get("_ai_recommendation") or r.get("Рекомендация") or ""
                ),
                "send_status": "pending",
                "send_error": "",
            }
            chat_id = resolve_telegram_chat_id(rec, messenger_index=messenger_index)
            if chat_id is not None:
                rec["tg_chat_id"] = chat_id
            # Личные TG-рассылки — только те, у кого есть @ник или chat_id.
            if channel_l == "telegram" and chat_id is None and not tg:
                skipped_no_tg += 1
                continue
            recipients.append(rec)

        # Пост в канал можно создать и без персональной аудитории.
        if channel_l == "telegram_channel" and not recipients:
            recipients = [{
                "id": "channel",
                "name": "Telegram-канал",
                "phone": "",
                "tg": "",
                "recommendation": "",
                "send_status": "pending",
                "send_error": "",
            }]

        item = {
            "id": str(uuid.uuid4()),
            "title": title,
            "mode": mode,  # manual | auto
            "channel": channel,
            "message": message,
            "status": CampaignStatus.DRAFT.value,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "filters": filters or {},
            "recipients": recipients,
            "sent_count": 0,
            "failed_count": 0,
            "skipped_no_tg": skipped_no_tg,
            "last_error": "",
        }
        self._campaigns.insert(0, item)
        await self._persist()
        return item

    async def list_campaigns(self) -> list[dict[str, Any]]:
        await self._ensure_loaded()
        return list(self._campaigns)

    async def get(self, campaign_id: str) -> dict[str, Any] | None:
        await self._ensure_loaded()
        for item in self._campaigns:
            if item.get("id") == campaign_id:
                return item
        return None

    async def mark_sent(
        self, campaign_id: str, recipient_ids: list[str] | None = None
    ) -> dict[str, Any] | None:
        """Пометить отправку без API (demo / fallback)."""
        item = await self.get(campaign_id)
        if not item:
            return None
        recipients = item.get("recipients") or []
        if recipient_ids:
            wanted = set(recipient_ids)
            targets = [r for r in recipients if r.get("id") in wanted]
        else:
            targets = recipients
        for rec in targets:
            if rec.get("send_status") == "sent":
                continue
            rec["send_status"] = "demo"
            rec["sent_at"] = datetime.now(timezone.utc).isoformat()
        item["sent_count"] = sum(1 for r in recipients if r.get("send_status") in {"sent", "demo"})
        item["status"] = (
            CampaignStatus.ACTIVE.value
            if item["sent_count"] < len(recipients)
            else CampaignStatus.DONE.value
        )
        item["last_sent_at"] = datetime.now(timezone.utc).isoformat()
        await self._persist()
        return item

    async def send_telegram(
        self,
        campaign_id: str,
        *,
        telegram_client: Any,
        messenger_index: dict[str, Any] | None = None,
        recipient_ids: list[str] | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any] | None:
        """Реальная (или dry-run) отправка кампании в Telegram."""
        item = await self.get(campaign_id)
        if not item:
            return None
        if str(item.get("channel") or "").lower() not in {"telegram", "telegram_channel"}:
            raise ValueError("Кампания не для канала Telegram")

        channel = str(item.get("channel") or "").lower()
        if channel == "telegram_channel":
            return await self._send_telegram_channel(
                item,
                telegram_client=telegram_client,
                dry_run=dry_run,
            )

        recipients = item.get("recipients") or []
        if recipient_ids:
            wanted = set(recipient_ids)
            targets = [r for r in recipients if r.get("id") in wanted]
        else:
            targets = [r for r in recipients if r.get("send_status") != "sent"]

        enabled = bool(getattr(telegram_client, "enabled", False))
        if not enabled and not dry_run:
            # Без токена — demo-пометка, чтобы UI не ломался.
            return await self.mark_sent(campaign_id, recipient_ids)

        base_message = str(item.get("message") or "").strip()
        mode = str(item.get("mode") or "manual")
        sent = 0
        failed = 0
        last_error = ""

        for rec in targets:
            if rec.get("send_status") == "sent":
                continue
            text = base_message
            if mode == "auto":
                text = self.demo_ai_message({
                    "Наименование": rec.get("name"),
                    "_ai_recommendation": rec.get("recommendation"),
                    "Рекомендация": rec.get("recommendation"),
                })
            if not text:
                text = "Здравствуйте!"

            chat_id = resolve_telegram_chat_id(rec, messenger_index=messenger_index)
            if chat_id is None:
                rec["send_status"] = "failed"
                rec["send_error"] = "Нет Telegram (@ник или chat_id). Клиент должен написать боту."
                failed += 1
                last_error = rec["send_error"]
                continue

            if dry_run or not enabled:
                rec["send_status"] = "demo"
                rec["tg_chat_id"] = chat_id
                rec["sent_at"] = datetime.now(timezone.utc).isoformat()
                sent += 1
                continue

            try:
                await telegram_client.send_message(chat_id, text, parse_mode=None)
                rec["send_status"] = "sent"
                rec["tg_chat_id"] = chat_id
                rec["send_error"] = ""
                rec["sent_at"] = datetime.now(timezone.utc).isoformat()
                sent += 1
            except Exception as exc:  # noqa: BLE001 — фиксируем ошибку по получателю
                logger.warning("Telegram send failed for %s: %s", rec.get("id"), exc)
                rec["send_status"] = "failed"
                rec["send_error"] = str(exc)[:240]
                failed += 1
                last_error = rec["send_error"]
            await asyncio.sleep(0.05)

        item["sent_count"] = sum(1 for r in recipients if r.get("send_status") in {"sent", "demo"})
        item["failed_count"] = sum(1 for r in recipients if r.get("send_status") == "failed")
        item["last_error"] = last_error
        item["last_sent_at"] = datetime.now(timezone.utc).isoformat()
        pending = sum(1 for r in recipients if r.get("send_status") in {"pending", "failed"})
        item["status"] = (
            CampaignStatus.DONE.value if pending == 0 else CampaignStatus.ACTIVE.value
        )
        await self._persist()
        return item

    async def _send_telegram_channel(
        self,
        item: dict[str, Any],
        *,
        telegram_client: Any,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Один пост в Telegram-канал (маркетинговый канал)."""
        text = str(item.get("message") or "").strip() or "Новость от Iris CRM"
        enabled = bool(getattr(telegram_client, "enabled", False))
        channel_ok = bool(getattr(telegram_client, "channel_configured", False))
        recipients = item.get("recipients") or []

        if dry_run or not enabled or not channel_ok:
            item["sent_count"] = 1
            item["failed_count"] = 0
            item["status"] = CampaignStatus.DONE.value
            item["last_sent_at"] = datetime.now(timezone.utc).isoformat()
            item["channel_post_status"] = "demo"
            if not channel_ok and enabled:
                item["last_error"] = "TELEGRAM_CHANNEL_ID не задан"
                item["channel_post_status"] = "failed"
                item["failed_count"] = 1
                item["sent_count"] = 0
            for rec in recipients:
                rec["send_status"] = item["channel_post_status"]
            logger.info(
                "TG channel post demo campaign=%s status=%s",
                item.get("id"),
                item["channel_post_status"],
            )
            await self._persist()
            return item

        try:
            await telegram_client.send_to_channel(text, parse_mode=None)
            item["sent_count"] = 1
            item["failed_count"] = 0
            item["channel_post_status"] = "sent"
            item["last_error"] = ""
            item["status"] = CampaignStatus.DONE.value
            for rec in recipients:
                rec["send_status"] = "sent"
            logger.info("TG channel post ok campaign=%s", item.get("id"))
        except Exception as exc:  # noqa: BLE001
            logger.warning("TG channel post failed: %s", exc)
            item["sent_count"] = 0
            item["failed_count"] = 1
            item["channel_post_status"] = "failed"
            item["last_error"] = str(exc)[:240]
            item["status"] = CampaignStatus.ACTIVE.value
            for rec in recipients:
                rec["send_status"] = "failed"
                rec["send_error"] = item["last_error"]
        item["last_sent_at"] = datetime.now(timezone.utc).isoformat()
        await self._persist()
        return item

    @staticmethod
    def demo_ai_message(row: dict[str, Any]) -> str:
        rec = str(row.get("_ai_recommendation") or row.get("Рекомендация") or "").strip()
        if rec:
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
            "failed_count": 0,
        }
