from __future__ import annotations

import io
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

SEGMENT_COLUMNS = [
    "Группы",
    "Заказчик или получатель",
    "Пол",
    "ТГ ник",
]

AI_EXTRA_COLUMNS = [
    "Теги",
    "Саммари",
]

COMPUTED_COLUMNS = [
    "Тип продаж",
    "Статус последнего заказа",
    "ВИП",
    "Постоянный клиент",
]

CLIENT_DISPLAY_COLUMNS = [
    "Наименование",
    "Телефон",
    "E-mail",
    "Тип продаж",
    "Канал продаж",
    "Статус последнего заказа",
    "Группы",
    "Теги",
    "Заказчик или получатель",
    "Пол",
    "ТГ ник",
    "ВИП",
    "Постоянный клиент",
    "Средний чек",
    "Всего заказов",
    "Саммари",
]

CONTRAGENT_MARKERS = {"UUID", "Наименование", "Тип контрагента"}
ORDER_MARKERS = {"Контрагент", "Организация", "Статус"}


@dataclass
class ParsedWorkbook:
    source_type: str
    rows: list[dict[str, Any]]
    context_columns: list[str]
    segment_columns: list[str]
    total_rows: int
    meta: dict[str, Any] = field(default_factory=dict)


def _normalize(value: Any) -> Any:
    if pd.isna(value):
        return None
    if isinstance(value, float) and value == int(value):
        return int(value)
    return value


def _row_to_dict(row: pd.Series) -> dict[str, Any]:
    return {str(k): _normalize(v) for k, v in row.items()}


def _detect_header_row(df_raw: pd.DataFrame, markers: set[str]) -> int | None:
    for idx in range(min(15, len(df_raw))):
        row_values = {str(v).strip() for v in df_raw.iloc[idx].tolist() if pd.notna(v)}
        if markers.issubset(row_values) or len(markers & row_values) >= 2:
            return idx
    return None


def _read_sheet(content: bytes) -> tuple[pd.DataFrame, dict[str, Any]]:
    # Read the workbook ONCE (openpyxl parsing is the slow part) and reuse the
    # raw frame for header detection + final slicing, instead of re-reading the
    # file two or three times.
    xl = pd.ExcelFile(io.BytesIO(content))
    sheet = xl.sheet_names[0]
    raw = xl.parse(sheet_name=sheet, header=None)

    header_row = _detect_header_row(raw, CONTRAGENT_MARKERS)
    source_type = "contragents"

    if header_row is None:
        header_row = _detect_header_row(raw, ORDER_MARKERS)
        source_type = "orders"

    if header_row is None:
        header_row = 0
        source_type = "unknown"

    header_cells = raw.iloc[header_row].tolist()
    keep_idx = [
        i
        for i, cell in enumerate(header_cells)
        if pd.notna(cell) and str(cell).strip()
    ]

    df = raw.iloc[header_row + 1 :, keep_idx].reset_index(drop=True)
    df.columns = [str(header_cells[i]).strip() for i in keep_idx]
    df = df.dropna(how="all")

    return df, {"sheet": sheet, "header_row": header_row, "source_type": source_type}


def parse_workbook(content: bytes) -> ParsedWorkbook:
    df, meta = _read_sheet(content)
    source_type = meta["source_type"]

    segment_present = [c for c in SEGMENT_COLUMNS if c in df.columns]
    context_columns = [c for c in df.columns if c not in SEGMENT_COLUMNS]

    rows = [_row_to_dict(row) for _, row in df.iterrows()]
    rows = [r for r in rows if any(v is not None for v in r.values())]

    return ParsedWorkbook(
        source_type=source_type,
        rows=rows,
        context_columns=context_columns,
        segment_columns=segment_present,
        total_rows=len(rows),
        meta=meta,
    )


def enrich_with_orders(
    contragents: ParsedWorkbook, orders: ParsedWorkbook
) -> ParsedWorkbook:
    if not orders.rows:
        return contragents

    by_name: dict[str, list[dict[str, Any]]] = {}
    for order in orders.rows:
        key = str(order.get("Контрагент") or "").strip().lower()
        if key:
            by_name.setdefault(key, []).append(order)

    enriched_rows: list[dict[str, Any]] = []
    for row in contragents.rows:
        copy = dict(row)
        keys = [
            str(row.get("Наименование") or "").strip().lower(),
            str(row.get("Телефон") or "").strip().lower(),
        ]
        related: list[dict[str, Any]] = []
        for key in keys:
            if key and key in by_name:
                related.extend(by_name[key])

        if related:
            copy["_orders_context"] = related[:5]
            copy["_orders_count"] = len(related)
        enriched_rows.append(copy)

    contragents.rows = enriched_rows
    contragents.meta["orders_enriched"] = True
    contragents.meta["orders_total"] = orders.total_rows
    return contragents
