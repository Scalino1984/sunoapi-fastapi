"""add audio transcripts for one click srt

Revision ID: 0010_audio_transcripts
Revises: 0009_song_waveforms
Create Date: 2026-06-17
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0010_audio_transcripts"
down_revision = "0009_song_waveforms"
branch_labels = None
depends_on = None


def _table_names() -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return set(inspector.get_table_names())


def upgrade() -> None:
    if "audio_transcripts" in _table_names():
        return
    op.create_table(
        "audio_transcripts",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("audio_asset_id", sa.Integer(), nullable=False, index=True),
        sa.Column("backend", sa.String(length=80), nullable=False, index=True),
        sa.Column("language", sa.String(length=20), nullable=True),
        sa.Column("mode", sa.String(length=80), nullable=False, server_default="lyrics_source_of_truth"),
        sa.Column("match_mode", sa.String(length=80), nullable=False, server_default="lenient"),
        sa.Column("srt_text", sa.Text(), nullable=True),
        sa.Column("srt_path", sa.Text(), nullable=True),
        sa.Column("segments_json", sa.JSON(), nullable=True),
        sa.Column("words_json", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="created", index=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("generated_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )


def downgrade() -> None:
    if "audio_transcripts" in _table_names():
        op.drop_table("audio_transcripts")
