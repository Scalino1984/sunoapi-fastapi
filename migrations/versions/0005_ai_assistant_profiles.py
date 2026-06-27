"""add ai assistant profiles and instruction files

Revision ID: 0005_ai_assistant_profiles
Revises: 0004_admin_ai_vocal_tags
Create Date: 2026-06-08
"""

from alembic import op
import sqlalchemy as sa

revision = "0005_ai_assistant_profiles"
down_revision = "0004_admin_ai_vocal_tags"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_assistant_profiles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("provider", sa.String(length=80), nullable=False, server_default="openai"),
        sa.Column("model", sa.String(length=120), nullable=False, server_default="GPT-5.4-mini"),
        sa.Column("system_instruction", sa.Text(), nullable=True),
        sa.Column("response_format_instruction", sa.Text(), nullable=True),
        sa.Column("temperature", sa.Float(), nullable=True),
        sa.Column("max_output_tokens", sa.Integer(), nullable=True),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column("deleted_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_ai_assistant_profiles_name", "ai_assistant_profiles", ["name"])
    op.create_table(
        "ai_instruction_files",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=True),
        sa.Column("content_type", sa.String(length=120), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column("deleted_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_ai_instruction_files_title", "ai_instruction_files", ["title"])
    op.create_table(
        "ai_assistant_profile_files",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("profile_id", sa.Integer(), nullable=False),
        sa.Column("file_id", sa.Integer(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_ai_assistant_profile_files_profile_id", "ai_assistant_profile_files", ["profile_id"])
    op.create_index("ix_ai_assistant_profile_files_file_id", "ai_assistant_profile_files", ["file_id"])
    with op.batch_alter_table("ai_chat_sessions") as batch_op:
        batch_op.add_column(sa.Column("assistant_profile_id", sa.Integer(), nullable=True))
        batch_op.create_index("ix_ai_chat_sessions_assistant_profile_id", ["assistant_profile_id"])


def downgrade() -> None:
    with op.batch_alter_table("ai_chat_sessions") as batch_op:
        batch_op.drop_index("ix_ai_chat_sessions_assistant_profile_id")
        batch_op.drop_column("assistant_profile_id")
    op.drop_table("ai_assistant_profile_files")
    op.drop_table("ai_instruction_files")
    op.drop_table("ai_assistant_profiles")
