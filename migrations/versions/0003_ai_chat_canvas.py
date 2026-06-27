"""add ai chat canvas tables

Revision ID: 0003_ai_chat_canvas
Revises: 0002_add_users_auth
Create Date: 2026-06-07
"""
from alembic import op
import sqlalchemy as sa

revision = "0003_ai_chat_canvas"
down_revision = "0002_add_users_auth"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_chat_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), index=True, nullable=True),
        sa.Column("lyric_draft_id", sa.Integer(), index=True, nullable=True),
        sa.Column("title", sa.String(length=255), index=True, nullable=False),
        sa.Column("provider", sa.String(length=80), index=True, nullable=False),
        sa.Column("model", sa.String(length=120), index=True, nullable=False),
        sa.Column("canvas_content", sa.Text(), nullable=True),
        sa.Column("current_history_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column("deleted_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "ai_chat_messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("session_id", sa.Integer(), index=True, nullable=False),
        sa.Column("role", sa.String(length=40), index=True, nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("provider", sa.String(length=80), nullable=True),
        sa.Column("model", sa.String(length=120), nullable=True),
        sa.Column("canvas_before", sa.Text(), nullable=True),
        sa.Column("canvas_after", sa.Text(), nullable=True),
        sa.Column("change_summary", sa.Text(), nullable=True),
        sa.Column("raw_response", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "lyric_canvas_history",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("session_id", sa.Integer(), index=True, nullable=False),
        sa.Column("version_index", sa.Integer(), index=True, nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=80), index=True, nullable=False),
        sa.Column("change_summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("lyric_canvas_history")
    op.drop_table("ai_chat_messages")
    op.drop_table("ai_chat_sessions")
