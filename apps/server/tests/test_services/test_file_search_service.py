"""Database retrieval survives removal of embeddings and background indexing."""

from sqlmodel import Session

from models import File, Project, User
from services.infra.file_search_service import FileSearchService


def _seed(session: Session):
    owner = User(email='search-owner@example.com', username='search_owner', hashed_password='unused')
    other = User(email='search-other@example.com', username='search_other', hashed_password='unused')
    session.add_all([owner, other])
    session.flush()
    project = Project(name='Search project', owner_id=owner.id)
    foreign = Project(name='Other project', owner_id=other.id)
    session.add_all([project, foreign])
    session.flush()
    live = File(project_id=project.id, title='Moon harbour', file_type='draft', content='Opening\nThe harbour at night.')
    session.add_all([
        live,
        File(project_id=project.id, title='harbour deleted', file_type='draft', content='private', is_deleted=True),
        File(project_id=project.id, title='harbour folder', file_type='folder', content=''),
        File(project_id=foreign.id, title='harbour foreign', file_type='draft', content='private'),
        File(project_id=project.id, title='harbour notes', file_type='lore', content='Map'),
    ])
    session.commit()
    return project, live


def test_keyword_search_preserves_project_deleted_type_and_snippet_contract(db_session):
    project, live = _seed(db_session)
    results = FileSearchService().search(project_id=project.id, query='harbour', entity_types=['draft'], session=db_session)
    assert [r.entity_id for r in results] == [live.id]
    assert 'harbour' in results[0].snippet
    assert results[0].line_start is not None
    assert results[0].sources == ['lexical']
    assert results[0].metadata['lexical_rank'] == 1


def test_search_reads_committed_edits_without_an_index_job(db_session):
    project, live = _seed(db_session)
    service = FileSearchService()
    assert service.search(project_id=project.id, query='newscene', session=db_session) == []
    live.content = 'The newscene is already saved.'
    db_session.add(live)
    db_session.commit()
    result = service.search(project_id=project.id, query='newscene', session=db_session, include_content=True)
    assert [r.entity_id for r in result] == [live.id]
    assert result[0].content == live.content
    live.is_deleted = True
    db_session.add(live)
    db_session.commit()
    assert service.search(project_id=project.id, query='newscene', session=db_session) == []
