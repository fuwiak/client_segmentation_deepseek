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
  apply_resolved_gender,
  collect_client_comments,
  empty_fillable_columns,
  extract_email_from_row,
  extract_tg_nick_from_row,
  guess_gender,
  infer_gender_heuristic,
  normalize_gender_label,
  normalize_naimenovanie_key,
  sales_type_from_channel,
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
   - "маркетплейс" — канал продаж это маркетплейс (Flowwow, Ozon, Яндекс, Flawery)
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

6. "Саммари" — 2–3 предложения на русском о МОТИВАЦИИ покупки (intent), а не о профиле клиента.
   НЕ пиши «постоянный клиент», «высокий средний чек», «настроение не определено» — это уже в других полях.
   Фокус:
   - СОБЫТИЕ/ПОВОД: день рождения, 8 марта, 14 февраля, годовщина, свадьба, извинение, выпускной, Новый год и т.д.
   - INTENT: зачем покупает — подарок (кому именно), для себя, романтический жест, корпоративный заказ, срочная доставка «к 18:00»
   - ПАТТЕРН: если заказы повторяются в одни даты — укажи регулярное событие (например, «ежегодно на 8 марта»)
   Источники: комментарии заказов, переписка, даты заказов, имена получателей.
   Если повод не ясен — одной фразой «повод не определён из данных», без общих описаний клиента.

7. "Фамилия (для ИП и физ. лиц)", "Имя (для ИП и физ. лиц)", "Отчество (для ИП и физ. лиц)" —
   заполни из ФИО заказчика/получателя, если явно указаны в данных или комментариях.

8. "E-mail" — только если явно есть в комментариях или полях клиента.

9. "Дата рождения" — только если явно указана в комментариях (формат ДД.ММ.ГГГГ).

10. Если есть messages_sample (WhatsApp/Telegram) — учитывай тон переписки, поводы, жалобы,
   благодарности, имена получателей. Указывай в references канал (whatsapp/telegram).

11. Для каждого поля из empty_fields — попробуй заполнить по данным клиента и заказов.
    Адреса, ИНН/КПП/ОГРН/ОКПО, банковские реквизиты (БИК, Банк, К/с, Р/с), тип контрагента,
    полное наименование, местонахождение, комментарии, статус, канал продаж — ТОЛЬКО при явном
    указании в данных. Не выдумывай юридические и банковские реквизиты.

12. "Рекомендация" — 1–2 предложения: что предложить клиенту сейчас (оффер, тайминг, канал связи).
    Это действие для оператора, а не описание клиента. Опирайся на Саммари, теги, историю заказов.
    Если данных мало — предложи нейтральный follow-up (например, напоминание о сезонном букете).

Дополнительно в reasoning укажи источник данных (поле, заказ или переписка).

ВАЖНО:
- Опирайся ТОЛЬКО на данные. Если сигнала нет — ставь null, не фантазируй.
- reasoning — 1 короткое предложение на русском с указанием источника.
- references — объект: поле → откуда взято (например {"Пол": "имя в комментарии заказа №123"}).
- Верни СТРОГО JSON-объект вида {"results": [...]}, где каждый элемент содержит ключи:
  uuid, "Группы", "Заказчик или получатель", "Пол", "ТГ ник", "Теги", "Саммари", "Рекомендация",
  "Фамилия (для ИП и физ. лиц)", "Имя (для ИП и физ. лиц)", "Отчество (для ИП и физ. лиц)",
  "E-mail", "Дата рождения",
  а также любые поля из empty_fields клиента, если удалось определить значение,
  reasoning, confidence, references
  confidence — число от 0 до 1."""

GENDER_CONFIRM_SYSTEM_PROMPT = """Ты определяешь пол человека по ФИО или имени из CRM цветочного магазина.
Форматы: «Фамилия Имя», «Имя Фамилия», «Имя», латиница (Vladislav Koroteev), ник Telegram (@username).
Учитывай heuristic_guess как подсказку, но исправь если уверен в другом значении.
Верни СТРОГО JSON {"results": [{"name": "исходное имя как во входе", "Пол": "Мужской"|"Женский"|null}]}.
null только для явно неоднозначных имён (Саша, Женя без фамилии) или если это не имя человека."""

_PHONE_RE = re.compile(r"^[\+\d\s\(\)\-]{6,}$")


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

    async def confirm_gender_by_naimenovanie(
        self,
        names: list[str],
        heuristic_map: dict[str, str],
    ) -> dict[str, str]:
        """AI-подтверждение пола по уникальным Наименование (после эвристики)."""
        if not names or not self._settings.openrouter_api_key:
            return dict(heuristic_map)

        merged_map = dict(heuristic_map)
        batch_size = 50
        async with httpx.AsyncClient(
            timeout=self._settings.ai_timeout_seconds
        ) as client:
            self._client = client
            for offset in range(0, len(names), batch_size):
                chunk = names[offset : offset + batch_size]
                payload = [
                    {
                        "name": name,
                        "heuristic_guess": heuristic_map.get(
                            normalize_naimenovanie_key(name)
                        ),
                    }
                    for name in chunk
                ]
                user_prompt = (
                    "Определи пол по списку имён. Верни JSON {\"results\": [...]}.\n\n"
                    f"{json.dumps(payload, ensure_ascii=False)}"
                )
                content = await self._call_with_retry(
                    user_prompt,
                    system_prompt=GENDER_CONFIRM_SYSTEM_PROMPT,
                )
                if content is None:
                    continue
                parsed = self._extract_json(content)
                if parsed is None:
                    continue
                items = (
                    parsed.get("results", parsed)
                    if isinstance(parsed, dict)
                    else parsed
                )
                if not isinstance(items, list):
                    continue
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    name = str(item.get("name") or "").strip()
                    gender = normalize_gender_label(item.get("Пол"))
                    if name and gender:
                        merged_map[normalize_naimenovanie_key(name)] = gender
        return merged_map

    async def _segment_batch(
        self, rows: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        payload_rows = [
            {
                "uuid": self._row_key(row),
                "current": {col: row.get(col) for col in AI_COLUMNS},
                "empty_fields": empty_fillable_columns(row),
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

    async def _call_with_retry(
        self,
        user_prompt: str,
        *,
        system_prompt: str | None = None,
    ) -> str | None:
        last_exc: Exception | None = None
        sys_content = system_prompt or SYSTEM_PROMPT
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
                            {"role": "system", "content": sys_content},
                            {"role": "user", "content": user_prompt},
                        ],
                        "temperature": self._settings.ai_temperature,
                        "response_format": {"type": "json_object"},
                    },
                )
                resp.raise_for_status()
                return resp.json()["choices"][0]["message"]["content"]
            except httpx.HTTPStatusError as exc:
                last_exc = exc
                if exc.response.status_code in (401, 403):
                    return None
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
            target_cols = list(
                dict.fromkeys([*AI_COLUMNS, *empty_fillable_columns(row)])
            )
            for col in target_cols:
                if col == "Пол":
                    continue
                value = ai.get(col)
                if value not in (None, "", "null"):
                    apply_ai_field(merged, col, value, ai_fields)

            apply_resolved_gender(merged, ai.get("Пол"), ai_fields)

            merged["_reasoning"] = ai.get("reasoning", "")
            merged["_confidence"] = ai.get("confidence")
            merged["_ai_refs"] = ai.get("references") or {}
            recommendation = ai.get("Рекомендация") or ai.get("recommendation")
            if recommendation not in (None, "", "null"):
                merged["_ai_recommendation"] = str(recommendation).strip()
            elif not merged.get("_ai_recommendation"):
                rec = self._heuristic_recommendation(merged)
                if rec:
                    merged["_ai_recommendation"] = rec
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
            guessed = infer_gender_heuristic(merged)
            if guessed:
                apply_ai_field(merged, "Пол", guessed, ai_fields)

        if not merged.get("ТГ ник"):
            tg = extract_tg_nick_from_row(row)
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

        if not merged.get("Саммари"):
            summary = self._heuristic_intent_summary(row)
            if summary:
                apply_ai_field(merged, "Саммари", summary, ai_fields)

        rec = self._heuristic_recommendation(merged)
        if rec:
            merged["_ai_recommendation"] = rec

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

    _EVENT_HINTS: tuple[tuple[tuple[str, ...], str], ...] = (
        (("день рождения", "д.р.", "др ", "birthday"), "день рождения"),
        (("8 марта", "8марта"), "8 марта"),
        (("14 февраля", "14февраля", "валентин"), "14 февраля"),
        (("свадьб", "бракосочет"), "свадьба"),
        (("годовщин",), "годовщина"),
        (("выпуск",), "выпускной"),
        (("новый год", "новогод"), "Новый год"),
        (("1 сентября", "1сентября"), "1 сентября"),
        (("извин", "прости"), "извинение"),
    )

    _INTENT_HINTS: tuple[tuple[tuple[str, ...], str], ...] = (
        (("мам", "маме", "матери", "мамочк"), "подарок маме"),
        (("девушк", "жене", "жён", "подруг", "любим"), "подарок партнёру"),
        (("коллег", "началь", "босс", "корпоратив"), "корпоративный заказ"),
        (("для себя", "себе", "домой"), "для себя"),
        (("подарок", "подар"), "подарок"),
        (("срочн", "к 18", "к 19", "к 20", "к 21"), "срочная доставка"),
    )

    @classmethod
    def _collect_intent_text(cls, row: dict[str, Any]) -> str:
        parts = [collect_client_comments(row).lower()]
        for msg in row.get("_messenger_context") or []:
            parts.append(str(msg.get("text") or "").lower())
        return " ".join(parts)

    @classmethod
    def _heuristic_intent_summary(cls, row: dict[str, Any]) -> str | None:
        """Саммари: события и intent покупки из комментариев и переписки."""
        text = cls._collect_intent_text(row)
        if not text.strip():
            return None

        events: list[str] = []
        for keywords, label in cls._EVENT_HINTS:
            if any(k in text for k in keywords):
                events.append(label)

        intents: list[str] = []
        for keywords, label in cls._INTENT_HINTS:
            if any(k in text for k in keywords):
                intents.append(label)

        parts: list[str] = []
        if events:
            parts.append(f"Поводы: {', '.join(dict.fromkeys(events))}.")
        if intents:
            parts.append(f"Intent: {', '.join(dict.fromkeys(intents))}.")

        recipient = row.get("Заказчик или получатель")
        if recipient and str(recipient).strip():
            parts.append(f"Получатель: {recipient}.")

        if parts:
            return " ".join(parts)
        if row.get("_orders_context") or row.get("_messenger_context"):
            return "Повод покупки не определён из доступных комментариев и переписки."
        return None

    @classmethod
    def _heuristic_recommendation(cls, row: dict[str, Any]) -> str | None:
        """Практическая рекомендация оператору: оффер и тайминг."""
        tags = str(row.get("Теги") or "").lower()
        summary = str(row.get("Саммари") or "").lower()
        text = f"{tags} {summary} {cls._collect_intent_text(row)}"
        hints: list[str] = []

        if any(k in text for k in ("день рождения", "др ", "birthday", "#деньрождения")):
            hints.append("Напомнить о букете ко дню рождения за 3–5 дней и предложить готовый вариант с доставкой.")
        if any(k in text for k in ("8 марта", "8марта", "#8марта")):
            hints.append("За 7–10 дней до 8 марта отправить персональное предложение с акцентом на любимые цветы.")
        if any(k in text for k in ("14 февраля", "валентин")):
            hints.append("Предложить романтический букет с доставкой к точному времени.")
        if "#vip" in tags or row.get("ВИП") == "да":
            hints.append("Сделать персональное VIP-предложение с премиум-составом и приоритетной доставкой.")
        if "#проблемный" in tags:
            hints.append("Связаться лично, уточнить прошлый опыт и предложить компенсационный букет.")
        if "#доволен" in tags:
            hints.append("Поблагодарить и предложить бонус на следующий заказ в любимом стиле.")

        channel = row.get("Канал продаж") or ""
        contact = "Telegram" if row.get("ТГ ник") else ("WhatsApp" if row.get("Телефон") else "телефон")
        if not hints:
            try:
                orders = int(row.get("Всего заказов") or row.get("_orders_count") or 0)
            except (TypeError, ValueError):
                orders = 0
            if orders > 2:
                hints.append(
                    f"Напомнить о регулярном заказе через {contact}"
                    + (f" (канал: {channel})." if channel else ".")
                )
            elif orders == 1:
                hints.append("Предложить повторный заказ со скидкой на доставку в течение 2 недель.")
            else:
                hints.append(
                    f"Связаться через {contact} с предложением сезонного букета"
                    " или welcome-скидки на первый заказ."
                )

        return " ".join(dict.fromkeys(hints))

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
            row.get("Канал продаж") or row.get("Тип канала продаж") or ""
        )
        if channel:
            parts.append(sales_type_from_channel(channel))

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
        return extract_tg_nick_from_row(row)
