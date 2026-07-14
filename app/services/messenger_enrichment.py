"""Обогащение профилей клиентов данными из WhatsApp и Telegram."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Callable
from datetime import datetime
from typing import Any

import httpx

from app.config import Settings
from app.services.cache import CacheService
from app.services.excel_parser import AI_COLUMNS, AI_EXTRA_COLUMNS, SEGMENT_COLUMNS
from app.services.fields import (
  apply_ai_field,
  apply_resolved_gender,
  collect_client_comments,
  empty_fillable_columns,
  extract_tg_nick_from_messages,
)
from app.services.tag_rules import evaluate_tags_for_row, normalize_tags_field
from app.services.green_api import get_green_api_client
from app.services.messenger_store import MessengerMessageStore
from app.services.telegram_export import (
  messages_for_row as export_messages_for_row,
  tg_nick_for_row,
)
from app.services.segmentation import SegmentationService
from app.services.telegram_bot import get_telegram_client

ENRICHMENT_COLUMNS = AI_COLUMNS

SYSTEM_PROMPT = """Ты — CRM-аналитик цветочного бизнеса.
По переписке клиента в WhatsApp/Telegram, комментариям контрагента и заказов заполни поля профиля.

ПРАВИЛА:
1. "Группы" — сегмент (премиум, постоянный клиент, новый, маркетплейс и т.д.)
2. "Заказчик или получатель" — кто заказывает; ФИО получателя если есть в переписке или комментариях
3. "Пол" — "Мужской" или "Женский" по имени; для услуг/фирм без ФИО → "не применимо"; если неоднозначно → null
4. "ТГ ник" — @username только если явно есть в переписке, комментариях или профиле
5. "Теги" — одна строка с хэштегами через пробел: #деньрождения #vip #доволен (не массив JSON).
6. "Саммари" — 2–3 предложения о МОТИВАЦИИ покупки (intent), не о профиле клиента.
   НЕ пиши «постоянный покупатель», «высокий чек», «настроение не определено».
   Фокус: СОБЫТИЕ/ПОВОД (день рождения, 8 марта, годовщина, свадьба…) и INTENT (подарок кому, для себя, срочно, корпоратив).
   Если повод не ясен — «повод не определён из переписки/заказов».
7. "Фамилия (для ИП и физ. лиц)", "Имя (для ИП и физ. лиц)", "Отчество (для ИП и физ. лиц)" — из ФИО в данных
8. "E-mail" — только если явно указан
9. "Дата рождения" — только если явно указана (ДД.ММ.ГГГГ)

10. Для каждого поля из empty_fields — попробуй заполнить по переписке, комментариям и заказам.
    Юридические и банковские реквизиты — только при явном указании. Нет данных → null.

ВАЖНО:
- Учитывай all_comments: комментарий контрагента и комментарии к заказам.
- Опирайся ТОЛЬКО на переписку и данные клиента. Нет сигнала → null.
- reasoning — откуда взяты ключевые поля (канал, цитата).
- references — объект поле → источник.
- Верни JSON: {"results": [{"uuid", ...поля..., "empty_fields" values, "reasoning", "confidence", "references"}]}"""


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
    def __init__(
        self,
        settings: Settings,
        cache: CacheService | None = None,
    ) -> None:
        from app.services.cache import get_cache

        self._settings = settings
        self._cache = cache or get_cache(settings)
        self._wa = get_green_api_client(settings)
        self._tg = get_telegram_client(settings)
        self._segmentation = SegmentationService(settings)
        self._store = MessengerMessageStore(settings, self._cache)
        self._export_index: dict[str, Any] | None = None
        self._export_hydrated = False

    @property
    def export_loaded(self) -> bool:
        return bool(self._export_index and self._export_index.get("by_phone"))

    @property
    def available(self) -> bool:
        if self._export_index:
            return True
        if not self._settings.messenger_enabled:
            return False
        return self._wa.enabled or self._tg.enabled

    @property
    def telegram_enabled(self) -> bool:
        return self._tg.enabled

    @property
    def stats(self) -> dict[str, Any]:
        return self._store.stats

    async def sync_telegram_inbox(self) -> int:
        return await self._store.sync_telegram()

    async def load_telegram_export(self) -> dict[str, Any] | None:
        if self._export_hydrated:
            return self._export_index
        self._export_hydrated = True
        cached = await self._cache.get_telegram_export_index()
        if isinstance(cached, dict) and cached.get("by_phone") is not None:
            self._export_index = cached
            return cached
        self._export_index = None
        return None

    async def save_telegram_export(self, index: dict[str, Any]) -> None:
        self._export_index = index
        await self._cache.save_telegram_export_index(index)

    @property
    def export_stats(self) -> dict[str, Any]:
        meta = (self._export_index or {}).get("meta") or {}
        return {
            "loaded": bool(self._export_index),
            **meta,
        }

    def _export_messages_for_row(self, row: dict[str, Any]) -> list[dict[str, Any]]:
        if not self._export_index:
            return []
        return export_messages_for_row(
            self._export_index,
            row,
            limit=self._settings.enrichment_chat_limit,
        )

    async def attach_messages(
        self,
        rows: list[dict[str, Any]],
        *,
        sync_live: bool | None = None,
        fetch_live: bool | None = None,
    ) -> list[dict[str, Any]]:
        if not self.available:
            return rows

        await self._store.load()
        await self.load_telegram_export()
        should_sync = (
            self._settings.telegram_sync_on_attach
            if sync_live is None
            else sync_live
        )
        if should_sync and self._tg.enabled:
            try:
                await self.sync_telegram_inbox()
            except httpx.HTTPError as exc:
                logging.getLogger(__name__).warning(
                    "Telegram inbox sync skipped, using cached messages: %s", exc
                )

        use_live_fetch = fetch_live if fetch_live is not None else should_sync
        if not should_sync and not use_live_fetch:
            has_store = bool(self._store.stats.get("messages_total"))
            if not self.export_loaded and not has_store:
                return rows

        semaphore = asyncio.Semaphore(self._settings.enrichment_concurrency)
        batch_size = max(50, self._settings.enrichment_batch_size * 20)

        async def _attach(row: dict[str, Any]) -> dict[str, Any]:
            async with semaphore:
                copy = dict(row)
                messages = self._cached_messages_for_row(copy, live=use_live_fetch)
                export_msgs = self._export_messages_for_row(copy)
                if export_msgs:
                    copy["_tg_export_context"] = export_msgs
                copy["_messenger_context"] = messages
                copy["_messenger_sources"] = sorted(
                    {m.get("channel") for m in messages if m.get("channel")}
                )
                return copy

        attached: list[dict[str, Any]] = []
        for offset in range(0, len(rows), batch_size):
            chunk = rows[offset : offset + batch_size]
            attached.extend(await asyncio.gather(*(_attach(row) for row in chunk)))
            await asyncio.sleep(0)
        return attached

    async def attach_tg_export_only(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        await self.load_telegram_export()
        if not self.export_loaded:
            return rows
        updated: list[dict[str, Any]] = []
        for row in rows:
            copy = dict(row)
            export_msgs = self._export_messages_for_row(copy)
            if not export_msgs:
                updated.append(copy)
                continue
            copy["_tg_export_context"] = export_msgs
            combined = list(copy.get("_messenger_context") or [])
            seen = {f"{m.get('date')}:{m.get('text')}" for m in combined}
            for msg in export_msgs:
                key = f"{msg.get('date')}:{msg.get('text')}"
                if key not in seen:
                    seen.add(key)
                    combined.append(msg)
            combined.sort(key=lambda m: m.get("date") or "")
            copy["_messenger_context"] = combined[-self._settings.enrichment_chat_limit :]
            sources = set(copy.get("_messenger_sources") or [])
            sources.add("telegram")
            copy["_messenger_sources"] = sorted(sources)
            if not copy.get("ТГ ник"):
                nick = tg_nick_for_row(self._export_index, copy)
                if not nick:
                    nick = extract_tg_nick_from_messages(export_msgs)
                if nick:
                    copy["ТГ ник"] = nick
            updated.append(copy)
        return updated

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

        await self._store.load()
        limit = count or self._settings.enrichment_chat_limit
        nick = _normalize_tg(tg_nick)

        if nick:
            row = {"ТГ ник": f"@{nick}"}
            matched = self._store.messages_for_row(row)
            if matched:
                return matched[-limit:]

        # Без ника — вернуть все сообщения из кэша бота (для ручной привязки/AI)
        all_messages = list(self._store._index.get("messages") or [])
        all_messages.sort(key=lambda m: m.get("date") or "")
        return all_messages[-limit:]

    def _cached_messages_for_row(
        self,
        row: dict[str, Any],
        *,
        live: bool,
    ) -> list[dict[str, Any]]:
        combined: list[dict[str, Any]] = []
        seen: set[str] = set()

        def _add(items: list[dict[str, Any]]) -> None:
            for item in items:
                key = f"{item.get('channel')}:{item.get('date')}:{item.get('text')}"
                if key not in seen:
                    seen.add(key)
                    combined.append(item)

        _add(self._export_messages_for_row(row))
        _add(self._store.messages_for_row(row))

        if live:
            return combined

        combined.sort(key=lambda m: m.get("date") or "")
        return combined[-self._settings.enrichment_chat_limit :]

    async def fetch_client_messages(
        self,
        row: dict[str, Any],
        *,
        live: bool = True,
    ) -> list[dict[str, Any]]:
        await self._store.load()
        if not self._export_hydrated:
            await self.load_telegram_export()
        if not live:
            return self._cached_messages_for_row(row, live=False)

        combined: list[dict[str, Any]] = []
        seen: set[str] = set()

        def _add(items: list[dict[str, Any]]) -> None:
            for item in items:
                key = f"{item.get('channel')}:{item.get('date')}:{item.get('text')}"
                if key not in seen:
                    seen.add(key)
                    combined.append(item)

        _add(self._export_messages_for_row(row))
        _add(self._store.messages_for_row(row))

        phone = row.get("Телефон")
        tg = row.get("ТГ ник")
        tasks: list[Any] = []
        if phone and self._wa.enabled:
            tasks.append(self.fetch_whatsapp_history(str(phone)))
        if self._tg.enabled and tg and not combined:
            tasks.append(self.fetch_telegram_history(str(tg)))
        if tasks:
            parts = await asyncio.gather(*tasks, return_exceptions=True)
            for part in parts:
                if isinstance(part, Exception):
                    continue
                _add(list(part))

        combined.sort(key=lambda m: m.get("date") or "")
        return combined[-self._settings.enrichment_chat_limit :]

    async def enrich_all(
        self,
        rows: list[dict[str, Any]],
        progress_cb: Callable[[int], None] | None = None,
        *,
        live: bool | None = None,
    ) -> list[dict[str, Any]]:
        if not rows:
            return []

        use_live = (
            self._settings.messenger_live_fetch
            if live is None
            else live
        )
        batch_size = max(1, self._settings.enrichment_batch_size)
        batches = [rows[i : i + batch_size] for i in range(0, len(rows), batch_size)]
        semaphore = asyncio.Semaphore(self._settings.enrichment_concurrency)

        async def _run(batch: list[dict[str, Any]]) -> list[dict[str, Any]]:
            async with semaphore:
                enriched_batch: list[dict[str, Any]] = []
                for row in batch:
                    messages = await self.fetch_client_messages(row, live=use_live)
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
        export_msgs = self._export_messages_for_row(row)
        if export_msgs:
            row["_tg_export_context"] = export_msgs
        row["_messenger_sources"] = sorted(
            {m.get("channel") for m in messages if m.get("channel")}
        )

        if not messages:
            if self._settings.openrouter_api_key and self._has_profile_context(row):
                ai_row = await self._enrich_with_ai(row, [])
                if ai_row:
                    return ai_row
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
            "empty_fields": empty_fillable_columns(row),
            "client": {
                k: v
                for k, v in row.items()
                if not str(k).startswith("_") and v is not None
            },
            "messages": messages[-30:],
            "orders_sample": (row.get("_orders_context") or [])[:3],
        }
        comments = collect_client_comments(row)
        if comments:
            payload["all_comments"] = comments[:2000]
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

        for col in dict.fromkeys([*ENRICHMENT_COLUMNS, *empty_fillable_columns(row)]):
            if col == "Пол":
                continue
            value = ai.get(col)
            if value not in (None, "", "null"):
                apply_ai_field(merged, col, value, ai_fields)
                if col not in enrichment_fields:
                    enrichment_fields.append(col)

        apply_resolved_gender(
            merged,
            ai.get("Пол"),
            ai_fields,
            enrichment_fields=enrichment_fields,
        )

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
        row_with_messages = dict(row)
        row_with_messages["_messenger_context"] = messages
        merged = self._segmentation._heuristic_row(row_with_messages)
        ai_fields: list[str] = list(merged.get("_ai_fields") or [])
        enrichment_fields: list[str] = list(merged.get("_enrichment_fields") or [])
        merged["_messenger_context"] = messages

        if not merged.get("ТГ ник"):
            nick = extract_tg_nick_from_messages(messages)
            if nick:
                apply_ai_field(merged, "ТГ ник", nick, ai_fields)
                enrichment_fields.append("ТГ ник")

        tags, tag_reasons = evaluate_tags_for_row(merged)
        if tags:
            existing = normalize_tags_field(merged.get("Теги")) or ""
            existing_list = [t for t in existing.split() if t]
            combined = normalize_tags_field(" ".join(dict.fromkeys([*existing_list, *tags.split()])))
            if combined:
                apply_ai_field(merged, "Теги", combined, ai_fields)
                enrichment_fields.append("Теги")
            merged["_ai_tag_reasons"] = {**dict(merged.get("_ai_tag_reasons") or {}), **tag_reasons}

        if not merged.get("Саммари"):
            summary = self._segmentation._heuristic_intent_summary(merged)
            if summary:
                apply_ai_field(merged, "Саммари", summary, ai_fields)
                enrichment_fields.append("Саммари")

        rec = self._segmentation._heuristic_recommendation(merged)
        if rec:
            merged["_ai_recommendation"] = rec

        merged["_reasoning"] = "Эвристика по переписке (без AI или API недоступен)"
        merged["_ai_processed"] = True
        merged["_ai_fields"] = list(dict.fromkeys(ai_fields))
        merged["_enrichment_fields"] = list(dict.fromkeys(enrichment_fields))
        merged["_enrichment_source"] = "messenger_heuristic"
        return merged

    def _heuristic_from_orders(self, row: dict[str, Any]) -> dict[str, Any]:
        base = self._segmentation._heuristic_row(dict(row))
        base["_enrichment_source"] = "orders_only"
        base["_messenger_sources"] = row.get("_messenger_sources") or []
        base["_messenger_context"] = row.get("_messenger_context") or []
        base["_ai_processed"] = True
        if base.get("_ai_fields"):
            base["_enrichment_fields"] = list(base.get("_ai_fields") or [])
        return base

    @staticmethod
    def _has_profile_context(row: dict[str, Any]) -> bool:
        if row.get("_orders_context"):
            return True
        return bool(collect_client_comments(row).strip())

    @staticmethod
    def _row_key(row: dict[str, Any]) -> str:
        return str(row.get("UUID") or row.get("uuid") or row.get("Наименование"))
