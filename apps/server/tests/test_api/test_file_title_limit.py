import pytest
from httpx import AsyncClient
from pydantic import ValidationError
from sqlmodel import Session

from api.agent_api import FileCreate as AgentFileCreate
from api.agent_api import FileUpdate as AgentFileUpdate
from api.files import FileCreate, FileUpdate


@pytest.mark.parametrize("model", [FileCreate, AgentFileCreate])
@pytest.mark.parametrize("title", ["设定" * 1600, "😀" * 256], ids=["body-sized-cjk", "over-limit-emoji"])
def test_requests_reject_body_sized_titles(model, title):
    with pytest.raises(ValidationError):
        model(title=title)


@pytest.mark.parametrize("model", [FileCreate, FileUpdate, AgentFileCreate, AgentFileUpdate])
def test_title_boundary_keeps_long_body(model):
    body = "正文" * 4000
    value = model(title="😀" * 255, content=body)
    assert value.content == body
    assert value.title == "😀" * 255


def test_agent_rejects_invalid_title_before_any_database_use():
    from agent.tools.file_ops.crud import FileCRUD
    class NoDatabase:
        def __getattr__(self, name):
            pytest.fail(f"Invalid title reached database: {name}")
    crud = FileCRUD(NoDatabase(), "user")
    with pytest.raises(ValueError, match="255"):
        crud.create_file("project", "设定" * 1600, content="")
    with pytest.raises(ValueError, match="255"):
        crud.update_file("file", title="😀" * 256)


async def _login(client: AsyncClient, db_session: Session, name: str) -> dict:
    from models import User
    from services.core.auth_service import hash_password

    db_session.add(User(username=name, email=f"{name}@example.com", hashed_password=hash_password("password123"),
                        email_verified=True, is_active=True))
    db_session.commit()
    login = await client.post("/api/auth/login", data={"username": name, "password": "password123"})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _legacy_file(db_session: Session, username: str):
    from sqlmodel import select

    from models import File, Project, User

    user = db_session.exec(select(User).where(User.username == username)).one()
    project = Project(name="旧项目", owner_id=user.id)
    db_session.add(project)
    db_session.commit()
    # Saved before the limit existed: the title is longer than 255.
    legacy = File(project_id=project.id, title="雨" * 300, file_type="draft", content="旧正文")
    db_session.add(legacy)
    db_session.commit()
    return legacy.id


@pytest.mark.integration
async def test_legacy_long_title_still_saves_body_but_cannot_be_renamed_longer(client: AsyncClient, db_session: Session):
    headers = await _login(client, db_session, "legacy_title")
    file_id = _legacy_file(db_session, "legacy_title")

    body_only = await client.put(f"/api/v1/files/{file_id}", json={"content": "新正文"}, headers=headers)
    assert body_only.status_code == 200, body_only.text
    unchanged = await client.put(f"/api/v1/files/{file_id}", json={"title": "雨" * 300, "content": "再改"}, headers=headers)
    assert unchanged.status_code == 200, unchanged.text
    renamed = await client.put(f"/api/v1/files/{file_id}", json={"title": "雪" * 256}, headers=headers)
    assert renamed.status_code == 422, renamed.text
    shortened = await client.put(f"/api/v1/files/{file_id}", json={"title": "雨夜"}, headers=headers)
    assert shortened.status_code == 200, shortened.text


@pytest.mark.integration
async def test_agent_api_legacy_long_title_still_saves_body(client: AsyncClient, db_session: Session):
    headers = await _login(client, db_session, "legacy_agent")
    file_id = _legacy_file(db_session, "legacy_agent")
    key = await client.post("/api/v1/agent-api-keys", json={"name": "t", "scopes": ["read", "write"]}, headers=headers)
    assert key.status_code == 201, key.text
    agent = {"X-Agent-API-Key": key.json()["key"]}

    unchanged = await client.put(f"/api/v1/agent/files/{file_id}", json={"title": "雨" * 300, "content": "新"}, headers=agent)
    assert unchanged.status_code == 200, unchanged.text
    renamed = await client.put(f"/api/v1/agent/files/{file_id}", json={"title": "雪" * 256}, headers=agent)
    assert renamed.status_code == 422, renamed.text
