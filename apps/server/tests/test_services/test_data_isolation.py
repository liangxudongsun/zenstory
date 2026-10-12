"""
Tests for data isolation across multi-tenant boundaries.

Verifies that:
1. Keyword search results are properly filtered by project_id
2. Context assembler validates project ownership
"""

import pytest
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

from agent.context.assembler import ContextAssembler
from models import File, Project, User
from services.infra.file_search_service import (
    FileSearchService,
    SearchResult,
)


@pytest.fixture(name="session")
def session_fixture():
    """Create an in-memory SQLite database for testing."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture(name="test_users")
def test_users_fixture(session: Session):
    """Create test users."""
    user1 = User(
        id="user1",
        email="user1@example.com",
        username="user1",
        hashed_password="hashed",
    )
    user2 = User(
        id="user2",
        email="user2@example.com",
        username="user2",
        hashed_password="hashed",
    )
    session.add(user1)
    session.add(user2)
    session.commit()
    session.refresh(user1)
    session.refresh(user2)
    return user1, user2


@pytest.fixture(name="test_projects")
def test_projects_fixture(session: Session, test_users):
    """Create test projects for each user."""
    user1, user2 = test_users

    project1 = Project(
        id="project1",
        name="User 1 Project",
        description="User 1 Project",
        owner_id=user1.id,
    )
    project2 = Project(
        id="project2",
        name="User 2 Project",
        description="User 2 Project",
        owner_id=user2.id,
    )
    session.add(project1)
    session.add(project2)
    session.commit()
    session.refresh(project1)
    session.refresh(project2)
    return project1, project2


@pytest.fixture(name="test_files")
def test_files_fixture(session: Session, test_projects):
    """Create test files for each project."""
    project1, project2 = test_projects

    file1 = File(
        id="file1",
        project_id=project1.id,
        title="File 1",
        content="Content for file 1",
        file_type="draft",
        is_deleted=False,
    )
    file2 = File(
        id="file2",
        project_id=project2.id,
        title="File 2",
        content="Content for file 2",
        file_type="draft",
        is_deleted=False,
    )
    session.add(file1)
    session.add(file2)
    session.commit()
    session.refresh(file1)
    session.refresh(file2)
    return file1, file2


class TestFileSearchIsolation:
    """Tests for vector search data isolation."""


    def test_lexical_search_supports_multi_token_query(self, session: Session, test_projects):
        """Lexical search should tokenize query instead of requiring full-phrase contains."""
        project1, _ = test_projects
        file_one = File(
            id="lex_file_1",
            project_id=project1.id,
            title="Hero arrives",
            content="chapter intro",
            file_type="draft",
            is_deleted=False,
        )
        file_two = File(
            id="lex_file_2",
            project_id=project1.id,
            title="City watch",
            content="the city is tense",
            file_type="draft",
            is_deleted=False,
        )
        session.add(file_one)
        session.add(file_two)
        session.commit()

        service = FileSearchService()
        results = service._lexical_search(
            session=session,
            project_id=project1.id,
            query="hero city",
            top_k=5,
            entity_types=["draft"],
        )

        result_ids = {r.entity_id for r in results}
        assert file_one.id in result_ids
        assert file_two.id in result_ids

    def test_lexical_search_skips_oversized_tokens(self, session: Session, test_projects):
        """Oversized query tokens should be ignored to avoid excessive OR conditions."""
        project1, _ = test_projects
        file_one = File(
            id="lex_file_guardrail_1",
            project_id=project1.id,
            title="Hero patrol",
            content="hero scouts the old city",
            file_type="draft",
            is_deleted=False,
        )
        session.add(file_one)
        session.commit()

        service = FileSearchService()
        long_noise = "x" * 120
        results = service._lexical_search(
            session=session,
            project_id=project1.id,
            query=f"hero {long_noise} hero",
            top_k=5,
            entity_types=["draft"],
        )

        result_ids = {r.entity_id for r in results}
        assert file_one.id in result_ids

    def test_lexical_search_overlong_single_token_uses_safe_fallback(self, session: Session, test_projects):
        """When all tokens are oversized, lexical search should use safe truncated fallback."""
        project1, _ = test_projects
        overlong_prefix = "y" * 40
        file_one = File(
            id="lex_file_guardrail_2",
            project_id=project1.id,
            title="Noise capture",
            content=f"{overlong_prefix} tail",
            file_type="draft",
            is_deleted=False,
        )
        session.add(file_one)
        session.commit()

        service = FileSearchService()
        overlong_query = "y" * 120
        results = service._lexical_search(
            session=session,
            project_id=project1.id,
            query=overlong_query,
            top_k=5,
            entity_types=["draft"],
        )

        result_ids = {r.entity_id for r in results}
        assert file_one.id in result_ids

    def test_search_result_to_dict_includes_snippet_fields(self):
        result = SearchResult(
            entity_type="draft",
            entity_id="file1",
            title="Chapter 1",
            content="line1\nline2\nline3",
            score=0.8,
            sources=["semantic"],
        )

        payload = result.to_dict()
        assert "snippet" in payload
        assert "line_start" in payload
        assert "fused_score" in payload
        assert "sources" in payload
        assert payload["fused_score"] == payload["score"]


class TestContextAssemblerIsolation:
    """Tests for Context Assembler data isolation."""

    def test_assemble_with_valid_user(self, session: Session, test_users, test_projects):
        """Test that assemble() succeeds with valid user ownership."""
        user1, _ = test_users
        project1, _ = test_projects

        assembler = ContextAssembler()
        context_data = assembler.assemble(
            session=session,
            project_id=project1.id,
            user_id=user1.id,
            max_tokens=1000,
        )

        # Should return valid context data (not empty due to permission denial)
        assert context_data is not None
        assert isinstance(context_data.context, str)

    def test_assemble_with_wrong_user(self, session: Session, test_users, test_projects):
        """Test that assemble() returns empty context for wrong user."""
        user1, user2 = test_users
        project1, _ = test_projects

        assembler = ContextAssembler()
        context_data = assembler.assemble(
            session=session,
            project_id=project1.id,
            user_id=user2.id,  # Wrong user
            max_tokens=1000,
        )

        # Should return empty context due to permission denial
        assert context_data.context == ""
        assert context_data.items == []
        assert context_data.token_estimate == 0

    def test_assemble_without_user_id(self, session: Session, test_projects):
        """Test that assemble() works without user_id (skips verification)."""
        project1, _ = test_projects

        assembler = ContextAssembler()
        context_data = assembler.assemble(
            session=session,
            project_id=project1.id,
            user_id=None,  # No user verification
            max_tokens=1000,
        )

        # Should return valid context data
        assert context_data is not None
        assert isinstance(context_data.context, str)
