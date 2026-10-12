"""
Regression tests for database keyword search guardrails.

These cover the defensive limits added in:
- FILE_SEARCH_DB_CANDIDATE_* (cap/multiplier)
- FILE_SEARCH_TIME_BUDGET_* (early stopping)
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlmodel import Session, select

from config.datetime_utils import utcnow
from models import File, Project, User
from services.core.auth_service import hash_password
from services.infra import file_search_service as vss


def _seed_project_with_files(
    db_session: Session,
    *,
    file_count: int,
    query_token: str,
) -> tuple[User, Project]:
    suffix = uuid4().hex[:8]
    user = User(
        email=f"file-search-guardrails-{suffix}@example.com",
        username=f"file_search_guardrails_{suffix}",
        hashed_password=hash_password("password123"),
        email_verified=True,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    project = Project(
        name=f"File Search Guardrails {suffix}",
        owner_id=user.id,
        project_type="novel",
    )
    db_session.add(project)
    db_session.commit()
    db_session.refresh(project)

    base_time = utcnow() - timedelta(minutes=10)
    files: list[File] = []
    for i in range(file_count):
        files.append(
            File(
                project_id=project.id,
                title=f"{query_token} file {i}",
                content=f"{query_token} content {i}",
                file_type="draft",
                is_deleted=False,
                updated_at=base_time + timedelta(seconds=i),
            )
        )

    db_session.add_all(files)
    db_session.commit()

    return user, project


@pytest.mark.integration
class TestFileSearchGuardrails:

    def test_lexical_search_candidate_limit_respects_cap(self, db_session: Session, monkeypatch):
        """DB prefilter should not fetch more than FILE_SEARCH_DB_CANDIDATE_CAP rows."""
        _seed_project_with_files(db_session, file_count=25, query_token="needle")

        monkeypatch.setattr(vss, "FILE_SEARCH_DB_CANDIDATE_MULTIPLIER", 1)
        monkeypatch.setattr(vss, "FILE_SEARCH_DB_CANDIDATE_CAP", 5)

        service = vss.FileSearchService()
        project_id = db_session.exec(select(Project.id)).first()
        assert project_id is not None

        results = service._lexical_search(
            session=db_session,
            project_id=project_id,
            query="needle",
            top_k=10,
            entity_types=None,
            include_content=False,
        )

        assert len(results) == 5

    def test_lexical_search_time_budget_logs_and_stops_early(self, db_session: Session, monkeypatch):
        """When time budget is exceeded, lexical scoring loop should early stop (and log)."""
        _seed_project_with_files(db_session, file_count=120, query_token="needle")

        monkeypatch.setattr(vss, "FILE_SEARCH_TIME_BUDGET_MS", 1)
        monkeypatch.setattr(vss, "FILE_SEARCH_TIME_BUDGET_MIN_CANDIDATES", 1)

        monotonic_values = iter([0.0, 999.0])

        def _fake_monotonic():
            return next(monotonic_values)

        mock_log = MagicMock()
        monkeypatch.setattr(vss, "log_with_context", mock_log)
        monkeypatch.setattr(vss.time, "monotonic", _fake_monotonic)

        service = vss.FileSearchService()
        project_id = db_session.exec(select(Project.id)).first()
        assert project_id is not None

        results = service._lexical_search(
            session=db_session,
            project_id=project_id,
            query="needle",
            top_k=20,
            entity_types=None,
            include_content=False,
        )

        # Early stopping happens after 5 candidates, so results should be <= 5.
        assert len(results) <= 5

        assert any(
            (len(call.args) >= 3 and call.args[2] == "Lexical search time budget exceeded; early stopping")
            for call in mock_log.call_args_list
        )
