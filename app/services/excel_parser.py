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

AI_PROFILE_COLUMNS = [
    "Фамилия (для ИП и физ. лиц)",
    "Имя (для ИП и физ. лиц)",
    "Отчество (для ИП и физ. лиц)",
    "E-mail",
    "Дата рождения",
]

AI_COLUMNS = SEGMENT_COLUMNS + AI_EXTRA_COLUMNS + AI_PROFILE_COLUMNS

COMPUTED_COLUMNS = [
    "Тип продаж",
    "Статус последнего заказа",
    "ВИП",
    "Постоянный клиент",
]

CLIENT_TABLE_COLUMNS = [
    "UUID",
    "Наименование",
    "Телефон",
    "Статус",
    "Тип карала продаж",
    "Канал продаж",
    "Средний чек",
    "Дата последнего заказа",
    "Всего заказов",
    "Баллы начисленные",
    "Группы",
    "Заказчик или получатель",
    "Фактический адрес",
    "Фактический адрес (Комментарий)",
    "Тип контрагента",
    "Пол",
    "E-mail",
    "ТГ ник",
    "Код",
    "Внешний код",
    "Полное наименование",
    "Фамилия (для ИП и физ. лиц)",
    "Имя (для ИП и физ. лиц)",
    "Отчество (для ИП и физ. лиц)",
    "Юридический адрес",
    "Юридический адрес (Комментарий)",
    "ИНН",
    "КПП",
    "ОКПО",
    "Факс",
    "БИК",
    "Банк",
    "Местонахождение",
    "К/с",
    "Р/с",
    "Номер дисконтной карты",
    "ОГРН",
    "ОГРНИП",
    "Номер свидетельства",
    "Дата свидетельства",
    "Архивный",
    "Комментарий",
    "Дата рождения",
    "Юридический адрес (Код ФИАС)",
    "Фактический адрес (Код ФИАС)",
]

AI_NON_FILLABLE_COLUMNS = frozenset({
    "UUID",
    "Баллы начисленные",
    "Средний чек",
    "Всего заказов",
    "Дата последнего заказа",
})

AI_FILLABLE_COLUMNS = [
    col for col in CLIENT_TABLE_COLUMNS if col not in AI_NON_FILLABLE_COLUMNS
] + [col for col in AI_EXTRA_COLUMNS if col not in CLIENT_TABLE_COLUMNS]

CLIENT_DISPLAY_COLUMNS = [
    "Наименование",
    "Телефон",
    "Статус",
    "Тип карала продаж",
    "Канал продаж",
    "Средний чек",
    "Дата последнего заказа",
    "Всего заказов",
    "Баллы начисленные",
    "Группы",
    "Заказчик или получатель",
    "Фактический адрес",
    "Фактический адрес (Комментарий)",
    "Тип контрагента",
    "Пол",
    "E-mail",
    "ТГ ник",
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
    by_agent_id: dict[str, list[dict[str, Any]]] = {}
    for order in orders.rows:
        key = str(order.get("Контрагент") or "").strip().lower()
        if key:
            by_name.setdefault(key, []).append(order)
        agent_id = str(order.get("_moysklad_agent_id") or "").strip()
        if agent_id:
            by_agent_id.setdefault(agent_id, []).append(order)

    enriched_rows: list[dict[str, Any]] = []
    for row in contragents.rows:
        copy = dict(row)
        keys = [
            str(row.get("Наименование") or "").strip().lower(),
            str(row.get("Телефон") or "").strip().lower(),
        ]
        cp_id = str(row.get("UUID") or row.get("_moysklad_id") or "").strip()
        related: list[dict[str, Any]] = []
        seen_ids: set[str] = set()

        def _add(items: list[dict[str, Any]]) -> None:
            for item in items:
                oid = str(item.get("№") or item.get("_moysklad_id") or id(item))
                if oid not in seen_ids:
                    seen_ids.add(oid)
                    related.append(item)

        if cp_id and cp_id in by_agent_id:
            _add(by_agent_id[cp_id])
        for key in keys:
            if key and key in by_name:
                _add(by_name[key])

        if related:
            copy["_orders_context"] = related[:20]
            copy["_orders_count"] = len(related)
        enriched_rows.append(copy)

    contragents.rows = enriched_rows
    contragents.meta["orders_enriched"] = True
    contragents.meta["orders_total"] = orders.total_rows
    return contragents
