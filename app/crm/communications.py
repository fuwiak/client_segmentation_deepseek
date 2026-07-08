"""Настройки автокоммуникации с клиентом."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AutoCommRule:
  key: str
  title: str
  description: str
  enabled: bool = False
  template: str = ""
  channel: str = "whatsapp"
  delay_hours: int = 0


DEFAULT_RULES: list[AutoCommRule] = [
  AutoCommRule(
    key="order_accepted",
    title="Принятие заказа",
    description="Отбивка при принятии заказа",
    template="Здравствуйте, {name}! Ваш заказ принят. Номер: {order_id}.",
    channel="whatsapp",
  ),
  AutoCommRule(
    key="assembly",
    title="Сбор букета",
    description="Уведомление о сборе",
    template="{name}, ваш букет собирается. Скоро передадим курьеру.",
    channel="whatsapp",
  ),
  AutoCommRule(
    key="delivery",
    title="Доставка",
    description="Уведомление о доставке",
    template="{name}, курьер выехал. Ожидайте доставку.",
    channel="whatsapp",
  ),
  AutoCommRule(
    key="feedback",
    title="Обратная связь",
    description="Вопрос об удовлетворённости после доставки",
    template="{name}, как вам букет? Будем рады обратной связи!",
    channel="whatsapp",
    delay_hours=2,
  ),
  AutoCommRule(
    key="followup_3d",
    title="Напоминание через 3 дня",
    description="Повторный контакт через 3 дня",
    template="{name}, напоминаем о себе! Готовы помочь с новым заказом.",
    channel="telegram",
    delay_hours=72,
  ),
]


class CommunicationsSettings:
  def __init__(self) -> None:
    self._rules: dict[str, AutoCommRule] = {r.key: r for r in DEFAULT_RULES}

  def list_rules(self) -> list[AutoCommRule]:
    return list(self._rules.values())

  def update_rule(self, key: str, **kwargs: Any) -> AutoCommRule | None:
    rule = self._rules.get(key)
    if not rule:
      return None
    for k, v in kwargs.items():
      if hasattr(rule, k):
        setattr(rule, k, v)
    return rule


_settings: CommunicationsSettings | None = None


def get_comm_settings() -> CommunicationsSettings:
  global _settings
  if _settings is None:
    _settings = CommunicationsSettings()
  return _settings
