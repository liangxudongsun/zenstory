"""Account-wide final-slot proof on an explicitly owned disposable PostgreSQL DB."""

import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import create_engine
from sqlmodel import Session, SQLModel

import database
from models import User
from models.subscription import SubscriptionPlan, UsageQuota, UserSubscription
from services.quota_service import quota_service
from tests.test_services.test_free_ai_daily_limit import NOW, seed_account

pytestmark = pytest.mark.skipif(
    not os.getenv("ZENSTORY_TEST_POSTGRES_URL"), reason="explicitly owned disposable PostgreSQL URL required",
)
TABLES = [User.__table__, SubscriptionPlan.__table__, UserSubscription.__table__, UsageQuota.__table__]


@pytest.fixture
def daily_limit_engine():
    url = os.environ["ZENSTORY_TEST_POSTGRES_URL"]
    assert url == os.environ["DATABASE_URL"] and database.is_postgres is True
    engine = create_engine(url, connect_args={
        "options": "-c timezone=UTC -c statement_timeout=60000 -c lock_timeout=45000",
    })
    SQLModel.metadata.create_all(engine, tables=TABLES)
    try:
        yield engine
    finally:
        SQLModel.metadata.drop_all(engine, tables=TABLES)
        engine.dispose()


def test_free_account_last_daily_slot_is_reserved_once(daily_limit_engine, monkeypatch):
    monkeypatch.setattr("services.quota_service.utcnow", lambda: NOW)
    with Session(daily_limit_engine) as session:
        user_id, quota_id = seed_account(session, used=2)
    barrier = Barrier(4)

    def reserve():
        with Session(daily_limit_engine) as session:
            barrier.wait(timeout=10)
            return quota_service.reserve_ai_conversation(session, user_id)

    with ThreadPoolExecutor(max_workers=4) as pool:
        reservations = list(pool.map(lambda _: reserve(), range(4)))
    assert sum(value is not None for value in reservations) == 1
    with Session(daily_limit_engine) as session:
        assert session.get(UsageQuota, quota_id).ai_conversations_used == 3
        assert quota_service.check_ai_conversation_quota(session, user_id) == (False, 3, 3)
