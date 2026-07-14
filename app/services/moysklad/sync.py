"""Синхронизация данных Мой Склад → DataHub."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

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

if TYPE_CHECKING:
    from app.services.cache import CacheService

MOYSKLAD_SYNC_SCHEMA_VERSION = 2


@dataclass
class MoySkladSyncResult:
    success: bool
    counterparties_count: int
    orders_count: int
    message: str
    api_counterparties_total: int | None = None
    api_orders_total: int | None = None
    from_cache: bool = False


def _apply_rows_to_hub(
    hub: DataHub,
    counterparty_rows: list[dict[str, Any]],
    order_rows: list[dict[str, Any]],
) -> None:
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
    hub.workbook_hash = f"moysklad:{len(counterparty_rows)}:{len(order_rows)}"


def _cache_matches_limits(cached: dict[str, Any], max_counterparties: int, max_orders: int) -> bool:
    return (
        cached.get("schema_version") == MOYSKLAD_SYNC_SCHEMA_VERSION
        and cached.get("max_counterparties") == max_counterparties
        and cached.get("max_orders") == max_orders
    )


async def _load_from_cache(
    cache: CacheService,
    hub: DataHub,
    *,
    max_counterparties: int,
    max_orders: int,
) -> MoySkladSyncResult | None:
    cached = await cache.get_moysklad_sync()
    if not cached or not _cache_matches_limits(cached, max_counterparties, max_orders):
        return None
    counterparty_rows = cached.get("counterparty_rows") or []
    order_rows = cached.get("order_rows") or []
    if not counterparty_rows:
        return None
    api_cp_total = cached.get("api_cp_total")
    if api_cp_total and len(counterparty_rows) < api_cp_total:
        return None
    _apply_rows_to_hub(hub, counterparty_rows, order_rows)
    cp_count = len(counterparty_rows)
    orders_count = len(order_rows)
    return MoySkladSyncResult(
        success=True,
        counterparties_count=cp_count,
        orders_count=orders_count,
        api_counterparties_total=cached.get("api_cp_total"),
        api_orders_total=cached.get("api_orders_total"),
        from_cache=True,
        message=(
            f"Из кэша: {cp_count} контрагентов и {orders_count} заказов "
            f"(Мой Склад)"
        ),
    )


async def sync_moysklad_to_hub(
    client: MoySkladClientBase,
    hub: DataHub,
    *,
    max_counterparties: int = 0,
    max_orders: int = 0,
    cache: CacheService | None = None,
    force_refresh: bool = False,
) -> MoySkladSyncResult:
    if not client.enabled:
        return MoySkladSyncResult(
            success=False,
            counterparties_count=0,
            orders_count=0,
            message="Мой Склад не настроен (MOYSKLAD_API_TOKEN / MOYSKLAD_ENABLED)",
        )

    if cache and not force_refresh:
        cached_result = await _load_from_cache(
            cache,
            hub,
            max_counterparties=max_counterparties,
            max_orders=max_orders,
        )
        if cached_result:
            return cached_result

    try:
        api_cp_total = await client.get_entity_count("/entity/counterparty")
        api_orders_total = await client.get_entity_count("/entity/customerorder")
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

    _apply_rows_to_hub(hub, counterparty_rows, order_rows)

    if cache:
        await cache.save_moysklad_sync(
            {
                "schema_version": MOYSKLAD_SYNC_SCHEMA_VERSION,
                "counterparty_rows": counterparty_rows,
                "order_rows": order_rows,
                "api_cp_total": api_cp_total,
                "api_orders_total": api_orders_total,
                "max_counterparties": max_counterparties,
                "max_orders": max_orders,
            }
        )

    return MoySkladSyncResult(
        success=True,
        counterparties_count=len(counterparty_rows),
        orders_count=len(order_rows),
        api_counterparties_total=api_cp_total,
        api_orders_total=api_orders_total,
        message=(
            f"Загружено {len(counterparty_rows)} контрагентов "
            f"и {len(order_rows)} заказов из Мой Склад"
        ),
    )
