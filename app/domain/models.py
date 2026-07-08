"""Единая доменная модель клиентской базы.

Это «истина» системы — не зависит ни от источника данных (Excel, Мой Склад, 1С,
мессенджеры), ни от способа хранения (in-memory, Postgres). Коннекторы приводят
сырые данные к этим моделям, репозиторий их хранит, агенты дополняют.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class Gender(str, Enum):
    MALE = "Мужской"
    FEMALE = "Женский"
    UNKNOWN = "Неизвестно"


class SourceType(str, Enum):
    EXCEL = "excel"
    MOYSKLAD = "moysklad"
    ONEC = "1c"
    MESSENGER = "messenger"
    MANUAL = "manual"


class SegmentOrigin(str, Enum):
    RULE = "rule"
    AI = "ai"
    MANUAL = "manual"


def normalize_phone(raw: str | None) -> str | None:
    """Приводит телефон к формату +7XXXXXXXXXX — стабильный ключ для склейки.

    Основной ключ дедупликации клиента между источниками.
    """
    if not raw:
        return None
    digits = re.sub(r"\D", "", str(raw))
    if not digits:
        return None
    if len(digits) == 11 and digits[0] in ("7", "8"):
        digits = "7" + digits[1:]
    elif len(digits) == 10:
        digits = "7" + digits
    return "+" + digits


class Segment(BaseModel):
    code: str
    title: str = ""
    origin: SegmentOrigin = SegmentOrigin.RULE
    confidence: float | None = None


class OrderItem(BaseModel):
    name: str = ""
    quantity: float | None = None
    price: float | None = None


class Order(BaseModel):
    id: str
    customer_id: str | None = None
    recipient_id: str | None = None
    date: datetime | None = None
    amount: float | None = None
    margin: float | None = None
    currency: str = "руб"
    payment_status: str | None = None
    shipment_status: str | None = None
    sales_channel: str | None = None
    warehouse: str | None = None
    items: list[OrderItem] = Field(default_factory=list)
    recipient: str | None = None  # legacy / сырой текст из источника
    delivery_address: str | None = None
    occasion: str | None = None
    comment: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class InteractionChannel(str, Enum):
    TELEGRAM = "telegram"
    WHATSAPP = "whatsapp"
    INSTAGRAM = "instagram"
    CALL = "call"
    EMAIL = "email"
    OTHER = "other"


class Interaction(BaseModel):
    id: str
    customer_id: str | None = None
    channel: InteractionChannel = InteractionChannel.OTHER
    direction: str = "in"
    text: str = ""
    date: datetime | None = None
    attachments: list[str] = Field(default_factory=list)
    transcript: str | None = None
    ai_labels: dict[str, Any] = Field(default_factory=dict)


class PreferenceOwner(str, Enum):
    CUSTOMER = "customer"
    RECIPIENT = "recipient"


class PreferenceProfile(BaseModel):
    """AI-driven профиль предпочтений заказчика или получателя."""

    id: str
    owner_type: PreferenceOwner = PreferenceOwner.CUSTOMER
    owner_id: str
    favorite_flowers: list[str] = Field(default_factory=list)
    disliked_flowers: list[str] = Field(default_factory=list)
    style: str | None = None
    price_range: str | None = None
    delivery_preferences: str | None = None
    confidence: float | None = None
    source: str = "agent"


class Recipient(BaseModel):
    """Получатель подарков — отдельная сущность, связанная с заказчиком."""

    id: str
    customer_id: str
    name: str | None = None
    relation: str | None = None
    gender: Gender = Gender.UNKNOWN
    preference_profile_id: str | None = None
    notes: str | None = None
    ai_labels: dict[str, Any] = Field(default_factory=dict)


class ImportantDateSource(str, Enum):
    AGENT = "agent"
    ORDER = "order"
    MANUAL = "manual"


class ImportantDate(BaseModel):
    """Важная дата: ДР, годовщина и т.д. — часто извлекается агентом из переписок."""

    id: str
    customer_id: str
    recipient_id: str | None = None
    event_type: str = ""
    event_date: date
    recurrence: bool = True
    source: ImportantDateSource = ImportantDateSource.AGENT
    confidence: float | None = None


class Customer(BaseModel):
    """Центральная сущность. `external_ids` хранит id клиента в каждом источнике,
    что делает возможной дедупликацию и двустороннюю синхронизацию."""

    id: str
    external_ids: dict[str, str] = Field(default_factory=dict)

    name: str | None = None
    phone: str | None = None
    email: str | None = None
    telegram: str | None = None
    gender: Gender = Gender.UNKNOWN
    birth_date: date | None = None

    addresses: list[str] = Field(default_factory=list)
    segments: list[Segment] = Field(default_factory=list)
    preferences: list[str] = Field(default_factory=list)
    channels: list[str] = Field(default_factory=list)

    average_check: float | None = None
    total_orders: int | None = None
    last_order_date: datetime | None = None
    bonus_points: float | None = None

    source: SourceType = SourceType.EXCEL
    archived: bool = False

    ai_confidence: float | None = None
    ai_reasoning: str | None = None
    ai_summary: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)

    @property
    def dedup_key(self) -> str | None:
        """Ключ для склейки записей из разных источников."""
        return normalize_phone(self.phone) or (self.email or "").lower() or None

    def segment_codes(self) -> list[str]:
        return [s.code for s in self.segments]


class LeadStatus(str, Enum):
    NEW = "new"
    QUALIFIED = "qualified"
    IN_PROGRESS = "in_progress"
    WON = "won"
    LOST = "lost"


class Lead(BaseModel):
    id: str
    source: str = ""
    contact: str = ""
    status: LeadStatus = LeadStatus.NEW
    customer_id: str | None = None
    assigned_operator: str | None = None
    created_at: datetime | None = None
    note: str | None = None


class CampaignStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    DONE = "done"


class Campaign(BaseModel):
    id: str
    title: str = ""
    target_segments: list[str] = Field(default_factory=list)
    channel: str = ""
    offer: str = ""
    trigger: str | None = None
    status: CampaignStatus = CampaignStatus.DRAFT
    metrics: dict[str, float] = Field(default_factory=dict)


class Recommendation(BaseModel):
    id: str
    customer_id: str | None = None
    recipient_id: str | None = None
    target_segment: str | None = None
    kind: str = ""
    text: str = ""
    author: str = "agent"
    confidence: float | None = None
