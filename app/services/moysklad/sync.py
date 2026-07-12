"""Синхронизация данных Мой Склад → DataHub."""

from __future__ import annotations

from dataclasses import dataclass

from app.services.data_hub import DataHub
from app.services.export_format import MOYSKLAD_EXCEL_COLUMNS
from app.services.excel_parser import ParsedWorkbook, SEGMENT_COLUMNS
from app.services.moysklad.client import MoySkladClientBase
from app.services.moysklad.mapper import (
    apply_order_stats,
    compute_order_stats,
    counterparty_to_row,
    order_to_row,
)


@dataclass
class MoySkladSyncResult:
    success: bool
    counterparties_count: int
    orders_count: int
    message: str


async def sync_moysklad_to_hub(
    client: MoySkladClientBase,
    hub: DataHub,
    *,
    max_counterparties: int = 500,
    max_orders: int = 2000,
) -> MoySkladSyncResult:
    if not client.enabled:
        return MoySkladSyncResult(
            success=False,
            counterparties_count=0,
            orders_count=0,
            message="Мой Склад не настроен (MOYSKLAD_API_TOKEN / MOYSKLAD_ENABLED)",
        )

    try:
        counterparties_raw = await client.fetch_all_counterparties(
            max_rows=max_counterparties
        )
        orders_raw = await client.fetch_all_customer_orders(max_rows=max_orders)
    except Exception as exc:  # noqa: BLE001 — показываем пользователю текст API-ошибки
        return MoySkladSyncResult(
            success=False,
            counterparties_count=0,
            orders_count=0,
            message=f"Ошибка API Мой Склад: {exc}",
        )

    agents_by_id = {
        str(cp.get("id")): str(cp.get("name") or "")
        for cp in counterparties_raw
        if cp.get("id")
    }

    counterparty_rows = [counterparty_to_row(cp) for cp in counterparties_raw]
    order_rows = [order_to_row(order, agents_by_id) for order in orders_raw]
    apply_order_stats(counterparty_rows, compute_order_stats(order_rows))

    contragents = ParsedWorkbook(
        source_type="contragents",
        rows=counterparty_rows,
        context_columns=[c for c in MOYSKLAD_EXCEL_COLUMNS if c not in SEGMENT_COLUMNS],
        segment_columns=[],
        total_rows=len(counterparty_rows),
        meta={"source": "moysklad", "synced": True},
    )
    orders_wb = ParsedWorkbook(
        source_type="orders",
        rows=order_rows,
        context_columns=[
            "№",
            "Контрагент",
            "Дата",
            "Сумма",
            "Статус",
            "Комментарий",
            "Канал продаж",
        ],
        segment_columns=[],
        total_rows=len(order_rows),
        meta={"source": "moysklad", "synced": True},
    )

    hub.set_workbook(contragents, orders_wb)
    hub.results = []
    hub.meta = {}
    hub.results_from_cache = False
    hub.workbook_hash = f"moysklad:{len(counterparty_rows)}:{len(order_rows)}"

    return MoySkladSyncResult(
        success=True,
        counterparties_count=len(counterparty_rows),
        orders_count=len(order_rows),
        message=(
            f"Загружено {len(counterparty_rows)} контрагентов "
            f"и {len(order_rows)} заказов из Мой Склад"
        ),
    )
