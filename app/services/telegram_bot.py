"""Telegram Bot API — отправка сообщений и проверка бота."""

from __future__ import annotations

import logging

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)


class TelegramBotClient:
  def __init__(self, settings: Settings) -> None:
    self._token = settings.telegram_bot_token
    self._enabled = settings.telegram_enabled and bool(self._token)
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

  async def send_message(self, chat_id: str | int, text: str) -> dict:
    if not self.enabled:
      raise RuntimeError("Telegram бот не настроен")
    async with httpx.AsyncClient(timeout=self._timeout) as client:
      resp = await client.post(
        self._url("sendMessage"),
        json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
      )
      resp.raise_for_status()
      return resp.json()

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
