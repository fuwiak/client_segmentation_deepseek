"""Коннекторы источников данных.

Активен: ExcelConnector. Остальные — placeholder до подключения интеграций.
"""

from app.connectors.base import DataSourceConnector
from app.connectors.excel import ExcelConnector
from app.connectors.messenger import MessengerConnector
from app.connectors.moysklad import MoySkladConnector
from app.connectors.onec import OneCConnector

__all__ = [
    "DataSourceConnector",
    "ExcelConnector",
    "MessengerConnector",
    "MoySkladConnector",
    "OneCConnector",
]
