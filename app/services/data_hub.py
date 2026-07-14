"""Центральное хранилище данных CRM в памяти процесса."""

from __future__ import annotations

from typing import Any

from app.domain import normalize_phone
from app.services.excel_parser import ParsedWorkbook, enrich_with_orders, orders_for_client_row
from app.services.export_format import (
  collect_group_counts,
  merge_enriched_rows,
  row_has_group,
  row_keyword_text,
  row_matches_phone,
  sales_channels_index,
  sales_channel_types_index,
  sort_client_rows,
)
from app.services.fields import enrich_row_computed, refresh_row_for_display, row_sales_type_filter_value, order_count_for_row, ensure_ai_recommendation, ensure_ai_client_summary, enrich_gender_by_unique_naimenovanie, enrich_tg_nick_by_phone, is_empty_cell, is_non_person_label


def _rows_need_gender_enrich(rows: list[dict[str, Any]]) -> bool:
  for row in rows:
    if not is_empty_cell(row.get("Пол")):
      continue
    name = str(row.get("Наименование") or "").strip()
    if name and not is_non_person_label(name):
      return True
  return False


def _row_key(row: dict[str, Any]) -> str:
  return str(row.get("UUID") or row.get("uuid") or row.get("Наименование") or "")


def _register_client_index_keys(
  row: dict[str, Any],
  index: dict[str, dict[str, Any]],
) -> None:
  uid = str(row.get("UUID") or row.get("uuid") or "").strip().lower()
  if uid:
    index[uid] = row
  ms_id = str(row.get("_moysklad_id") or "").strip().lower()
  if ms_id:
    index[ms_id] = row
  name = str(row.get("Наименование") or "").strip().lower()
  if name:
    index[name] = row
  phone_text = str(row.get("Телефон") or "").strip().lower()
  if phone_text:
    index[phone_text] = row
  for raw in (row.get("Телефон"), row.get("Наименование"), row.get("Код")):
    phone = normalize_phone(str(raw) if raw else None)
    if phone:
      index[phone] = row


class DataHub:
  def __init__(self) -> None:
    self.parsed: ParsedWorkbook | None = None
    self.orders_parsed: ParsedWorkbook | None = None
    self.results: list[dict[str, Any]] = []
    self.meta: dict[str, Any] = {}
    self.workbook_hash: str | None = None
    self.results_from_cache: bool = False
    self.version: int = 0
    self._active_rows_cache: tuple[int, list[dict[str, Any]]] | None = None
    self._filter_cache: dict[str, list[dict[str, Any]]] = {}
    self._client_index: dict[str, dict[str, Any]] | None = None
    self._client_index_version: int = -1
    self._results_by_key: dict[str, dict[str, Any]] | None = None
    self._results_index_version: int = -1
    self._order_lookup_cache: dict[str, dict[str, Any]] | None = None
    self._order_lookup_version: int = -1
    self._agent_segment_cache: tuple[int, tuple[dict[str, set[str]], dict[str, str]]] | None = None
    self._phone_username_map: dict[str, str] = {}

  @property
  def phone_username_map(self) -> dict[str, str]:
    return self._phone_username_map

  def set_phone_username_map(self, phone_username_map: dict[str, str]) -> None:
    self._phone_username_map = dict(phone_username_map)
    self.touch()

  def touch(self) -> None:
    self.version += 1
    self._active_rows_cache = None
    self._filter_cache.clear()
    self._client_index = None
    self._results_by_key = None
    self._order_lookup_cache = None
    self._agent_segment_cache = None

  def set_workbook(
    self,
    contragents: ParsedWorkbook,
    orders: ParsedWorkbook | None = None,
  ) -> None:
    self.parsed = contragents
    self.orders_parsed = orders
    if orders and orders.rows:
      self.parsed = enrich_with_orders(contragents, orders)
    self.touch()

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
          "_order_channels_all",
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
    self.touch()

  def active_rows(self) -> list[dict[str, Any]]:
    if self._active_rows_cache and self._active_rows_cache[0] == self.version:
      return self._active_rows_cache[1]
    if self.parsed and self.parsed.rows:
      if self.parsed.meta.get("from_cache"):
        base = self.parsed.rows
      else:
        base = [refresh_row_for_display(r) for r in self.parsed.rows]
      if self.results:
        rows = merge_enriched_rows(base, self.results, key_fn=_row_key)
      else:
        rows = base
    elif self.results:
      rows = self.results
    else:
      rows = []
    if _rows_need_gender_enrich(rows):
      rows = enrich_gender_by_unique_naimenovanie(rows)
    rows = enrich_tg_nick_by_phone(rows, self._phone_username_map)
    self._active_rows_cache = (self.version, rows)
    return rows

  def set_results(self, results: list[dict[str, Any]], meta: dict[str, Any]) -> None:
    self.results = [enrich_row_computed(r) for r in results]
    self.meta = meta
    self.results_from_cache = False
    self.touch()

  def upsert_results(self, rows: list[dict[str, Any]]) -> None:
    """Добавить или обновить AI-результаты по ключу строки (lazy evaluation)."""
    if not rows:
      return
    by_key = {_row_key(r): enrich_row_computed(r) for r in self.results}
    for row in rows:
      by_key[_row_key(row)] = enrich_row_computed(row)
    self.results = list(by_key.values())
    self.results_from_cache = False
    self.touch()

  def apply_cached_results(self, payload: dict[str, Any]) -> bool:
    results = payload.get("results")
    if not results:
      return False
    self.results = list(results)
    self.meta = payload.get("meta") or {}
    if payload.get("workbook_key"):
      self.workbook_hash = str(payload["workbook_key"])
    self.results_from_cache = True
    self.touch()
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

  def _ensure_client_index(self) -> dict[str, dict[str, Any]]:
    if self._client_index is not None and self._client_index_version == self.version:
      return self._client_index
    index: dict[str, dict[str, Any]] = {}
    if self.parsed and self.parsed.rows:
      for row in self.parsed.rows:
        _register_client_index_keys(row, index)
    elif self.results:
      for row in self.results:
        _register_client_index_keys(row, index)
    self._client_index = index
    self._client_index_version = self.version
    return index

  def _ensure_results_index(self) -> dict[str, dict[str, Any]]:
    if self._results_by_key is not None and self._results_index_version == self.version:
      return self._results_by_key
    self._results_by_key = {_row_key(row): row for row in self.results}
    self._results_index_version = self.version
    return self._results_by_key

  def lookup_client_row(self, client_id: str) -> dict[str, Any] | None:
    """O(1) поиск строки клиента без полного active_rows()."""
    index = self._ensure_client_index()
    key = client_id.strip().lower()
    row = index.get(key)
    if row is not None:
      return row
    key_phone = normalize_phone(client_id)
    if key_phone:
      return index.get(key_phone)
    return None

  def get_client(self, client_id: str) -> dict[str, Any] | None:
    row = self.lookup_client_row(client_id)
    if not row:
      return None
    display = refresh_row_for_display(dict(row))
    client = display
    if self.results:
      overlay = self._ensure_results_index().get(_row_key(row))
      if overlay:
        merged = merge_enriched_rows([display], [overlay], key_fn=_row_key)
        client = merged[0] if merged else display
    client = self._ensure_client_orders_context(client)
    return ensure_ai_client_summary(ensure_ai_recommendation(client))

  def _ensure_client_orders_context(self, row: dict[str, Any]) -> dict[str, Any]:
    orders = self.resolve_order_entities(row.get("_orders_context") or [])
    if not orders and self.orders_parsed and self.orders_parsed.rows:
      found = orders_for_client_row(
        row,
        self.orders_parsed.rows,
        contragent_rows=self.parsed.rows if self.parsed else None,
      )
      orders = self.resolve_order_entities(found)
    if not orders:
      return row
    updated = dict(row)
    updated["_orders_context"] = orders[:20]
    linked_total = int(row.get("_orders_count") or 0)
    if linked_total < len(orders):
      linked_total = len(orders)
    updated["_orders_count"] = linked_total
    if linked_total:
      updated["Всего заказов"] = linked_total
    return updated

  def _order_lookup(self) -> dict[str, dict[str, Any]]:
    if self._order_lookup_cache is not None and self._order_lookup_version == self.version:
      return self._order_lookup_cache
    order_by_key: dict[str, dict[str, Any]] = {}
    if not self.orders_parsed or not self.orders_parsed.rows:
      self._order_lookup_cache = order_by_key
      self._order_lookup_version = self.version
      return order_by_key
    for order in self.orders_parsed.rows:
      for key in (order.get("_moysklad_id"), order.get("№"), order.get("Номер")):
        text = str(key or "").strip()
        if text:
          order_by_key[text] = order
    self._order_lookup_cache = order_by_key
    self._order_lookup_version = self.version
    return order_by_key

  def _agent_segment_indexes(self) -> tuple[dict[str, set[str]], dict[str, str]]:
    if self._agent_segment_cache and self._agent_segment_cache[0] == self.version:
      return self._agent_segment_cache[1]
    order_rows = self.orders_parsed.rows if self.orders_parsed else []
    indexes = (sales_channels_index(order_rows), sales_channel_types_index(order_rows))
    self._agent_segment_cache = (self.version, indexes)
    return indexes

  def resolve_order_entities(self, orders: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Подтянуть полные строки заказов из orders_parsed (позиции, канал, статус)."""
    order_by_key = self._order_lookup()
    if not order_by_key:
      return orders
    resolved: list[dict[str, Any]] = []
    seen: set[str] = set()
    for order in orders:
      lookup_key = str(
        order.get("_moysklad_id") or order.get("№") or order.get("Номер") or ""
      ).strip()
      item = order_by_key.get(lookup_key) if lookup_key else None
      item = item or order
      item_key = str(
        item.get("_moysklad_id") or item.get("№") or item.get("Номер") or id(item)
      )
      if item_key in seen:
        continue
      seen.add(item_key)
      resolved.append(item)
    return resolved

  def get_client_orders(
    self,
    client_id: str,
  ) -> tuple[dict[str, Any] | None, list[dict[str, Any]], int]:
    """Быстрый путь для HTMX-раскрытия заказов в карточке клиента."""
    row = self.lookup_client_row(client_id)
    if not row:
      return None, [], 0
    row = dict(row)
    orders: list[dict[str, Any]] = []
    if self.orders_parsed and self.orders_parsed.rows:
      found = orders_for_client_row(
        row,
        self.orders_parsed.rows,
        contragent_rows=self.parsed.rows if self.parsed else None,
      )
      orders = self.resolve_order_entities(found)
    if not orders:
      orders = self.resolve_order_entities(row.get("_orders_context") or [])
    total = order_count_for_row(row)
    if len(orders) > total:
      total = len(orders)
    return row, orders, total

  def sync_orders_context_from_order_rows(self) -> None:
    """Обновить _orders_context у клиентов после догрузки позиций без enrich_with_orders."""
    if not self.parsed or not self.parsed.rows or not self.orders_parsed:
      return
    for cp_row in self.parsed.rows:
      ctx = cp_row.get("_orders_context")
      if not ctx:
        continue
      cp_row["_orders_context"] = self.resolve_order_entities(ctx)[:20]
    self.touch()

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
    cache_key = (
      f"{self.version}:{sales_filter}:{tag}:{group}:{status}:{q}:{phone}:{sort}:{order}"
    )
    cached = self._filter_cache.get(cache_key)
    if cached is not None:
      return cached

    rows = self.active_rows()
    agent_channels, agent_channel_types = self._agent_segment_indexes()
    if sales_filter == "marketplace":
      rows = [r for r in rows if "маркетплейс" in row_sales_type_filter_value(r)]
    elif sales_filter == "direct":
      rows = [
        r for r in rows
        if "прямы" in row_sales_type_filter_value(r)
      ]
    if group:
      rows = [
        r for r in rows
        if row_has_group(
          r,
          group,
          agent_channels=agent_channels,
          agent_channel_types=agent_channel_types,
        )
      ]
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
    rows = sort_client_rows(rows, sort, order)
    self._filter_cache[cache_key] = rows
    return rows

  def filter_rows_with_groups(
    self,
    *,
    sales_filter: str = "all",
    tag: str = "",
    group: str = "",
    status: str = "",
    q: str = "",
    phone: str = "",
    sort: str = "",
    order: str = "asc",
  ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    """Отфильтровать клиентов и вернуть (строки, облако групп, всего до фильтра группы)."""
    base_rows = self.filter_rows(
      sales_filter=sales_filter,
      tag=tag,
      group="",
      status=status,
      q=q,
      phone=phone,
      sort=sort,
      order=order,
    )
    agent_channels, agent_channel_types = self._agent_segment_indexes()
    group_options = collect_group_counts(
      base_rows,
      agent_channels=agent_channels,
      agent_channel_types=agent_channel_types,
    )
    if group:
      rows = [
        r for r in base_rows
        if row_has_group(
          r,
          group,
          agent_channels=agent_channels,
          agent_channel_types=agent_channel_types,
        )
      ]
    else:
      rows = base_rows
    return rows, group_options, len(base_rows)


_hub: DataHub | None = None


def get_data_hub() -> DataHub:
  global _hub
  if _hub is None:
    _hub = DataHub()
  return _hub
