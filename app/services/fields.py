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


DIRECT_SALES_CHANNEL_EXACT = frozenset({
  "telegram",
  "whatsapp/max",
  "whatsapp",
  "max",
  "витрина",
  "прямые продажи",
  "сайт vereskflowers.ru",
})

DIRECT_SALES_CHANNEL_SUBSTRINGS = (
  "vereskflowers.ru",
  "telegram",
  "whatsapp",
)

SALES_CHANNEL_TYPE_MARKETPLACE = "маркетплейс"
SALES_CHANNEL_TYPE_DIRECT = "прямые продажи"
SALES_CHANNEL_TYPE_HYBRID = "прямые продажи/маркетплейс"

# Старое имя поля с опечаткой — только для чтения legacy-данных.
LEGACY_SALES_CHANNEL_TYPE_KEY = "Тип карала продаж"
SALES_CHANNEL_TYPE_KEY = "Тип канала продаж"


def _normalize_channel(channel: str) -> str:
  return channel.strip().lower().replace("ё", "е")


def is_direct_sales_channel(channel: str | None) -> bool:
  """Прямые продажи: Telegram, WhatsApp/MAX, Витрина, Прямые продажи, vereskflowers.ru."""
  if not channel or not str(channel).strip():
    return False
  text = _normalize_channel(str(channel))
  if text in DIRECT_SALES_CHANNEL_EXACT:
    return True
  return any(part in text for part in DIRECT_SALES_CHANNEL_SUBSTRINGS)


def is_marketplace_channel(channel: str | None) -> bool:
  """Маркетплейс: любой канал, не входящий в список прямых продаж."""
  if not channel or not str(channel).strip():
    return False
  return not is_direct_sales_channel(channel)


def channel_type_from_channel(channel: str | None) -> str:
  """Классификация одного канала продаж из МойСклад."""
  if is_direct_sales_channel(channel):
    return SALES_CHANNEL_TYPE_DIRECT
  if channel and str(channel).strip():
    return SALES_CHANNEL_TYPE_MARKETPLACE
  return SALES_CHANNEL_TYPE_DIRECT


def sales_type_from_channel(channel: str | None) -> str:
  """Тип продаж по одному каналу из заказа МойСклад."""
  return channel_type_from_channel(channel)


def _order_channels(row: dict[str, Any]) -> list[str]:
  channels: list[str] = []
  for order in row.get("_orders_context") or []:
    ch = order.get("Канал продаж")
    if ch and str(ch).strip():
      channels.append(str(ch).strip())
  if not channels:
    ch = row.get("Канал продаж")
    if ch and str(ch).strip() and not _looks_like_sales_type_label(str(ch)):
      channels.append(str(ch).strip())
  return channels


def _order_channels_for_type(row: dict[str, Any]) -> list[str]:
  """Канал продаж по каждому заказу (пустая строка, если не задан)."""
  stored = row.get("_order_channels_all")
  if isinstance(stored, list):
    return [str(ch).strip() if ch is not None else "" for ch in stored]
  channels: list[str] = []
  for order in row.get("_orders_context") or []:
    ch = order.get("Канал продаж")
    channels.append(str(ch).strip() if ch else "")
  if channels:
    return channels
  ch = row.get("Канал продаж")
  if ch and str(ch).strip() and not _looks_like_sales_type_label(str(ch)):
    return [str(ch).strip()]
  return []


def sales_channel_type_from_channels(channels: list[str]) -> str:
  """Прямые продажи только если каждый заказ из белого списка каналов."""
  if not channels:
    return SALES_CHANNEL_TYPE_DIRECT
  for channel in channels:
    if not channel or not is_direct_sales_channel(channel):
      return SALES_CHANNEL_TYPE_MARKETPLACE
  return SALES_CHANNEL_TYPE_DIRECT


def unique_sales_channels(row: dict[str, Any]) -> list[str]:
  """Уникальные каналы продаж клиента (из заказов и поля строки)."""
  seen: set[str] = set()
  result: list[str] = []
  for ch in _order_channels(row):
    key = ch.lower()
    if key not in seen and not _looks_like_sales_type_label(ch):
      seen.add(key)
      result.append(ch)
  return result


def unique_sales_channel_types(row: dict[str, Any]) -> list[str]:
  """Тип канала продаж клиента (если есть данные для определения)."""
  channels = _order_channels_for_type(row)
  if not channels:
    return []
  return [sales_channel_type_from_channels(channels)]


def sales_channel_type_for_row(row: dict[str, Any]) -> str:
  """Тип канала продаж по всем заказам контрагента."""
  return sales_channel_type_from_channels(_order_channels_for_type(row))


def sales_type_for_row(row: dict[str, Any]) -> str:
  return sales_channel_type_for_row(row)


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


def order_count_for_row(row: dict[str, Any]) -> int:
  for key in ("_orders_count", "Всего заказов"):
    val = row.get(key)
    if val not in (None, ""):
      try:
        return max(0, int(val))
      except (TypeError, ValueError):
        pass
  orders = row.get("_orders_context") or []
  return len(orders)


def client_status_from_orders(row: dict[str, Any]) -> str:
  """Статус клиента по числу заказов: 1 — новый, 2 — повторный, 3+ — постоянный."""
  count = order_count_for_row(row)
  if count >= 3:
    return "постоянный"
  if count == 2:
    return "повторный"
  return "новый"


def is_permanent(row: dict[str, Any]) -> bool:
  return order_count_for_row(row) >= 3


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
  channel = row.get("Канал продаж") or row.get("Тип канала продаж")
  if channel and not _looks_like_sales_type_label(str(channel)):
    return str(channel).strip()
  orders = row.get("_orders_context") or []
  best: tuple[datetime | None, dict[str, Any]] | None = None
  for order in orders:
    dt = _parse_date(order.get("Дата") or order.get("Момент времени"))
    if best is None or (dt and (best[0] is None or dt > best[0])):
      best = (dt, order)
  if best is None:
    return None
  order = best[1]
  raw = str(
    order.get("Канал продаж") or order.get("Тип канала продаж") or ""
  ).strip()
  if raw and not _looks_like_sales_type_label(raw):
    return raw
  return None


def _looks_like_sales_type_label(value: str) -> bool:
  text = value.strip().lower().replace("ё", "е")
  return text in {
    SALES_CHANNEL_TYPE_MARKETPLACE,
    SALES_CHANNEL_TYPE_DIRECT,
    SALES_CHANNEL_TYPE_HYBRID,
    "прямые",
    "marketplace",
    "direct",
  } or ("прямы" in text and "маркет" in text)


def sales_type_label_for_row(row: dict[str, Any]) -> str:
  return sales_channel_type_for_row(row)


def row_sales_type_filter_value(row: dict[str, Any]) -> str:
  return str(
    row.get("Тип продаж")
    or row.get(SALES_CHANNEL_TYPE_KEY)
    or row.get(LEGACY_SALES_CHANNEL_TYPE_KEY)
    or ""
  ).strip().lower()


_TG_USERNAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{3,31}$")


def extract_tg_nick_from_messages(messages: list[dict[str, Any]]) -> str | None:
  for msg in messages:
    if msg.get("channel") != "telegram":
      continue
    for raw in (msg.get("username"), msg.get("sender")):
      if not raw:
        continue
      text = str(raw).strip()
      if text.startswith("@"):
        text = text[1:]
      if _TG_USERNAME_RE.match(text):
        return f"@{text}"
  return None


def enrich_row_computed(row: dict[str, Any]) -> dict[str, Any]:
  """Добавляет вычисляемые поля к строке клиента."""
  enriched = dict(row)
  channel = sales_channel_for_row(row)
  if channel:
    enriched["Канал продаж"] = channel
  sales_type = sales_channel_type_for_row(enriched)
  enriched["Тип продаж"] = sales_type
  enriched[SALES_CHANNEL_TYPE_KEY] = sales_type
  enriched["Статус последнего заказа"] = last_order_status(row)
  enriched["Статус"] = client_status_from_orders(enriched)
  enriched["ВИП"] = "да" if is_vip(row) else "нет"
  enriched["Постоянный клиент"] = "да" if is_permanent(row) else "нет"
  if not enriched.get("Дата последнего заказа"):
    enriched["Дата последнего заказа"] = last_order_date(row)
  if not enriched.get("ТГ ник"):
    tg = extract_tg_nick_from_messages(
      list(enriched.get("_messenger_context") or [])
      + list(enriched.get("_tg_export_context") or [])
    )
    if tg:
      enriched["ТГ ник"] = tg
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
  """После AI/обогащения пометить незаполненные AI-поля как no data."""
  merged = refresh_row_for_display(row)
  if not merged.get("_ai_processed"):
    return merged
  unknown = [col for col in AI_FILLABLE_COLUMNS if is_empty_cell(merged.get(col))]
  merged["_ai_unknown_fields"] = unknown
  return merged


def refresh_row_for_display(row: dict[str, Any]) -> dict[str, Any]:
  """Пересчитать поля из заказов МойСклад и убрать ложные AI-метки."""
  merged = enrich_row_computed(dict(row))
  unknown = list(merged.get("_ai_unknown_fields") or [])
  if unknown:
    merged["_ai_unknown_fields"] = [
      col for col in unknown
      if col in AI_FILLABLE_COLUMNS and is_empty_cell(merged.get(col))
    ]
    if not merged["_ai_unknown_fields"]:
      merged.pop("_ai_unknown_fields", None)
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
