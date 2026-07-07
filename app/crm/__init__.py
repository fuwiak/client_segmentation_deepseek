"""CRM-слой: бизнес-логика поверх репозитория.

Активно: StatsService. LeadService и CampaignService — placeholder.
"""

from app.crm.campaigns import CampaignService
from app.crm.leads import LeadService
from app.crm.stats import CrmStats, StatsService

__all__ = ["CampaignService", "CrmStats", "LeadService", "StatsService"]
