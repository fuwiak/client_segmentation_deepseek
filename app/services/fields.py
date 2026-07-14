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
  actual = len(row.get("_orders_context") or [])
  stored = 0
  for key in ("_orders_count", "Всего заказов"):
    val = row.get(key)
    if val not in (None, ""):
      try:
        stored = max(stored, int(val))
      except (TypeError, ValueError):
        pass
  return max(actual, stored)


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
_PHONE_RE = re.compile(r"^[\+\d\s\(\)\-]{6,}$")
_PERSON_NAME_RE = re.compile(r"^[А-ЯЁ][а-яё]+(?:\s+[А-ЯЁ][а-яё]+){0,2}$")
_INTRO_NAME_RE = re.compile(
  r"(?:\bменя зовут|\bэто)\s+([А-ЯЁ][а-яё]+)",
  re.IGNORECASE,
)
_FOR_RECIPIENT_RE = re.compile(r"\bдля\s+([А-ЯЁ][а-яё]+)", re.IGNORECASE)
_RECIPIENT_IN_ORDER_RE = re.compile(r"[Пп]олучатель\t?\s*([А-ЯЁ][а-яё]+)")
_RECIPIENT_IN_COMMENT_RE = re.compile(
  r"[Пп]олучатель[:\s]+([А-ЯЁ][а-яё]+(?:\s+[А-ЯЁ][а-яё]+){0,2})"
)

FEMALE_NAMES = {
  "ксения", "ольга", "анна", "мария", "елена", "татьяна", "наталья", "ирина",
  "светлана", "юлия", "екатерина", "виктория", "дарья", "полина", "алина",
  "марина", "оксана", "людмила", "галина", "надежда", "вера", "любовь",
  "валентина", "лариса", "нина", "евгения", "александра", "софия", "софья",
  "алёна", "алена", "кристина", "яна", "инна", "жанна", "маргарита", "лидия",
  "элина", "диана", "карина", "ангелина", "вероника", "валерия", "лилия",
  "зоя", "раиса", "тамара", "элла", "снежана", "милана", "арина", "варвара",
  "ульяна", "василиса", "майя", "злата", "стефания", "мирослава", "виолетта",
  "регина", "эмилия", "камилла", "амина", "алиса", "мадина", "гульнара",
  "фаина", "клара", "роза", "нелли", "зинаида", "антонина", "анастасия",
  "настя", "лена", "катя", "маша", "даша", "оля", "таня", "света", "юля",
}
MALE_NAMES = {
  "иван", "пётр", "петр", "сергей", "александр", "андрей", "дмитрий", "алексей",
  "михаил", "николай", "владимир", "евгений", "максим", "артём", "артем",
  "денис", "роман", "антон", "павел", "игорь", "виктор", "олег", "константин",
  "юрий", "василий", "григорий", "борис", "фёдор", "федор", "никита", "илья",
  "кирилл", "тимофей", "матвей", "егор", "глеб", "степан", "богдан", "вадим",
  "руслан", "тимур", "марк", "лев", "данил", "даниил", "арсений", "герман",
  "владислав", "вячеслав", "станислав", "георгий", "платон", "савелий", "ярослав",
  "филипп", "семён", "семен", "тихон", "прохор", "назар", "эмиль", "адам",
  "влад", "коля", "вова", "дима", "слава", "костя", "паша",
}
_MALE_A_ENDING = frozenset({
  "илья", "никита", "фома", "кузьма", "савва", "лука", "миша", "саша", "женя",
})
_FEMALE_PATRONYMIC_SUFFIXES = ("овна", "евна", "ична", "инична")
_MALE_PATRONYMIC_SUFFIXES = ("ович", "евич", "ич")
_COMPANY_MARKERS = (
  "ооо", "оао", "зао", "пао", "ип ", "ип\"", "банк", "ао ", "компания", "фирма",
  "холдинг", "групп", "лизинг", "страхован",
)
_GENDER_LABEL_ALIASES = {
  "мужской": "Мужской",
  "male": "Мужской",
  "m": "Мужской",
  "man": "Мужской",
  "женский": "Женский",
  "female": "Женский",
  "f": "Женский",
  "woman": "Женский",
}


def _gender_from_token(token: str) -> str | None:
  text = token.lower().strip(".,").replace("ё", "е")
  if text in FEMALE_NAMES:
    return "Женский"
  if text in MALE_NAMES:
    return "Мужской"
  patronymic = gender_from_patronymic(text)
  if patronymic:
    return patronymic
  if len(text) >= 3 and text.endswith(("а", "я")) and text not in _MALE_A_ENDING:
    return "Женский"
  return None


def _name_token_order(part_count: int) -> list[int]:
  """Порядок проверки частей ФИО: имя, отчество, фамилия."""
  if part_count <= 1:
    return [0]
  if part_count == 2:
    return [1, 0]
  return [1, 2, 0]


def guess_gender(name: str | None) -> str | None:
  """Пол по ФИО: учитывает «Фамилия Имя» и «Имя Фамилия»."""
  if not name:
    return None
  parts = [part for part in name.strip().split() if part.strip()]
  if not parts:
    return None
  for idx in _name_token_order(len(parts)):
    gender = _gender_from_token(parts[idx])
    if gender:
      return gender
  return None


def normalize_naimenovanie_key(name: str) -> str:
  return name.strip().lower().replace("ё", "е")


def unique_person_naimenovanie(rows: list[dict[str, Any]]) -> list[str]:
  """Уникальные Наименование, похожие на ФИО физлица."""
  seen: set[str] = set()
  result: list[str] = []
  for row in rows:
    name = str(row.get("Наименование") or "").strip()
    if not name:
      continue
    key = normalize_naimenovanie_key(name)
    if key in seen or not _looks_like_person_name(name):
      continue
    seen.add(key)
    result.append(name)
  return result


def build_heuristic_gender_map(names: list[str]) -> dict[str, str]:
  gender_map: dict[str, str] = {}
  for name in names:
    gender = guess_gender(name)
    if gender:
      gender_map[normalize_naimenovanie_key(name)] = gender
  return gender_map


def apply_gender_map_to_rows(
  rows: list[dict[str, Any]],
  gender_map: dict[str, str],
) -> list[dict[str, Any]]:
  if not gender_map:
    return rows
  updated: list[dict[str, Any]] = []
  for row in rows:
    merged = dict(row)
    if is_empty_cell(merged.get("Пол")):
      key = normalize_naimenovanie_key(str(merged.get("Наименование") or ""))
      gender = gender_map.get(key)
      if gender:
        merged["Пол"] = gender
    updated.append(merged)
  return updated


def enrich_gender_by_unique_naimenovanie(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
  """Эвристика по уникальным Наименование → применить Пол ко всем строкам."""
  names = unique_person_naimenovanie(rows)
  gender_map = build_heuristic_gender_map(names)
  return apply_gender_map_to_rows(rows, gender_map)


def normalize_gender_label(value: Any) -> str | None:
  if value in (None, "", "null"):
    return None
  text = str(value).strip().lower().replace("ё", "е")
  if text in _GENDER_LABEL_ALIASES:
    return _GENDER_LABEL_ALIASES[text]
  if text in ("мужской", "женский"):
    return text[:1].upper() + text[1:]
  return None


def gender_from_patronymic(name: str) -> str | None:
  text = name.strip().lower().replace("ё", "е")
  if not text:
    return None
  for suffix in _FEMALE_PATRONYMIC_SUFFIXES:
    if text.endswith(suffix):
      return "Женский"
  for suffix in _MALE_PATRONYMIC_SUFFIXES:
    if text.endswith(suffix) and not text.endswith("овична"):
      return "Мужской"
  return None


def _looks_like_person_name(value: Any) -> bool:
  text = str(value or "").strip()
  if not text or _PHONE_RE.match(text):
    return False
  low = text.lower().replace("ё", "е")
  if any(marker in low for marker in _COMPANY_MARKERS):
    return False
  return bool(_PERSON_NAME_RE.match(text))


def recipient_name_from_row(row: dict[str, Any]) -> str | None:
  for order in row.get("_orders_context") or []:
    for value in order.values():
      match = _RECIPIENT_IN_ORDER_RE.search(str(value))
      if match:
        return match.group(1)
  comments = collect_client_comments(row)
  if comments:
    match = _RECIPIENT_IN_COMMENT_RE.search(comments)
    if match:
      return match.group(1).strip()
  return None


def _names_from_messages(messages: list[dict[str, Any]]) -> list[str]:
  names: list[str] = []
  seen: set[str] = set()

  def add(raw: Any) -> None:
    if not raw:
      return
    text = str(raw).strip()
    if not text or text.startswith("@") or text.isdigit():
      return
    first = text.split()[0].lower().replace("ё", "е")
    if first in {"мамы", "маме", "мама", "папы", "папе", "папа", "жены", "жена", "мужа", "муж", "сына", "сын", "дочери", "дочь"}:
      return
    key = text.lower()
    if key in seen:
      return
    seen.add(key)
    names.append(text)

  for msg in messages:
    add(msg.get("display_name"))
    sender = msg.get("sender")
    if sender and not str(sender).startswith("@"):
      add(sender)
    add(msg.get("chat_name"))
    text = str(msg.get("text") or "")
    for pattern in (_INTRO_NAME_RE, _FOR_RECIPIENT_RE):
      for match in pattern.finditer(text):
        add(match.group(1))
  return names


def collect_gender_name_candidates(row: dict[str, Any]) -> list[str]:
  candidates: list[str] = []
  seen: set[str] = set()

  def add(raw: Any) -> None:
    if not raw:
      return
    text = str(raw).strip()
    if not text:
      return
    key = text.lower()
    if key in seen:
      return
    seen.add(key)
    candidates.append(text)

  add(row.get("Заказчик или получатель"))
  add(recipient_name_from_row(row))
  add(row.get("Имя (для ИП и физ. лиц)"))
  parts = [
    row.get("Фамилия (для ИП и физ. лиц)"),
    row.get("Имя (для ИП и физ. лиц)"),
    row.get("Отчество (для ИП и физ. лиц)"),
  ]
  full_name = " ".join(str(part).strip() for part in parts if part)
  add(full_name)
  if _looks_like_person_name(row.get("Наименование")):
    add(row.get("Наименование"))
  messages = list(row.get("_messenger_context") or []) + list(row.get("_tg_export_context") or [])
  for name in _names_from_messages(messages):
    add(name)
  return candidates


def infer_gender_heuristic(row: dict[str, Any]) -> str | None:
  """Эвристика пола: МойСклад, ФИО, заказы, переписка Telegram/WhatsApp."""
  existing = normalize_gender_label(row.get("Пол"))
  if existing:
    return existing

  middle = row.get("Отчество (для ИП и физ. лиц)")
  if middle:
    patronymic_gender = gender_from_patronymic(str(middle))
    if patronymic_gender:
      return patronymic_gender

  votes: dict[str, int] = {}
  for candidate in collect_gender_name_candidates(row):
    parts = candidate.split()
    if len(parts) >= 3:
      patronymic_gender = gender_from_patronymic(parts[2])
      if patronymic_gender:
        votes[patronymic_gender] = votes.get(patronymic_gender, 0) + 3
    gender = guess_gender(candidate)
    if gender:
      votes[gender] = votes.get(gender, 0) + 1

  if not votes:
    return None
  ranked = sorted(votes.items(), key=lambda item: item[1], reverse=True)
  if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
    return None
  return ranked[0][0]


def apply_resolved_gender(
  merged: dict[str, Any],
  ai_gender: Any,
  ai_fields: list[str],
  *,
  enrichment_fields: list[str] | None = None,
) -> None:
  """Сначала эвристика, затем AI для согласованности (AI перекрывает расхождение)."""
  heuristic = infer_gender_heuristic(merged) if is_empty_cell(merged.get("Пол")) else None
  ai_norm = normalize_gender_label(ai_gender) if ai_gender not in (None, "", "null") else None

  if ai_norm is not None:
    apply_ai_field(merged, "Пол", ai_norm, ai_fields)
    if enrichment_fields is not None and "Пол" not in enrichment_fields:
      enrichment_fields.append("Пол")
    return

  if heuristic and is_empty_cell(merged.get("Пол")):
    apply_ai_field(merged, "Пол", heuristic, ai_fields)
    if enrichment_fields is not None and "Пол" not in enrichment_fields:
      enrichment_fields.append("Пол")


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
  if is_empty_cell(enriched.get("Пол")):
    gender = infer_gender_heuristic(enriched)
    if gender:
      enriched["Пол"] = gender
  return enriched


def ensure_ai_recommendation(row: dict[str, Any]) -> dict[str, Any]:
  """Подставить рекомендацию AI для карточки клиента, если её ещё нет."""
  if row.get("_ai_recommendation"):
    return row
  from app.services.segmentation import SegmentationService

  rec = SegmentationService._heuristic_recommendation(row)
  if not rec:
    return row
  updated = dict(row)
  updated["_ai_recommendation"] = rec
  return updated


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
