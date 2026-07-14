"""Дашборд CRM — метрики с фильтром периода."""

from __future__ import annotations

import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

PERIOD_LABELS = {
  "day": "День",
  "week": "Неделя",
  "month": "Месяц",
  "year": "Год",
  "all": "За всё время",
  "custom": "Произвольный",
}


@dataclass
class MetricBlock:
  total: float | int = 0
  growth_pct: float | None = None
  monthly: list[tuple[str, float | int]] = field(default_factory=list)


@dataclass
class DashboardData:
  period: str = "month"
  period_label: str = "Месяц"
  date_from: date | None = None
  date_to: date | None = None
  clients: MetricBlock = field(default_factory=MetricBlock)
  orders: MetricBlock = field(default_factory=MetricBlock)
  revenue: MetricBlock = field(default_factory=MetricBlock)
  marketplace_clients: MetricBlock = field(default_factory=MetricBlock)
  marketplace_breakdown: dict[str, MetricBlock] = field(default_factory=dict)
  direct_clients: MetricBlock = field(default_factory=MetricBlock)
  direct_breakdown: dict[str, MetricBlock] = field(default_factory=dict)
  repeat_clients: MetricBlock = field(default_factory=MetricBlock)
  open_tasks: int = 0
  open_dialogs: int = 0
  orders_by_status: dict[str, int] = field(default_factory=dict)


def _parse_date(value: Any) -> datetime | None:
  if value is None:
    return None
  if isinstance(value, datetime):
    return value
  if isinstance(value, date):
    return datetime.combine(value, datetime.min.time())
  text = str(value).strip()
  for fmt in ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y", "%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
    try:
      return datetime.strptime(text[:19], fmt)
    except ValueError:
      continue
  try:
    return datetime.fromisoformat(text)
  except ValueError:
    return None


def _period_bounds(
  period: str,
  date_from: date | None = None,
  date_to: date | None = None,
) -> tuple[datetime, datetime, datetime, datetime]:
  now = datetime.now()
  end = datetime.combine(date_to or now.date(), datetime.max.time())
  if period == "day":
    start = datetime.combine(end.date(), datetime.min.time())
    prev_start = start - timedelta(days=1)
    prev_end = start - timedelta(seconds=1)
  elif period == "week":
    start = end - timedelta(days=7)
    prev_start = start - timedelta(days=7)
    prev_end = start - timedelta(seconds=1)
  elif period == "month":
    start = end - timedelta(days=30)
    prev_start = start - timedelta(days=30)
    prev_end = start - timedelta(seconds=1)
  elif period == "year":
    start = end - timedelta(days=365)
    prev_start = start - timedelta(days=365)
    prev_end = start - timedelta(seconds=1)
  elif period == "custom" and date_from:
    start = datetime.combine(date_from, datetime.min.time())
    span = (end - start).days or 1
    prev_end = start - timedelta(seconds=1)
    prev_start = prev_end - timedelta(days=span)
  else:
    start = datetime(2000, 1, 1)
    prev_start = start
    prev_end = start
  return start, end, prev_start, prev_end


def _growth(current: float | int, previous: float | int) -> float | None:
  if previous == 0:
    return 100.0 if current > 0 else None
  return round((current - previous) / previous * 100, 1)


def _month_key(dt: datetime) -> str:
  return dt.strftime("%Y-%m")


def _month_key(dt: datetime) -> str:
  return dt.strftime("%Y-%m")


class _DashboardCache:
  def __init__(self, *, ttl: float = 60.0, max_items: int = 32) -> None:
    self._ttl = ttl
    self._max_items = max_items
    self._store: dict[str, tuple[float, DashboardData]] = {}

  def get(self, key: str) -> DashboardData | None:
    entry = self._store.get(key)
    if not entry:
      return None
    expires_at, value = entry
    if time.monotonic() > expires_at:
      del self._store[key]
      return None
    return value

  def set(self, key: str, value: DashboardData) -> None:
    if len(self._store) >= self._max_items:
      oldest_key = min(self._store, key=lambda item: self._store[item][0])
      del self._store[oldest_key]
    self._store[key] = (time.monotonic() + self._ttl, value)


class DashboardService:
  def __init__(self, *, cache_ttl: float = 60.0) -> None:
    self._cache = _DashboardCache(ttl=cache_ttl)

  def cache_key(
    self,
    *,
    hub_version: int,
    period: str,
    date_from: date | None,
    date_to: date | None,
  ) -> str:
    return f"{hub_version}:{period}:{date_from}:{date_to}"

  def compute_cached(
    self,
    rows: list[dict[str, Any]],
    *,
    hub_version: int,
    period: str = "month",
    date_from: date | None = None,
    date_to: date | None = None,
  ) -> DashboardData:
    key = self.cache_key(
      hub_version=hub_version,
      period=period,
      date_from=date_from,
      date_to=date_to,
    )
    cached = self._cache.get(key)
    if cached is not None:
      return cached
    data = self.compute(rows, period=period, date_from=date_from, date_to=date_to)
    self._cache.set(key, data)
    return data

  def compute(
    self,
    rows: list[dict[str, Any]],
    period: str = "month",
    date_from: date | None = None,
    date_to: date | None = None,
  ) -> DashboardData:
    start, end, prev_start, prev_end = _period_bounds(period, date_from, date_to)
    data = DashboardData(
      period=period,
      period_label=PERIOD_LABELS.get(period, period),
      date_from=date_from,
      date_to=date_to,
    )

    all_orders: list[tuple[datetime | None, dict[str, Any], dict[str, Any]]] = []
    for row in rows:
      for order in row.get("_orders_context") or []:
        dt = _parse_date(order.get("Дата") or order.get("Момент времени"))
        all_orders.append((dt, order, row))

    def in_range(dt: datetime | None, a: datetime, b: datetime) -> bool:
      if dt is None:
        return period == "all"
      return a <= dt <= b

    cur_order_pairs = [(dt, o) for dt, o, _ in all_orders if in_range(dt, start, end)]
    prev_order_pairs = [(dt, o) for dt, o, _ in all_orders if in_range(dt, prev_start, prev_end)]
    cur_orders = [o for _, o in cur_order_pairs]
    prev_orders = [o for _, o in prev_order_pairs]

    cur_clients = {str(r.get("UUID") or r.get("Наименование")) for dt, _, r in all_orders if in_range(dt, start, end)}
    prev_clients = {str(r.get("UUID") or r.get("Наименование")) for dt, _, r in all_orders if in_range(dt, prev_start, prev_end)}
    if not all_orders:
      cur_clients = {str(r.get("UUID") or r.get("Наименование")) for r in rows}
      prev_clients = set()

    def sum_amount(orders: list[dict]) -> float:
      total = 0.0
      for o in orders:
        try:
          total += float(o.get("Сумма") or 0)
        except (TypeError, ValueError):
          pass
      return total

    def monthly_counts(items: list, key_fn) -> list[tuple[str, float | int]]:
      buckets: dict[str, float] = defaultdict(float)
      for item in items:
        k = key_fn(item)
        if k:
          buckets[k] += 1
      return sorted(buckets.items())

    def monthly_revenue(order_pairs: list[tuple[datetime | None, dict[str, Any]]]) -> list[tuple[str, float]]:
      buckets: dict[str, float] = defaultdict(float)
      for dt, order in order_pairs:
        if dt:
          buckets[_month_key(dt)] += float(order.get("Сумма") or 0)
      return sorted(buckets.items())

    data.clients = MetricBlock(
      total=len(cur_clients) if cur_clients else len(rows),
      growth_pct=_growth(len(cur_clients) or len(rows), len(prev_clients)),
      monthly=monthly_counts(
        list(cur_clients) if cur_clients else [r.get("UUID") for r in rows],
        lambda _: _month_key(end),
      ),
    )
    data.orders = MetricBlock(
      total=len(cur_orders) if cur_orders else sum(int(r.get("Всего заказов") or 0) for r in rows),
      growth_pct=_growth(len(cur_orders), len(prev_orders)),
      monthly=monthly_revenue(cur_order_pairs) if cur_orders else [],
    )
    rev_cur = sum_amount(cur_orders) if cur_orders else sum(float(r.get("Средний чек") or 0) * int(r.get("Всего заказов") or 0) for r in rows)
    rev_prev = sum_amount(prev_orders)
    data.revenue = MetricBlock(
      total=round(rev_cur, 2),
      growth_pct=_growth(rev_cur, rev_prev),
      monthly=monthly_revenue(cur_order_pairs) if cur_orders else [],
    )

    mp_clients = [
      r for r in rows
      if "маркетплейс" in str(r.get("Тип продаж") or r.get("Тип канала продаж") or "")
    ]
    data.marketplace_clients = MetricBlock(
      total=len(mp_clients),
      growth_pct=None,
      monthly=[],
    )
    mp_breakdown: Counter[str] = Counter()
    for r in mp_clients:
      ch = str(r.get("Канал продаж") or "маркетплейс")
      mp_breakdown[ch] += 1
    data.marketplace_breakdown = {
      k: MetricBlock(total=v) for k, v in mp_breakdown.most_common()
    }

    direct_clients = [
      r for r in rows
      if "прямы" in str(r.get("Тип продаж") or r.get("Тип канала продаж") or "")
    ]
    data.direct_clients = MetricBlock(total=len(direct_clients), growth_pct=None)
    direct_breakdown: Counter[str] = Counter()
    for r in direct_clients:
      ch = str(r.get("Канал продаж") or "прямые")
      direct_breakdown[ch] += 1
    data.direct_breakdown = {
      k: MetricBlock(total=v) for k, v in direct_breakdown.most_common()
    }

    repeat = sum(1 for r in rows if int(r.get("Всего заказов") or r.get("_orders_count") or 0) > 1)
    data.repeat_clients = MetricBlock(total=repeat, growth_pct=None)

    status_counter: Counter[str] = Counter()
    for _, order, _ in all_orders:
      st = str(order.get("Статус") or order.get("Отгружено") or "неизвестно")
      status_counter[st] += 1
    data.orders_by_status = dict(status_counter.most_common(10))
    data.open_tasks = status_counter.get("новый", 0) + status_counter.get("в работе", 0)
    data.open_dialogs = sum(1 for r in rows if r.get("ТГ ник"))

    return data
