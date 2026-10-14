"""Persist new-account first-work eligibility and its original result.

Revision ID: 20261014_100000
Revises: 20261014_090000
"""
import sqlalchemy as sa

from alembic import op

revision = "20261014_100000"
down_revision = "20261014_090000"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "workspace_onboarding",
        sa.Column("user_id", sa.String(), sa.ForeignKey("user.id"), primary_key=True),
        sa.Column("registered_at", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("initialized_at", sa.DateTime()),
        sa.Column("project_id", sa.String()),
        sa.Column("file_id", sa.String()),
        sa.Column("opened_at", sa.DateTime()),
        sa.Column("first_manual_write_at", sa.DateTime()),
        sa.Column("first_ai_requested_at", sa.DateTime()),
    )
    op.create_index("ix_workspace_onboarding_project_id", "workspace_onboarding", ["project_id"])
    # No INSERT/backfill: only registrations handled by the new source enroll.


def downgrade():
    op.drop_index("ix_workspace_onboarding_project_id", table_name="workspace_onboarding")
    op.drop_table("workspace_onboarding")
