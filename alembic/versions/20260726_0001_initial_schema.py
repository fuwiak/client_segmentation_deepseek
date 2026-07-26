"""Initial CRM schema (sync_metadata, customers, orders, snapshots).

Revision ID: 20260726_0001
Revises:
Create Date: 2026-07-26

"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from alembic import op

revision: str = "20260726_0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA_PATH = Path(__file__).resolve().parents[2] / "app" / "db" / "schema.sql"


def upgrade() -> None:
  ddl = SCHEMA_PATH.read_text(encoding="utf-8")
  # schema.sql uses IF NOT EXISTS — безопасно на уже заполненной БД (Selectel).
  op.execute(ddl)


def downgrade() -> None:
  op.execute(
    """
    DROP TABLE IF EXISTS auxiliary_cache;
    DROP TABLE IF EXISTS segmentation_snapshots;
    DROP TABLE IF EXISTS orders;
    DROP TABLE IF EXISTS customers;
    DROP TABLE IF EXISTS sync_metadata;
    """
  )
