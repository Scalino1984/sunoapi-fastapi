"""enterprise baseline

Revision ID: 0001_enterprise_baseline
Revises:
Create Date: 2026-06-07
"""
from __future__ import annotations

from alembic import op

revision = "0001_enterprise_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Baseline-Migration: bestehende Installationen nutzen die automatische leichte Migration.
    # Für neue Enterprise-Installationen kann danach `alembic revision --autogenerate`
    # auf Basis von app.models erzeugt werden.
    pass


def downgrade() -> None:
    pass
