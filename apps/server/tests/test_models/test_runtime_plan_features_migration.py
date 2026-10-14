"""The config-only cleanup never rewrites usage, paid periods or real rights."""
from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlmodel import Session, SQLModel, select

from models import User
from models.subscription import SubscriptionPlan, UsageQuota, UserSubscription
from tests.test_models.test_payment_order_migration import _alembic, _version


def test_runtime_plan_cleanup_preserves_counters_subscriptions_and_other_rights(tmp_path):
    url = f"sqlite:///{tmp_path / 'runtime-plans.db'}"
    engine = create_engine(url)
    SQLModel.metadata.create_all(engine)
    now = datetime(2026, 10, 13, 12, tzinfo=UTC)
    retired = {"context_window_tokens": 16384, "custom_prompts": True, "material_uploads": 5, "priority_support": True}
    real = {"max_projects": 7, "custom_skills": 42, "file_versions_per_file": 81, "operator_feature": {"enabled": True}}
    with Session(engine) as session:
        user = User(username='migration-only', email='migration-only@example.invalid', hashed_password='synthetic')
        free = SubscriptionPlan(name='free', display_name='Free', features={**retired, 'ai_conversations_per_day': 3, 'max_projects': 3})
        pro = SubscriptionPlan(name='pro', display_name='Pro', price_monthly_cents=5900, features={**retired, **real, 'inspiration_copies_monthly': 100})
        custom = SubscriptionPlan(name='custom', display_name='Custom', features={**retired, **real, 'inspiration_copies_monthly': 17})
        session.add_all([user, free, pro, custom])
        session.commit()
        quota = UsageQuota(user_id=user.id, ai_conversations_used=2, inspiration_copies_used=9, material_decompositions_used=4,
                           period_start=now, period_end=now+timedelta(days=1), last_reset_at=now)
        subscription = UserSubscription(user_id=user.id, plan_id=pro.id, current_period_start=now, current_period_end=now+timedelta(days=30))
        session.add_all([quota, subscription])
        session.commit()
        quota_id, before_quota = quota.id, quota.model_dump()
        subscription_id, before_subscription = subscription.id, subscription.model_dump()
    _alembic(url, 'stamp', '20261013_120000')
    _alembic(url, 'upgrade', '20261014_090000')
    with Session(engine) as session:
        assert _version(engine) == '20261014_090000'
        rows = {p.name: p for p in session.exec(select(SubscriptionPlan)).all()}
        assert rows['free'].features == {'ai_conversations_per_day': 3, 'max_projects': 3}
        assert rows['pro'].features == {**real, 'inspiration_copies_monthly': -1}
        assert rows['custom'].features == {**real, 'inspiration_copies_monthly': 17}
        assert rows['pro'].price_monthly_cents == 5900
        assert session.get(UsageQuota, quota_id).model_dump() == before_quota
        assert session.get(UserSubscription, subscription_id).model_dump() == before_subscription
    _alembic(url, 'downgrade', '20261013_120000')
    with Session(engine) as session:
        rows = {p.name: p for p in session.exec(select(SubscriptionPlan)).all()}
        assert rows['pro'].features == {**real, 'inspiration_copies_monthly': 100}
        assert rows['custom'].features == {**real, 'inspiration_copies_monthly': 17}
        assert session.get(UsageQuota, quota_id).model_dump() == before_quota
        assert session.get(UserSubscription, subscription_id).model_dump() == before_subscription
    engine.dispose()
