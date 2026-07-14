"""Green API — WhatsApp (и опционально Telegram-инстанс Green API)."""

from __future__ import annotations

import asyncio
import logging
import re

import httpx

from app.config import Settings
from app.services.http_retry import request_with_retry

logger = logging.getLogger(__name__)

_PHONE_DIGITS = re.compile(r"\D")
_request_semaphore: asyncio.Semaphore | None = None


def _get_request_semaphore(settings: Settings) -> asyncio.Semaphore:
  global _request_semaphore
  if _request_semaphore is None:
    _request_semaphore = asyncio.Semaphore(max(1, settings.green_api_concurrency))
  return _request_semaphore


class GreenApiClient:
  def __init__(self, settings: Settings) -> None:
    self._settings = settings
    self._id = settings.green_api_id_instance
    self._token = settings.green_api_token
    self._api_url = settings.green_api_url.rstrip("/")
    self._media_url = settings.green_api_media_url.rstrip("/")
    self._enabled = settings.green_api_enabled and bool(self._id and self._token)
    self._max_retries = max(0, settings.green_api_retry_max)

  @property
  def enabled(self) -> bool:
    return self._enabled

  def _base(self) -> str:
    return f"{self._api_url}/waInstance{self._id}"

  @staticmethod
  def normalize_chat_id(phone: str) -> str:
    digits = _PHONE_DIGITS.sub("", phone)
    if digits.startswith("8") and len(digits) == 11:
      digits = "7" + digits[1:]
    if not digits.endswith("@c.us"):
      digits = f"{digits}@c.us"
    return digits

  async def _request(
    self,
    method: str,
    url: str,
    *,
    timeout: float = 30,
    **kwargs,
  ) -> httpx.Response:
    sem = _get_request_semaphore(self._settings)
    async with sem:
      async with httpx.AsyncClient(timeout=timeout) as client:
        return await request_with_retry(
          client,
          method,
          url,
          max_retries=self._max_retries,
          **kwargs,
        )

  async def get_state(self) -> dict:
    if not self.enabled:
      return {"enabled": False, "state": "disabled"}
    url = f"{self._base()}/getStateInstance/{self._token}"
    try:
      resp = await self._request("GET", url)
      resp.raise_for_status()
      data = resp.json()
      data["enabled"] = True
      return data
    except httpx.HTTPError as exc:
      logger.warning("Green API getStateInstance failed: %s", exc)
      return {"enabled": False, "state": "error", "error": str(exc)}

  async def health_check(self) -> bool:
    if not self.enabled:
      return False
    try:
      state = await self.get_state()
      return state.get("stateInstance") in ("authorized", "sleepMode")
    except (httpx.HTTPError, KeyError):
      return False

  async def send_message(self, phone: str, text: str) -> dict:
    if not self.enabled:
      raise RuntimeError("Green API не настроен")
    chat_id = self.normalize_chat_id(phone)
    url = f"{self._base()}/sendMessage/{self._token}"
    payload = {"chatId": chat_id, "message": text}
    resp = await self._request("POST", url, json=payload)
    resp.raise_for_status()
    return resp.json()

  async def receive_notification(self) -> dict | None:
    if not self.enabled:
      return None
    url = f"{self._base()}/receiveNotification/{self._token}"
    resp = await self._request("GET", url)
    resp.raise_for_status()
    data = resp.json()
    return data if data else None

  async def delete_notification(self, receipt_id: int) -> None:
    if not self.enabled:
      return
    url = f"{self._base()}/deleteNotification/{self._token}/{receipt_id}"
    resp = await self._request("DELETE", url)
    resp.raise_for_status()

  async def get_chat_history(self, phone: str, *, count: int = 50) -> list[dict]:
    if not self.enabled:
      raise RuntimeError("Green API не настроен")
    chat_id = self.normalize_chat_id(phone)
    url = f"{self._base()}/getChatHistory/{self._token}"
    payload = {"chatId": chat_id, "count": max(1, min(count, 100))}
    try:
      resp = await self._request("POST", url, timeout=60, json=payload)
      resp.raise_for_status()
      data = resp.json()
      if isinstance(data, list):
        return data
      return data.get("messages") or data.get("history") or []
    except httpx.HTTPError as exc:
      logger.warning("Green API getChatHistory failed for %s: %s", chat_id, exc)
      return []


def get_green_api_client(settings: Settings) -> GreenApiClient:
  return GreenApiClient(settings)
