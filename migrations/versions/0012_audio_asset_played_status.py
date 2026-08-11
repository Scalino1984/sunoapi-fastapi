"""add persistent audio asset played status

Revision ID: 0012_audio_asset_played_status
Revises: 0011_video_assets
Create Date: 2026-08-08
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0012_audio_asset_played_status"
down_revision = "0011_video_assets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("audio_assets") as batch_op:
        batch_op.add_column(
            sa.Column("has_been_played", sa.Boolean(), nullable=False, server_default=sa.false())
        )
    # Der neue Punkt markiert nur künftig entstehende Varianten. Bestehende
    # Library-Inhalte bleiben beim Rollout bewusst ohne Neu-Markierung.
    op.execute("UPDATE audio_assets SET has_been_played = 1")


def downgrade() -> None:
    with op.batch_alter_table("audio_assets") as batch_op:
        batch_op.drop_column("has_been_played")
