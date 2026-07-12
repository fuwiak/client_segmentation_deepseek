"""Обогащение профилей клиентов данными из WhatsApp и Telegram."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Callable
from datetime import datetime
from typing import Any

import httpx

from app.config import Settings
from app.services.excel_parser import AI_EXTRA_COLUMNS, SEGMENT_COLUMNS
from app.services.green_api import get_green_api_client
from app.services.segmentation import SegmentationService, guess_gender
from app.services.telegram_bot import get_telegram_client

ENRICHMENT_COLUMNS = SEGMENT_COLUMNS + AI_EXTRA_COLUMNS

SYSTEM_PROMPT = """Ты — CRM-аналитик цветочного бизнеса.
По переписке клиента в WhatsApp/Telegram и данным заказов заполни поля профиля.

ПРАВИЛА:
1. "Группы" — сегмент (премиум, постоянный клиент, новый, маркетплейс и т.д.)
2. "Заказчик или получатель" — кто заказывает; ФИО получателя если есть в переписке
3. "Пол" — "Мужской" или "Женский" по имени; если неоднозначно → null
4. "ТГ ник" — @username только если явно есть в переписке или профиле
5. "Теги" — хэштеги: #деньрождения #vip #доволен #проблемный и т.д.
6. "Саммари" — 1-2 предложения: кто клиент, для кого заказывает, настроение

ВАЖНО:
- Опирайся ТОЛЬКО на переписку и данные клиента. Нет сигнала → null.
- reasoning — откуда взяты ключевые поля (канал, цитата).
- references — объект поле → источник.
- Верни JSON: {"results": [{"uuid", ...поля..., "reasoning", "confidence", "references"}]}"""


def _normalize_phone_key(phone: str | None) -> str:
    if not phone:
        return ""
    digits = re.sub(r"\D", "", str(phone))
    if digits.startswith("8") and len(digits) == 11:
        digits = "7" + digits[1:]
    return digits[-10:] if len(digits) >= 10 else digits


def _normalize_tg(value: str | None) -> str:
    if not value:
        return ""
    text = str(value).strip().lower()
    if text.startswith("@"):
        text = text[1:]
    return text


class MessengerEnrichmentService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._wa = get_green_api_client(settings)
        self._tg = get_telegram_client(settings)
        self._segmentation = SegmentationService(settings)

    @property
    def available(self) -> bool:
        return self._wa.enabled or self._tg.enabled

    async def fetch_whatsapp_history(
        self, phone: str, *, count: int | None = None
    ) -> list[dict[str, Any]]:
        if not self._wa.enabled or not phone:
            return []
        limit = count or self._settings.enrichment_chat_limit
        try:
            raw = await self._wa.get_chat_history(phone, count=limit)
        except (httpx.HTTPError, RuntimeError):
            return []

        messages: list[dict[str, Any]] = []
        for item in raw:
            text = (
                item.get("textMessage")
                or item.get("extendedTextMessage", {}).get("text")
                or item.get("caption")
                or ""
            )
            if not str(text).strip():
                continue
            sender = item.get("senderName") or item.get("senderId") or ""
            type_msg = str(item.get("typeMessage") or "").lower()
            direction = "out" if "outgoing" in type_msg else "in"
            ts = item.get("timestamp")
            date_val: str | None = None
            if ts:
                try:
                    date_val = datetime.fromtimestamp(int(ts)).isoformat()
                except (TypeError, ValueError, OSError):
                    date_val = str(ts)
            messages.append(
                {
                    "channel": "whatsapp",
                    "direction": direction,
                    "text": str(text).strip(),
                    "sender": str(sender),
                    "date": date_val,
                }
            )
        return messages

    async def fetch_telegram_history(
        self,
        tg_nick: str | None = None,
        *,
        count: int | None = None,
    ) -> list[dict[str, Any]]:
        if not self._tg.enabled:
            return []
        limit = count or self._settings.enrichment_chat_limit
        try:
            updates = await self._tg.get_updates(limit=limit * 2)
        except httpx.HTTPError:
            return []

        nick = _normalize_tg(tg_nick)
        messages: list[dict[str, Any]] = []
        for upd in updates:
            msg = upd.get("message") or upd.get("edited_message")
            if not msg:
                continue
            chat = msg.get("chat") or {}
            username = _normalize_tg(chat.get("username"))
            if nick and username and username != nick:
                continue
            text = msg.get("text") or msg.get("caption") or ""
            if not str(text).strip():
                continue
            from_user = msg.get("from") or {}
            direction = "in"
            if from_user.get("is_bot"):
                direction = "out"
            ts = msg.get("date")
            date_val: str | None = None
            if ts:
                try:
                    date_val = datetime.fromtimestamp(int(ts)).isoformat()
                except (TypeError, ValueError, OSError):
                    date_val = str(ts)
            messages.append(
                {
                    "channel": "telegram",
                    "direction": direction,
                    "text": str(text).strip(),
                    "sender": from_user.get("username") or from_user.get("first_name") or "",
                    "date": date_val,
                    "chat_id": chat.get("id"),
                }
            )
        return messages[:limit]

    async def fetch_client_messages(self, row: dict[str, Any]) -> list[dict[str, Any]]:
        phone = row.get("Телефон")
        tg = row.get("ТГ ник")
        tasks: list[Any] = []
        if phone and self._wa.enabled:
            tasks.append(self.fetch_whatsapp_history(str(phone)))
        if self._tg.enabled and tg:
            tasks.append(self.fetch_telegram_history(str(tg)))
        if not tasks:
            return []
        parts = await asyncio.gather(*tasks)
        combined: list[dict[str, Any]] = []
        for part in parts:
            combined.extend(part)
        combined.sort(key=lambda m: m.get("date") or "")
        return combined

    async def enrich_all(
        self,
        rows: list[dict[str, Any]],
        progress_cb: Callable[[int], None] | None = None,
    ) -> list[dict[str, Any]]:
        if not rows:
            return []

        batch_size = max(1, self._settings.enrichment_batch_size)
        batches = [rows[i : i + batch_size] for i in range(0, len(rows), batch_size)]
        semaphore = asyncio.Semaphore(self._settings.enrichment_concurrency)

        async def _run(batch: list[dict[str, Any]]) -> list[dict[str, Any]]:
            async with semaphore:
                enriched_batch: list[dict[str, Any]] = []
                for row in batch:
                    messages = await self.fetch_client_messages(row)
                    enriched_batch.append(
                        await self._enrich_single(dict(row), messages)
                    )
                if progress_cb:
                    progress_cb(len(batch))
                return enriched_batch

        chunks = await asyncio.gather(*(_run(batch) for batch in batches))
        merged: list[dict[str, Any]] = []
        for chunk in chunks:
            merged.extend(chunk)
        return merged

    async def _enrich_single(
        self,
        row: dict[str, Any],
        messages: list[dict[str, Any]],
    ) -> dict[str, Any]:
        row["_messenger_context"] = messages
        row["_messenger_sources"] = sorted(
            {m.get("channel") for m in messages if m.get("channel")}
        )

        if not messages:
            return self._heuristic_from_orders(row)

        if self._settings.openrouter_api_key:
            ai_row = await self._enrich_with_ai(row, messages)
            if ai_row:
                return ai_row

        return self._heuristic_from_messages(row, messages)

    async def _enrich_with_ai(
        self,
        row: dict[str, Any],
        messages: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        payload = {
            "uuid": self._row_key(row),
            "current": {col: row.get(col) for col in ENRICHMENT_COLUMNS},
            "client": {
                k: v
                for k, v in row.items()
                if not str(k).startswith("_") and v is not None
            },
            "messages": messages[-30:],
            "orders_sample": (row.get("_orders_context") or [])[:3],
        }
        user_prompt = (
            "Проанализируй переписку и заполни поля профиля клиента. "
            'Ответ — JSON {"results": [...]}.\n\n'
            f"{json.dumps(payload, ensure_ascii=False)}"
        )

        try:
            async with httpx.AsyncClient(timeout=self._settings.ai_timeout_seconds) as client:
                resp = await client.post(
                    f"{self._settings.openrouter_base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self._settings.openrouter_api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self._settings.openrouter_model,
                        "messages": [
                            {"role": "system", "content": SYSTEM_PROMPT},
                            {"role": "user", "content": user_prompt},
                        ],
                        "temperature": self._settings.ai_temperature,
                        "response_format": {"type": "json_object"},
                    },
                )
                resp.raise_for_status()
                content = resp.json()["choices"][0]["message"]["content"]
        except (httpx.HTTPError, KeyError, IndexError):
            return None

        parsed = self._segmentation._extract_json(content)
        if not isinstance(parsed, dict):
            return None
        items = parsed.get("results", parsed)
        if not isinstance(items, list) or not items:
            return None

        ai = next(
            (item for item in items if str(item.get("uuid")) == self._row_key(row)),
            items[0] if items else {},
        )
        return self._merge_ai(row, ai, source="messenger_ai")

    def _merge_ai(
        self,
        row: dict[str, Any],
        ai: dict[str, Any],
        *,
        source: str,
    ) -> dict[str, Any]:
        merged = dict(row)
        ai_fields: list[str] = list(merged.get("_ai_fields") or [])
        enrichment_fields: list[str] = list(merged.get("_enrichment_fields") or [])

        for col in ENRICHMENT_COLUMNS:
            value = ai.get(col)
            if value not in (None, "", "null"):
                if not merged.get(col):
                    ai_fields.append(col)
                    enrichment_fields.append(col)
                merged[col] = value

        if not merged.get("Пол"):
            guessed = guess_gender(merged.get("Заказчик или получатель"))
            if guessed:
                merged["Пол"] = guessed
                ai_fields.append("Пол")
                enrichment_fields.append("Пол")

        merged["_reasoning"] = ai.get("reasoning") or merged.get("_reasoning") or ""
        merged["_confidence"] = ai.get("confidence")
        merged["_ai_refs"] = ai.get("references") or merged.get("_ai_refs") or {}
        merged["_ai_processed"] = True
        merged["_ai_fields"] = list(dict.fromkeys(ai_fields))
        merged["_enrichment_fields"] = list(dict.fromkeys(enrichment_fields))
        merged["_enrichment_source"] = source
        return merged

    def _heuristic_from_messages(
        self,
        row: dict[str, Any],
        messages: list[dict[str, Any]],
    ) -> dict[str, Any]:
        merged = dict(row)
        ai_fields: list[str] = list(merged.get("_ai_fields") or [])
        enrichment_fields: list[str] = list(merged.get("_enrichment_fields") or [])
        all_text = " ".join(m.get("text", "") for m in messages).lower()

        if not merged.get("ТГ ник"):
            for msg in messages:
                if msg.get("channel") == "telegram" and msg.get("sender"):
                    nick = _normalize_tg(str(msg["sender"]))
                    if nick:
                        merged["ТГ ник"] = f"@{nick}"
                        ai_fields.append("ТГ ник")
                        enrichment_fields.append("ТГ ник")
                        break

        tags: list[str] = []
        if any(w in all_text for w in ("спасибо", "отлично", "супер", "класс")):
            tags.append("#доволен")
        if any(w in all_text for w in ("жалоб", "плох", "разочар", "верните")):
            tags.append("#проблемный")
        if any(w in all_text for w in ("день рождения", "др ", "birthday")):
            tags.append("#деньрождения")
        if any(w in all_text for w in ("8 марта", "8марта")):
            tags.append("#8марта")

        if tags and not merged.get("Теги"):
            merged["Теги"] = " ".join(dict.fromkeys(tags))
            ai_fields.append("Теги")
            enrichment_fields.append("Теги")

        if not merged.get("Саммари") and messages:
            channels = ", ".join(sorted({m.get("channel", "") for m in messages}))
            merged["Саммари"] = (
                f"Переписка в {channels}: {len(messages)} сообщений. "
                f"Последнее: {messages[-1].get('text', '')[:120]}"
            )
            ai_fields.append("Саммари")
            enrichment_fields.append("Саммари")

        merged["_reasoning"] = "Эвристика по переписке (без AI или API недоступен)"
        merged["_ai_processed"] = bool(merged.get("_ai_processed"))
        merged["_ai_fields"] = list(dict.fromkeys(ai_fields))
        merged["_enrichment_fields"] = list(dict.fromkeys(enrichment_fields))
        merged["_enrichment_source"] = "messenger_heuristic"
        return merged

    def _heuristic_from_orders(self, row: dict[str, Any]) -> dict[str, Any]:
        base = self._segmentation._heuristic_row(dict(row))
        base["_enrichment_source"] = "orders_only"
        base["_messenger_sources"] = row.get("_messenger_sources") or []
        base["_messenger_context"] = row.get("_messenger_context") or []
        return base

    @staticmethod
    def _row_key(row: dict[str, Any]) -> str:
        return str(row.get("UUID") or row.get("uuid") or row.get("Наименование"))
