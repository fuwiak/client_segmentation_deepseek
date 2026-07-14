"""Центральное хранилище данных CRM в памяти процесса."""

from __future__ import annotations

from typing import Any

from app.domain import normalize_phone
from app.services.excel_parser import ParsedWorkbook, enrich_with_orders
from app.services.export_format import merge_enriched_rows, row_has_group, row_keyword_text, row_matches_phone, sort_client_rows
from app.services.fields import enrich_row_computed, refresh_row_for_display


def _row_key(row: dict[str, Any]) -> str:
  return str(row.get("UUID") or row.get("uuid") or row.get("Наименование") or "")


class DataHub:
  def __init__(self) -> None:
    self.parsed: ParsedWorkbook | None = None
    self.orders_parsed: ParsedWorkbook | None = None
    self.results: list[dict[str, Any]] = []
    self.meta: dict[str, Any] = {}
    self.workbook_hash: str | None = None
    self.results_from_cache: bool = False

  def set_workbook(
    self,
    contragents: ParsedWorkbook,
    orders: ParsedWorkbook | None = None,
  ) -> None:
    self.parsed = contragents
    self.orders_parsed = orders
    if orders and orders.rows:
      self.parsed = enrich_with_orders(contragents, orders)

  def relink_orders(self) -> None:
    """Перепривязать заказы к контрагентам (обновление каналов и статистики)."""
    if not self.parsed or not self.orders_parsed or not self.orders_parsed.rows:
      return
    raw_rows = [
      {
        k: v
        for k, v in dict(row).items()
        if k
        not in (
          "_orders_context",
          "_orders_count",
          "_ordered_positions",
          "Заказанные позиции",
        )
      }
      for row in self.parsed.rows
    ]
    contragents = ParsedWorkbook(
      source_type=self.parsed.source_type,
      rows=raw_rows,
      context_columns=list(self.parsed.context_columns),
      segment_columns=list(self.parsed.segment_columns),
      total_rows=len(raw_rows),
      meta=dict(self.parsed.meta),
    )
    self.parsed = enrich_with_orders(contragents, self.orders_parsed)

  def active_rows(self) -> list[dict[str, Any]]:
    if self.parsed and self.parsed.rows:
      base = [refresh_row_for_display(r) for r in self.parsed.rows]
      if self.results:
        return merge_enriched_rows(base, self.results, key_fn=_row_key)
      return base
    if self.results:
      return self.results
    return []

  def set_results(self, results: list[dict[str, Any]], meta: dict[str, Any]) -> None:
    self.results = [enrich_row_computed(r) for r in results]
    self.meta = meta
    self.results_from_cache = False

  def apply_cached_results(self, payload: dict[str, Any]) -> bool:
    results = payload.get("results")
    if not results:
      return False
    self.results = [enrich_row_computed(r) for r in results]
    self.meta = payload.get("meta") or {}
    if payload.get("workbook_key"):
      self.workbook_hash = str(payload["workbook_key"])
    self.results_from_cache = True
    return True

  def data_source_label(self) -> str:
    if self.parsed and self.parsed.meta.get("source") == "moysklad":
      return "moysklad"
    if self.parsed:
      return str(self.parsed.meta.get("source") or "excel")
    return "none"

  def has_parsed_data(self) -> bool:
    return self.parsed is not None and bool(self.parsed.rows)

  def has_data(self) -> bool:
    return bool(self.results) or self.has_parsed_data()

  def get_client(self, client_id: str) -> dict[str, Any] | None:
    key = client_id.strip().lower()
    key_phone = normalize_phone(client_id)
    for row in self.active_rows():
      uid = str(row.get("UUID") or row.get("uuid") or "").lower()
      name = str(row.get("Наименование") or "").strip().lower()
      phone_text = str(row.get("Телефон") or "").strip().lower()
      row_phone = normalize_phone(row.get("Телефон") or row.get("Наименование"))
      if uid == key or name == key or phone_text == key:
        return row
      if key_phone and row_phone and key_phone == row_phone:
        return row
    return None

  def filter_rows(
    self,
    sales_filter: str = "all",
    tag: str = "",
    group: str = "",
    status: str = "",
    q: str = "",
    phone: str = "",
    sort: str = "",
    order: str = "asc",
  ) -> list[dict[str, Any]]:
    rows = self.active_rows()
    if sales_filter == "marketplace":
      rows = [r for r in rows if r.get("Тип продаж") == "маркетплейс"]
    elif sales_filter == "direct":
      rows = [r for r in rows if r.get("Тип продаж") == "прямые продажи"]
    if group:
      rows = [r for r in rows if row_has_group(r, group)]
    if tag:
      tag_l = tag.lower().lstrip("#")
      rows = [
        r
        for r in rows
        if tag_l in str(r.get("Теги") or "").lower()
        or tag_l in str(r.get("Группы") or "").lower()
      ]
    if status:
      rows = [
        r
        for r in rows
        if status.lower() in str(r.get("Статус последнего заказа") or "").lower()
      ]
    if q:
      q_l = q.lower().strip()
      rows = [r for r in rows if q_l in row_keyword_text(r)]
    if phone:
      rows = [r for r in rows if row_matches_phone(r, phone)]
    return sort_client_rows(rows, sort, order)


_hub: DataHub | None = None


def get_data_hub() -> DataHub:
  global _hub
  if _hub is None:
    _hub = DataHub()
  return _hub
