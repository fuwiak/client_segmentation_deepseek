"""Центральное хранилище данных CRM в памяти процесса."""

from __future__ import annotations

from typing import Any

from app.services.excel_parser import ParsedWorkbook, enrich_with_orders
from app.services.export_format import merge_enriched_rows
from app.services.fields import enrich_row_computed


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

  def active_rows(self) -> list[dict[str, Any]]:
    if self.parsed and self.parsed.rows:
      base = [enrich_row_computed(r) for r in self.parsed.rows]
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
    for row in self.active_rows():
      uid = str(row.get("UUID") or row.get("uuid") or "").lower()
      name = str(row.get("Наименование") or "").strip().lower()
      if uid == key or name == key:
        return row
    return None

  def filter_rows(
    self,
    sales_filter: str = "all",
    tag: str = "",
    status: str = "",
  ) -> list[dict[str, Any]]:
    rows = self.active_rows()
    if sales_filter == "marketplace":
      rows = [r for r in rows if r.get("Тип продаж") == "маркетплейс"]
    elif sales_filter == "direct":
      rows = [r for r in rows if r.get("Тип продаж") == "прямые продажи"]
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
    return rows


_hub: DataHub | None = None


def get_data_hub() -> DataHub:
  global _hub
  if _hub is None:
    _hub = DataHub()
  return _hub
