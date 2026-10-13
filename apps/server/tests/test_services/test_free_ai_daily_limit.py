"""The free daily policy is account-wide, atomic and preserves reservation periods."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier

import pytest
from sqlalchemy import create_engine
from sqlmodel import Session, SQLModel

from config.datetime_utils import beijing_day_bounds
from models import User
from models.subscription import SubscriptionPlan, UsageQuota, UserSubscription
from services.quota_service import quota_service
from services.subscription.defaults import clone_default_free_features, resolve_plan_feature

NOW = datetime(2026, 10, 13, 12, tzinfo=UTC)


def seed_account(session: Session, *, used: int, plan_name: str = "free") -> tuple[str, str]:
    user = User(username="daily-limit-writer", email="daily-limit@example.com", hashed_password="synthetic", email_verified=True)
    plan = SubscriptionPlan(
        name=plan_name, display_name=plan_name, display_name_en=plan_name,
        price_monthly_cents=0 if plan_name == "free" else 4900,
        price_yearly_cents=0 if plan_name == "free" else 39900,
        features={"ai_conversations_per_day": 10} if plan_name == "free" else {},
    )
    session.add(user)
    session.add(plan)
    session.commit()
    period_start, period_end = beijing_day_bounds(NOW)
    quota = UsageQuota(
        user_id=user.id, period_start=period_start, period_end=period_end,
        last_reset_at=NOW, ai_conversations_used=used,
        material_decompositions_used=2, inspiration_copies_used=4,
        monthly_period_start=period_start, monthly_period_end=period_end + timedelta(days=28),
    )
    session.add(quota)
    if plan_name != "free":
        session.add(UserSubscription(
            user_id=user.id, plan_id=plan.id, status="active",
            current_period_start=NOW - timedelta(days=1), current_period_end=NOW + timedelta(days=30),
        ))
    session.commit()
    return user.id, quota.id


@pytest.mark.parametrize("stored", [20, 10, 3, 0, -1, None])
def test_free_daily_policy_overrides_legacy_plan_values(stored):
    assert resolve_plan_feature("free", {"ai_conversations_per_day": stored}, "ai_conversations_per_day") == 3
    assert clone_default_free_features()["ai_conversations_per_day"] == 3


def test_custom_paid_plan_keeps_its_explicit_daily_limit():
    assert resolve_plan_feature("enterprise", {"ai_conversations_per_day": 7}, "ai_conversations_per_day") == 7


def test_custom_plan_missing_daily_key_keeps_its_previous_fallback():
    assert resolve_plan_feature("enterprise", {}, "ai_conversations_per_day") == 10
    assert resolve_plan_feature(None, None, "ai_conversations_per_day") == 3
    assert resolve_plan_feature("pro", {}, "ai_conversations_per_day") == -1


@pytest.mark.parametrize("used", [2, 3, 7])
def test_existing_use_is_preserved_when_enforcing_three(db_session, monkeypatch, used):
    monkeypatch.setattr("services.quota_service.utcnow", lambda: NOW)
    user_id, quota_id = seed_account(db_session, used=used)
    before = db_session.get(UsageQuota, quota_id)
    original_period = (before.period_start, before.period_end, before.last_reset_at)
    assert quota_service.check_ai_conversation_quota(db_session, user_id) == (used < 3, used, 3)
    reservation = quota_service.reserve_ai_conversation(db_session, user_id)
    assert (reservation is not None) is (used < 3)
    db_session.expire_all()
    after = db_session.get(UsageQuota, quota_id)
    assert after.ai_conversations_used == used + (1 if used < 3 else 0)
    assert (after.period_start, after.period_end, after.last_reset_at) == original_period
    assert after.material_decompositions_used == 2
    assert after.inspiration_copies_used == 4
    snapshot = quota_service.get_quota_snapshot(db_session, user_id)
    assert snapshot["ai_conversations"]["limit"] == 3
    assert snapshot["ai_conversations"]["used"] == after.ai_conversations_used


def test_parallel_reservations_share_the_last_account_slot(tmp_path, monkeypatch):
    monkeypatch.setattr("services.quota_service.utcnow", lambda: NOW)
    engine = create_engine(f"sqlite:///{tmp_path / 'daily-limit.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        user_id, quota_id = seed_account(session, used=2)
    barrier = Barrier(4)

    def reserve():
        with Session(engine) as session:
            barrier.wait(timeout=10)
            return quota_service.reserve_ai_conversation(session, user_id)

    try:
        with ThreadPoolExecutor(max_workers=4) as pool:
            reservations = list(pool.map(lambda _: reserve(), range(4)))
        assert sum(value is not None for value in reservations) == 1
        with Session(engine) as session:
            assert session.get(UsageQuota, quota_id).ai_conversations_used == 3
            assert quota_service.check_ai_conversation_quota(session, user_id) == (False, 3, 3)
    finally:
        engine.dispose()


def test_beijing_midnight_and_late_refund_keep_the_charged_day(db_session, monkeypatch):
    current = NOW
    monkeypatch.setattr("services.quota_service.utcnow", lambda: current)
    user_id, quota_id = seed_account(db_session, used=2)
    current = datetime(2026, 10, 13, 15, 59, 59, tzinfo=UTC)
    old_reservation = quota_service.reserve_ai_conversation(db_session, user_id)
    assert old_reservation == datetime(2026, 10, 12, 16, tzinfo=UTC)
    current = datetime(2026, 10, 13, 16, tzinfo=UTC)
    assert quota_service.check_ai_conversation_quota(db_session, user_id) == (True, 0, 3)
    new_reservation = quota_service.reserve_ai_conversation(db_session, user_id)
    assert new_reservation == datetime(2026, 10, 13, 16, tzinfo=UTC)
    assert quota_service.release_ai_conversation(db_session, user_id, period_start=old_reservation) is False
    assert quota_service.check_ai_conversation_quota(db_session, user_id) == (True, 1, 3)
    assert quota_service.release_ai_conversation(db_session, user_id, period_start=new_reservation) is True
    assert quota_service.check_ai_conversation_quota(db_session, user_id) == (True, 0, 3)
    quota = db_session.get(UsageQuota, quota_id)
    assert quota.material_decompositions_used == 2
    assert quota.inspiration_copies_used == 4


def test_pro_remains_unlimited(db_session, monkeypatch):
    monkeypatch.setattr("services.quota_service.utcnow", lambda: NOW)
    user_id, quota_id = seed_account(db_session, used=1000, plan_name="pro")
    assert quota_service.check_ai_conversation_quota(db_session, user_id) == (True, 1000, -1)
    assert quota_service.reserve_ai_conversation(db_session, user_id) is not None
    db_session.expire_all()
    assert db_session.get(UsageQuota, quota_id).ai_conversations_used == 1001
    assert quota_service.get_quota_snapshot(db_session, user_id)["ai_conversations"]["limit"] == -1
