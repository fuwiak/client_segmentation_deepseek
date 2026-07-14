"""Кэш и индекс сообщений Telegram/WhatsApp для сопоставления с клиентами."""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx

from app.config import Settings
from app.services.cache import CacheService
from app.services.telegram_bot import TelegramBotClient, get_telegram_client

logger = logging.getLogger(__name__)

MESSENGER_INDEX_KEY = "telegram_index"


def _normalize_phone(value: str | None) -> str:
    if not value:
        return ""
    digits = re.sub(r"\D", "", str(value))
    if digits.startswith("8") and len(digits) == 11:
        digits = "7" + digits[1:]
    return digits[-10:] if len(digits) >= 10 else digits


def _normalize_tg(value: str | None) -> str:
    if not value:
        return ""
    text = str(value).strip().lower()
    return text[1:] if text.startswith("@") else text


def _normalize_name(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"\s+", " ", str(value).strip().lower())


def parse_telegram_update(update: dict[str, Any]) -> dict[str, Any] | None:
    msg = update.get("message") or update.get("edited_message")
    if not msg:
        return None

    text = msg.get("text") or msg.get("caption") or ""
    if not str(text).strip() and not msg.get("contact"):
        return None

    chat = msg.get("chat") or {}
    from_user = msg.get("from") or {}
    direction = "out" if from_user.get("is_bot") else "in"
    ts = msg.get("date")
    date_val = str(ts) if ts is not None else None

    phone = None
    contact = msg.get("contact") or {}
    if contact.get("phone_number"):
        phone = _normalize_phone(contact["phone_number"])

    username = _normalize_tg(chat.get("username") or from_user.get("username"))
    display_name = " ".join(
        part
        for part in [from_user.get("first_name"), from_user.get("last_name")]
        if part
    ).strip()

    return {
        "channel": "telegram",
        "direction": direction,
        "text": str(text).strip(),
        "sender": username or display_name or str(chat.get("id") or ""),
        "date": date_val,
        "chat_id": chat.get("id"),
        "username": username,
        "phone": phone,
        "display_name": display_name,
        "update_id": update.get("update_id"),
    }


class MessengerMessageStore:
    def __init__(self, settings: Settings, cache: CacheService) -> None:
        self._settings = settings
        self._cache = cache
        self._tg: TelegramBotClient = get_telegram_client(settings)
        self._index: dict[str, Any] = {
            "bot_username": settings.telegram_bot_username,
            "messages": [],
            "by_username": {},
            "by_phone": {},
            "by_chat_id": {},
            "by_name": {},
            "last_update_id": 0,
        }
        self._loaded = False

    @property
    def enabled(self) -> bool:
        return self._settings.messenger_enabled and self._tg.enabled

    async def load(self) -> None:
        if self._loaded:
            return
        cached = await self._cache.get_messenger_index()
        if isinstance(cached, dict) and cached.get("messages") is not None:
            self._index = cached
        self._loaded = True

    async def save(self) -> None:
        await self._cache.save_messenger_index(self._index)

    async def sync_telegram(self) -> int:
        if not self.enabled:
            return 0

        await self.load()
        offset = int(self._index.get("last_update_id") or 0) + 1
        if offset <= 1:
            offset = None

        try:
            fetched = await self._tg.fetch_all_updates(offset=offset)
        except httpx.HTTPError as exc:
            logger.warning("Telegram sync failed, using cached messages: %s", exc)
            return 0

        added = 0
        for update in fetched:
            parsed = parse_telegram_update(update)
            if not parsed:
                continue
            self._append_message(parsed)
            added += 1
            update_id = update.get("update_id")
            if update_id:
                self._index["last_update_id"] = max(
                    int(self._index.get("last_update_id") or 0),
                    int(update_id),
                )

        if added:
            await self.save()
            self._loaded = True
        return added

    def _append_message(self, message: dict[str, Any]) -> None:
        messages: list[dict[str, Any]] = self._index.setdefault("messages", [])
        messages.append(message)
        if len(messages) > self._settings.messenger_cache_limit:
            overflow = len(messages) - self._settings.messenger_cache_limit
            del messages[:overflow]

        username = message.get("username")
        if username:
            self._index.setdefault("by_username", {}).setdefault(username, []).append(message)

        phone = message.get("phone")
        if phone:
            self._index.setdefault("by_phone", {}).setdefault(phone, []).append(message)

        chat_id = message.get("chat_id")
        if chat_id is not None:
            self._index.setdefault("by_chat_id", {}).setdefault(str(chat_id), []).append(message)

        name = _normalize_name(message.get("display_name"))
        if name:
            self._index.setdefault("by_name", {}).setdefault(name, []).append(message)

    def messages_for_row(self, row: dict[str, Any]) -> list[dict[str, Any]]:
        if not self.enabled:
            return []

        matched: list[dict[str, Any]] = []
        seen: set[str] = set()

        def _add(items: list[dict[str, Any]] | None) -> None:
            for item in items or []:
                key = f"{item.get('channel')}:{item.get('date')}:{item.get('text')}"
                if key not in seen:
                    seen.add(key)
                    matched.append(item)

        tg_nick = _normalize_tg(row.get("ТГ ник"))
        if tg_nick:
            _add(self._index.get("by_username", {}).get(tg_nick))

        phone = _normalize_phone(row.get("Телефон"))
        if phone:
            _add(self._index.get("by_phone", {}).get(phone))

        name = _normalize_name(row.get("Наименование"))
        if name:
            _add(self._index.get("by_name", {}).get(name))

        matched.sort(key=lambda m: m.get("date") or "")
        limit = self._settings.enrichment_chat_limit
        return matched[-limit:]

    @property
    def stats(self) -> dict[str, Any]:
        return {
            "bot_username": self._index.get("bot_username") or self._settings.telegram_bot_username,
            "messages_total": len(self._index.get("messages") or []),
            "last_update_id": self._index.get("last_update_id") or 0,
        }
