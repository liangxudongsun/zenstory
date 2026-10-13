"""The daily free quota applies to the account across actual stream project routes."""

import asyncio
from unittest.mock import patch

import pytest
from sqlmodel import select

from models import Project
from models.subscription import UsageQuota
from services.core.auth_service import create_access_token
from tests.conftest import TestSessionLocal
from tests.test_api.test_agent_stream_hardening import _PROSE, _FakeService, _sse
from tests.test_services.test_free_ai_daily_limit import NOW, seed_account


@pytest.mark.integration
async def test_third_message_blocks_another_project_while_the_inflight_stream_can_finish(client, db_session, monkeypatch):
    monkeypatch.setattr("services.quota_service.utcnow", lambda: NOW)
    monkeypatch.setattr("database.create_session", TestSessionLocal)
    user_id, quota_id = seed_account(db_session, used=2)
    projects = [Project(name=f"Synthetic writing project {index}", owner_id=user_id) for index in range(2)]
    db_session.add_all(projects)
    db_session.commit()
    project_ids = [project.id for project in projects]
    token = create_access_token({"sub": user_id})
    running, finish = asyncio.Event(), asyncio.Event()

    async def frames():
        yield _sse("content", {"text": _PROSE})
        running.set()
        await finish.wait()
        yield _sse("done", {})

    with patch("api.agent.get_agent_service", return_value=_FakeService(frames)):
        third_task = asyncio.create_task(client.post(
            "/api/v1/agent/stream", json={"project_id": project_ids[0], "message": "Synthetic local request"},
            headers={"Authorization": f"Bearer {token}"},
        ))
        try:
            await asyncio.wait_for(running.wait(), timeout=5)
            blocked = await client.post(
                "/api/v1/agent/stream", json={"project_id": project_ids[1], "message": "Synthetic local request"},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert blocked.status_code == 402
            assert blocked.json()["error_code"] == "ERR_QUOTA_AI_CONVERSATIONS_EXCEEDED"
            assert third_task.done() is False
        finally:
            finish.set()
            third = await third_task
    assert third.status_code == 200
    assert "event: content" in third.text
    assert "quota_refunded" not in third.text
    db_session.expire_all()
    assert db_session.get(UsageQuota, quota_id).ai_conversations_used == 3
    assert len(db_session.exec(select(UsageQuota).where(UsageQuota.user_id == user_id)).all()) == 1
