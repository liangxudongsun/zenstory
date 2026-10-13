"""The free daily-limit data migration preserves every usage counter and other plan."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlmodel import Session, SQLModel, select

from models import User
from models.subscription import SubscriptionPlan, UsageQuota
from tests.test_models.test_payment_order_migration import _alembic, _version

REVISION = "20261013_120000"
PREVIOUS_REVISION = "20261009_120000"


@pytest.mark.integration
@pytest.mark.parametrize("old_limit", [10, 20, 3, None])
def test_free_daily_limit_migration_preserves_usage_and_other_features(tmp_path, old_limit):
    db_url = f"sqlite:///{tmp_path / 'free-limit.db'}"
    engine = create_engine(db_url)
    SQLModel.metadata.create_all(engine)
    now = datetime(2026, 10, 13, 12, tzinfo=UTC)
    free_features = {"max_projects": 3, "custom_skills": 3, "file_versions_per_file": 10, "custom_field": "preserved"}
    if old_limit is not None:
        free_features["ai_conversations_per_day"] = old_limit
    pro_features = {"ai_conversations_per_day": -1, "custom_skills": 20, "max_projects": -1}
    enterprise_features = {"ai_conversations_per_day": 7, "custom_skills": 200}
    with Session(engine) as session:
        user = User(username="migration-writer", email="migration@example.com", hashed_password="synthetic")
        free = SubscriptionPlan(name="free", display_name="Free", display_name_en="Free", price_monthly_cents=0, features=free_features)
        pro = SubscriptionPlan(name="pro", display_name="Pro", display_name_en="Pro", price_monthly_cents=4900, features=pro_features)
        enterprise = SubscriptionPlan(name="enterprise", display_name="Enterprise", price_monthly_cents=99900, features=enterprise_features)
        session.add_all([user, free, pro, enterprise])
        session.commit()
        old_updated_at = free.updated_at
        quota = UsageQuota(
            user_id=user.id, period_start=now, period_end=now + timedelta(hours=4),
            last_reset_at=now, ai_conversations_used=7, material_decompositions_used=2,
            inspiration_copies_used=9, skill_creates_used=3,
        )
        session.add(quota)
        session.commit()
        quota_id = quota.id
        before = dict(quota.model_dump())
    _alembic(db_url, "stamp", PREVIOUS_REVISION)
    _alembic(db_url, "upgrade", REVISION)
    with Session(engine) as session:
        assert _version(engine) == REVISION
        free = session.exec(select(SubscriptionPlan).where(SubscriptionPlan.name == "free")).one()
        pro = session.exec(select(SubscriptionPlan).where(SubscriptionPlan.name == "pro")).one()
        assert free.features == {**free_features, "ai_conversations_per_day": 3}
        assert pro.features == pro_features
        enterprise = session.exec(select(SubscriptionPlan).where(SubscriptionPlan.name == "enterprise")).one()
        assert enterprise.features == enterprise_features
        assert session.get(UsageQuota, quota_id).model_dump() == before
        timestamp = free.updated_at
        if old_limit == 3:
            assert timestamp == old_updated_at
    _alembic(db_url, "downgrade", PREVIOUS_REVISION)
    with Session(engine) as session:
        free = session.exec(select(SubscriptionPlan).where(SubscriptionPlan.name == "free")).one()
        assert free.features == {**free_features, "ai_conversations_per_day": 10}
        assert session.get(UsageQuota, quota_id).model_dump() == before
    _alembic(db_url, "upgrade", REVISION)
    _alembic(db_url, "upgrade", REVISION)
    with Session(engine) as session:
        free = session.exec(select(SubscriptionPlan).where(SubscriptionPlan.name == "free")).one()
        assert free.features == {**free_features, "ai_conversations_per_day": 3}
        assert free.updated_at >= timestamp
        assert session.get(UsageQuota, quota_id).model_dump() == before
    engine.dispose()


@pytest.mark.integration
def test_downgrade_preserves_operator_changes_after_upgrade(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'operator-free-limit.db'}"
    engine = create_engine(db_url)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(SubscriptionPlan(name="free", display_name="Free", price_monthly_cents=0, features={"ai_conversations_per_day": 10, "max_projects": 3}))
        session.commit()
    _alembic(db_url, "stamp", PREVIOUS_REVISION)
    _alembic(db_url, "upgrade", REVISION)
    with Session(engine) as session:
        free = session.exec(select(SubscriptionPlan).where(SubscriptionPlan.name == "free")).one()
        free.features = {**free.features, "ai_conversations_per_day": 7, "custom_field": "later edit"}
        session.add(free)
        session.commit()
        updated_at = free.updated_at
    _alembic(db_url, "downgrade", PREVIOUS_REVISION)
    with Session(engine) as session:
        free = session.exec(select(SubscriptionPlan).where(SubscriptionPlan.name == "free")).one()
        assert free.features == {"ai_conversations_per_day": 7, "max_projects": 3, "custom_field": "later edit"}
        assert free.updated_at == updated_at
    engine.dispose()
