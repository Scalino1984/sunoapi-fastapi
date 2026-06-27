"""add audio waveform cache fields

Revision ID: 0008_audio_waveforms
Revises: 0007_status_notifications
Create Date: 2026-06-08
"""
from alembic import op
import sqlalchemy as sa

revision = "0008_audio_waveforms"
down_revision = "0007_status_notifications"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("audio_assets") as batch_op:
        batch_op.add_column(sa.Column("waveform_json", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("waveform_generated_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("structure_segments_json", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("audio_assets") as batch_op:
        batch_op.drop_column("structure_segments_json")
        batch_op.drop_column("waveform_generated_at")
        batch_op.drop_column("waveform_json")
