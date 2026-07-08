"""Коннектор мессенджеров — Green API (WhatsApp) + Telegram Bot API."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from app.config import Settings, get_settings
from app.connectors.base import DataSourceConnector
from app.domain import Customer, Interaction, InteractionChannel, Order, SourceType
from app.services.green_api import get_green_api_client
from app.services.telegram_bot import get_telegram_client


class MessengerConnector(DataSourceConnector):
  source_type = SourceType.MESSENGER

  def __init__(self, settings: Settings | None = None) -> None:
    self._settings = settings or get_settings()
    self._wa = get_green_api_client(self._settings)
    self._tg = get_telegram_client(self._settings)

  @property
  def available(self) -> bool:
    return self._wa.enabled or self._tg.enabled

  async def fetch_customers(self, **kwargs: Any) -> list[Customer]:
    return []

  async def fetch_orders(self, **kwargs: Any) -> list[Order]:
    return []

  async def fetch_interactions(self, **kwargs: Any) -> list[Interaction]:
    interactions: list[Interaction] = []
    if self._wa.enabled:
      note = await self._wa.receive_notification()
      if note and note.get("body"):
        body = note["body"]
        if body.get("typeWebhook") == "incomingMessageReceived":
          msg = body.get("messageData", {})
          text = msg.get("textMessageData", {}).get("textMessage", "")
          sender = body.get("senderData", {}).get("sender", "")
          interactions.append(
            Interaction(
              id=str(note.get("receiptId") or uuid.uuid4()),
              channel=InteractionChannel.WHATSAPP,
              direction="in",
              text=text,
              date=datetime.now(),
              ai_labels={"sender": sender},
            )
          )
          receipt = note.get("receiptId")
          if receipt:
            await self._wa.delete_notification(int(receipt))
    return interactions

  async def send_whatsapp(self, phone: str, text: str) -> dict:
    return await self._wa.send_message(phone, text)

  async def send_telegram(self, chat_id: str | int, text: str) -> dict:
    return await self._tg.send_message(chat_id, text)

  async def health(self) -> dict[str, bool]:
    return {
      "whatsapp": await self._wa.health_check() if self._wa.enabled else False,
      "telegram": await self._tg.health_check() if self._tg.enabled else False,
    }
