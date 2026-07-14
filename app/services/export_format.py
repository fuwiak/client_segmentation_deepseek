"""Колонки экспорта и форматирование строк под Excel-шаблон."""

from __future__ import annotations

import re
from collections import Counter
from datetime import datetime
from typing import Any
from urllib.parse import quote, urlencode

from app.services.telegram_export import tg_conversation_label
from app.services.fields import (
    AI_NO_DATA_LABEL,
    is_empty_cell,
    refresh_row_for_display,
    unique_sales_channel_types,
    unique_sales_channels,
)

from app.services.excel_parser import (
    AI_EXTRA_COLUMNS,
    AI_FILLABLE_COLUMNS,
    CLIENT_DISPLAY_COLUMNS,
    CLIENT_TABLE_COLUMNS,
    SEGMENT_COLUMNS,
    ParsedWorkbook,
)

AI_RUNNING_LABEL = "running"

_NUMERIC_SORT_COLUMNS = frozenset({"Средний чек", "Всего заказов", "Баллы начисленные"})
_DATE_SORT_COLUMNS = frozenset({"Дата последнего заказа"})
_KEYWORD_SEARCH_EXTRA_KEYS = ("Теги", "Комментарий", "Саммари")

# Колонки как в Excel-выгрузке контрагентов из Мой Склад (online.moysklad.ru)
MOYSKLAD_EXCEL_COLUMNS = list(CLIENT_TABLE_COLUMNS)

# AI-поля, которые дополняются при экспорте
MOYSKLAD_AI_EXPORT_COLUMNS = [
    "Заказчик или получатель",
    "ТГ ник",
    "Ник в тг/вк",
    *AI_EXTRA_COLUMNS,
    "История переписки",
    "Тип продаж",
    "Статус последнего заказа",
    "ВИП",
    "Постоянный клиент",
]

MOYSKLAD_EXPORT_COLUMNS = MOYSKLAD_EXCEL_COLUMNS + MOYSKLAD_AI_EXPORT_COLUMNS

TG_NICK_COLUMNS = {"ТГ ник", "Ник в тг/вк", "Ник в тг", "Telegram"}

COLUMN_ALIASES: dict[str, list[str]] = {
    "Фамилия (для ИП и физ. лиц)": ["Фамилия (для ИП и физ. лиц)", "Фамилия"],
    "Имя (для ИП и физ. лиц)": ["Имя (для ИП и физ. лиц)", "Имя"],
    "Отчество (для ИП и физ. лиц)": ["Отчество (для ИП и физ. лиц)", "Отчество"],
    "Тип канала продаж": [
        "Тип канала продаж",
        "Тип карала продаж",
    ],
    "ТГ ник": list(TG_NICK_COLUMNS),
}


def export_columns(parsed: ParsedWorkbook | None = None) -> list[str]:
    """Порядок колонок: как во входном Excel + AI-поля."""
    if parsed and parsed.meta.get("source") == "moysklad":
        cols: list[str] = []
        seen: set[str] = set()
        for col in MOYSKLAD_EXCEL_COLUMNS:
            if col not in seen:
                cols.append(col)
                seen.add(col)
        for col in SEGMENT_COLUMNS + MOYSKLAD_AI_EXPORT_COLUMNS:
            if col not in seen:
                cols.append(col)
                seen.add(col)
        return cols

    if parsed and parsed.context_columns:
        cols: list[str] = []
        seen: set[str] = set()
        for col in parsed.context_columns:
            if col not in seen:
                cols.append(col)
                seen.add(col)
        for col in SEGMENT_COLUMNS + AI_EXTRA_COLUMNS:
            if col not in seen:
                cols.append(col)
                seen.add(col)
        for col in ("История переписки", "Ник в тг/вк"):
            if col not in seen:
                cols.append(col)
                seen.add(col)
        return cols
    return list(MOYSKLAD_EXPORT_COLUMNS)


def format_messenger_history(messages: list[dict[str, Any]], *, limit: int = 10) -> str:
    if not messages:
        return ""
    lines: list[str] = []
    for msg in messages[-limit:]:
        channel = msg.get("channel") or "?"
        arrow = "←" if msg.get("direction") == "in" else "→"
        text = str(msg.get("text") or "").replace("\n", " ").strip()
        if text:
            lines.append(f"[{channel}{arrow}] {text}")
    return "\n".join(lines)


def _resolve_aliases(row: dict[str, Any], col: str) -> Any:
    for key in COLUMN_ALIASES.get(col, [col]):
        val = row.get(key)
        if val not in (None, ""):
            return val
    return row.get(col)


def _cell_value(row: dict[str, Any], col: str) -> Any:
    if col in TG_NICK_COLUMNS:
        return _resolve_aliases(row, "ТГ ник")
    if col == "История переписки":
        return format_messenger_history(row.get("_messenger_context") or [])
    if col == "TG conversation":
        return tg_conversation_label(row)
    if col == "Группы":
        return row.get("Группы") or row.get("_moysklad_tags_display")
    if col == "Теги":
        from app.services.tag_rules import normalize_tags_field

        return normalize_tags_field(row.get("Теги")) or row.get("Теги")
    if col in COLUMN_ALIASES:
        return _resolve_aliases(row, col)
    return row.get(col)


def format_money_rub(value: Any) -> str:
    """Формат суммы: «5 760 р.»"""
    if value in (None, ""):
        return "—"
    try:
        num = float(value)
    except (TypeError, ValueError):
        text = str(value).strip()
        return text or "—"
    if num.is_integer():
        amount = int(num)
    else:
        amount = int(round(num))
    formatted = f"{amount:,}".replace(",", " ")
    return f"{formatted} р."


def display_cell_value(value: Any) -> Any:
    """Отображение ячейки: 0 и другие falsy-значения не превращать в «—»."""
    if value is None or value == "":
        return "—"
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def client_cell_state(row: dict[str, Any], col: str) -> str:
    """Состояние ячейки: value | running | unknown | empty."""
    if col in (row.get("_ai_unknown_fields") or []):
        return "unknown"
    value = _cell_value(row, col)
    if not is_empty_cell(value):
        return "value"
    if col in AI_FILLABLE_COLUMNS and not row.get("_ai_processed"):
        return "running"
    return "empty"


def client_cell_value(row: dict[str, Any], col: str) -> Any:
    """Значение ячейки для таблицы клиентов и экспорта."""
    state = client_cell_state(row, col)
    if state == "unknown":
        return AI_NO_DATA_LABEL
    if state == "running":
        return AI_RUNNING_LABEL
    return _cell_value(row, col)


def _normalize_phone_digits(value: Any) -> str:
    return re.sub(r"\D", "", str(value or ""))


def row_keyword_text(row: dict[str, Any]) -> str:
    parts: list[str] = []
    for col in CLIENT_DISPLAY_COLUMNS:
        val = _cell_value(row, col)
        if not is_empty_cell(val):
            parts.append(str(val))
    for key in _KEYWORD_SEARCH_EXTRA_KEYS:
        val = row.get(key)
        if val not in (None, ""):
            parts.append(str(val))
    return " ".join(parts).lower()


def row_matches_phone(row: dict[str, Any], phone_query: str) -> bool:
    digits = _normalize_phone_digits(phone_query)
    if not digits:
        return True
    for key in ("Телефон", "Наименование", "Код"):
        if digits in _normalize_phone_digits(row.get(key)):
            return True
    return False


def _parse_sort_date(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(text[:10], fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")[:19])
    except ValueError:
        return None


def _sort_scalar(row: dict[str, Any], col: str) -> Any:
    raw = _cell_value(row, col)
    if is_empty_cell(raw):
        return None
    if col in _NUMERIC_SORT_COLUMNS:
        try:
            return float(raw)
        except (TypeError, ValueError):
            return str(raw).lower()
    if col in _DATE_SORT_COLUMNS:
        parsed = _parse_sort_date(raw)
        return parsed or str(raw).lower()
    return str(raw).lower()


def sort_client_rows(
    rows: list[dict[str, Any]],
    sort_col: str,
    order: str = "asc",
) -> list[dict[str, Any]]:
    if not sort_col or sort_col not in CLIENT_DISPLAY_COLUMNS:
        return rows
    descending = order == "desc"

    def sort_key(row: dict[str, Any]) -> tuple[int, Any]:
        val = _sort_scalar(row, sort_col)
        return (1 if val is None else 0, val)

    return sorted(rows, key=sort_key, reverse=descending)


def row_groups(row: dict[str, Any]) -> list[str]:
    """Отдельные группы клиента из поля «Группы» (МойСклад / AI)."""
    raw = str(row.get("Группы") or row.get("_moysklad_tags_display") or "").strip()
    if not raw:
        return []
    parts = re.split(r"[,/|;]", raw)
    seen: set[str] = set()
    groups: list[str] = []
    for part in parts:
        name = part.strip()
        key = name.lower()
        if name and key not in seen:
            seen.add(key)
            groups.append(name)
    return groups


def sales_channels_index(order_rows: list[dict[str, Any]]) -> dict[str, set[str]]:
    """Каналы продаж по контрагенту из всех заказов (agent_id → названия)."""
    from app.services.fields import _looks_like_sales_type_label

    index: dict[str, set[str]] = {}
    for order in order_rows:
        agent_id = str(order.get("_moysklad_agent_id") or "").strip()
        if not agent_id:
            continue
        channel = str(order.get("Канал продаж") or "").strip()
        if not channel or _looks_like_sales_type_label(channel):
            continue
        index.setdefault(agent_id, set()).add(channel)
    return index


def sales_channel_types_index(order_rows: list[dict[str, Any]]) -> dict[str, str]:
    """Тип канала продаж по контрагенту из всех заказов (agent_id → тип)."""
    from collections import defaultdict

    from app.services.fields import sales_channel_type_for_row

    orders_by_agent: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for order in order_rows:
        agent_id = str(order.get("_moysklad_agent_id") or "").strip()
        if agent_id:
            orders_by_agent[agent_id].append(order)

    index: dict[str, str] = {}
    for agent_id, orders in orders_by_agent.items():
        label = sales_channel_type_for_row({
            "_orders_context": orders,
            "_order_channels_all": [
                str(order.get("Канал продаж") or "").strip()
                for order in orders
            ],
        })
        if label:
            index[agent_id] = label
    return index


def row_segment_names(
    row: dict[str, Any],
    *,
    agent_channels: dict[str, set[str]] | None = None,
    agent_channel_types: dict[str, str] | None = None,
) -> list[str]:
    """Сегменты для фильтра «Группы»: теги, каналы и типы канала продаж."""
    seen: set[str] = set()
    names: list[str] = []
    candidates = list(row_groups(row))
    candidates.extend(unique_sales_channels(row))
    candidates.extend(unique_sales_channel_types(row))
    cp_id = str(row.get("UUID") or row.get("_moysklad_id") or "").strip()
    if agent_channels and cp_id:
        candidates.extend(agent_channels.get(cp_id, ()))
    if agent_channel_types and cp_id:
        channel_type = agent_channel_types.get(cp_id)
        if channel_type:
            candidates.append(channel_type)
    for name in candidates:
        text = str(name).strip()
        key = text.lower()
        if text and key not in seen:
            seen.add(key)
            names.append(text)
    return names


def row_has_group(
    row: dict[str, Any],
    group: str,
    *,
    agent_channels: dict[str, set[str]] | None = None,
    agent_channel_types: dict[str, str] | None = None,
) -> bool:
    target = group.strip().lower()
    if not target:
        return True
    return any(
        n.lower() == target
        for n in row_segment_names(
            row,
            agent_channels=agent_channels,
            agent_channel_types=agent_channel_types,
        )
    )


def collect_group_counts(
    rows: list[dict[str, Any]],
    *,
    agent_channels: dict[str, set[str]] | None = None,
    agent_channel_types: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Уникальные группы, каналы и типы канала продаж с числом клиентов."""
    counter: Counter[str] = Counter()
    display: dict[str, str] = {}
    for row in rows:
        for name in row_segment_names(
            row,
            agent_channels=agent_channels,
            agent_channel_types=agent_channel_types,
        ):
            key = name.lower()
            counter[key] += 1
            display.setdefault(key, name)
    items = [
        {"name": display[key], "count": counter[key], "hue": group_chip_hue(display[key])}
        for key in counter
    ]
    items.sort(key=lambda item: (-int(item["count"]), str(item["name"]).lower()))
    return items


def group_chip_hue(name: str) -> int:
    return sum(ord(c) for c in name) % 360


def client_url_id(row_or_id: dict[str, Any] | str) -> str:
    """ID клиента для URL path (percent-encoded)."""
    if isinstance(row_or_id, dict):
        key = str(
            row_or_id.get("UUID")
            or row_or_id.get("uuid")
            or row_or_id.get("Наименование")
            or ""
        ).strip()
    else:
        key = str(row_or_id).strip()
    return quote(key, safe="")


def build_clients_query(
    *,
    sales_filter: str = "direct",
    tag: str = "",
    group: str = "",
    status: str = "",
    q: str = "",
    phone: str = "",
    sort: str = "",
    order: str = "asc",
    page: int | None = None,
    **overrides: Any,
) -> str:
    params: dict[str, str] = {
        "filter": sales_filter,
        "tag": tag,
        "group": group,
        "status": status,
        "q": q,
        "phone": phone,
        "sort": sort,
        "order": order,
    }
    if page is not None:
        params["page"] = str(page)
    params.update({k: str(v) for k, v in overrides.items() if v is not None})
    return urlencode({k: v for k, v in params.items() if v not in ("", None)})


def row_for_export(row: dict[str, Any], columns: list[str]) -> dict[str, Any]:
    item: dict[str, Any] = {}
    for col in columns:
        if str(col).startswith("_"):
            continue
        item[col] = _cell_value(row, col)
    return item


def merge_enriched_rows(
    all_rows: list[dict[str, Any]],
    enriched: list[dict[str, Any]],
    *,
    key_fn: Any,
) -> list[dict[str, Any]]:
    from app.services.excel_parser import AI_EXTRA_COLUMNS, SEGMENT_COLUMNS

    ai_overlay_keys = frozenset(SEGMENT_COLUMNS + AI_EXTRA_COLUMNS + [
        "Фамилия (для ИП и физ. лиц)",
        "Имя (для ИП и физ. лиц)",
        "Отчество (для ИП и физ. лиц)",
        "E-mail",
        "Дата рождения",
    ])
    ai_meta_keys = frozenset({
        "_ai_fields",
        "_enrichment_fields",
        "_ai_processed",
        "_ai_original",
        "_ai_recommendation",
        "_ai_client_summary",
        "_reasoning",
        "_messenger_context",
        "_tg_export_context",
        "_tg_export_meta",
    })
    overlay_skip_keys = frozenset({
        "_orders_context",
        "_orders_count",
        "_order_channels_all",
        "_ordered_positions",
        "Всего заказов",
        "Статус",
        "Постоянный клиент",
    })
    preserve_from_base = (
        "_orders_context",
        "_orders_count",
        "_order_channels_all",
        "_ordered_positions",
        "Заказанные позиции",
        "Всего заказов",
        "Средний чек",
        "Дата последнего заказа",
        "Баллы начисленные",
        "Канал продаж",
        "Тип канала продаж",
        "Наименование",
        "Телефон",
        "Фактический адрес",
        "Фактический адрес (Комментарий)",
        "Тип контрагента",
        "Пол",
        "E-mail",
        "Группы",
    )

    enriched_map = {key_fn(r): r for r in enriched}
    merged: list[dict[str, Any]] = []
    for row in all_rows:
        key = key_fn(row)
        if key in enriched_map:
            base = dict(row)
            overlay = enriched_map[key]
            combined = dict(base)
            for field, value in overlay.items():
                if field in overlay_skip_keys:
                    continue
                if field in ai_meta_keys:
                    combined[field] = value
                elif field in ai_overlay_keys and not is_empty_cell(value):
                    combined[field] = value
                elif field.startswith("_"):
                    combined[field] = value
            for field in preserve_from_base:
                base_val = base.get(field)
                if not is_empty_cell(base_val) and is_empty_cell(combined.get(field)):
                    combined[field] = base_val
            base_orders = base.get("_orders_context") or []
            combined_orders = combined.get("_orders_context") or []
            if len(base_orders) > len(combined_orders):
                combined["_orders_context"] = base_orders
                combined["_orders_count"] = base.get("_orders_count") or len(base_orders)
            merged.append(refresh_row_for_display(combined))
        else:
            merged.append(refresh_row_for_display(row))
    return merged


def _format_order_amount(value: Any) -> str:
    return format_money_rub(value)


def _format_order_date(value: Any) -> str:
    parsed = _parse_sort_date(value)
    if parsed:
        return parsed.strftime("%d.%m.%Y")
    text = str(value or "").strip()
    if not text:
        return "—"
    return text[:10]


def _truncate_text(value: str, limit: int = 80) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def compact_orders_for_display(
    orders: list[dict[str, Any]], *, limit: int = 20
) -> list[dict[str, str | bool]]:
    """Компактные строки заказов для быстрого HTMX-рендера."""
    sorted_orders = sorted(
        orders,
        key=lambda o: _parse_sort_date(o.get("Дата") or o.get("Момент времени"))
        or datetime.min,
        reverse=True,
    )
    items: list[dict[str, str | bool]] = []
    for order in sorted_orders[:limit]:
        positions = _truncate_text(str(order.get("Позиции") or ""), 72)
        comment = _truncate_text(str(order.get("Комментарий") or ""), 60)
        channel = str(order.get("Канал продаж") or "").strip()
        items.append(
            {
                "number": str(order.get("№") or order.get("Номер") or "—"),
                "date": _format_order_date(
                    order.get("Дата") or order.get("Момент времени")
                ),
                "amount": _format_order_amount(order.get("Сумма")),
                "status": str(order.get("Статус") or order.get("Отгружено") or "—"),
                "channel": channel,
                "positions": positions,
                "comment": comment,
                "has_positions": bool(positions),
                "has_comment": bool(comment),
            }
        )
    return items
