"""set the free account daily AI message limit to three

Revision ID: 20261013_120000
Revises: 20261009_120000

Only the free plan's one feature key changes. Usage counters, reset timestamps,
active reservations and all paid-plan features are deliberately untouched.
Previous application code remains compatible and enforces its own daily limit
until the matching application release is promoted.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261013_120000"
down_revision: str | None = "20261009_120000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

subscription_plan = sa.table(
    "subscription_plan",
    sa.column("id", sa.String()),
    sa.column("name", sa.String()),
    sa.column("features", sa.JSON()),
    sa.column("updated_at", sa.DateTime()),
)


def _set_free_daily_limit(limit: int, *, expected: int | None = None) -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.select(subscription_plan.c.id, subscription_plan.c.features).where(
            subscription_plan.c.name == "free"
        ).with_for_update()
    ).all()
    for plan_id, features in rows:
        current = dict(features or {})
        previous = current.get("ai_conversations_per_day")
        if previous == limit or (expected is not None and previous != expected):
            continue
        bind.execute(
            subscription_plan.update().where(subscription_plan.c.id == plan_id).values(
                features={**current, "ai_conversations_per_day": limit},
                updated_at=sa.func.current_timestamp(),
            )
        )


def upgrade() -> None:
    _set_free_daily_limit(3)


def downgrade() -> None:
    # Restore the previous canonical policy only if this migration's value is
    # still present; an operator's later change must survive rollback.
    _set_free_daily_limit(10, expected=3)
