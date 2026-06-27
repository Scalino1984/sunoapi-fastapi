"""add status notifications

Revision ID: 0007_status_notifications
Revises: 0006_user_nickname
Create Date: 2026-06-08
"""
from alembic import op
import sqlalchemy as sa

revision = "0007_status_notifications"
down_revision = "0006_user_nickname"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "status_notifications",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("event_type", sa.String(length=120), nullable=False, index=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("severity", sa.String(length=40), nullable=False, index=True),
        sa.Column("status", sa.String(length=40), nullable=False, index=True),
        sa.Column("task_local_id", sa.Integer(), nullable=True, index=True),
        sa.Column("suno_task_id", sa.String(length=255), nullable=True, index=True),
        sa.Column("content_type", sa.String(length=80), nullable=True, index=True),
        sa.Column("content_id", sa.Integer(), nullable=True, index=True),
        sa.Column("target_tab", sa.String(length=80), nullable=True),
        sa.Column("target_payload", sa.JSON(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column("deleted_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("status_notifications")
