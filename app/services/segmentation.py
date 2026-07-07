from __future__ import annotations

import json
from typing import Any

import httpx

from app.config import Settings
from app.services.excel_parser import SEGMENT_COLUMNS

SYSTEM_PROMPT = """Ты — аналитик CRM для цветочного бизнеса.
На основе данных о клиенте определи сегментацию и заполни поля:
- Группы: сегмент клиента (например: "букет от 10 000", "маркетплейс", "постоянный клиент", "флаувау", "событие")
- Заказчик или получатель: ФИО заказчика/получателя, если можно определить из данных
- Пол: "Мужской", "Женский" или null если неизвестно
- ТГ ник: telegram username с @ если можно определить, иначе null

Отвечай ТОЛЬКО валидным JSON-массивом объектов с ключами:
uuid, Группы, Заказчик или получатель, Пол, ТГ ник, reasoning

reasoning — краткое объяснение на русском (1 предложение)."""


def _compact_row(row: dict[str, Any]) -> dict[str, Any]:
    skip = {"_orders_context"}
    compact = {k: v for k, v in row.items() if k not in skip and v is not None}
    if "_orders_context" in row:
        compact["orders_sample"] = row["_orders_context"][:3]
    return compact


class SegmentationService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def segment_batch(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not self._settings.openrouter_api_key:
            return self._fallback_segment(rows)

        payload_rows = []
        for row in rows:
            payload_rows.append({
                "uuid": row.get("UUID") or row.get("uuid") or row.get("Наименование"),
                "current": {col: row.get(col) for col in SEGMENT_COLUMNS},
                "data": _compact_row(row),
            })

        user_prompt = (
            "Проанализируй клиентов и заполни сегментационные поля.\n"
            f"Данные:\n{json.dumps(payload_rows, ensure_ascii=False, indent=2)}"
        )

        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{self._settings.openrouter_base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self._settings.openrouter_api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://client-segmentation.railway.app",
                    "X-Title": "Client Segmentation",
                },
                json={
                    "model": self._settings.openrouter_model,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": 0.2,
                },
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]

        return self._parse_ai_response(content, rows)

    def _parse_ai_response(
        self, content: str, original_rows: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        text = content.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0]

        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return self._fallback_segment(original_rows)

        by_uuid = {str(item.get("uuid")): item for item in parsed}
        results = []
        for row in original_rows:
            key = str(row.get("UUID") or row.get("uuid") or row.get("Наименование"))
            ai = by_uuid.get(key, {})
            merged = dict(row)
            for col in SEGMENT_COLUMNS:
                if ai.get(col):
                    merged[col] = ai[col]
            merged["_reasoning"] = ai.get("reasoning", "")
            merged["_ai_processed"] = True
            results.append(merged)
        return results

    def _fallback_segment(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        results = []
        for row in rows:
            merged = dict(row)
            channel = str(row.get("Канал продаж") or row.get("Тип карала продаж") or "")
            if channel and not merged.get("Группы"):
                if "маркетплейс" in channel.lower():
                    merged["Группы"] = "маркетплейс"
                elif "прямые" in channel.lower():
                    merged["Группы"] = "прямые продажи"
            merged["_reasoning"] = "Эвристика без AI (ключ API не задан)"
            merged["_ai_processed"] = False
            results.append(merged)
        return results

    async def segment_all(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        batch_size = self._settings.ai_batch_size
        all_results: list[dict[str, Any]] = []
        for i in range(0, len(rows), batch_size):
            batch = rows[i : i + batch_size]
            results = await self.segment_batch(batch)
            all_results.extend(results)
        return all_results
