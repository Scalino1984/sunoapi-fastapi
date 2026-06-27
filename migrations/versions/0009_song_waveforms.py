"""add song waveform cache fields

Revision ID: 0009_song_waveforms
Revises: 0008_audio_waveforms
Create Date: 2026-06-09
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0009_song_waveforms"
down_revision = "0008_audio_waveforms"
branch_labels = None
depends_on = None


def _column_names(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if table_name not in inspector.get_table_names():
        return set()
    return {column["name"] for column in inspector.get_columns(table_name)}


def upgrade() -> None:
    columns = _column_names("songs")
    if not columns:
        return

    with op.batch_alter_table("songs") as batch_op:
        if "waveform_json" not in columns:
            batch_op.add_column(sa.Column("waveform_json", sa.JSON(), nullable=True))
        if "waveform_generated_at" not in columns:
            batch_op.add_column(sa.Column("waveform_generated_at", sa.DateTime(), nullable=True))
        if "structure_segments_json" not in columns:
            batch_op.add_column(sa.Column("structure_segments_json", sa.JSON(), nullable=True))


def downgrade() -> None:
    columns = _column_names("songs")
    if not columns:
        return

    with op.batch_alter_table("songs") as batch_op:
        if "structure_segments_json" in columns:
            batch_op.drop_column("structure_segments_json")
        if "waveform_generated_at" in columns:
            batch_op.drop_column("waveform_generated_at")
        if "waveform_json" in columns:
            batch_op.drop_column("waveform_json")
