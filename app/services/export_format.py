"""Колонки экспорта и форматирование строк под Excel-шаблон."""

from __future__ import annotations

from typing import Any

from app.services.excel_parser import (
    AI_EXTRA_COLUMNS,
    CLIENT_TABLE_COLUMNS,
    SEGMENT_COLUMNS,
    ParsedWorkbook,
)

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
    if col == "Группы":
        return row.get("Группы") or row.get("_moysklad_tags_display")
    if col in COLUMN_ALIASES:
        return _resolve_aliases(row, col)
    return row.get(col)


def client_cell_value(row: dict[str, Any], col: str) -> Any:
    """Значение ячейки для таблицы клиентов и экспорта."""
    return _cell_value(row, col)


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
    enriched_map = {key_fn(r): r for r in enriched}
    merged: list[dict[str, Any]] = []
    for row in all_rows:
        key = key_fn(row)
        if key in enriched_map:
            merged.append(enriched_map[key])
        else:
            merged.append(row)
    return merged
