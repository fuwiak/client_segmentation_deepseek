from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Callable
from typing import Any

import httpx

from app.config import Settings
from app.services.excel_parser import AI_COLUMNS, AI_EXTRA_COLUMNS, SEGMENT_COLUMNS
from app.services.fields import (
  apply_ai_field,
  apply_name_parts,
  collect_client_comments,
  extract_email_from_row,
  COUNTERPARTY_COMMENT_KEYS,
)
from app.services.tag_rules import evaluate_tags_for_row

SYSTEM_PROMPT = """Ты — старший CRM-аналитик цветочного бизнеса (продажа букетов, доставка).
Твоя задача — по данным клиента и его заказов заполнить поля сегментации и профиль клиента.

ПРАВИЛА ПО КАЖДОМУ ПОЛЮ:

1. "Группы" — сегмент клиента. Определи по среднему чеку, числу заказов и каналу продаж.
   Возможные значения (можно несколько через "/"):
   - "букет от 10 000" — если средний чек ≥ 10000
   - "премиум" — средний чек ≥ 20000
   - "постоянный клиент" — заказов ≥ 3
   - "новый" — заказов ≤ 1
   - "маркетплейс" — канал продаж это маркетплейс (Яндекс, Ozon, Wildberries)
   - "прямые продажи" — прямой канал
   - "корпоративный" — если это юрлицо/ИП
   - "событие" — если в данных есть указание на праздник/событие
   Если уже есть значение в "Группы" — уточни или дополни его, не удаляй.

2. "Заказчик или получатель" — кто заказывает: заказчик или получатель; укажи ФИО если есть.
   Ищи в комментариях к заказу, в комментарии контрагента (Комментарий, комментарии к адресам),
   в Наименовании, в полях Фамилия/Имя/Отчество.

3. "Пол" — "Мужской" или "Женский", определяй по имени получателя/заказчика.
   Если имя неизвестно или неоднозначно (Саша, Женя) → null.

4. "ТГ ник" — telegram username в формате @username.
   Ищи в email, комментариях контрагента и заказов, поле Наименование. НЕ выдумывай.

5. "Теги" — хэштеги событий и характеристик через пробел, например: #деньрождения #vip #проблемный #доволен
   Определи по датам заказов (праздники), сумме, комментариям контрагента и заказов, тону коммуникации.
   Теги: события (8марта, деньрождения, свадьба), настроение (доволен/недоволен), проблемный, постоянный, vip.

6. "Саммари" — 1-2 предложения на русском: кто клиент, для кого заказывает, постоянный ли, есть ли проблемы.

7. "Фамилия (для ИП и физ. лиц)", "Имя (для ИП и физ. лиц)", "Отчество (для ИП и физ. лиц)" —
   заполни из ФИО заказчика/получателя, если явно указаны в данных или комментариях.

8. "E-mail" — только если явно есть в комментариях или полях клиента.

9. "Дата рождения" — только если явно указана в комментариях (формат ДД.ММ.ГГГГ).

10. Если есть messages_sample (WhatsApp/Telegram) — учитывай тон переписки, поводы, жалобы,
   благодарности, имена получателей. Указывай в references канал (whatsapp/telegram).

Дополнительно в reasoning укажи источник данных (поле, заказ или переписка).

ВАЖНО:
- Опирайся ТОЛЬКО на данные. Если сигнала нет — ставь null, не фантазируй.
- reasoning — 1 короткое предложение на русском с указанием источника.
- references — объект: поле → откуда взято (например {"Пол": "имя в комментарии заказа №123"}).
- Верни СТРОГО JSON-объект вида {"results": [...]}, где каждый элемент содержит ключи:
  uuid, "Группы", "Заказчик или получатель", "Пол", "ТГ ник", "Теги", "Саммари",
  "Фамилия (для ИП и физ. лиц)", "Имя (для ИП и физ. лиц)", "Отчество (для ИП и физ. лиц)",
  "E-mail", "Дата рождения",
  reasoning, confidence, references
  confidence — число от 0 до 1."""

FEMALE_NAMES = {
    "ксения", "ольга", "анна", "мария", "елена", "татьяна", "наталья", "ирина",
    "светлана", "юлия", "екатерина", "виктория", "дарья", "полина", "алина",
    "марина", "оксана", "людмила", "галина", "надежда", "вера", "любовь",
    "валентина", "лариса", "нина", "евгения", "александра", "софия", "софья",
    "алёна", "алена", "кристина", "яна", "инна", "жанна", "маргарита", "лидия",
    "элина", "диана", "карина", "ангелина", "вероника", "валерия", "лилия",
    "зоя", "раиса", "тамара", "элла", "снежана", "милана", "арина", "варвара",
}
MALE_NAMES = {
    "иван", "пётр", "петр", "сергей", "александр", "андрей", "дмитрий", "алексей",
    "михаил", "николай", "владимир", "евгений", "максим", "артём", "артем",
    "денис", "роман", "антон", "павел", "игорь", "виктор", "олег", "константин",
    "юрий", "василий", "григорий", "борис", "фёдор", "федор", "никита", "илья",
    "кирилл", "тимофей", "матвей", "егор", "глеб", "степан", "богдан", "вадим",
    "руслан", "тимур", "марк", "лев", "данил", "даниил", "арсений", "герман",
}

_PHONE_RE = re.compile(r"^[\+\d\s\(\)\-]{6,}$")
_TG_RE = re.compile(r"@([A-Za-z][A-Za-z0-9_]{3,31})")


def guess_gender(name: str | None) -> str | None:
    if not name:
        return None
    first = name.strip().split()[0].lower().strip(".,")
    if first in FEMALE_NAMES:
        return "Женский"
    if first in MALE_NAMES:
        return "Мужской"
    return None


def _compact_row(row: dict[str, Any]) -> dict[str, Any]:
    skip = {
        "_orders_context",
        "_orders_count",
        "_reasoning",
        "_ai_processed",
        "_messenger_context",
    }
    compact = {
        k: v
        for k, v in row.items()
        if k not in skip and v is not None and not str(k).startswith("_")
    }
    if row.get("_orders_context"):
        compact["orders_sample"] = row["_orders_context"][:3]
    if row.get("_orders_count"):
        compact["orders_count_matched"] = row["_orders_count"]
    if row.get("_messenger_context"):
        compact["messages_sample"] = row["_messenger_context"][:8]
        compact["messages_count"] = len(row["_messenger_context"])
    comments = collect_client_comments(row)
    if comments:
        compact["all_comments"] = comments[:2000]
    return compact


class SegmentationService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def segment_all(
        self,
        rows: list[dict[str, Any]],
        progress_cb: Callable[[int], None] | None = None,
    ) -> list[dict[str, Any]]:
        if not self._settings.openrouter_api_key:
            results = []
            for row in rows:
                results.append(self._heuristic_row(row))
                if progress_cb:
                    progress_cb(1)
            return results

        batch_size = self._settings.ai_batch_size
        batches = [
            rows[i : i + batch_size] for i in range(0, len(rows), batch_size)
        ]

        semaphore = asyncio.Semaphore(self._settings.ai_concurrency)

        async def _run(batch: list[dict[str, Any]]) -> list[dict[str, Any]]:
            async with semaphore:
                result = await self._segment_batch(batch)
                if progress_cb:
                    progress_cb(len(batch))
                return result

        async with httpx.AsyncClient(
            timeout=self._settings.ai_timeout_seconds
        ) as client:
            self._client = client
            batch_results = await asyncio.gather(
                *(_run(batch) for batch in batches)
            )

        merged: list[dict[str, Any]] = []
        for chunk in batch_results:
            merged.extend(chunk)
        return merged

    async def _segment_batch(
        self, rows: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        payload_rows = [
            {
                "uuid": self._row_key(row),
                "current": {col: row.get(col) for col in AI_COLUMNS},
                "data": _compact_row(row),
            }
            for row in rows
        ]
        user_prompt = (
            "Проанализируй клиентов и заполни поля сегментации. "
            "Ответ верни как JSON-объект {\"results\": [...]}.\n\n"
            f"{json.dumps(payload_rows, ensure_ascii=False)}"
        )

        content = await self._call_with_retry(user_prompt)
        if content is None:
            return [self._heuristic_row(r) for r in rows]
        return self._parse_ai_response(content, rows)

    async def _call_with_retry(self, user_prompt: str) -> str | None:
        last_exc: Exception | None = None
        for attempt in range(self._settings.ai_max_retries + 1):
            try:
                resp = await self._client.post(
                    f"{self._settings.openrouter_base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self._settings.openrouter_api_key}",
                        "Content-Type": "application/json",
                        "HTTP-Referer": "https://client-segmentation-deepseek.up.railway.app",
                        "X-Title": "Client Segmentation",
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
                return resp.json()["choices"][0]["message"]["content"]
            except (httpx.HTTPError, KeyError, IndexError) as exc:
                last_exc = exc
                if attempt < self._settings.ai_max_retries:
                    await asyncio.sleep(1.5 * (attempt + 1))
        return None

    def _parse_ai_response(
        self, content: str, original_rows: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        parsed = self._extract_json(content)
        if parsed is None:
            return [self._heuristic_row(r) for r in original_rows]

        items = parsed.get("results", parsed) if isinstance(parsed, dict) else parsed
        if not isinstance(items, list):
            return [self._heuristic_row(r) for r in original_rows]

        by_uuid = {str(item.get("uuid")): item for item in items if isinstance(item, dict)}

        results = []
        for row in original_rows:
            ai = by_uuid.get(self._row_key(row), {})
            merged = dict(row)
            ai_fields: list[str] = []
            all_ai_cols = AI_COLUMNS
            for col in all_ai_cols:
                value = ai.get(col)
                if value not in (None, "", "null"):
                    apply_ai_field(merged, col, value, ai_fields)

            if not merged.get("Пол"):
                guessed = guess_gender(merged.get("Заказчик или получатель"))
                if guessed:
                    apply_ai_field(merged, "Пол", guessed, ai_fields)

            merged["_reasoning"] = ai.get("reasoning", "")
            merged["_confidence"] = ai.get("confidence")
            merged["_ai_refs"] = ai.get("references") or {}
            merged["_ai_processed"] = True
            merged["_ai_fields"] = ai_fields
            results.append(merged)
        return results

    @staticmethod
    def _extract_json(content: str) -> Any | None:
        text = content.strip()
        if text.startswith("```"):
            text = re.sub(r"^```[a-zA-Z]*\n", "", text)
            text = text.rsplit("```", 1)[0]
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"[\{\[].*[\}\]]", text, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(0))
                except json.JSONDecodeError:
                    return None
            return None

    @staticmethod
    def _row_key(row: dict[str, Any]) -> str:
        return str(row.get("UUID") or row.get("uuid") or row.get("Наименование"))

    def _heuristic_row(self, row: dict[str, Any]) -> dict[str, Any]:
        merged = dict(row)
        ai_fields: list[str] = []

        if not merged.get("Группы"):
            group = self._heuristic_group(row)
            if group:
                apply_ai_field(merged, "Группы", group, ai_fields)

        recipient = self._extract_recipient(row)
        if recipient and not merged.get("Заказчик или получатель"):
            apply_ai_field(merged, "Заказчик или получатель", recipient, ai_fields)

        if not merged.get("Пол"):
            guessed = guess_gender(
                merged.get("Заказчик или получатель") or merged.get("Наименование")
            )
            if guessed:
                apply_ai_field(merged, "Пол", guessed, ai_fields)

        if not merged.get("ТГ ник"):
            tg = self._extract_tg(row)
            if tg:
                apply_ai_field(merged, "ТГ ник", tg, ai_fields)

        recipient = merged.get("Заказчик или получатель")
        if recipient:
            apply_name_parts(merged, str(recipient), ai_fields)

        if not merged.get("E-mail"):
            email = extract_email_from_row(row)
            if email:
                apply_ai_field(merged, "E-mail", email, ai_fields)

        if not merged.get("Теги"):
            tags, tag_reasons = evaluate_tags_for_row(merged)
            if tags:
                apply_ai_field(merged, "Теги", tags, ai_fields)
                merged["_ai_tag_reasons"] = {**dict(merged.get("_ai_tag_reasons") or {}), **tag_reasons}

        if not merged.get("Саммари") and row.get("_messenger_context"):
            msgs = row["_messenger_context"]
            channels = ", ".join(sorted({m.get("channel", "") for m in msgs if m.get("channel")}))
            apply_ai_field(
                merged,
                "Саммари",
                (
                    f"Есть переписка ({channels}, {len(msgs)} сообщ.). "
                    f"Последнее: {msgs[-1].get('text', '')[:100]}"
                ),
                ai_fields,
            )

        merged["_reasoning"] = "Эвристика без AI (ключ API не задан)"
        merged["_confidence"] = None
        merged["_ai_refs"] = {}
        merged["_ai_processed"] = False
        merged["_ai_fields"] = ai_fields
        return merged

    @staticmethod
    def _heuristic_tags(row: dict[str, Any]) -> str | None:
        tags: list[str] = []
        try:
            orders = int(row.get("Всего заказов") or row.get("_orders_count") or 0)
        except (TypeError, ValueError):
            orders = 0
        if orders > 2:
            tags.append("#постоянный")
        try:
            avg = float(row.get("Средний чек") or 0)
            if avg >= 15000:
                tags.append("#vip")
        except (TypeError, ValueError):
            pass
        for order in row.get("_orders_context") or []:
            comment = str(order.get("Комментарий") or "").lower()
            if any(w in comment for w in ("день рождения", "др", "birthday")):
                tags.append("#деньрождения")
            if any(w in comment for w in ("8 марта", "8марта")):
                tags.append("#8марта")
        counterparty_comments = collect_client_comments(row).lower()
        if any(w in counterparty_comments for w in ("день рождения", "др", "birthday")):
            tags.append("#деньрождения")
        if any(w in counterparty_comments for w in ("8 марта", "8марта")):
            tags.append("#8марта")
        all_text = " ".join(
            str(m.get("text") or "")
            for m in row.get("_messenger_context") or []
        ).lower()
        if any(w in all_text for w in ("спасибо", "отлично", "супер")):
            tags.append("#доволен")
        if any(w in all_text for w in ("жалоб", "плох", "разочар")):
            tags.append("#проблемный")
        if any(w in all_text for w in ("день рождения", "др ", "birthday")):
            tags.append("#деньрождения")
        return " ".join(dict.fromkeys(tags)) if tags else None

    @staticmethod
    def _heuristic_group(row: dict[str, Any]) -> str | None:
        parts: list[str] = []
        avg = row.get("Средний чек")
        try:
            avg_val = float(avg) if avg is not None else 0
        except (TypeError, ValueError):
            avg_val = 0
        if avg_val >= 20000:
            parts.append("премиум")
        elif avg_val >= 10000:
            parts.append("букет от 10 000")

        try:
            orders = int(row.get("Всего заказов") or 0)
        except (TypeError, ValueError):
            orders = 0
        if orders >= 3:
            parts.append("постоянный клиент")

        channel = str(
            row.get("Канал продаж") or row.get("Тип карала продаж") or ""
        ).lower()
        if any(m in channel for m in ("маркетплейс", "яндекс", "ozon", "wildberries")):
            parts.append("маркетплейс")
        elif "прямые" in channel:
            parts.append("прямые продажи")

        return "/".join(dict.fromkeys(parts)) or None

    @staticmethod
    def _extract_recipient(row: dict[str, Any]) -> str | None:
        for order in row.get("_orders_context", []) or []:
            for value in order.values():
                text = str(value)
                match = re.search(r"[Пп]олучатель\t?\s*([А-ЯЁ][а-яё]+)", text)
                if match:
                    return match.group(1)

        comments = collect_client_comments(row)
        if comments:
            match = re.search(
                r"[Пп]олучатель[:\s]+([А-ЯЁ][а-яё]+(?:\s+[А-ЯЁ][а-яё]+){0,2})",
                comments,
            )
            if match:
                return match.group(1).strip()

        name = row.get("Наименование")
        if name and not _PHONE_RE.match(str(name).strip()):
            return str(name)
        return None

    @staticmethod
    def _extract_tg(row: dict[str, Any]) -> str | None:
        search_text = collect_client_comments(row)
        for key in ("ТГ ник", "E-mail", "Наименование", *COUNTERPARTY_COMMENT_KEYS):
            value = row.get(key)
            if value:
                search_text = f"{search_text} {value}"
        match = _TG_RE.search(search_text)
        if match:
            return f"@{match.group(1)}"
        return None
