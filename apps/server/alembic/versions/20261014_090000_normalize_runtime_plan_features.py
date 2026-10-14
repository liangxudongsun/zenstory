"""Normalize inactive plan keys and preserve Pro's existing unlimited copying.

Revision ID: 20261014_090000
Revises: 20261013_120000

No usage, subscription, reservation, or ledger row is changed. Before production
execution, retain a verified database backup and read back the plan rows.
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261014_090000"
down_revision: str | None = "20261013_120000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

plan = sa.table("subscription_plan", sa.column("id", sa.String()), sa.column("name", sa.String()),
                sa.column("features", sa.JSON()), sa.column("updated_at", sa.DateTime()))
RETIRED_KEYS = frozenset({
    "context_window_tokens", "custom_prompts", "material_uploads", "priority_support",
    "writing_credits_monthly", "agent_runs_monthly", "active_projects_limit", "context_tokens_limit",
    "material_uploads_monthly", "material_decompositions_monthly", "custom_skills_limit",
    "skill_creates_monthly", "priority_queue_level",
})


def upgrade() -> None:
    bind = op.get_bind()
    for plan_id, name, raw in bind.execute(sa.select(plan.c.id, plan.c.name, plan.c.features).with_for_update()).all():
        current = dict(raw or {})
        normalized = {key: value for key, value in current.items() if key not in RETIRED_KEYS}
        if name == "pro":
            normalized["inspiration_copies_monthly"] = -1
        if normalized != current:
            bind.execute(plan.update().where(plan.c.id == plan_id).values(
                features=normalized, updated_at=sa.func.current_timestamp(),
            ))


def downgrade() -> None:
    # Restore the old canonical representation; old code already bypassed Pro's
    # copy quota. Do not invent removed, unenforced configuration values: restore
    # the pre-release backup if the exact historical raw JSON is required.
    bind = op.get_bind()
    for plan_id, raw in bind.execute(sa.select(plan.c.id, plan.c.features).where(plan.c.name == "pro").with_for_update()).all():
        current = dict(raw or {})
        if current.get("inspiration_copies_monthly") == -1:
            bind.execute(plan.update().where(plan.c.id == plan_id).values(
                features={**current, "inspiration_copies_monthly": 100}, updated_at=sa.func.current_timestamp(),
            ))
