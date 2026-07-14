"""Вычисляемые поля клиента и заказов (не AI)."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from app.services.excel_parser import AI_FILLABLE_COLUMNS

COUNTERPARTY_COMMENT_KEYS = (
  "Комментарий",
  "Фактический адрес (Комментарий)",
  "Юридический адрес (Комментарий)",
)

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.\w+")

def collect_client_comments(row: dict[str, Any]) -> str:
  """Комментарии контрагента и его заказов — единый текст для AI и эвристик."""
  parts: list[str] = []
  for key in COUNTERPARTY_COMMENT_KEYS:
    val = str(row.get(key) or "").strip()
    if val:
      parts.append(val)
  for order in row.get("_orders_context") or []:
    for key in ("Комментарий", "Описание"):
      val = str(order.get(key) or "").strip()
      if val:
        parts.append(val)
  return " ".join(parts)


def extract_email_from_row(row: dict[str, Any]) -> str | None:
  if row.get("E-mail"):
    return None
  text = " ".join(
    str(row.get(key) or "")
    for key in ("E-mail", "Наименование", *COUNTERPARTY_COMMENT_KEYS)
  )
  text = f"{text} {collect_client_comments(row)}"
  match = _EMAIL_RE.search(text)
  return match.group(0) if match else None


def apply_name_parts(merged: dict[str, Any], full_name: str, ai_fields: list[str]) -> None:
  """Разбить ФИО на части, если поля ещё пустые."""
  name = full_name.strip()
  if not name:
    return
  parts = name.split()
  if len(parts) >= 3:
    if not merged.get("Фамилия (для ИП и физ. лиц)"):
      apply_ai_field(merged, "Фамилия (для ИП и физ. лиц)", parts[0], ai_fields)
    if not merged.get("Имя (для ИП и физ. лиц)"):
      apply_ai_field(merged, "Имя (для ИП и физ. лиц)", parts[1], ai_fields)
    if not merged.get("Отчество (для ИП и физ. лиц)"):
      apply_ai_field(merged, "Отчество (для ИП и физ. лиц)", parts[2], ai_fields)
  elif len(parts) == 2:
    if not merged.get("Имя (для ИП и физ. лиц)"):
      apply_ai_field(merged, "Имя (для ИП и физ. лиц)", parts[0], ai_fields)
    if not merged.get("Фамилия (для ИП и физ. лиц)"):
      apply_ai_field(merged, "Фамилия (для ИП и физ. лиц)", parts[1], ai_fields)


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


def last_order_date(row: dict[str, Any]) -> str | None:
  orders = row.get("_orders_context") or []
  if not orders:
    return None
  best: tuple[datetime | None, dict[str, Any]] | None = None
  for order in orders:
    dt = _parse_date(order.get("Дата") or order.get("Момент времени"))
    if best is None or (dt and (best[0] is None or dt > best[0])):
      best = (dt, order)
  if best is None or best[0] is None:
    return None
  return best[0].strftime("%d.%m.%Y %H:%M:%S")


def sales_channel_for_row(row: dict[str, Any]) -> str | None:
  channel = row.get("Канал продаж") or row.get("Тип канала продаж") or row.get("Тип карала продаж")
  if channel:
    return str(channel)
  orders = row.get("_orders_context") or []
  best: tuple[datetime | None, dict[str, Any]] | None = None
  for order in orders:
    dt = _parse_date(order.get("Дата") or order.get("Момент времени"))
    if best is None or (dt and (best[0] is None or dt > best[0])):
      best = (dt, order)
  if best is None:
    return None
  order = best[1]
  return str(order.get("Канал продаж") or order.get("Тип канала продаж") or order.get("Тип карала продаж") or "")


def enrich_row_computed(row: dict[str, Any]) -> dict[str, Any]:
  """Добавляет вычисляемые поля к строке клиента."""
  enriched = dict(row)
  enriched["Тип продаж"] = sales_type_for_row(row)
  enriched["Статус последнего заказа"] = last_order_status(row)
  enriched["ВИП"] = "да" if is_vip(row) else "нет"
  enriched["Постоянный клиент"] = "да" if is_permanent(row) else "нет"
  if not enriched.get("Дата последнего заказа"):
    enriched["Дата последнего заказа"] = last_order_date(row)
  if not enriched.get("Канал продаж"):
    channel = sales_channel_for_row(row)
    if channel:
      enriched["Канал продаж"] = channel
  if not enriched.get("Тип карала продаж"):
    channel = enriched.get("Канал продаж") or row.get("Тип канала продаж")
    if channel:
      enriched["Тип карала продаж"] = channel
  return enriched


AI_NO_DATA_LABEL = "no data"


def _normalized_cell(value: Any) -> str:
  if value in (None, "", "null"):
    return ""
  return str(value).strip()


def is_empty_cell(value: Any) -> bool:
  text = _normalized_cell(value)
  if not text or text.lower() in {"—", "-", "нет", "none", "n/a", AI_NO_DATA_LABEL}:
    return True
  return False


def empty_fillable_columns(row: dict[str, Any]) -> list[str]:
  return [col for col in AI_FILLABLE_COLUMNS if is_empty_cell(row.get(col))]


def finalize_ai_coverage_row(row: dict[str, Any]) -> dict[str, Any]:
  """После AI/обогащения пометить незаполненные поля как no data."""
  if not row.get("_ai_processed"):
    return row
  merged = dict(row)
  unknown = [col for col in AI_FILLABLE_COLUMNS if is_empty_cell(merged.get(col))]
  merged["_ai_unknown_fields"] = unknown
  return merged


def apply_ai_field(
  merged: dict[str, Any],
  col: str,
  new_value: Any,
  ai_fields: list[str],
) -> None:
  """Записать AI-поле и сохранить прежнее значение, если оно изменилось."""
  new_str = _normalized_cell(new_value)
  if not new_str:
    return
  old_str = _normalized_cell(merged.get(col))
  if old_str and old_str != new_str:
    originals = dict(merged.get("_ai_original") or {})
    originals[col] = merged.get(col)
    merged["_ai_original"] = originals
  merged[col] = new_value
  if col not in ai_fields:
    ai_fields.append(col)
