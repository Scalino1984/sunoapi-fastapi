"""add user nickname

Revision ID: 0006_user_nickname
Revises: 0005_ai_assistant_profiles
Create Date: 2026-06-08
"""
from alembic import op
import sqlalchemy as sa

revision = "0006_user_nickname"
down_revision = "0005_ai_assistant_profiles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(sa.Column("nickname", sa.String(length=120), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("nickname")
