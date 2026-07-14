"""Колонки экспорта и форматирование строк под Excel-шаблон."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from urllib.parse import urlencode

from app.services.telegram_export import tg_conversation_label
from app.services.fields import AI_NO_DATA_LABEL, is_empty_cell, refresh_row_for_display

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
    "Тип карала продаж": ["Тип карала продаж", "Тип канала продаж", "Канал продаж"],
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
    if col in COLUMN_ALIASES:
        return _resolve_aliases(row, col)
    return row.get(col)


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


def build_clients_query(
    *,
    sales_filter: str = "direct",
    tag: str = "",
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
        "_messenger_context",
        "_tg_export_context",
        "_tg_export_meta",
    })
    overlay_skip_keys = frozenset({
        "_orders_context",
        "_orders_count",
        "_ordered_positions",
    })
    preserve_from_base = (
        "_orders_context",
        "_orders_count",
        "_ordered_positions",
        "Заказанные позиции",
        "Всего заказов",
        "Средний чек",
        "Дата последнего заказа",
        "Баллы начисленные",
        "Канал продаж",
        "Тип карала продаж",
        "Статус",
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
    if value in (None, ""):
        return "—"
    try:
        num = float(value)
    except (TypeError, ValueError):
        return str(value)
    if num >= 1000:
        formatted = f"{num:,.0f}".replace(",", "\u202f")
        return f"{formatted} ₽"
    if num.is_integer():
        return f"{int(num)} ₽"
    return f"{num:.2f} ₽"


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
