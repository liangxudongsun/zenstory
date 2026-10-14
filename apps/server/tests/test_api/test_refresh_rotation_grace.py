"""A fixed rotation-conflict window preserves sessions without accepting replay."""

from datetime import timedelta
from uuid import uuid4

import pytest
from sqlmodel import select

import api.auth as auth_api
from config.datetime_utils import normalize_datetime_to_utc, utcnow
from models import RefreshTokenRecord, User
from services.core.auth_service import create_refresh_token, get_refresh_token_expires_at, verify_token


@pytest.fixture
async def rotated_session(client, db_session):
    user = User(username="rotation-owner", email="rotation@example.com", hashed_password="unused", email_verified=True)
    db_session.add(user)
    db_session.flush()
    jti, family = uuid4().hex, uuid4().hex
    db_session.add(RefreshTokenRecord(user_id=user.id, token_jti=jti, family_id=family,
                                     expires_at=get_refresh_token_expires_at()))
    db_session.commit()
    token = create_refresh_token({"sub": user.id, "jti": jti, "family_id": family})
    response = await client.post("/api/auth/refresh", json={"refresh_token": token})
    assert response.status_code == 200
    db_session.expire_all()
    old = db_session.exec(select(RefreshTokenRecord).where(RefreshTokenRecord.token_jti == jti)).one()
    child_jti = verify_token(response.json()["refresh_token"])["jti"]
    child = db_session.exec(select(RefreshTokenRecord).where(RefreshTokenRecord.token_jti == child_jti)).one()
    return {"old_token": token, "child_token": response.json()["refresh_token"], "old": old, "child": child}


async def post_refresh(client, token):
    return await client.post("/api/auth/refresh", json={"refresh_token": token})


async def test_conflicts_do_not_issue_credentials_or_extend_the_original_window(client, db_session, monkeypatch, rotated_session):
    actor = rotated_session
    revoked_at = normalize_datetime_to_utc(actor["old"].revoked_at)
    original_updated = actor["old"].updated_at
    for seconds in [1, 5, 9, 10]:
        monkeypatch.setattr(auth_api, "utcnow", lambda seconds=seconds: revoked_at + timedelta(seconds=seconds))
        response = await post_refresh(client, actor["old_token"])
        assert response.status_code == 409
        assert "access_token" not in response.json() and "refresh_token" not in response.json()
        db_session.expire_all()
        assert len(db_session.exec(select(RefreshTokenRecord)).all()) == 2
        assert actor["old"].revoke_reason == "rotated"
        assert actor["old"].updated_at == original_updated
        assert normalize_datetime_to_utc(actor["old"].revoked_at) == revoked_at
        assert actor["child"].revoked_at is None
    monkeypatch.setattr(auth_api, "utcnow", lambda: revoked_at + timedelta(seconds=11))
    assert (await post_refresh(client, actor["old_token"])).status_code == 401
    db_session.expire_all()
    assert actor["child"].revoke_reason == "replay_detected"
    assert (await post_refresh(client, actor["child_token"])).status_code == 401


async def test_recent_old_request_remains_a_conflict_after_another_rotation(client, db_session, rotated_session):
    actor = rotated_session
    next_rotation = await post_refresh(client, actor["child_token"])
    assert next_rotation.status_code == 200
    assert (await post_refresh(client, actor["old_token"])).status_code == 409
    db_session.expire_all()
    rows = db_session.exec(select(RefreshTokenRecord)).all()
    assert len(rows) == 3 and len([row for row in rows if row.revoked_at is None]) == 1
    assert not any(row.revoke_reason == "replay_detected" for row in rows)
    assert (await post_refresh(client, next_rotation.json()["refresh_token"])).status_code == 200


@pytest.mark.parametrize("reason", ["logout", "password_changed", "replay_detected", "expired"])
async def test_non_rotation_revocation_never_gets_a_conflict_window(client, db_session, rotated_session, reason):
    actor = rotated_session
    actor["old"].revoke_reason = reason
    db_session.add(actor["old"])
    db_session.commit()
    assert (await post_refresh(client, actor["old_token"])).status_code == 401
    assert (await post_refresh(client, actor["child_token"])).status_code == 401


@pytest.mark.parametrize("successor", ["missing", "missing-link", "revoked", "expired"])
async def test_a_recent_rotation_without_a_live_family_is_not_benign(client, db_session, rotated_session, successor):
    actor = rotated_session
    if successor == "missing":
        db_session.delete(actor["child"])
    elif successor == "missing-link":
        actor["old"].replaced_by_jti = None
        db_session.add(actor["old"])
    else:
        if successor == "revoked":
            actor["child"].revoked_at = utcnow()
            actor["child"].revoke_reason = "logout"
        else:
            actor["child"].expires_at = utcnow() - timedelta(seconds=1)
        db_session.add(actor["child"])
    db_session.commit()
    assert (await post_refresh(client, actor["old_token"])).status_code == 401


async def test_future_rotation_timestamp_does_not_bypass_replay_detection(client, db_session, rotated_session):
    actor = rotated_session
    actor["old"].revoked_at = utcnow() + timedelta(seconds=1)
    db_session.add(actor["old"])
    db_session.commit()
    assert (await post_refresh(client, actor["old_token"])).status_code == 401
    assert (await post_refresh(client, actor["child_token"])).status_code == 401
