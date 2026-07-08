"""Маппинг сущностей Мой Склад в строки CRM и доменные модели."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from app.domain import Customer, Order, SourceType, normalize_phone


def href_id(href: str | None) -> str:
    if not href:
        return ""
    return href.rstrip("/").split("/")[-1]


def _minor_to_rub(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value) / 100.0
    except (TypeError, ValueError):
        return None


def counterparty_to_row(counterparty: dict[str, Any]) -> dict[str, Any]:
    tags = counterparty.get("tags") or []
    groups = ", ".join(str(t) for t in tags) if isinstance(tags, list) else str(tags)

    return {
        "UUID": counterparty.get("id"),
        "Наименование": counterparty.get("name"),
        "Телефон": counterparty.get("phone"),
        "E-mail": counterparty.get("email"),
        "Группы": groups,
        "Код": counterparty.get("externalCode"),
        "Архивный": "да" if counterparty.get("archived") else "нет",
        "Фактический адрес": counterparty.get("actualAddress"),
        "Юридический адрес": counterparty.get("legalAddress"),
        "_moysklad_id": counterparty.get("id"),
        "_moysklad_tags": list(tags) if isinstance(tags, list) else [],
        "_source": SourceType.MOYSKLAD.value,
    }


def order_to_row(
    order: dict[str, Any],
    agents_by_id: dict[str, str],
) -> dict[str, Any]:
    agent = order.get("agent") or {}
    agent_id = href_id((agent.get("meta") or {}).get("href"))
    agent_name = agent.get("name") or agents_by_id.get(agent_id, "")

    state = order.get("state") or {}
    state_name = state.get("name") or ""

    return {
        "№": order.get("name"),
        "Контрагент": agent_name,
        "Дата": order.get("moment"),
        "Сумма": _minor_to_rub(order.get("sum")),
        "Статус": state_name,
        "Комментарий": order.get("description"),
        "Канал продаж": "Мой Склад",
        "_moysklad_id": order.get("id"),
        "_moysklad_agent_id": agent_id,
        "_source": SourceType.MOYSKLAD.value,
    }


def compute_order_stats(
    order_rows: list[dict[str, Any]],
) -> dict[str, dict[str, float | int]]:
    by_agent: dict[str, list[float]] = {}
    for row in order_rows:
        agent_id = str(row.get("_moysklad_agent_id") or "")
        if not agent_id:
            continue
        amount = row.get("Сумма")
        by_agent.setdefault(agent_id, []).append(float(amount) if amount is not None else 0.0)

    stats: dict[str, dict[str, float | int]] = {}
    for agent_id, amounts in by_agent.items():
        count = len(amounts)
        stats[agent_id] = {
            "count": count,
            "avg": round(sum(amounts) / count, 2) if count else 0.0,
        }
    return stats


def apply_order_stats(
    counterparty_rows: list[dict[str, Any]],
    stats: dict[str, dict[str, float | int]],
) -> None:
    for row in counterparty_rows:
        cp_id = str(row.get("UUID") or row.get("_moysklad_id") or "")
        item = stats.get(cp_id)
        if not item:
            continue
        row["Всего заказов"] = int(item["count"])
        row["Средний чек"] = float(item["avg"])


def customer_from_counterparty(counterparty: dict[str, Any]) -> Customer:
    ext_id = str(counterparty.get("id") or uuid.uuid4())
    phone = normalize_phone(counterparty.get("phone"))
    tags = counterparty.get("tags") or []
    addresses = [
        a
        for a in [counterparty.get("actualAddress"), counterparty.get("legalAddress")]
        if a
    ]
    return Customer(
        id=ext_id,
        external_ids={SourceType.MOYSKLAD.value: ext_id},
        name=counterparty.get("name"),
        phone=phone,
        email=counterparty.get("email"),
        addresses=addresses,
        source=SourceType.MOYSKLAD,
        archived=bool(counterparty.get("archived")),
        raw=counterparty,
        preferences=[str(t) for t in tags] if isinstance(tags, list) else [],
    )


def order_from_customerorder(
    order: dict[str, Any],
    agents_by_id: dict[str, str] | None = None,
) -> Order:
    agents_by_id = agents_by_id or {}
    agent = order.get("agent") or {}
    agent_id = href_id((agent.get("meta") or {}).get("href"))
    agent_name = agent.get("name") or agents_by_id.get(agent_id, "")

    state = order.get("state") or {}
    moment = order.get("moment")
    parsed_date: datetime | None = None
    if moment:
        try:
            parsed_date = datetime.fromisoformat(str(moment).replace("Z", "+00:00"))
        except ValueError:
            parsed_date = None

    return Order(
        id=str(order.get("id") or order.get("name") or uuid.uuid4()),
        customer_id=agent_id or None,
        date=parsed_date,
        amount=_minor_to_rub(order.get("sum")),
        payment_status=state.get("name"),
        sales_channel="Мой Склад",
        comment=order.get("description"),
        recipient=agent_name or None,
        raw=order,
    )
