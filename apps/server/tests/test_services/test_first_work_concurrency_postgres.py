"""Owned PostgreSQL proof of first-work serialization and rollback."""
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlmodel import Session, SQLModel, func, select

from models import File, Project, SubscriptionPlan, User, UserPersonaProfile, WorkspaceOnboarding
from services.first_work_service import enroll_new_user, initialize_first_work
from services.project_service import create_project_with_default_folders

pytestmark = pytest.mark.skipif(not os.getenv("ZENSTORY_TEST_POSTGRES_URL"), reason="owned PostgreSQL URL required")


@pytest.fixture(scope="module")
def owned_engine():
    url = os.environ["ZENSTORY_TEST_POSTGRES_URL"]
    assert url == os.environ["DATABASE_URL"]
    engine = create_engine(url, connect_args={"options": "-c lock_timeout=5000 -c statement_timeout=15000"})
    assert engine.dialect.name == "postgresql"
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(SubscriptionPlan(name="free", display_name="Free", features={"max_projects": 3}))
        session.commit()
    try:
        yield engine
    finally:
        SQLModel.metadata.drop_all(engine)
        engine.dispose()


def seed(engine):
    with Session(engine) as session:
        suffix = uuid4().hex
        user = User(username=suffix, email=f"{suffix}@example.test", hashed_password="unused", email_verified=True)
        session.add(user)
        enroll_new_user(session, user)
        session.add(UserPersonaProfile(user_id=user.id, skipped=True))
        session.commit()
        return user.id


@pytest.mark.parametrize("leader,fail", [("initialize", False), ("manual", False), ("initialize", True)])
def test_owner_gate_serializes_initialization_with_other_tabs(owned_engine, monkeypatch, leader, fail):
    import services.project_service as projects

    uid = seed(owned_engine)
    staged, release, contender_started = threading.Event(), threading.Event(), threading.Event()
    original = projects.stage_project_with_default_folders
    calls = 0
    contender_pid = []
    def gate(session, project, lang="zh"):
        nonlocal calls
        calls += 1
        if calls == 1:
            folders = original(session, project, lang)
            staged.set()
            assert release.wait(5)
            if fail:
                raise RuntimeError("synthetic post-folder failure")
            return folders
        return original(session, project, lang)
    monkeypatch.setattr(projects, "stage_project_with_default_folders", gate)
    def first():
        with Session(owned_engine) as session:
            if leader == "manual":
                project = Project(name="Author work", owner_id=uid)
                create_project_with_default_folders(session, project)
                return project.id
            return initialize_first_work(session, uid)
    def second():
        with Session(owned_engine) as session:
            contender_pid.append(session.exec(text("select pg_backend_pid()")).scalar_one())
            contender_started.set()
            return initialize_first_work(session, uid)
    with ThreadPoolExecutor(max_workers=2) as pool:
        a = pool.submit(first)
        assert staged.wait(5)
        b = pool.submit(second)
        assert contender_started.wait(5)
        # It cannot stage a second project while the owner transaction is held.
        blocked = False
        until = time.monotonic() + 2
        while time.monotonic() < until:
            with owned_engine.connect() as observer:
                blocked = observer.execute(text("select wait_event_type from pg_stat_activity where pid=:pid"),
                                           {"pid": contender_pid[0]}).scalar() == "Lock"
            if blocked:
                break
            time.sleep(0.01)
        assert blocked and not b.done() and calls == 1
        release.set()
        if fail:
            with pytest.raises(RuntimeError, match="synthetic post-folder failure"):
                a.result(timeout=5)
        else:
            first_result = a.result(timeout=5)
        second_result = b.result(timeout=5)
    with Session(owned_engine) as session:
        projects = session.exec(select(Project).where(Project.owner_id == uid)).all()
        assert len(projects) == 1
        record = session.get(WorkspaceOnboarding, uid)
        assert record.status == ("skipped_existing" if leader == "manual" else "created")
        if leader == "manual":
            assert second_result.project_id is None
        else:
            assert second_result.project_id == projects[0].id
            if not fail:
                assert first_result.project_id == second_result.project_id
            assert session.exec(select(func.count()).select_from(File).where(
                File.project_id == projects[0].id, File.file_type != "folder")).one() == 1
