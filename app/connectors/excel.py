"""Excel-коннектор — единственный полностью рабочий на текущем этапе.

Использует существующий парсер `app.services.excel_parser` и приводит строки к
доменным моделям `Customer` / `Order`. Тестируется на уже имеющихся XLSX.
"""

from __future__ import annotations

import uuid
from typing import Any

from app.connectors.base import DataSourceConnector
from app.domain import Customer, Order, SourceType, normalize_phone
from app.services.excel_parser import ParsedWorkbook, parse_workbook


def _to_float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _to_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def customer_from_row(row: dict[str, Any]) -> Customer:
    ext_id = str(row.get("UUID") or row.get("Код") or uuid.uuid4())
    phone = normalize_phone(row.get("Телефон")) or (
        normalize_phone(row.get("Наименование"))
    )
    return Customer(
        id=ext_id,
        external_ids={SourceType.EXCEL.value: ext_id},
        name=row.get("Наименование") if not phone else row.get("Полное наименование"),
        phone=phone,
        email=row.get("E-mail"),
        telegram=row.get("ТГ ник"),
        addresses=[a for a in [row.get("Фактический адрес"), row.get("Юридический адрес")] if a],
        average_check=_to_float(row.get("Средний чек")),
        total_orders=_to_int(row.get("Всего заказов")),
        bonus_points=_to_float(row.get("Баллы начисленные")),
        source=SourceType.EXCEL,
        archived=str(row.get("Архивный") or "").strip().lower() in ("да", "yes", "true"),
        raw=row,
    )


def order_from_row(row: dict[str, Any]) -> Order:
    return Order(
        id=str(row.get("№") or row.get("Номер") or uuid.uuid4()),
        amount=_to_float(row.get("Сумма")),
        payment_status=row.get("Оплачено"),
        shipment_status=row.get("Отгружено"),
        sales_channel=row.get("Канал продаж"),
        warehouse=row.get("Склад"),
        comment=row.get("Комментарий") or row.get("Комментарий к адресу"),
        raw=row,
    )


class ExcelConnector(DataSourceConnector):
    source_type = SourceType.EXCEL

    def __init__(self, content: bytes | None = None) -> None:
        self._content = content
        self._parsed: ParsedWorkbook | None = None

    def load(self, content: bytes) -> ParsedWorkbook:
        self._content = content
        self._parsed = parse_workbook(content)
        return self._parsed

    @property
    def available(self) -> bool:
        return self._content is not None or self._parsed is not None

    def _ensure_parsed(self) -> ParsedWorkbook:
        if self._parsed is None:
            if self._content is None:
                raise ValueError("Excel-коннектор: не загружен файл (load(content)).")
            self._parsed = parse_workbook(self._content)
        return self._parsed

    async def fetch_customers(self, **kwargs: Any) -> list[Customer]:
        parsed = self._ensure_parsed()
        if parsed.source_type == "orders":
            return []
        return [customer_from_row(r) for r in parsed.rows]

    async def fetch_orders(self, **kwargs: Any) -> list[Order]:
        parsed = self._ensure_parsed()
        if parsed.source_type != "orders":
            return []
        return [order_from_row(r) for r in parsed.rows]
