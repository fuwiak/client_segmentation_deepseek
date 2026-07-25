"""Telegram Bot API — отправка сообщений и проверка бота."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)


class TelegramBotClient:
  def __init__(self, settings: Settings) -> None:
    self._token = settings.telegram_bot_token
    self._enabled = settings.telegram_enabled and bool(self._token)
    self._channel_id = (settings.telegram_channel_id or "").strip()
    self._timeout = httpx.Timeout(
      connect=min(10.0, float(settings.telegram_api_timeout_seconds)),
      read=float(settings.telegram_api_timeout_seconds),
      write=float(settings.telegram_api_timeout_seconds),
      pool=float(settings.telegram_api_timeout_seconds),
    )

  @property
  def enabled(self) -> bool:
    return self._enabled

  def _url(self, method: str) -> str:
    return f"https://api.telegram.org/bot{self._token}/{method}"

  async def get_me(self) -> dict:
    if not self.enabled:
      return {"enabled": False}
    try:
      async with httpx.AsyncClient(timeout=self._timeout) as client:
        resp = await client.get(self._url("getMe"))
        resp.raise_for_status()
        data = resp.json()
        if data.get("ok"):
          result = data["result"]
          result["enabled"] = True
          return result
        return {"enabled": False, "error": data}
    except httpx.HTTPError as exc:
      logger.warning("Telegram getMe failed: %s", exc)
      return {"enabled": False, "error": str(exc)}

  async def health_check(self) -> bool:
    if not self.enabled:
      return False
    try:
      me = await self.get_me()
      return bool(me.get("enabled") and me.get("id"))
    except httpx.HTTPError:
      return False

  async def send_message(
    self,
    chat_id: str | int,
    text: str,
    *,
    parse_mode: str | None = None,
  ) -> dict:
    if not self.enabled:
      raise RuntimeError("Telegram бот не настроен")
    payload: dict[str, Any] = {"chat_id": chat_id, "text": text}
    if parse_mode:
      payload["parse_mode"] = parse_mode
    async with httpx.AsyncClient(timeout=self._timeout) as client:
      resp = await client.post(self._url("sendMessage"), json=payload)
      if resp.status_code >= 400:
        detail = ""
        try:
          detail = str(resp.json())
        except Exception:  # noqa: BLE001
          detail = resp.text[:300]
        raise RuntimeError(f"Telegram API {resp.status_code}: {detail}")
      data = resp.json()
      if not data.get("ok"):
        raise RuntimeError(f"Telegram API error: {data}")
      return data

  async def get_updates(self, *, offset: int | None = None, limit: int = 100) -> list[dict]:
    if not self.enabled:
      return []
    params: dict[str, int] = {"limit": max(1, min(limit, 100))}
    if offset is not None:
      params["offset"] = offset
    try:
      async with httpx.AsyncClient(timeout=self._timeout) as client:
        resp = await client.get(self._url("getUpdates"), params=params)
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok"):
          return []
        return data.get("result") or []
    except httpx.HTTPError as exc:
      logger.warning("Telegram getUpdates failed: %s", exc)
      return []

  async def get_chat(self, chat_id: str | int) -> dict[str, Any]:
    if not self.enabled:
      return {"ok": False, "enabled": False}
    async with httpx.AsyncClient(timeout=self._timeout) as client:
      resp = await client.get(self._url("getChat"), params={"chat_id": chat_id})
      data = resp.json()
      if not data.get("ok"):
        return {"ok": False, "error": data, "enabled": True}
      result = data.get("result") or {}
      result["ok"] = True
      result["enabled"] = True
      return result

  async def send_to_channel(
    self,
    text: str,
    *,
    channel_id: str | int | None = None,
    parse_mode: str | None = None,
  ) -> dict:
    """Пост в Telegram-канал (бот должен быть админом канала)."""
    target = channel_id if channel_id is not None else self.channel_id
    if not target:
      raise RuntimeError("Telegram-канал не настроен (TELEGRAM_CHANNEL_ID)")
    return await self.send_message(target, text, parse_mode=parse_mode)

  @property
  def channel_id(self) -> str:
    return (self._channel_id or "").strip()

  @property
  def channel_configured(self) -> bool:
    return self.enabled and bool(self.channel_id)

  async def fetch_all_updates(
    self,
    *,
    offset: int | None = None,
    max_pages: int = 20,
  ) -> list[dict]:
    if not self.enabled:
      return []
    collected: list[dict] = []
    next_offset = offset
    for _ in range(max(1, max_pages)):
      batch = await self.get_updates(offset=next_offset, limit=100)
      if not batch:
        break
      collected.extend(batch)
      next_offset = int(batch[-1]["update_id"]) + 1
      if len(batch) < 100:
        break
    return collected


def get_telegram_client(settings: Settings) -> TelegramBotClient:
  return TelegramBotClient(settings)
