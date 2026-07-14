"""Маппинг русских полей Excel/МойСклад → snake_case колонки Postgres."""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

# Основные колонки customers (snake_case в БД)
CUSTOMER_SCALAR_FIELDS: dict[str, str] = {
    "UUID": "id",
    "uuid": "id",
    "Наименование": "name",
    "Телефон": "phone",
    "Статус": "status",
    "Тип карала продаж": "sales_channel_type",
    "Канал продаж": "sales_channel",
    "Тип продаж": "sales_type",
    "Средний чек": "average_check",
    "Дата последнего заказа": "last_order_date",
    "Всего заказов": "total_orders",
    "Баллы начисленные": "bonus_points",
    "Группы": "groups_text",
    "Заказчик или получатель": "customer_or_recipient",
    "Фактический адрес": "actual_address",
    "Фактический адрес (Комментарий)": "actual_address_comment",
    "Тип контрагента": "counterparty_type",
    "Пол": "gender",
    "E-mail": "email",
    "ТГ ник": "telegram_nick",
    "Код": "code",
    "Внешний код": "external_code",
    "Полное наименование": "full_name",
    "Фамилия (для ИП и физ. лиц)": "last_name",
    "Имя (для ИП и физ. лиц)": "first_name",
    "Отчество (для ИП и физ. лиц)": "middle_name",
    "Юридический адрес": "legal_address",
    "Юридический адрес (Комментарий)": "legal_address_comment",
    "ИНН": "inn",
    "КПП": "kpp",
    "ОКПО": "okpo",
    "Факс": "fax",
    "БИК": "bik",
    "Банк": "bank",
    "Местонахождение": "location",
    "К/с": "corr_account",
    "Р/с": "bank_account",
    "Номер дисконтной карты": "discount_card",
    "ОГРН": "ogrn",
    "ОГРНИП": "ogrnip",
    "Номер свидетельства": "certificate_number",
    "Дата свидетельства": "certificate_date",
    "Дата рождения": "birth_date",
    "Архивный": "archived_label",
    "Комментарий": "comment_text",
    "Теги": "tags",
    "Саммари": "summary",
    "Статус последнего заказа": "last_order_status",
    "ВИП": "is_vip_label",
    "Постоянный клиент": "is_regular_label",
    "Заказанные позиции": "ordered_positions_text",
}

ORDER_SCALAR_FIELDS: dict[str, str] = {
    "№": "order_number",
    "Контрагент": "customer_name",
    "Дата": "order_date",
    "Сумма": "amount",
    "Статус": "status",
    "Комментарий": "comment_text",
    "Канал продаж": "sales_channel",
    "Позиции": "positions_text",
}

CUSTOMER_DB_COLUMNS: list[str] = [
    "id",
    "moysklad_id",
    "name",
    "phone",
    "email",
    "status",
    "sales_type",
    "sales_channel_type",
    "sales_channel",
    "average_check",
    "last_order_date",
    "total_orders",
    "bonus_points",
    "groups_text",
    "customer_or_recipient",
    "gender",
    "telegram_nick",
    "tags",
    "summary",
    "actual_address",
    "actual_address_comment",
    "counterparty_type",
    "code",
    "external_code",
    "full_name",
    "last_name",
    "first_name",
    "middle_name",
    "legal_address",
    "legal_address_comment",
    "inn",
    "kpp",
    "okpo",
    "fax",
    "bik",
    "bank",
    "location",
    "corr_account",
    "bank_account",
    "discount_card",
    "ogrn",
    "ogrnip",
    "certificate_number",
    "certificate_date",
    "birth_date",
    "archived_label",
    "comment_text",
    "last_order_status",
    "is_vip",
    "is_regular",
    "ordered_positions_text",
    "source",
    "row_data",
]

ORDER_DB_COLUMNS: list[str] = [
    "id",
    "moysklad_id",
    "order_number",
    "customer_name",
    "moysklad_agent_id",
    "agent_phone",
    "order_date",
    "amount",
    "status",
    "comment_text",
    "sales_channel",
    "positions_text",
    "positions",
    "source",
    "row_data",
]


def resolve_customer_id(row: dict[str, Any]) -> str:
    for key in ("UUID", "uuid", "_moysklad_id"):
        val = row.get(key)
        if val not in (None, ""):
            return str(val)
    return str(uuid.uuid4())


def resolve_order_id(row: dict[str, Any]) -> str:
    for key in ("_moysklad_id", "UUID", "uuid"):
        val = row.get(key)
        if val not in (None, ""):
            return str(val)
    number = row.get("№")
    if number not in (None, ""):
        return f"order:{number}"
    return str(uuid.uuid4())


def _parse_decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value).replace(",", ".").replace(" ", ""))
    except (InvalidOperation, ValueError):
        return None


def _parse_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(str(value).replace(",", ".").replace(" ", "")))
    except (TypeError, ValueError):
        return None


def _parse_bool_label(value: Any) -> bool | None:
    if value in (None, ""):
        return None
    text = str(value).strip().lower()
    if text in {"да", "yes", "true", "1", "vip", "вип"}:
        return True
    if text in {"нет", "no", "false", "0"}:
        return False
    return None


def _parse_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    text = str(value).strip()
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%d",
        "%d.%m.%Y",
        "%d.%m.%Y %H:%M:%S",
    ):
        try:
            return datetime.strptime(text[:26], fmt)
        except ValueError:
            continue
    return None


def _parse_date(value: Any) -> date | None:
    dt = _parse_datetime(value)
    return dt.date() if dt else None


def customer_row_to_db(row: dict[str, Any], *, source: str = "moysklad") -> dict[str, Any]:
    """Строка CRM → запись для INSERT в customers."""
    record: dict[str, Any] = {col: None for col in CUSTOMER_DB_COLUMNS}
    record["id"] = resolve_customer_id(row)
    record["moysklad_id"] = row.get("_moysklad_id") or row.get("UUID") or row.get("uuid")
    record["source"] = str(row.get("_source") or source)
    record["row_data"] = json.loads(json.dumps(row, default=str))

    for src_key, db_key in CUSTOMER_SCALAR_FIELDS.items():
        if db_key == "id":
            continue
        val = row.get(src_key)
        if val in (None, ""):
            continue
        if db_key in {"average_check", "bonus_points"}:
            record[db_key] = _parse_decimal(val)
        elif db_key == "total_orders":
            record[db_key] = _parse_int(val)
        elif db_key == "last_order_date":
            record[db_key] = _parse_datetime(val)
        elif db_key == "birth_date":
            record[db_key] = _parse_date(val)
        elif db_key == "is_vip_label":
            record["is_vip"] = _parse_bool_label(val)
        elif db_key == "is_regular_label":
            record["is_regular"] = _parse_bool_label(val)
        else:
            record[db_key] = str(val).strip() if val is not None else None

    if row.get("_ordered_positions"):
        record["ordered_positions_text"] = record.get("ordered_positions_text") or row.get(
            "Заказанные позиции"
        )

    return record


def order_row_to_db(row: dict[str, Any], *, source: str = "moysklad") -> dict[str, Any]:
    """Строка заказа → запись для INSERT в orders."""
    record: dict[str, Any] = {col: None for col in ORDER_DB_COLUMNS}
    record["id"] = resolve_order_id(row)
    record["moysklad_id"] = row.get("_moysklad_id")
    record["moysklad_agent_id"] = row.get("_moysklad_agent_id")
    record["agent_phone"] = row.get("_moysklad_agent_phone")
    record["source"] = str(row.get("_source") or source)
    record["positions"] = row.get("_positions") or []
    record["row_data"] = json.loads(json.dumps(row, default=str))

    for src_key, db_key in ORDER_SCALAR_FIELDS.items():
        val = row.get(src_key)
        if val in (None, ""):
            continue
        if db_key == "amount":
            record[db_key] = _parse_decimal(val)
        elif db_key == "order_date":
            record[db_key] = _parse_datetime(val)
        else:
            record[db_key] = str(val).strip() if val is not None else None

    return record
