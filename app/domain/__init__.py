"""Доменные модели — единая структура клиентской базы."""

from app.domain.models import (
    Campaign,
    CampaignStatus,
    Customer,
    Gender,
    Interaction,
    InteractionChannel,
    Lead,
    LeadStatus,
    Order,
    OrderItem,
    Recommendation,
    Segment,
    SegmentOrigin,
    SourceType,
    normalize_phone,
)

__all__ = [
    "Campaign",
    "CampaignStatus",
    "Customer",
    "Gender",
    "Interaction",
    "InteractionChannel",
    "Lead",
    "LeadStatus",
    "Order",
    "OrderItem",
    "Recommendation",
    "Segment",
    "SegmentOrigin",
    "SourceType",
    "normalize_phone",
]
