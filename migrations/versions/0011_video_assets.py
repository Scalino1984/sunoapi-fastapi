"""add video assets table

Revision ID: 0011_video_assets
Revises: 0010_audio_transcripts
Create Date: 2026-07-06
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0011_video_assets"
down_revision = "0010_audio_transcripts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "video_assets",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("audio_asset_id", sa.Integer(), nullable=False, index=True),
        sa.Column("song_id", sa.Integer(), nullable=True, index=True),
        sa.Column("task_local_id", sa.Integer(), nullable=True, index=True),
        sa.Column("suno_task_id", sa.String(length=255), nullable=True, index=True),
        sa.Column("audio_id", sa.String(length=255), nullable=True, index=True),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("local_path", sa.Text(), nullable=True),
        sa.Column("public_url", sa.Text(), nullable=True),
        sa.Column("filename", sa.String(length=255), nullable=True),
        sa.Column("content_type", sa.String(length=120), nullable=True),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=True, index=True),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="created", index=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column("deleted_reason", sa.Text(), nullable=True),
    )
    op.create_index("ix_video_assets_audio_deleted_created", "video_assets", ["audio_asset_id", "is_deleted", "created_at", "id"])
    op.create_index("ix_video_assets_audio_id_deleted", "video_assets", ["audio_id", "is_deleted"])
    op.create_index("ix_video_assets_task_deleted", "video_assets", ["suno_task_id", "is_deleted"])


def downgrade() -> None:
    op.drop_index("ix_video_assets_task_deleted", table_name="video_assets")
    op.drop_index("ix_video_assets_audio_id_deleted", table_name="video_assets")
    op.drop_index("ix_video_assets_audio_deleted_created", table_name="video_assets")
    op.drop_table("video_assets")
