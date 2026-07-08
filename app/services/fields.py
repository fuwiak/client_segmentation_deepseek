"""Вычисляемые поля клиента и заказов (не AI)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

MARKETPLACE_KEYWORDS = (
  "маркетплейс",
  "яндекс",
  "ozon",
  "wildberries",
  "wb ",
  "авито",
  "lamoda",
  "сбермега",
)


def sales_type_from_channel(channel: str | None) -> str:
  """Тип продаж: маркетплейс или прямые продажи (≠ канал продаж из файла)."""
  text = (channel or "").lower()
  if any(k in text for k in MARKETPLACE_KEYWORDS):
    return "маркетплейс"
  return "прямые продажи"


def sales_type_for_row(row: dict[str, Any]) -> str:
  channel = row.get("Канал продаж") or row.get("Тип канала продаж")
  if channel:
    return sales_type_from_channel(str(channel))
  orders = row.get("_orders_context") or []
  for order in orders:
    ch = order.get("Канал продаж") or order.get("Тип канала продаж")
    if ch:
      return sales_type_from_channel(str(ch))
  return "прямые продажи"


def _parse_date(value: Any) -> datetime | None:
  if value is None:
    return None
  if isinstance(value, datetime):
    return value
  text = str(value).strip()
  for fmt in ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y", "%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
    try:
      return datetime.strptime(text[: len(fmt.replace("%", "0"))], fmt)
    except ValueError:
      continue
  try:
    return datetime.fromisoformat(text)
  except ValueError:
    return None


def last_order_status(row: dict[str, Any]) -> str | None:
  orders = row.get("_orders_context") or []
  if not orders:
    return None
  best: tuple[datetime | None, dict[str, Any]] | None = None
  for order in orders:
    dt = _parse_date(order.get("Дата") or order.get("Момент времени"))
    if best is None or (dt and (best[0] is None or dt > best[0])):
      best = (dt, order)
  if best is None:
    return str(orders[-1].get("Статус") or orders[-1].get("Отгружено") or "—")
  order = best[1]
  return str(order.get("Статус") or order.get("Отгружено") or order.get("Оплачено") or "—")


def is_vip(row: dict[str, Any]) -> bool:
  orders = row.get("_orders_context") or []
  for order in orders:
    try:
      amount = float(order.get("Сумма") or 0)
    except (TypeError, ValueError):
      amount = 0
    if amount >= 15000:
      return True
  try:
    avg = float(row.get("Средний чек") or 0)
    return avg >= 15000
  except (TypeError, ValueError):
    return False


def is_permanent(row: dict[str, Any]) -> bool:
  count = row.get("_orders_count") or row.get("Всего заказов")
  try:
    return int(count or 0) > 2
  except (TypeError, ValueError):
    return False


def enrich_row_computed(row: dict[str, Any]) -> dict[str, Any]:
  """Добавляет вычисляемые поля к строке клиента."""
  enriched = dict(row)
  enriched["Тип продаж"] = sales_type_for_row(row)
  enriched["Статус последнего заказа"] = last_order_status(row)
  enriched["ВИП"] = "да" if is_vip(row) else "нет"
  enriched["Постоянный клиент"] = "да" if is_permanent(row) else "нет"
  return enriched
