"""Маппинг сущностей Мой Склад в строки CRM и доменные модели."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from app.domain import Customer, Order, OrderItem, SourceType, normalize_phone

COMPANY_TYPE_LABELS = {
    "legal": "Юридическое лицо",
    "individual": "Физическое лицо",
    "entrepreneur": "Индивидуальный предприниматель",
}

SEX_LABELS = {
    "MALE": "Мужской",
    "FEMALE": "Женский",
}


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


def _tags_list(counterparty: dict[str, Any]) -> list[str]:
    tags = counterparty.get("tags") or []
    if isinstance(tags, list):
        return [str(t) for t in tags if t]
    if tags:
        return [str(tags)]
    return []


def _tags_to_groups(tags: list[str]) -> str:
    return ", ".join(tags)


def _archived_label(value: Any) -> str:
    return "да" if value else "нет"


def _company_type_label(value: Any) -> str | None:
    if not value:
        return None
    key = str(value).strip().lower()
    return COMPANY_TYPE_LABELS.get(key, str(value))


def _sex_label(value: Any) -> str | None:
    if not value:
        return None
    key = str(value).strip().upper()
    return SEX_LABELS.get(key, str(value))


def _counterparty_status(tags: list[str]) -> str | None:
    joined = " ".join(tags).lower()
    if any(w in joined for w in ("постоянный", "vip", "премиум")):
        return "Постоянный"
    if tags:
        return "Новый"
    return None


def _address_full(counterparty: dict[str, Any], key: str) -> dict[str, Any]:
    value = counterparty.get(key) or {}
    return value if isinstance(value, dict) else {}


def _location_label(addr_full: dict[str, Any]) -> str | None:
    if not addr_full:
        return None
    parts = [
        str(addr_full.get("city") or "").strip(),
        str(addr_full.get("region") or addr_full.get("state") or "").strip(),
    ]
    joined = ", ".join(p for p in parts if p)
    return joined or None


def _accounts_list(counterparty: dict[str, Any]) -> list[dict[str, Any]]:
    """accounts в Remap 1.2 — list или MetaArray {meta, rows}."""
    raw = counterparty.get("accounts")
    if isinstance(raw, list):
        items = raw
    elif isinstance(raw, dict):
        items = raw.get("rows") or []
    else:
        items = []
    return [a for a in items if isinstance(a, dict)]


def _bonus_points(counterparty: dict[str, Any]) -> int | float | None:
    """Бонусные баллы по активной бонусной программе (bonusPoints в Remap 1.2)."""
    raw = counterparty.get("bonusPoints")
    if raw is None:
        raw = counterparty.get("bonus_points")
    if raw is None:
        return None
    try:
        num = float(raw)
    except (TypeError, ValueError):
        return None
    return int(num) if num.is_integer() else num


def _bank_fields(counterparty: dict[str, Any]) -> dict[str, Any]:
    accounts = _accounts_list(counterparty)
    account = accounts[0] if accounts else {}
    return {
        "БИК": account.get("bic"),
        "Банк": account.get("bankName"),
        "К/с": account.get("correspondentAccount"),
        "Р/с": account.get("accountNumber"),
    }


def counterparty_to_row(counterparty: dict[str, Any]) -> dict[str, Any]:
    """Маппинг API Remap 1.2 → строка как в Excel-выгрузке контрагентов."""
    tags = _tags_list(counterparty)
    groups = _tags_to_groups(tags)
    legal_full = _address_full(counterparty, "legalAddressFull")
    actual_full = _address_full(counterparty, "actualAddressFull")
    bank = _bank_fields(counterparty)

    return {
        "UUID": counterparty.get("id"),
        "Наименование": counterparty.get("name"),
        "Телефон": counterparty.get("phone"),
        "Статус": _counterparty_status(tags),
        "Группы": groups,
        "Фактический адрес": counterparty.get("actualAddress"),
        "Фактический адрес (Комментарий)": actual_full.get("comment"),
        "Тип контрагента": _company_type_label(counterparty.get("companyType")),
        "Пол": _sex_label(counterparty.get("sex")),
        "E-mail": counterparty.get("email"),
        "Код": counterparty.get("code") or counterparty.get("externalCode"),
        "Внешний код": counterparty.get("externalCode"),
        "Полное наименование": counterparty.get("legalTitle") or counterparty.get("name"),
        "Фамилия (для ИП и физ. лиц)": counterparty.get("legalLastName"),
        "Имя (для ИП и физ. лиц)": counterparty.get("legalFirstName"),
        "Отчество (для ИП и физ. лиц)": counterparty.get("legalMiddleName"),
        "Юридический адрес": counterparty.get("legalAddress"),
        "Юридический адрес (Комментарий)": legal_full.get("comment"),
        "ИНН": counterparty.get("inn"),
        "КПП": counterparty.get("kpp"),
        "ОКПО": counterparty.get("okpo"),
        "Факс": counterparty.get("fax"),
        "Местонахождение": _location_label(actual_full) or _location_label(legal_full),
        "Номер дисконтной карты": counterparty.get("discountCardNumber"),
        "ОГРН": counterparty.get("ogrn"),
        "ОГРНИП": counterparty.get("ogrnip"),
        "Номер свидетельства": counterparty.get("certificateNumber"),
        "Дата свидетельства": counterparty.get("certificateDate"),
        "Архивный": _archived_label(counterparty.get("archived")),
        "Комментарий": counterparty.get("description"),
        "Дата рождения": counterparty.get("birthDate"),
        "Юридический адрес (Код ФИАС)": legal_full.get("fiasCode") or legal_full.get("code"),
        "Фактический адрес (Код ФИАС)": actual_full.get("fiasCode") or actual_full.get("code"),
        "Баллы начисленные": _bonus_points(counterparty),
        **bank,
        "_moysklad_id": counterparty.get("id"),
        "_moysklad_tags": tags,
        "_moysklad_tags_display": groups,
        "_source": SourceType.MOYSKLAD.value,
    }


def _sales_channel_from_order(order: dict[str, Any]) -> str | None:
    """Канал продаж из заказа покупателя (salesChannel в Remap 1.2)."""
    sc = order.get("salesChannel") or order.get("sales_channel")
    if isinstance(sc, dict):
        name = sc.get("name")
        if name:
            return str(name).strip()
    return None


def position_to_item(position: dict[str, Any]) -> dict[str, Any]:
    """Маппинг позиции заказа Remap 1.2 → dict для CRM."""
    assortment = position.get("assortment") or {}
    name = str(assortment.get("name") or position.get("name") or "").strip()
    code = str(assortment.get("code") or "").strip()
    if code and code not in name:
        name = f"{code} {name}".strip() if name else code
    return {
        "name": name,
        "quantity": position.get("quantity"),
        "price": _minor_to_rub(position.get("price")),
    }


def positions_label(positions: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for item in positions:
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        qty = item.get("quantity")
        try:
            qty_val = float(qty) if qty is not None else 1.0
        except (TypeError, ValueError):
            qty_val = 1.0
        if qty_val != 1:
            parts.append(f"{name} (×{qty_val:g})")
        else:
            parts.append(name)
    return ", ".join(parts)


def apply_positions_to_orders(
    order_rows: list[dict[str, Any]],
    positions_by_order_id: dict[str, list[dict[str, Any]]],
) -> None:
    for row in order_rows:
        order_id = str(row.get("_moysklad_id") or "")
        raw_positions = positions_by_order_id.get(order_id) or []
        items = [position_to_item(p) for p in raw_positions if isinstance(p, dict)]
        row["_positions"] = items
        if items:
            row["Позиции"] = positions_label(items)


def aggregate_client_positions(orders: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Суммирует позиции по всем заказам клиента."""
    totals: dict[str, float] = {}
    for order in orders:
        for item in order.get("_positions") or []:
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            try:
                qty = float(item.get("quantity") or 1)
            except (TypeError, ValueError):
                qty = 1.0
            totals[name] = totals.get(name, 0.0) + qty
    return [{"name": name, "quantity": qty} for name, qty in totals.items()]


def order_to_row(
    order: dict[str, Any],
    agents_by_id: dict[str, str],
) -> dict[str, Any]:
    agent = order.get("agent") or {}
    agent_id = href_id((agent.get("meta") or {}).get("href"))
    agent_name = agent.get("name") or agents_by_id.get(agent_id, "")

    state = order.get("state") or {}
    state_name = state.get("name") or ""
    sales_channel = _sales_channel_from_order(order)

    return {
        "№": order.get("name"),
        "Контрагент": agent_name,
        "Дата": order.get("moment"),
        "Сумма": _minor_to_rub(order.get("sum")),
        "Статус": state_name,
        "Комментарий": order.get("description"),
        "Канал продаж": sales_channel,
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
    tags = _tags_list(counterparty)
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
        preferences=tags,
    )


def order_from_customerorder(
    order: dict[str, Any],
    agents_by_id: dict[str, str] | None = None,
    positions: list[dict[str, Any]] | None = None,
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

    items = [
        OrderItem(
            name=str(p.get("name") or ""),
            quantity=p.get("quantity"),
            price=p.get("price"),
        )
        for p in (positions or [])
    ]

    return Order(
        id=str(order.get("id") or order.get("name") or uuid.uuid4()),
        customer_id=agent_id or None,
        date=parsed_date,
        amount=_minor_to_rub(order.get("sum")),
        payment_status=state.get("name"),
        sales_channel="Мой Склад",
        comment=order.get("description"),
        recipient=agent_name or None,
        items=items,
        raw=order,
    )
