from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Callable
from typing import Any

import httpx

from app.config import Settings
from app.services.excel_parser import SEGMENT_COLUMNS

SYSTEM_PROMPT = """Ты — старший CRM-аналитик цветочного бизнеса (продажа букетов, доставка).
Твоя задача — по данным клиента и его заказов заполнить 4 поля сегментации.

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

2. "Заказчик или получатель" — ФИО реального человека.
   Ищи в: комментариях к заказу (шаблон "Получатель<TAB>Имя телефон"), в поле Наименование
   (если это имя, а не номер телефона), в полях Фамилия/Имя/Отчество.
   Если только номер телефона и нет имени — null.

3. "Пол" — "Мужской" или "Женский", определяй по имени получателя/заказчика:
   - женские имена (Ксения, Ольга, Анна, Мария, Елена...) → "Женский"
   - мужские имена (Иван, Пётр, Сергей, Александр...) → "Мужской"
   - имя на -а/-я обычно женское, на согласную обычно мужское (кроме Никита, Илья и т.п.)
   Если имя неизвестно или неоднозначно (Саша, Женя) → null.

4. "ТГ ник" — telegram username в формате @username.
   Ищи в email (часть до @, если похоже на ник), в комментариях, в поле Наименование.
   Если явного ника нет — null. НЕ выдумывай ник.

ВАЖНО:
- Опирайся ТОЛЬКО на данные. Если сигнала нет — ставь null, не фантазируй.
- reasoning — 1 короткое предложение на русском, на основании чего сделан вывод.
- Верни СТРОГО JSON-объект вида {"results": [...]}, где каждый элемент содержит ключи:
  uuid, "Группы", "Заказчик или получатель", "Пол", "ТГ ник", reasoning, confidence
  confidence — число от 0 до 1 (общая уверенность в заполнении)."""

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
    skip = {"_orders_context", "_orders_count", "_reasoning", "_ai_processed"}
    compact = {
        k: v
        for k, v in row.items()
        if k not in skip and v is not None and not str(k).startswith("_")
    }
    if row.get("_orders_context"):
        compact["orders_sample"] = row["_orders_context"][:3]
    if row.get("_orders_count"):
        compact["orders_count_matched"] = row["_orders_count"]
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
                "current": {col: row.get(col) for col in SEGMENT_COLUMNS},
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
            for col in SEGMENT_COLUMNS:
                value = ai.get(col)
                if value not in (None, "", "null"):
                    merged[col] = value

            if not merged.get("Пол"):
                guessed = guess_gender(merged.get("Заказчик или получатель"))
                if guessed:
                    merged["Пол"] = guessed

            merged["_reasoning"] = ai.get("reasoning", "")
            merged["_confidence"] = ai.get("confidence")
            merged["_ai_processed"] = True
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

        if not merged.get("Группы"):
            merged["Группы"] = self._heuristic_group(row)

        recipient = self._extract_recipient(row)
        if recipient and not merged.get("Заказчик или получатель"):
            merged["Заказчик или получатель"] = recipient

        if not merged.get("Пол"):
            guessed = guess_gender(
                merged.get("Заказчик или получатель") or merged.get("Наименование")
            )
            if guessed:
                merged["Пол"] = guessed

        if not merged.get("ТГ ник"):
            tg = self._extract_tg(row)
            if tg:
                merged["ТГ ник"] = tg

        merged["_reasoning"] = "Эвристика без AI (ключ API не задан)"
        merged["_confidence"] = None
        merged["_ai_processed"] = False
        return merged

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

        name = row.get("Наименование")
        if name and not _PHONE_RE.match(str(name).strip()):
            return str(name)
        return None

    @staticmethod
    def _extract_tg(row: dict[str, Any]) -> str | None:
        for key in ("ТГ ник", "E-mail", "Наименование", "Комментарий"):
            value = row.get(key)
            if value:
                match = _TG_RE.search(str(value))
                if match:
                    return f"@{match.group(1)}"
        return None
