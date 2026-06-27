"""admin ai settings and vocal tags

Revision ID: 0004_admin_ai_vocal_tags
Revises: 0003_ai_chat_canvas
Create Date: 2026-06-07
"""
from alembic import op
import sqlalchemy as sa

revision = "0004_admin_ai_vocal_tags"
down_revision = "0003_ai_chat_canvas"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()

    if "users" in tables:
        columns = {column["name"] for column in inspector.get_columns("users")}
        if "is_admin" not in columns:
            op.add_column("users", sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.text("0")))

    if "app_settings" not in tables:
        op.create_table(
            "app_settings",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("key", sa.String(length=160), nullable=False, unique=True, index=True),
            sa.Column("value", sa.JSON(), nullable=True),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )

    if "vocal_tags" not in tables:
        op.create_table(
            "vocal_tags",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("label", sa.String(length=255), nullable=False, index=True),
            sa.Column("tag", sa.Text(), nullable=False),
            sa.Column("category", sa.String(length=120), nullable=False, index=True),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
            sa.Column("metadata_json", sa.JSON(), nullable=True),
            sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.text("0")),
            sa.Column("deleted_at", sa.DateTime(), nullable=True),
            sa.Column("deleted_reason", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()
    if "vocal_tags" in tables:
        op.drop_table("vocal_tags")
    if "app_settings" in tables:
        op.drop_table("app_settings")
