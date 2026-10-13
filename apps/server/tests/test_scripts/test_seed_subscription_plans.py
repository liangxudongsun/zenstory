from datetime import UTC, datetime, timedelta

from sqlmodel import select

import scripts.seed_subscription_plans as seed
from models import User
from models.subscription import SubscriptionPlan, UsageQuota


def test_free_plan_seed_includes_material_library_fields() -> None:
    assert seed.FREE_PLAN_FEATURES["ai_conversations_per_day"] == 3
    assert seed.FREE_PLAN_FEATURES["materials_library_access"] is False
    assert seed.FREE_PLAN_FEATURES["material_uploads"] == 0
    assert seed.FREE_PLAN_FEATURES["material_decompositions"] == 0


def test_pro_plan_seed_includes_material_library_fields() -> None:
    assert seed.PRO_PLAN_FEATURES["materials_library_access"] is True
    assert seed.PRO_PLAN_FEATURES["material_uploads"] == 5
    assert seed.PRO_PLAN_FEATURES["material_decompositions"] == 5


def test_non_force_seed_creates_current_free_plan_without_resetting_existing_data(db_session, monkeypatch) -> None:
    monkeypatch.setattr(seed, "sync_engine", db_session.get_bind())
    now = datetime(2026, 10, 13, 12, tzinfo=UTC)
    user = User(username="seed-policy-writer", email="seed-policy@example.com", hashed_password="synthetic")
    pro = SubscriptionPlan(
        name="pro", display_name="Operator Pro", price_monthly_cents=5900,
        features={"ai_conversations_per_day": -1, "max_projects": 7, "operator_feature": {"enabled": True}},
    )
    custom = SubscriptionPlan(
        name="enterprise", display_name="Custom Plan", price_monthly_cents=99900,
        features={"ai_conversations_per_day": 7, "custom_skills": 200},
    )
    db_session.add_all([user, pro, custom])
    db_session.commit()
    quota = UsageQuota(
        user_id=user.id, ai_conversations_used=2,
        period_start=now - timedelta(hours=20), period_end=now + timedelta(hours=4), last_reset_at=now,
        material_decompositions_used=2, inspiration_copies_used=4,
    )
    db_session.add(quota)
    db_session.commit()
    db_session.refresh(quota)
    db_session.refresh(pro)
    db_session.refresh(custom)
    quota_id, quota_before = quota.id, quota.model_dump()
    paid_before = {plan.name: plan.model_dump() for plan in [pro, custom]}

    seed.seed_plans(force=False)
    db_session.expire_all()
    plans = {plan.name: plan for plan in db_session.exec(select(SubscriptionPlan)).all()}
    assert set(plans) == {"free", "pro", "enterprise"}
    assert plans["free"].features["ai_conversations_per_day"] == 3
    assert plans["free"].features["max_projects"] == 3
    assert {name: plans[name].model_dump() for name in paid_before} == paid_before
    assert db_session.get(UsageQuota, quota_id).model_dump() == quota_before
    free_before = plans["free"].model_dump()

    seed.seed_plans(force=False)
    db_session.expire_all()
    plans = {plan.name: plan for plan in db_session.exec(select(SubscriptionPlan)).all()}
    assert set(plans) == {"free", "pro", "enterprise"}
    assert plans["free"].model_dump() == free_before
    assert {name: plans[name].model_dump() for name in paid_before} == paid_before
    assert db_session.get(UsageQuota, quota_id).model_dump() == quota_before
