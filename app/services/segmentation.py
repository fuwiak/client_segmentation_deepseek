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
  apply_ai_client_summary,
  apply_name_parts,
  apply_resolved_gender,
  build_client_history_summary,
  collect_client_comments,
  empty_fillable_columns,
  extract_email_from_row,
  extract_tg_nick_from_row,
  gender_analysis_payload,
  guess_gender,
  infer_gender_heuristic,
  normalize_gender_label,
  normalize_naimenovanie_key,
  sales_type_from_channel,
  COUNTERPARTY_COMMENT_KEYS,
)
from app.services.ai_narrative_style import AI_NARRATIVE_STYLE
from app.services.tag_rules import evaluate_tags_for_row, normalize_tags_field

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
   - "событие <месяц>" — праздник/повод обязательно с месяцем
     (например «событие марта», «событие июля»); без голого «событие»
   Если уже есть значение в "Группы" — уточни или дополни его, не удаляй.

2. "Заказчик или получатель" — кто заказывает: заказчик или получатель; укажи ФИО если есть.
   Ищи в комментариях к заказу, в комментарии контрагента (Комментарий, комментарии к адресам),
   в Наименовании, в полях Фамилия/Имя/Отчество.

3. "Пол" — "Мужской" или "Женский" по имени получателя/заказчика.
   Если это не имя человека (Аренда, Доставка, название фирмы без ФИО) → "не применимо".
   Если имя неоднозначно (Саша, Женя) → null.

4. "ТГ ник" — telegram username в формате @username.
   Ищи в email, комментариях контрагента и заказов, поле Наименование. НЕ выдумывай.

5. "Теги" — одна строка с хэштегами через пробел: #nik1 #nik2 #nik3 (каждый с одним #, не массив JSON).
   Пример: #деньрождения #др_март #vip #проблемный #доволен
   Определи по датам заказов (праздники), сумме, комментариям контрагента и заказов, тону коммуникации.
   Теги: события (8марта, деньрождения, др_<месяц>, свадьба), настроение (доволен/недоволен), проблемный, постоянный, vip.
   Если известен месяц ДР/события — добавь #др_март / #событие_июль.

6. "Саммари" — 2–4 предложения на русском о МОТИВАЦИИ покупки (intent), а не о профиле клиента.
   НЕ пиши «постоянный клиент», «высокий средний чек», «настроение не определено» — это уже в других полях.
   ГЛАВНЫЙ ИСТОЧНИК ПАТТЕРНОВ — ИСТОРИЯ ЗАКАЗОВ (orders_sample + order_marketing_patterns):
   даты, суммы, каналы, позиции, комментарии к заказам. Переписка — дополнение, не замена.
   По смыслу (связный текст, не маркеры «События:» / «Intent:» / «Маркетинг:»):
   - событие + КОГДА (день+месяц или месяц; годы повторов);
   - INTENT: подарок (кому), для себя, романтика, корпоратив, свадьба, сезон;
   - предпочтения из позиций/комментов при наличии.
   Если повод неясен — так и скажи коротко, без дампа полей.

7. "Саммари клиента" — 4–7 предложений: профиль и ИСТОРИЯ клиента в CRM (не рекомендация оператору).
   Связный рассказ: кто клиент (имя), лояльность/VIP/число заказов/средний чек, канал,
   сезонность или календарь поводов, предпочтения, тон переписки если есть.
   Не дублируй «Рекомендацию».

8. "Фамилия (для ИП и физ. лиц)", "Имя (для ИП и физ. лиц)", "Отчество (для ИП и физ. лиц)" —
   заполни из ФИО заказчика/получателя, если явно указаны в данных или комментариях.

9. "E-mail" — только если явно есть в комментариях или полях клиента.

10. "Дата рождения" — только если явно указана (формат ДД.ММ.ГГГГ или ДД.ММ).
    Если в тексте только месяц — не выдумывай день; месяц отрази в «Саммари»/тегах.

11. Если есть messages_sample (WhatsApp/Telegram) — извлекай:
    поводы и даты, предпочтения по цветам/доставке/оплате, жалобы, благодарности, имена получателей.
    Указывай в references канал (whatsapp/telegram).

12. Для каждого поля из empty_fields — попробуй заполнить по данным клиента и заказов.
    Адреса, ИНН/КПП/ОГРН/ОКПО, банковские реквизиты (БИК, Банк, К/с, Р/с), тип контрагента,
    полное наименование, местонахождение, комментарии, статус, канал продаж — ТОЛЬКО при явном
    указании в данных. Не выдумывай юридические и банковские реквизиты.

13. "Рекомендация" — ГОТОВЫЙ МАРКЕТИНГОВЫЙ БРИФ (не эссе). Всегда с датой/праздником.
    Формат: Касание (окно дат + повод) → Оффер (что + бюджет) → Контекст
    (когда купил, зачем, чек выше/ниже среднего по peer_benchmarks/похожим) → Канал.
    Первый заказ / мало данных: блок «По похожим клиентам…» обязателен
    (тот же праздник/месяц/канал из peer_benchmarks или календарь РФ).
    Без даты/праздника и без оффера — ответ считается плохим.
""" + AI_NARRATIVE_STYLE + """
Дополнительно в reasoning укажи источник данных (поле, заказ или переписка).

ВАЖНО:
- Опирайся ТОЛЬКО на данные. Если сигнала нет — ставь null, не фантазируй.
- reasoning — 1 короткое предложение на русском с указанием источника.
- references — объект: поле → откуда взято (например {"Пол": "имя в комментарии заказа №123"}).
- Верни СТРОГО JSON-объект вида {"results": [...]}, где каждый элемент содержит ключи:
  uuid, "Группы", "Заказчик или получатель", "Пол", "ТГ ник", "Теги", "Саммари клиента", "Саммари", "Рекомендация",
  "Фамилия (для ИП и физ. лиц)", "Имя (для ИП и физ. лиц)", "Отчество (для ИП и физ. лиц)",
  "E-mail", "Дата рождения",
  а также любые поля из empty_fields клиента, если удалось определить значение,
  reasoning, confidence, references
  confidence — число от 0 до 1."""

GENDER_CONFIRM_SYSTEM_PROMPT = """Ты определяешь пол человека по ФИО или имени из CRM цветочного магазина.
Игнорируй префиксы ИП, ООО, ОАО, ЗАО — смотри на cleaned_name (имя/фамилия физлица).
Ролевые подписи без ФИО: «Покупатель с улицы» → Мужской (мужской род слова «покупатель»).
Форматы: «Фамилия Имя», «Имя Фамилия», «Имя», русские и иностранные имена (латиница, Vladislav Koroteev).
Учитывай heuristic_guess как подсказку, но исправь если уверен в другом значении.
Верни СТРОГО JSON {"results": [{"name": "исходное имя как во входе", "Пол": "Мужской"|"Женский"|"не применимо"|null}]}.
«не применимо» — для услуг (Аренда, Доставка), организаций и ярлыков без ФИО.
null — только для неоднозначных имён (Саша, Женя без фамилии)."""

_PHONE_RE = re.compile(r"^[\+\d\s\(\)\-]{6,}$")


def _compact_row(row: dict[str, Any], peer_benchmarks: dict[str, Any] | None = None) -> dict[str, Any]:
    skip = {
        "_orders_context",
        "_orders_count",
        "_reasoning",
        "_ai_processed",
        "_messenger_context",
        "_peer_benchmarks",
    }
    compact = {
        k: v
        for k, v in row.items()
        if k not in skip and v is not None and not str(k).startswith("_")
    }
    orders = row.get("_orders_context") or []
    if orders:
        # История заказов — основа маркетинговых паттернов (даты/поводы/бюджет).
        compact["orders_sample"] = orders[:20]
        patterns = SegmentationService.build_order_marketing_patterns(row)
        if patterns:
            compact["order_marketing_patterns"] = patterns
    if row.get("_orders_count"):
        compact["orders_count_matched"] = row["_orders_count"]
    if row.get("_messenger_context"):
        compact["messages_sample"] = row["_messenger_context"][-20:]
        compact["messages_count"] = len(row["_messenger_context"])
    comments = collect_client_comments(row)
    if comments:
        compact["all_comments"] = comments[:3000]
    peers = peer_benchmarks or row.get("_peer_benchmarks")
    if peers:
        compact["peer_benchmarks"] = peers
        hint = SegmentationService._peer_hint_for_row(row, peers)
        if hint:
            compact["similar_clients_hint"] = hint
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
                    gender_analysis_payload(name, heuristic_map)
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
        peers = self.build_peer_benchmarks(rows)
        for row in rows:
            row["_peer_benchmarks"] = peers
        payload_rows = [
            {
                "uuid": self._row_key(row),
                "current": {col: row.get(col) for col in AI_COLUMNS},
                "empty_fields": empty_fillable_columns(row),
                "data": _compact_row(row, peers),
            }
            for row in rows
        ]
        user_prompt = (
            "Проанализируй клиентов и заполни поля сегментации. "
            "Поле «Рекомендация» — маркетинговый бриф: Касание (даты+праздник), "
            "Оффер+бюджет, Контекст (когда/зачем купил, чек vs средний), Канал; "
            "для 1-го заказа обязательно блок «по похожим» из peer_benchmarks. "
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
            client_summary = ai.get("Саммари клиента") or ai.get("client_summary")
            if client_summary not in (None, "", "null"):
                apply_ai_client_summary(merged, client_summary)
            elif not merged.get("_ai_client_summary"):
                hist = build_client_history_summary(merged)
                if hist:
                    merged["_ai_client_summary"] = hist
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

        if not merged.get("_ai_client_summary"):
            hist = build_client_history_summary(merged)
            if hist:
                merged["_ai_client_summary"] = hist

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
        return normalize_tags_field(" ".join(dict.fromkeys(tags))) if tags else None

    _EVENT_HINTS: tuple[tuple[tuple[str, ...], str], ...] = (
        (("день рождения", "д.р.", "др ", "др.", "birthday"), "день рождения"),
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

    _PREF_HINTS: tuple[tuple[tuple[str, ...], str], ...] = (
        (("эквайринг", "оплата по эквайринг"), "оплата эквайрингом"),
        (("перевод на карт", "на карту", "сбер"), "оплата переводом на карту"),
        (("к 18", "к 19", "к 20", "к 21", "точн"), "доставка к точному времени"),
        (("роз", "пиону", "пион", "тюльпан", "гортенз", "фрези"), "предпочтения по цветам из заказов"),
    )

    _MONTHS_GENITIVE = (
        "",
        "января",
        "февраля",
        "марта",
        "апреля",
        "мая",
        "июня",
        "июля",
        "августа",
        "сентября",
        "октября",
        "ноября",
        "декабря",
    )
    _MONTHS_PREPOSITIONAL = (
        "",
        "январе",
        "феврале",
        "марте",
        "апреле",
        "мае",
        "июне",
        "июле",
        "августе",
        "сентябре",
        "октябре",
        "ноябре",
        "декабре",
    )
    _MONTH_NAME_TO_NUM = {
        "январ": 1,
        "феврал": 2,
        "март": 3,
        "апрел": 4,
        "ма": 5,
        "июн": 6,
        "июл": 7,
        "август": 8,
        "сентябр": 9,
        "октябр": 10,
        "ноябр": 11,
        "декабр": 12,
    }
    _DATE_IN_TEXT_RE = re.compile(
        r"(?P<d>\d{1,2})[./-](?P<m>\d{1,2})(?:[./-](?P<y>\d{2,4}))?"
    )
    _OCCASION_IN_ORDER_HINTS: tuple[tuple[tuple[str, ...], str], ...] = (
        (("невест", "свадьб", "бракосочет"), "свадьба"),
        (("новогод", "ёлк", "елк", "амариллис", "корпоратив"), "Новый год / корпоратив"),
        (("8 марта", "8марта", "международн"), "8 марта"),
        (("день рождения", "др ", "др.", "birthday"), "день рождения"),
        (("валентин", "14 февраля"), "14 февраля"),
        (("23 февраля", "день защитника", "защитника отечества"), "23 февраля"),
        (("день матери", "днём матери"), "День матери"),
        (("день учителя", "учителю", "учительниц"), "День учителя"),
        (("1 сентября", "день знаний", "линейк"), "1 сентября"),
        (("годовщин",), "годовщина"),
        (("маме", "матери", "мамочк"), "подарок маме"),
    )
    # Российские праздники, когда дарят цветы: (месяц, день|None, название, окно касания, дней до праздника для матчинга заказа).
    # day=None → окно по месяцу / вычисляемая дата (День матери).
    _RU_FLOWER_HOLIDAYS: tuple[tuple[int, int | None, str, str, int], ...] = (
        (2, 14, "14 февраля (День святого Валентина)", "5–12 февраля", 12),
        (2, 23, "23 февраля (День защитника Отечества)", "16–22 февраля", 10),
        (3, 8, "8 марта (Международный женский день)", "1–5 марта", 14),
        (5, 9, "9 мая (День Победы)", "4–8 мая", 7),
        (9, 1, "1 сентября (День знаний)", "25 августа – 1 сентября", 10),
        (10, 5, "5 октября (День учителя)", "28 сентября – 4 октября", 10),
        (11, None, "День матери (последнее воскресенье ноября)", "за 5–7 дней до Дня матери", 10),
        (12, 31, "Новый год / корпоратив", "25 ноября – 20 декабря", 40),
    )

    @classmethod
    def _order_ymd(cls, order: dict[str, Any]) -> tuple[int | None, int | None, int | None]:
        raw = str(order.get("Дата") or order.get("Момент времени") or "").strip()
        if not raw:
            return None, None, None
        iso = re.search(r"(\d{4})-(\d{2})-(\d{2})", raw)
        if iso:
            return int(iso.group(1)), int(iso.group(2)), int(iso.group(3))
        match = cls._DATE_IN_TEXT_RE.search(raw)
        if not match:
            return None, None, None
        day = int(match.group("d"))
        month = int(match.group("m"))
        year_raw = match.group("y")
        year = int(year_raw) if year_raw else None
        if year is not None and year < 100:
            year += 2000
        if not (1 <= month <= 12 and 1 <= day <= 31):
            return None, None, None
        return year, month, day

    @classmethod
    def _mother_day_date(cls, year: int) -> tuple[int, int]:
        """День матери в РФ — последнее воскресенье ноября."""
        from datetime import date, timedelta

        d = date(year, 11, 30)
        while d.weekday() != 6:  # Sunday
            d -= timedelta(days=1)
        return d.month, d.day

    @classmethod
    def _holiday_for_order_date(
        cls,
        year: int | None,
        month: int,
        day: int | None,
    ) -> dict[str, Any] | None:
        """Если заказ перед/в день праздника цветов РФ — вернуть повод и окно касания."""
        from datetime import date

        if not day:
            # Только месяц: грубые эвристики
            for h_month, h_day, name, touch, _lead in cls._RU_FLOWER_HOLIDAYS:
                if month == h_month and h_day is not None:
                    return {"occasion": name, "marketing_touch_window": touch, "holiday_month": h_month, "holiday_day": h_day}
                if month == 11 and h_day is None:
                    return {"occasion": name, "marketing_touch_window": touch, "holiday_month": 11, "holiday_day": None}
            return None

        y = year or date.today().year
        try:
            order_dt = date(y, month, day)
        except ValueError:
            return None

        best: dict[str, Any] | None = None
        best_delta: int | None = None
        for h_month, h_day, name, touch, lead_days in cls._RU_FLOWER_HOLIDAYS:
            if h_day is None:
                # День матери
                if year:
                    hm, hd = cls._mother_day_date(year)
                else:
                    hm, hd = cls._mother_day_date(y)
            else:
                hm, hd = h_month, h_day
            try:
                holiday_dt = date(y, hm, hd)
            except ValueError:
                continue
            # Заказ в том же сезоне: за lead_days до праздника или в день праздника (+1)
            delta = (holiday_dt - order_dt).days
            if delta < -1:
                # заказ после праздника в этом году — смотрим следующий год
                try:
                    if h_day is None:
                        hm2, hd2 = cls._mother_day_date(y + 1)
                        holiday_dt = date(y + 1, hm2, hd2)
                    else:
                        holiday_dt = date(y + 1, hm, hd)
                    delta = (holiday_dt - order_dt).days
                except ValueError:
                    continue
            if -1 <= delta <= lead_days:
                if best_delta is None or delta < best_delta:
                    best_delta = delta
                    best = {
                        "occasion": name,
                        "marketing_touch_window": touch,
                        "holiday_month": hm,
                        "holiday_day": hd,
                        "days_before_holiday": delta,
                    }
        return best

    @classmethod
    def _offer_style_for_row(cls, row: dict[str, Any], occasion: str | None = None) -> str:
        """Что предложить: предпочтения / реальный чек / типовой оффер под праздник РФ."""
        prefs = cls._preference_labels(row)
        if prefs:
            return prefs[0]
        try:
            avg = float(row.get("Средний чек") or 0)
        except (TypeError, ValueError):
            avg = 0.0
        if avg >= 5000:
            return f"букет в бюджете ~{int(avg)} р."

        occ = (occasion or "").lower()
        if "8 марта" in occ or "женск" in occ:
            return "весенний букет к 8 марта (тюльпаны / фрезия / микс)"
        if "14 февраля" in occ or "валентин" in occ:
            return "романтический букет к 14 февраля"
        if "23 февраля" in occ:
            return "композиция / букет к 23 февраля"
        if "матери" in occ:
            return "букет ко Дню матери"
        if "учител" in occ:
            return "букет ко Дню учителя"
        if "1 сентября" in occ or "знаний" in occ:
            return "школьный букет к 1 сентября"
        if "новый год" in occ or "корпоратив" in occ:
            return "новогодняя / корпоративная композиция"
        if "свадьб" in occ:
            return "букет / композиция на свадьбу"
        return "сезонный букет под ближайший праздник"

    @classmethod
    def _orders_count(cls, row: dict[str, Any]) -> int:
        try:
            return int(row.get("Всего заказов") or row.get("_orders_count") or 0)
        except (TypeError, ValueError):
            ctx = row.get("_orders_context") or []
            return len(ctx) if ctx else 0

    @classmethod
    def build_order_marketing_patterns(cls, row: dict[str, Any]) -> list[dict[str, Any]]:
        """Паттерны из истории заказов: когда и на какую оказию заказывают (маркетинг)."""
        from collections import Counter, defaultdict

        orders = row.get("_orders_context") or []
        if not orders:
            return []

        by_month: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for order in orders:
            year, month, day = cls._order_ymd(order)
            if not month:
                continue
            amount = order.get("Сумма")
            try:
                amount_f = float(amount) if amount not in (None, "") else None
            except (TypeError, ValueError):
                amount_f = None
            text = " ".join(
                str(order.get(k) or "")
                for k in ("Комментарий", "Описание", "Позиции", "Статус")
            ).lower()
            occasion = None
            for keywords, label in cls._OCCASION_IN_ORDER_HINTS:
                if any(k in text for k in keywords):
                    occasion = label
                    break
            # Заказ перед важным праздником цветов в РФ (даже без текста в комментарии).
            holiday = cls._holiday_for_order_date(year, month, day)
            touch_from_holiday = holiday.get("marketing_touch_window") if holiday else None
            if occasion is None and holiday:
                occasion = str(holiday["occasion"])
            by_month[month].append(
                {
                    "year": year,
                    "day": day,
                    "amount": amount_f,
                    "occasion": occasion,
                    "touch": touch_from_holiday,
                    "channel": str(order.get("Канал продаж") or "").strip() or None,
                    "positions": str(order.get("Позиции") or "").strip()[:120] or None,
                    "comment": str(order.get("Комментарий") or "").strip()[:160] or None,
                }
            )

        patterns: list[dict[str, Any]] = []
        for month in sorted(by_month.keys()):
            items = by_month[month]
            years = sorted({i["year"] for i in items if i.get("year")})
            occasions = [i["occasion"] for i in items if i.get("occasion")]
            occasion = None
            if occasions:
                occasion = Counter(occasions).most_common(1)[0][0]
            amounts = [i["amount"] for i in items if i.get("amount") is not None]
            avg_amount = int(round(sum(amounts) / len(amounts))) if amounts else None
            recurrent = len(years) >= 2
            prev_month = 12 if month == 1 else month - 1
            touch_from_items = next((i.get("touch") for i in items if i.get("touch")), None)
            if touch_from_items:
                touch = touch_from_items
            elif occasion and "8 марта" in occasion:
                touch = "1–5 марта"
            elif occasion and "14 февраля" in occasion:
                touch = "5–12 февраля"
            elif occasion and "23 февраля" in occasion:
                touch = "16–22 февраля"
            elif occasion and "День матери" in occasion:
                touch = "за 5–7 дней до Дня матери (конец ноября)"
            elif occasion and "День учителя" in occasion:
                touch = "28 сентября – 4 октября"
            elif occasion and "1 сентября" in occasion:
                touch = "25 августа – 1 сентября"
            elif occasion and "Новый год" in occasion:
                touch = "25 ноября – 20 декабря"
            else:
                touch = (
                    f"конец {cls._MONTHS_GENITIVE[prev_month]} / "
                    f"начало {cls._MONTHS_PREPOSITIONAL[month]}"
                )
            label = occasion or f"сезон {cls._MONTHS_GENITIVE[month]}"
            if recurrent:
                years_txt = ", ".join(str(y) for y in years)
                summary = (
                    f"{label} — ежегодно в {cls._MONTHS_PREPOSITIONAL[month]} "
                    f"({years_txt}, {len(items)} заказ.)"
                )
            else:
                years_txt = ", ".join(str(y) for y in years) if years else "год н/д"
                summary = (
                    f"{label} — {cls._MONTHS_GENITIVE[month]} "
                    f"({years_txt}, {len(items)} заказ.)"
                )
            patterns.append(
                {
                    "month": month,
                    "month_name": cls._MONTHS_GENITIVE[month],
                    "years": years,
                    "orders_in_month": len(items),
                    "recurrent_yearly": recurrent,
                    "occasion": label,
                    "avg_check": avg_amount,
                    "marketing_touch_window": touch,
                    "summary": summary,
                    "sample_positions": next(
                        (i["positions"] for i in items if i.get("positions")), None
                    ),
                    "sample_comment": next(
                        (i["comment"] for i in items if i.get("comment")), None
                    ),
                }
            )

        # Приоритет: ежегодные и «праздничные» месяцы сверху.
        patterns.sort(
            key=lambda p: (
                0 if p.get("recurrent_yearly") else 1,
                0 if p.get("occasion") and "сезон" not in str(p.get("occasion")) else 1,
                -int(p.get("orders_in_month") or 0),
            )
        )
        return patterns

    @classmethod
    def _collect_intent_text(cls, row: dict[str, Any]) -> str:
        parts = [collect_client_comments(row).lower()]
        for msg in row.get("_messenger_context") or []:
            parts.append(str(msg.get("text") or "").lower())
        for key in ("Группы", "Теги", "Саммари", "Дата рождения"):
            val = row.get(key)
            if val:
                parts.append(str(val).lower())
        return " ".join(parts)

    @classmethod
    def _parse_month_day_from_text(cls, text: str) -> tuple[int | None, int | None]:
        match = cls._DATE_IN_TEXT_RE.search(text or "")
        if match:
            day = int(match.group("d"))
            month = int(match.group("m"))
            if 1 <= month <= 12 and 1 <= day <= 31:
                return month, day
        lowered = (text or "").lower()
        for stem, month in cls._MONTH_NAME_TO_NUM.items():
            if stem == "ма":
                if re.search(r"\bмая\b|\bмай\b|\bмае\b", lowered):
                    return month, None
                continue
            if stem in lowered:
                return month, None
        return None, None

    @classmethod
    def _month_from_order_dates(cls, row: dict[str, Any]) -> int | None:
        """Частый месяц заказов (если один доминирует) — кандидат месяца события."""
        months: list[int] = []
        for order in row.get("_orders_context") or []:
            raw = str(order.get("Дата") or order.get("Момент времени") or "")
            dt_month, _ = cls._parse_month_day_from_text(raw)
            if dt_month:
                months.append(dt_month)
                continue
            # ISO / YYYY-MM-DD
            iso = re.search(r"(\d{4})-(\d{2})-(\d{2})", raw)
            if iso:
                months.append(int(iso.group(2)))
        if not months:
            return None
        from collections import Counter

        month, count = Counter(months).most_common(1)[0]
        if count >= 2 or len(months) == 1:
            return month
        return None

    @classmethod
    def _dated_event_labels(cls, row: dict[str, Any]) -> list[str]:
        """События с календарной привязкой (месяц/день), без «голых» ярлыков."""
        text = cls._collect_intent_text(row)
        labels: list[str] = []
        birthday_date = str(row.get("Дата рождения") or "").strip()
        b_month, b_day = cls._parse_month_day_from_text(birthday_date)
        order_month = cls._month_from_order_dates(row)

        for keywords, label in cls._EVENT_HINTS:
            if not any(k in text for k in keywords):
                continue
            if label == "8 марта":
                labels.append("8 марта")
                continue
            if label == "14 февраля":
                labels.append("14 февраля")
                continue
            if label == "1 сентября":
                labels.append("1 сентября")
                continue
            if label == "Новый год":
                labels.append("Новый год (декабрь)")
                continue
            if label == "день рождения":
                month, day = b_month, b_day
                if month is None:
                    # дата рядом с упоминанием ДР в тексте
                    for chunk in re.split(r"[.;\n]", text):
                        if any(k in chunk for k in keywords):
                            month, day = cls._parse_month_day_from_text(chunk)
                            if month:
                                break
                if month is None:
                    month = order_month
                if month and day:
                    labels.append(f"день рождения — {day} {cls._MONTHS_GENITIVE[month]}")
                elif month:
                    labels.append(
                        f"день рождения — {cls._MONTHS_GENITIVE[month]} "
                        f"(день не найден в данных)"
                    )
                else:
                    labels.append("день рождения — месяц не найден в данных")
                continue
            # свадьба / годовщина / др. — месяц из текста или заказов
            month, day = cls._parse_month_day_from_text(text)
            if month is None:
                month = order_month
            if month and day:
                labels.append(f"{label} — {day} {cls._MONTHS_GENITIVE[month]}")
            elif month:
                labels.append(f"{label} — {cls._MONTHS_GENITIVE[month]}")
            else:
                labels.append(f"{label} — месяц не найден в данных")

        # Сегмент вида «событие марта»
        groups = str(row.get("Группы") or "").lower()
        for stem, month in cls._MONTH_NAME_TO_NUM.items():
            if stem == "ма":
                pattern = r"событие\s+мая\b"
            else:
                pattern = rf"событие\s+{stem}"
            if re.search(pattern, groups):
                label = f"событие — {cls._MONTHS_GENITIVE[month]}"
                if label not in labels and not any("событие —" in x for x in labels):
                    labels.append(label)

        # История заказов: паттерны по месяцам / повторам лет.
        for pattern in cls.build_order_marketing_patterns(row):
            summary = str(pattern.get("summary") or "").strip()
            if summary:
                labels.append(summary)

        return list(dict.fromkeys(labels))

    @classmethod
    def _preference_labels(cls, row: dict[str, Any]) -> list[str]:
        text = cls._collect_intent_text(row)
        for order in row.get("_orders_context") or []:
            text += " " + str(order.get("Позиции") or "").lower()
            text += " " + str(order.get("Комментарий") or "").lower()
        prefs: list[str] = []
        for keywords, label in cls._PREF_HINTS:
            if any(k in text for k in keywords):
                prefs.append(label)
        return list(dict.fromkeys(prefs))

    @classmethod
    def _heuristic_intent_summary(cls, row: dict[str, Any]) -> str | None:
        """Саммари: события с календарём, intent и предпочтения."""
        text = cls._collect_intent_text(row)
        has_orders = bool(row.get("_orders_context") or row.get("_messenger_context"))
        if not text.strip() and not has_orders:
            return None

        events = cls._dated_event_labels(row)
        order_patterns = cls.build_order_marketing_patterns(row)
        intents: list[str] = []
        for keywords, label in cls._INTENT_HINTS:
            if any(k in text for k in keywords):
                intents.append(label)
        for pattern in order_patterns:
            occ = str(pattern.get("occasion") or "")
            if "свадьба" in occ.lower():
                intents.append("подарок на свадьбу")
            if "корпоратив" in occ.lower() or "Новый год" in occ:
                intents.append("корпоративный / праздничный заказ")
            if "8 марта" in occ:
                intents.append("подарок к 8 марта")
        prefs = cls._preference_labels(row)

        parts: list[str] = []
        if events:
            parts.append(
                "Покупки связаны с поводами: "
                + "; ".join(events[:6])
                + "."
            )
        if intents:
            parts.append(
                "Мотивация: " + ", ".join(dict.fromkeys(intents)) + "."
            )
        if prefs:
            parts.append("Предпочтения: " + ", ".join(prefs) + ".")
        marketing_windows = [
            f"{p['occasion']} — касание {p['marketing_touch_window']}"
            + (f", ориентир чека ~{p['avg_check']} р." if p.get("avg_check") else "")
            for p in order_patterns[:4]
            if p.get("marketing_touch_window")
        ]
        if marketing_windows:
            parts.append(
                "Сезонность и окна касания: " + "; ".join(marketing_windows) + "."
            )

        recipient = row.get("Заказчик или получатель")
        if recipient and str(recipient).strip() and not _PHONE_RE.match(str(recipient).strip()):
            parts.append(f"Получатель/роль: {recipient}.")

        if parts:
            return " ".join(parts)
        if has_orders:
            return "Повод покупки не определён из истории заказов, комментариев и переписки."
        return None

    @classmethod
    def _offer_window_for_month(cls, month: int | None, day: int | None = None) -> str:
        if not month:
            return "уточнить точную дату события, затем поставить касание за 5–7 дней"
        month_prep = cls._MONTHS_PREPOSITIONAL[month]
        prev_month = 12 if month == 1 else month - 1
        if day:
            return (
                f"касание в конце {cls._MONTHS_GENITIVE[prev_month]} "
                f"или за 5–7 дней до {day} {cls._MONTHS_GENITIVE[month]}"
            )
        return f"касание в конце {cls._MONTHS_GENITIVE[prev_month]} / в начале {month_prep}"

    @classmethod
    def _median(cls, values: list[float]) -> float | None:
        if not values:
            return None
        ordered = sorted(values)
        mid = len(ordered) // 2
        if len(ordered) % 2:
            return ordered[mid]
        return (ordered[mid - 1] + ordered[mid]) / 2

    @classmethod
    def _client_check_amount(cls, row: dict[str, Any]) -> float | None:
        for key in ("Средний чек",):
            raw = row.get(key)
            if raw in (None, "", "—", 0, "0"):
                continue
            try:
                val = float(raw)
            except (TypeError, ValueError):
                continue
            if val > 0:
                return val
        amounts: list[float] = []
        for order in row.get("_orders_context") or []:
            try:
                amount = float(order.get("Сумма") or 0)
            except (TypeError, ValueError):
                continue
            if amount > 0:
                amounts.append(amount)
        return cls._median(amounts)

    @classmethod
    def _default_store_avg(cls) -> float:
        return 5500.0

    @classmethod
    def build_peer_benchmarks(cls, rows: list[dict[str, Any]]) -> dict[str, Any]:
        """Медианы чеков по магазину / каналу / поводу — для сравнения и «похожих»."""
        from collections import defaultdict

        store: list[float] = []
        by_channel: dict[str, list[float]] = defaultdict(list)
        by_occasion: dict[str, list[float]] = defaultdict(list)
        occasion_touch: dict[str, str] = {}

        for row in rows:
            amount = cls._client_check_amount(row)
            if amount is None:
                continue
            store.append(amount)
            channel = str(
                row.get("Канал продаж")
                or row.get("Тип канала продаж")
                or row.get("Тип продаж")
                or "без канала"
            ).strip() or "без канала"
            by_channel[channel].append(amount)

            for order in (row.get("_orders_context") or [])[:5]:
                year, month, day = cls._order_ymd(order)
                if not month:
                    continue
                holiday = cls._holiday_for_order_date(year, month, day)
                if not holiday:
                    continue
                occ = str(holiday["occasion"])
                try:
                    order_amount = float(order.get("Сумма") or amount)
                except (TypeError, ValueError):
                    order_amount = amount
                by_occasion[occ].append(order_amount)
                touch = str(holiday.get("marketing_touch_window") or "")
                if touch:
                    occasion_touch[occ] = touch

        store_avg = cls._median(store) or cls._default_store_avg()
        return {
            "store_median_check": int(store_avg),
            "by_channel": {
                ch: int(med)
                for ch, vals in by_channel.items()
                if (med := cls._median(vals)) is not None and len(vals) >= 1
            },
            "by_holiday_occasion": {
                occ: {
                    "median_check": int(med),
                    "sample_size": len(vals),
                    "typical_touch_window": occasion_touch.get(occ),
                }
                for occ, vals in by_occasion.items()
                if (med := cls._median(vals)) is not None
            },
        }

    @classmethod
    def _benchmark_for_row(
        cls, row: dict[str, Any], peers: dict[str, Any] | None = None
    ) -> tuple[float, str]:
        peers = peers or row.get("_peer_benchmarks") or {}
        channel = str(
            row.get("Канал продаж")
            or row.get("Тип канала продаж")
            or row.get("Тип продаж")
            or ""
        ).strip()
        by_channel = peers.get("by_channel") or {}
        if channel and channel in by_channel:
            return float(by_channel[channel]), f"по каналу «{channel}»"

        # Повод первого/последнего заказа
        for order in (row.get("_orders_context") or [])[:3]:
            year, month, day = cls._order_ymd(order)
            if not month:
                continue
            holiday = cls._holiday_for_order_date(year, month, day)
            if not holiday:
                continue
            occ = str(holiday["occasion"])
            by_occ = (peers.get("by_holiday_occasion") or {}).get(occ) or {}
            if by_occ.get("median_check"):
                return float(by_occ["median_check"]), f"по похожим к «{occ}»"

        store = peers.get("store_median_check")
        if store:
            return float(store), "по магазину"
        return cls._default_store_avg(), "по магазину (типичный ориентир)"

    @classmethod
    def _check_vs_average_line(
        cls, row: dict[str, Any], peers: dict[str, Any] | None = None
    ) -> str:
        amount = cls._client_check_amount(row)
        bench, label = cls._benchmark_for_row(row, peers)
        if amount is None:
            return f"чек неизвестен; ориентир {label} ~{int(bench)} р."
        diff = amount - bench
        if abs(diff) / bench <= 0.12:
            cmp = "около среднего"
        elif diff > 0:
            cmp = "выше среднего"
        else:
            cmp = "ниже среднего"
        return f"чек {int(amount)} р. — {cmp} {label} (~{int(bench)} р.)"

    @classmethod
    def _peer_hint_for_row(
        cls, row: dict[str, Any], peers: dict[str, Any] | None = None
    ) -> str | None:
        peers = peers or row.get("_peer_benchmarks") or {}
        by_occ = peers.get("by_holiday_occasion") or {}
        for order in (row.get("_orders_context") or [])[:3]:
            year, month, day = cls._order_ymd(order)
            if not month:
                continue
            holiday = cls._holiday_for_order_date(year, month, day)
            if not holiday:
                continue
            occ = str(holiday["occasion"])
            meta = by_occ.get(occ) or {}
            touch = meta.get("typical_touch_window") or holiday.get("marketing_touch_window")
            med = meta.get("median_check")
            n = meta.get("sample_size")
            parts = [f"похожие с заказом к «{occ}»"]
            if n:
                parts.append(f"n≈{n}")
            if touch:
                parts.append(f"касание {touch}")
            if med:
                parts.append(f"типичный чек ~{int(med)} р.")
            return "; ".join(parts)
        channel = str(row.get("Канал продаж") or "").strip()
        by_ch = peers.get("by_channel") or {}
        if channel and channel in by_ch:
            return f"похожие по каналу «{channel}»: типичный чек ~{by_ch[channel]} р."
        store = peers.get("store_median_check")
        if store:
            return f"похожее по магазину: медиана чека ~{store} р."
        return None

    @classmethod
    def _intent_one_liner(cls, row: dict[str, Any]) -> str:
        text = cls._collect_intent_text(row)
        for keywords, label in cls._INTENT_HINTS:
            if any(k in text for k in keywords):
                return label
        events = cls._dated_event_labels(row)
        if events:
            return events[0]
        for order in row.get("_orders_context") or []:
            year, month, day = cls._order_ymd(order)
            if not month:
                continue
            holiday = cls._holiday_for_order_date(year, month, day)
            if holiday:
                return str(holiday["occasion"])
        return "повод не указан"

    @classmethod
    def _last_purchase_line(cls, row: dict[str, Any]) -> str:
        orders = row.get("_orders_context") or []
        if not orders:
            last = row.get("Дата последнего заказа")
            if last:
                return f"последний заказ {str(last)[:10]}"
            return "история заказов пуста"
        order = orders[0]
        # берём самый свежий по дате если возможно
        best = order
        best_key = (0, 0, 0)
        for o in orders:
            y, m, d = cls._order_ymd(o)
            key = (y or 0, m or 0, d or 0)
            if key >= best_key:
                best_key = key
                best = o
        y, m, d = cls._order_ymd(best)
        date_s = (
            f"{d:02d}.{m:02d}.{y}" if y and m and d else str(best.get("Дата") or "")[:10] or "дата ?"
        )
        try:
            amount = float(best.get("Сумма") or 0)
            amount_s = f" на {int(amount)} р." if amount else ""
        except (TypeError, ValueError):
            amount_s = ""
        return f"купил {date_s}{amount_s}"

    @classmethod
    def _contact_channel(cls, row: dict[str, Any]) -> str:
        if row.get("ТГ ник"):
            return "Telegram"
        if row.get("Телефон"):
            return "WhatsApp"
        channel = str(row.get("Канал продаж") or "").strip()
        if channel:
            return channel
        return "телефон"

    @classmethod
    def _primary_touch_plan(
        cls, row: dict[str, Any]
    ) -> tuple[str, str, str]:
        """Вернуть (окно касания, повод, оффер). Всегда с праздником/датой."""
        text = f"{row.get('Теги') or ''} {row.get('Саммари') or ''} {cls._collect_intent_text(row)}".lower()
        events = cls._dated_event_labels(row)
        order_patterns = cls.build_order_marketing_patterns(row)

        # ДР с датой
        if any("день рождения" in e for e in events) or any(
            k in text for k in ("день рождения", "#деньрождения")
        ):
            month = day = None
            for label in events:
                if "день рождения" not in label:
                    continue
                month, day = cls._parse_month_day_from_text(label.replace("—", " "))
                break
            if month is None:
                month, day = cls._parse_month_day_from_text(str(row.get("Дата рождения") or ""))
            if month is None:
                month = cls._month_from_order_dates(row)
            window = cls._offer_window_for_month(month, day)
            if month and day:
                occ = f"ДР {day} {cls._MONTHS_GENITIVE[month]}"
            elif month:
                occ = f"ДР в {cls._MONTHS_PREPOSITIONAL[month]}"
            else:
                occ = "день рождения (уточнить дату)"
            return window, occ, cls._offer_style_for_row(row, "день рождения")

        if order_patterns:
            p = order_patterns[0]
            touch = str(p.get("marketing_touch_window") or "за 7–14 дней до повода")
            occ = str(p.get("occasion") or "сезонный повод")
            return touch, occ, cls._offer_style_for_row(row, occ)

        for order in (row.get("_orders_context") or [])[:3]:
            year, month, day = cls._order_ymd(order)
            if not month:
                continue
            holiday = cls._holiday_for_order_date(year, month, day)
            if holiday:
                return (
                    str(holiday["marketing_touch_window"]),
                    str(holiday["occasion"]),
                    cls._offer_style_for_row(row, str(holiday["occasion"])),
                )

        if "8 марта" in text or "событие марта" in text:
            return "1–5 марта", "8 марта", cls._offer_style_for_row(row, "8 марта")
        if "14 февраля" in text or "валентин" in text:
            return "5–12 февраля", "14 февраля", cls._offer_style_for_row(row, "14 февраля")

        # Ближайший сильный праздник РФ от сегодня / от последнего заказа
        from datetime import date

        today = date.today()
        upcoming: list[tuple[int, str, str]] = []
        for h_month, h_day, name, touch, _lead in cls._RU_FLOWER_HOLIDAYS:
            if h_day is None:
                hm, hd = cls._mother_day_date(today.year)
            else:
                hm, hd = h_month, h_day
            try:
                hdate = date(today.year, hm, hd)
            except ValueError:
                continue
            if hdate < today:
                try:
                    if h_day is None:
                        hm, hd = cls._mother_day_date(today.year + 1)
                        hdate = date(today.year + 1, hm, hd)
                    else:
                        hdate = date(today.year + 1, hm, hd)
                except ValueError:
                    continue
            upcoming.append(((hdate - today).days, name, touch))
        if upcoming:
            upcoming.sort()
            _days, name, touch = upcoming[0]
            return touch, name, cls._offer_style_for_row(row, name)
        return "1–5 марта", "8 марта", cls._offer_style_for_row(row, "8 марта")

    @classmethod
    def _first_order_holiday_hints(cls, row: dict[str, Any], contact: str) -> list[str]:
        """Для 0–1 заказа: проверить близость к праздникам цветов в РФ."""
        hints: list[str] = []
        orders = row.get("_orders_context") or []
        for order in orders[:3]:
            year, month, day = cls._order_ymd(order)
            if not month:
                continue
            holiday = cls._holiday_for_order_date(year, month, day)
            if not holiday:
                continue
            occ = str(holiday["occasion"])
            touch = str(holiday["marketing_touch_window"])
            offer = cls._offer_style_for_row(row, occ)
            amount = order.get("Сумма")
            try:
                amount_f = float(amount) if amount not in (None, "") else None
            except (TypeError, ValueError):
                amount_f = None
            budget = f", ориентир по первому заказу ~{int(amount_f)} р." if amount_f else ""
            days = holiday.get("days_before_holiday")
            when = (
                f"заказ за {days} дн. до праздника"
                if isinstance(days, int) and days >= 0
                else "заказ рядом с праздником"
            )
            hints.append(
                f"Первый заказ похож на «{occ}» ({when}). "
                f"Следующее касание: {touch} через {contact} — предложить {offer}{budget}."
            )
        return hints

    @classmethod
    def _heuristic_recommendation(cls, row: dict[str, Any]) -> str | None:
        """Маркетинговый бриф: касание, оффер, контекст, похожие, канал."""
        peers = row.get("_peer_benchmarks") if isinstance(row.get("_peer_benchmarks"), dict) else None
        orders_n = cls._orders_count(row)
        contact = cls._contact_channel(row)
        touch, occasion, offer = cls._primary_touch_plan(row)
        check_line = cls._check_vs_average_line(row, peers)
        purchase = cls._last_purchase_line(row)
        intent = cls._intent_one_liner(row)
        amount = cls._client_check_amount(row)
        budget = f" ~{int(amount)} р." if amount else ""

        lines = [
            f"Касание: {touch} (к {occasion}).",
            f"Оффер: {offer}{budget}.",
            f"Контекст: {purchase}, цель — {intent}; {check_line}.",
        ]

        if orders_n <= 1:
            peer_hint = cls._peer_hint_for_row(row, peers)
            first_bits = cls._first_order_holiday_hints(row, contact)
            if peer_hint:
                lines.append(f"По похожим: {peer_hint}.")
            elif first_bits:
                # вытащить суть первого хинта без простыни
                lines.append(
                    f"По похожим: первый заказ к «{occasion}» — повторить касание "
                    f"в окне «{touch}», бюджет как в первом заказе{budget or ''}."
                )
            else:
                lines.append(
                    f"По похожим с первым заказом: обычно закрывают ближайший праздник цветов "
                    f"(«{occasion}») касанием «{touch}», оффер в том же бюджете."
                )
            if first_bits and "Первый заказ" not in " ".join(lines):
                lines[2] = lines[2].rstrip(".") + f"; Первый заказ под «{occasion}»."
            elif not first_bits and "Первый заказ" not in " ".join(lines):
                lines.append(f"Первый заказ / мало истории — опираемся на похожих и календарь «{occasion}».")

        if row.get("ВИП") == "да" or "#vip" in str(row.get("Теги") or "").lower():
            lines.append("VIP: персональный подбор и приоритетная доставка.")
        if "#проблемный" in str(row.get("Теги") or "").lower():
            lines.append("Учесть прошлый негатив: личный контакт перед оффером.")

        lines.append(f"Канал: {contact}.")
        return "\n".join(lines)

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
