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
  """Число заказов для статуса клиента — при расхождении доверяем привязанным заказам."""
  context = row.get("_orders_context") or []
  linked = len(context)

  def _stored_int(key: str) -> int | None:
    val = row.get(key)
    if val in (None, "", "—"):
      return None
    try:
      return int(val)
    except (TypeError, ValueError):
      return None

  linked_total = _stored_int("_orders_count")
  if linked_total is None and linked:
    linked_total = linked
  elif linked_total is not None and linked and linked_total < linked:
    linked_total = linked

  vsego = _stored_int("Всего заказов")

  if linked > 0:
    count = linked_total if linked_total is not None else linked
    if vsego is not None and vsego > count:
      return count
    if vsego is not None:
      return max(count, vsego)
    return count

  if vsego is not None:
    return vsego
  if linked_total is not None:
    return linked_total
  return 0


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
_TG_INLINE_RE = re.compile(r"@([A-Za-z][A-Za-z0-9_]{3,31})")
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
  "alexandra", "maria", "anna", "olga", "elena", "natalia", "natalya", "irina",
  "svetlana", "yulia", "ekaterina", "victoria", "darya", "polina", "alina",
  "marina", "oksana", "ksenia", "sofia", "sofya", "veronika", "valeria",
}
MALE_NAMES = {
  "иван", "пётр", "петр", "сергей", "александр", "андрей", "дмитрий", "алексей",
  "михаил", "николай", "владимир", "евгений", "максим", "артём", "артем",
  "денис", "роман", "антон", "павел", "игорь", "виктор", "олег", "константин",
  "юрий", "василий", "григорий", "борис", "фёдор", "федор", "никита", "илья",
  "кирилл", "тимофей", "матвей", "егор", "глеб", "степан", "богдан", "вадим",
  "руслан", "тимур", "марк", "лев", "данил", "даниил", "арсений", "герман",
  "владислав", "вячеслав", "станислав", "георгий", "платон", "савелий", "ярослав",
  "ростислав", "братислав", "святослав", "мстислав",
  "филипп", "семён", "семен", "тихон", "прохор", "назар", "эмиль", "адам",
  "влад", "коля", "вова", "дима", "слава", "костя", "паша",
  "vladislav", "alexey", "aleksey", "alex", "dmitry", "dmitri", "ivan", "sergey",
  "sergei", "nikolay", "nikolai", "mikhail", "maxim", "artem", "pavel", "roman",
  "denis", "andrey", "andrei", "eugene", "kirill", "timur", "ruslan", "george",
  "yaroslav", "philip", "konstantin", "vladimir", "oleg", "igor", "anton",
  "rostislav", "radislav", "bratislav", "svyatoslav",
}
_MALE_A_ENDING = frozenset({
  "илья", "никита", "фома", "кузьма", "савва", "лука", "миша", "саша", "женя",
  "nikita", "luka", "sasha", "ilya",
})
_FEMALE_PATRONYMIC_SUFFIXES = ("овна", "евна", "ична", "инична")
_MALE_PATRONYMIC_SUFFIXES = ("ович", "евич", "ич")
_COMPANY_MARKERS = (
  "банк", "холдинг", "групп", "лизинг", "страхован", "компания", "фирма",
  "аренда", "доставка", "логистик", "магазин", "салон", "ресторан", "кафе",
  "цветочн", "букетн", "оптов", "розниц",
)
_NON_PERSON_TOKENS = frozenset({
  "аренда", "доставка", "заказ", "оплата", "букет", "витрина", "магазин", "салон",
  "офис", "клиент", "гость", "продажа", "покупка", "услуга", "сервис", "филиал",
  "отдел", "склад", "цветы", "букеты", "курьер", "получатель", "отправитель",
  "контрагент", "абонент", "подписка", "предоплата", "наличные", "безнал",
  "розница", "опт", "промо", "акция", "скидка", "возврат", "обмен", "логистика",
  "касса", "самовывоз", "корпоратив", "маркетплейс",
})
_GENDER_LABEL_ALIASES = {
  "мужской": "Мужской",
  "male": "Мужской",
  "m": "Мужской",
  "man": "Мужской",
  "женский": "Женский",
  "female": "Женский",
  "f": "Женский",
  "woman": "Женский",
  "не применимо": "не применимо",
  "неприменимо": "не применимо",
  "n/a": "не применимо",
  "na": "не применимо",
  "not applicable": "не применимо",
}
GENDER_NOT_APPLICABLE = "не применимо"
_LEGAL_ENTITY_TOKENS = frozenset({
  "ип", "ооо", "ooo", "оао", "oao", "зао", "zao", "пао", "pao", "ао", "ao",
  "чп", "нп", "гуп", "муп", "фгуп", "нко",
})
_CYRILLIC_NAME_TOKEN_RE = re.compile(r"^[А-ЯЁ][а-яё]{2,}$")
_LATIN_NAME_TOKEN_RE = re.compile(r"^[A-Za-z][a-z]{2,}$")

def strip_legal_entity_prefixes(name: str) -> str:
  """Убрать ИП, ООО, ОАО и др. префиксы — оставить ФИО для определения пола."""
  text = str(name or "").strip()
  if not text:
    return ""
  parts = text.split()
  while parts:
    raw = parts[0].strip(".,;:\"'«»()")
    token = re.sub(r"[^\wа-яё]", "", raw, flags=re.IGNORECASE).lower().replace("ё", "е")
    if token in _LEGAL_ENTITY_TOKENS:
      parts.pop(0)
      continue
    break
  return " ".join(parts).strip()


def is_non_person_label(value: Any) -> bool:
  """Название услуги, фирмы или ярлык без ФИО — пол человека не определяется."""
  text = str(value or "").strip()
  if not text or _PHONE_RE.match(text):
    return False
  if gender_from_role_label(text):
    return False
  if _has_person_name_signal(text):
    return False
  cleaned = strip_legal_entity_prefixes(text)
  if not cleaned:
    return True
  low = cleaned.lower().replace("ё", "е")
  if any(marker in low for marker in _COMPANY_MARKERS):
    return True
  parts = _name_parts_for_gender(text)
  if len(parts) == 1:
    token = re.sub(r"[^\wа-яё]", "", parts[0], flags=re.IGNORECASE).lower().replace("ё", "е")
    if token in _NON_PERSON_TOKENS:
      return True
    if token.endswith(("ция", "ение", "ство", "ика", "инг")):
      return True
  return False


def gender_from_surname(token: str) -> str | None:
  """Пол по русской фамилии (-ов/-ова, -ев/-ева…)."""
  if not _CYRILLIC_NAME_TOKEN_RE.match(token):
    return None
  text = token.lower().replace("ё", "е")
  if len(text) < 4:
    return None
  if text.endswith(("ова", "ева", "ина", "ская", "цкая", "ая", "яя")):
    return "Женский"
  if text.endswith(("ов", "ев", "ин", "ский", "цкий", "ой", "ий", "ый")):
    return "Мужской"
  return None


def _gender_from_token(token: str) -> str | None:
  text = token.lower().strip(".,").replace("ё", "е")
  token_norm = re.sub(r"[^\wа-яё]", "", text, flags=re.IGNORECASE)
  if token_norm in _NON_PERSON_TOKENS:
    return None
  if text in FEMALE_NAMES:
    return "Женский"
  if text in MALE_NAMES:
    return "Мужской"
  patronymic = gender_from_patronymic(text)
  if patronymic:
    return patronymic
  if _CYRILLIC_NAME_TOKEN_RE.match(token):
    if token_norm.endswith("слава"):
      return "Женский"
    if token_norm.endswith("слав") and len(token_norm) >= 6:
      return "Мужской"
  surname_gender = gender_from_surname(token)
  if surname_gender:
    return surname_gender
  if _LATIN_NAME_TOKEN_RE.match(token) and len(text) >= 3 and text.endswith("a") and text not in _MALE_A_ENDING:
    return "Женский"
  return None


def _name_parts_for_gender(name: str) -> list[str]:
  text = strip_legal_entity_prefixes(name)
  if not text:
    text = str(name or "").strip()
  if text.startswith("@"):
    text = text[1:]
  parts: list[str] = []
  for raw in text.split():
    token = raw.strip(".,;:")
    if not token or len(token) == 1:
      continue
    norm = re.sub(r"[^\wа-яё]", "", token, flags=re.IGNORECASE).lower().replace("ё", "е")
    if norm in _LEGAL_ENTITY_TOKENS:
      continue
    parts.append(token)
  return parts


def _has_person_name_signal(name: str) -> bool:
  parts = _name_parts_for_gender(name)
  if not parts:
    return False
  for part in parts:
    low = part.lower().replace("ё", "е")
    if low in FEMALE_NAMES or low in MALE_NAMES:
      return True
    if gender_from_patronymic(part) or gender_from_surname(part):
      return True
    if _LATIN_NAME_TOKEN_RE.match(part):
      return True
  return False


def gender_analysis_payload(name: str, heuristic_map: dict[str, str] | None = None) -> dict[str, Any]:
  """Контекст для AI: исходное имя, без ИП/ООО, эвристика."""
  cleaned = strip_legal_entity_prefixes(name)
  heuristic = None
  if heuristic_map is not None:
    heuristic = heuristic_map.get(normalize_naimenovanie_key(name))
  if not heuristic:
    heuristic = gender_from_role_label(name) or (guess_gender(cleaned or name) if cleaned or name else None)
  return {
    "name": name,
    "cleaned_name": cleaned or None,
    "heuristic_guess": heuristic,
  }


def _name_token_order(part_count: int) -> list[int]:
  """Порядок проверки частей ФИО: имя, отчество, фамилия."""
  if part_count <= 1:
    return [0]
  if part_count == 2:
    return [0, 1]
  return [1, 2, 0]


_MASCULINE_ROLE_LABEL_RE = re.compile(
  r"^покупатель(?:\s+с\s+улиц[ыи])?$",
  re.IGNORECASE,
)


def gender_from_role_label(text: str | None) -> str | None:
  """Ролевые подписи без ФИО: «Покупатель с улицы» — мужской род."""
  if not text:
    return None
  low = re.sub(r"\s+", " ", str(text).strip().lower().replace("ё", "е"))
  if _MASCULINE_ROLE_LABEL_RE.match(low):
    return "Мужской"
  return None


def guess_gender(name: str | None) -> str | None:
  """Пол по ФИО: кириллица/латиница, «Фамилия Имя», ник @username, лишние слова."""
  if not name:
    return None
  if is_non_person_label(name):
    return None
  role_gender = gender_from_role_label(name)
  if role_gender:
    return role_gender
  parts = _name_parts_for_gender(name)
  if not parts:
    return None
  for idx in _name_token_order(len(parts)):
    gender = _gender_from_token(parts[idx])
    if gender:
      return gender
  return None


def normalize_naimenovanie_key(name: str) -> str:
  return name.strip().lower().replace("ё", "е")


def unique_naimenovanie_missing_gender(rows: list[dict[str, Any]]) -> list[str]:
  """Уникальные Наименование без пола — кандидаты для эвристики и LLM."""
  seen: set[str] = set()
  result: list[str] = []
  for row in rows:
    if not is_empty_cell(row.get("Пол")):
      continue
    name = str(row.get("Наименование") or "").strip()
    if not name:
      continue
    key = normalize_naimenovanie_key(name)
    if key in seen or not _is_gender_candidate_naimenovanie(name):
      continue
    seen.add(key)
    result.append(name)
  return result


def unique_person_naimenovanie(rows: list[dict[str, Any]]) -> list[str]:
  """Уникальные Наименование, похожие на ФИО физлица."""
  return unique_naimenovanie_missing_gender(rows)


def apply_gender_not_applicable_labels(
  rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
  """Проставить «не применимо» для Наименование-услуг и названий фирм."""
  updated: list[dict[str, Any]] = []
  for row in rows:
    merged = dict(row)
    if is_empty_cell(merged.get("Пол")):
      gender = infer_gender_heuristic(merged)
      if gender:
        merged["Пол"] = gender
      else:
        name = str(merged.get("Наименование") or "").strip()
        if name and is_non_person_label(name):
          merged["Пол"] = GENDER_NOT_APPLICABLE
    updated.append(merged)
  return updated


def build_heuristic_gender_map(names: list[str]) -> dict[str, str]:
  gender_map: dict[str, str] = {}
  for name in names:
    cleaned = strip_legal_entity_prefixes(name)
    gender = guess_gender(cleaned or name)
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
  """Эвристика по уникальным Наименование без пола → применить Пол ко всем строкам."""
  rows = apply_gender_not_applicable_labels(rows)
  names = unique_naimenovanie_missing_gender(rows)
  gender_map = build_heuristic_gender_map(names)
  return apply_gender_map_to_rows(rows, gender_map)


def apply_gender_map_to_hub(
  hub: Any,
  gender_map: dict[str, str],
) -> list[dict[str, Any]]:
  """Записать Пол в parsed/results и вернуть обновлённые строки results."""
  if not gender_map:
    return []
  if getattr(hub, "parsed", None) and hub.parsed and hub.parsed.rows:
    hub.parsed.rows = apply_gender_map_to_rows(hub.parsed.rows, gender_map)
    hub.touch()
  updated: list[dict[str, Any]] = []
  for row in hub.results or []:
    if not is_empty_cell(row.get("Пол")):
      continue
    key = normalize_naimenovanie_key(str(row.get("Наименование") or ""))
    gender = gender_map.get(key)
    if not gender:
      continue
    merged = dict(row)
    merged["Пол"] = gender
    ai_fields = list(merged.get("_ai_fields") or [])
    if "Пол" not in ai_fields:
      ai_fields.append("Пол")
    merged["_ai_fields"] = ai_fields
    unknown = list(merged.get("_ai_unknown_fields") or [])
    if "Пол" in unknown:
      unknown = [col for col in unknown if col != "Пол"]
      merged["_ai_unknown_fields"] = unknown
    updated.append(enrich_row_computed(merged))
  if updated:
    hub.upsert_results(updated)
  return updated


def normalize_gender_label(value: Any) -> str | None:
  if value in (None, "", "null"):
    return None
  text = str(value).strip().lower().replace("ё", "е")
  if text in _GENDER_LABEL_ALIASES:
    return _GENDER_LABEL_ALIASES[text]
  if text in ("мужской", "женский"):
    return text[:1].upper() + text[1:]
  if text == GENDER_NOT_APPLICABLE:
    return GENDER_NOT_APPLICABLE
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


def _is_gender_candidate_naimenovanie(value: Any) -> bool:
  text = str(value or "").strip()
  if text.startswith("@"):
    text = text[1:]
  if not text or _PHONE_RE.match(text):
    return False
  if is_non_person_label(text):
    return False
  if gender_from_role_label(text):
    return True
  cleaned = strip_legal_entity_prefixes(text)
  if not cleaned:
    return False
  low = cleaned.lower().replace("ё", "е")
  if any(marker in low for marker in _COMPANY_MARKERS):
    return False
  if not re.search(r"[a-zа-яё]", low):
    return False
  if len(text) > 80:
    return False
  return _has_person_name_signal(text)


def _looks_like_person_name(value: Any) -> bool:
  text = str(value or "").strip()
  if not text or _PHONE_RE.match(text):
    return False
  if is_non_person_label(text):
    return False
  cleaned = strip_legal_entity_prefixes(text)
  if not cleaned:
    return False
  if _has_person_name_signal(text):
    return True
  if _PERSON_NAME_RE.match(cleaned) and len(cleaned.split()) >= 2:
    return True
  if re.match(r"^[A-Za-z][a-z]+(?:\s+[A-Za-z][a-z]+){0,2}$", cleaned):
    return True
  return False


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
    cleaned = strip_legal_entity_prefixes(str(row.get("Наименование") or ""))
    if cleaned:
      add(cleaned)
  messages = list(row.get("_messenger_context") or []) + list(row.get("_tg_export_context") or [])
  for name in _names_from_messages(messages):
    add(name)
  return candidates


def confident_gender_from_row(row: dict[str, Any]) -> str | None:
  """Уверенный guess по ФИО (имя/фамилия), без голосования по переписке."""
  name = str(row.get("Наименование") or "").strip()
  if name:
    gender = guess_gender(strip_legal_entity_prefixes(name) or name)
    if gender:
      return gender
  parts = [
    row.get("Фамилия (для ИП и физ. лиц)"),
    row.get("Имя (для ИП и физ. лиц)"),
    row.get("Отчество (для ИП и физ. лиц)"),
  ]
  full_name = " ".join(str(part).strip() for part in parts if part)
  if full_name:
    gender = guess_gender(full_name)
    if gender:
      return gender
  return None


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
  """Эвристика по ФИО, затем AI; уверенная эвристика перекрывает ошибочный AI."""
  confident = confident_gender_from_row(merged)
  heuristic = infer_gender_heuristic(merged) if is_empty_cell(merged.get("Пол")) else None
  ai_norm = normalize_gender_label(ai_gender) if ai_gender not in (None, "", "null") else None

  if ai_norm is not None:
    if confident and ai_norm != confident:
      apply_ai_field(merged, "Пол", confident, ai_fields)
    else:
      apply_ai_field(merged, "Пол", ai_norm, ai_fields)
    if enrichment_fields is not None and "Пол" not in enrichment_fields:
      enrichment_fields.append("Пол")
    return

  if confident and is_empty_cell(merged.get("Пол")):
    apply_ai_field(merged, "Пол", confident, ai_fields)
    if enrichment_fields is not None and "Пол" not in enrichment_fields:
      enrichment_fields.append("Пол")
    return

  if heuristic and is_empty_cell(merged.get("Пол")):
    apply_ai_field(merged, "Пол", heuristic, ai_fields)
    if enrichment_fields is not None and "Пол" not in enrichment_fields:
      enrichment_fields.append("Пол")
    return

  if is_empty_cell(merged.get("Пол")):
    name = str(merged.get("Наименование") or "").strip()
    if name and is_non_person_label(name):
      apply_ai_field(merged, "Пол", GENDER_NOT_APPLICABLE, ai_fields)
      if enrichment_fields is not None and "Пол" not in enrichment_fields:
        enrichment_fields.append("Пол")


def extract_tg_nick_from_text(text: Any) -> str | None:
  """@username из строки: целиком «@nick» или встроенный в текст."""
  raw = str(text or "").strip()
  if not raw:
    return None
  if raw.startswith("@"):
    username = raw[1:].strip()
    if _TG_USERNAME_RE.match(username):
      return f"@{username}"
  match = _TG_INLINE_RE.search(raw)
  if match and _TG_USERNAME_RE.match(match.group(1)):
    return f"@{match.group(1)}"
  return None


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


def tg_nick_from_phone_map(
  phone: Any,
  phone_username_map: dict[str, str] | None,
) -> str | None:
  """@username по телефону из TG Data Export или кэша Bot API (не lookup по API)."""
  if not phone_username_map:
    return None
  from app.services.telegram_export import normalize_export_phone

  key = normalize_export_phone(str(phone or ""))
  if not key:
    return None
  username = phone_username_map.get(key)
  if not username:
    return None
  clean = str(username).strip().lstrip("@")
  if _TG_USERNAME_RE.match(clean):
    return f"@{clean}"
  return None


def extract_tg_nick_from_row(
  row: dict[str, Any],
  *,
  phone_username_map: dict[str, str] | None = None,
) -> str | None:
  """ТГ ник из телефона, Наименования, комментариев и переписки."""
  for key in ("ТГ ник",):
    nick = extract_tg_nick_from_text(row.get(key))
    if nick:
      return nick
  for key in ("Телефон",):
    nick = extract_tg_nick_from_text(row.get(key))
    if nick:
      return nick
    nick = tg_nick_from_phone_map(row.get(key), phone_username_map)
    if nick:
      return nick
  for key in ("Наименование", *COUNTERPARTY_COMMENT_KEYS):
    nick = extract_tg_nick_from_text(row.get(key))
    if nick:
      return nick
  nick = tg_nick_from_phone_map(row.get("Наименование"), phone_username_map)
  if nick:
    return nick
  return extract_tg_nick_from_messages(
    list(row.get("_messenger_context") or [])
    + list(row.get("_tg_export_context") or [])
  )


def enrich_tg_nick_by_phone(
  rows: list[dict[str, Any]],
  phone_username_map: dict[str, str] | None,
) -> list[dict[str, Any]]:
  """Подставить ТГ ник по телефону для всех строк без ника."""
  if not phone_username_map:
    return rows
  updated: list[dict[str, Any]] = []
  for row in rows:
    merged = dict(row)
    if is_empty_cell(merged.get("ТГ ник")):
      nick = extract_tg_nick_from_row(merged, phone_username_map=phone_username_map)
      if nick:
        merged["ТГ ник"] = nick
    updated.append(merged)
  return updated


def apply_tg_nick_by_phone_to_hub(hub: Any) -> list[dict[str, Any]]:
  """Записать ТГ ник в parsed/results по индексу телефон→username на hub."""
  phone_map = getattr(hub, "phone_username_map", None) or {}
  if not phone_map:
    return []
  if getattr(hub, "parsed", None) and hub.parsed and hub.parsed.rows:
    hub.parsed.rows = enrich_tg_nick_by_phone(hub.parsed.rows, phone_map)
    hub.touch()
  updated: list[dict[str, Any]] = []
  for row in hub.results or []:
    if not is_empty_cell(row.get("ТГ ник")):
      continue
    nick = extract_tg_nick_from_row(dict(row), phone_username_map=phone_map)
    if not nick:
      continue
    merged = dict(row)
    merged["ТГ ник"] = nick
    ai_fields = list(merged.get("_ai_fields") or [])
    if "ТГ ник" not in ai_fields:
      ai_fields.append("ТГ ник")
    merged["_ai_fields"] = ai_fields
    unknown = list(merged.get("_ai_unknown_fields") or [])
    if "ТГ ник" in unknown:
      unknown = [col for col in unknown if col != "ТГ ник"]
      merged["_ai_unknown_fields"] = unknown or None
      if merged["_ai_unknown_fields"] is None:
        merged.pop("_ai_unknown_fields", None)
    updated.append(enrich_row_computed(merged, phone_username_map=phone_map))
  if updated:
    hub.upsert_results(updated)
  return updated


def enrich_row_computed(
  row: dict[str, Any],
  *,
  phone_username_map: dict[str, str] | None = None,
) -> dict[str, Any]:
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
  if is_empty_cell(enriched.get("ТГ ник")):
    tg = extract_tg_nick_from_row(enriched, phone_username_map=phone_username_map)
    if tg:
      enriched["ТГ ник"] = tg
  if is_empty_cell(enriched.get("Пол")):
    gender = infer_gender_heuristic(enriched)
    if gender:
      enriched["Пол"] = gender
    else:
      name = str(enriched.get("Наименование") or "").strip()
      if name and is_non_person_label(name):
        enriched["Пол"] = GENDER_NOT_APPLICABLE
  else:
    correction = confident_gender_from_row(enriched)
    existing = normalize_gender_label(enriched.get("Пол"))
    if correction and existing and correction != existing:
      enriched["Пол"] = correction
  from app.services.tag_rules import normalize_tags_field

  tags = normalize_tags_field(enriched.get("Теги"))
  if tags:
    enriched["Теги"] = tags
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


def _format_rub_short(value: Any) -> str:
  try:
    num = float(value)
  except (TypeError, ValueError):
    return "—"
  if num == int(num):
    return f"{int(num):,}".replace(",", " ") + " р."
  return f"{num:,.0f}".replace(",", " ") + " р."


def build_client_history_summary(row: dict[str, Any]) -> str | None:
  """Развёрнутое саммари истории клиента (профиль и заказы), не рекомендация оператору."""
  parts: list[str] = []
  name = str(row.get("Наименование") or "Клиент").strip()
  orders_n = order_count_for_row(row)
  status = row.get("Статус") or client_status_from_orders(row)

  profile_bits = [name]
  role = row.get("Заказчик или получатель")
  if role:
    profile_bits.append(f"роль: {role}")
  gender = row.get("Пол")
  if gender and gender != GENDER_NOT_APPLICABLE:
    profile_bits.append(f"пол: {gender}")
  parts.append(" · ".join(profile_bits) + ".")

  loyalty_bits = [f"статус {status}", f"{orders_n} заказов"]
  if row.get("ВИП") == "да":
    loyalty_bits.append("VIP")
  if row.get("Постоянный клиент") == "да":
    loyalty_bits.append("постоянный клиент")
  if not is_empty_cell(row.get("Средний чек")):
    loyalty_bits.append(f"средний чек {_format_rub_short(row.get('Средний чек'))}")
  if not is_empty_cell(row.get("Баллы начисленные")):
    loyalty_bits.append(f"баллы {row.get('Баллы начисленные')}")
  if row.get("Дата последнего заказа"):
    loyalty_bits.append(f"последний заказ {row.get('Дата последнего заказа')}")
  parts.append("Лояльность: " + ", ".join(loyalty_bits) + ".")

  groups = str(row.get("Группы") or "").strip()
  if groups:
    parts.append(f"Сегменты: {groups}.")
  tags = str(row.get("Теги") or "").strip()
  if tags:
    parts.append(f"Теги: {tags}.")

  sales_bits = [
    str(row.get("Тип продаж") or row.get("Тип канала продаж") or "").strip(),
    str(row.get("Канал продаж") or "").strip(),
  ]
  sales_bits = [bit for bit in sales_bits if bit]
  if sales_bits:
    parts.append("Каналы: " + " / ".join(dict.fromkeys(sales_bits)) + ".")

  orders = row.get("_orders_context") or []
  if orders:
    order_lines: list[str] = []
    for order in orders[-4:]:
      num = order.get("№") or order.get("Номер") or "—"
      date = str(order.get("Дата") or order.get("Момент времени") or "")[:10] or "—"
      amount = _format_rub_short(order.get("Сумма"))
      channel = str(order.get("Канал продаж") or "").strip()
      line = f"№{num} ({date}, {amount}"
      if channel:
        line += f", {channel}"
      line += ")"
      order_lines.append(line)
    if order_lines:
      parts.append("История заказов: " + "; ".join(order_lines) + ".")

  positions = str(row.get("Заказанные позиции") or "").strip()
  if positions:
    parts.append(f"Позиции: {positions[:220]}{'…' if len(positions) > 220 else ''}.")

  messages = row.get("_messenger_context") or []
  if messages:
    inbound = sum(1 for m in messages if m.get("direction") == "in")
    outbound = sum(1 for m in messages if m.get("direction") == "out")
    parts.append(
      f"Переписка: {len(messages)} сообщений"
      f" (входящих {inbound}, исходящих {outbound})."
    )
    last_text = str(messages[-1].get("text") or "").strip()
    if last_text:
      parts.append(f"Последнее сообщение: «{last_text[:160]}{'…' if len(last_text) > 160 else ''}».")

  comments = collect_client_comments(row).strip()
  if comments:
    parts.append(
      f"Комментарии: {comments[:200]}{'…' if len(comments) > 200 else ''}."
    )

  if len(parts) < 2:
    return None
  return " ".join(parts)


def apply_ai_client_summary(merged: dict[str, Any], value: Any) -> None:
  text = str(value or "").strip()
  if text:
    merged["_ai_client_summary"] = text


def ensure_ai_client_summary(row: dict[str, Any]) -> dict[str, Any]:
  """Подставить саммари истории клиента, если AI ещё не заполнил."""
  if row.get("_ai_client_summary"):
    return row
  summary = build_client_history_summary(row)
  if not summary:
    return row
  updated = dict(row)
  updated["_ai_client_summary"] = summary
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
  if col == "Теги":
    from app.services.tag_rules import normalize_tags_field

    normalized = normalize_tags_field(new_value)
    if not normalized:
      return
    new_value = normalized
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
