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


def test_old_title_match_still_outranks_many_newer_body_matches(db_session):
    """The SQL step orders candidates by updated_at; the scorer must still see an old strong match."""
    from datetime import datetime, timedelta

    owner = User(email='pool@example.com', username='pool_owner', hashed_password='unused')
    db_session.add(owner)
    db_session.flush()
    project = Project(name='Pool', owner_id=owner.id)
    db_session.add(project)
    db_session.flush()
    start = datetime.utcnow() - timedelta(days=30)
    card = File(project_id=project.id, title='林风', file_type='character', content='主角', updated_at=start)
    db_session.add(card)
    db_session.add_all([
        File(project_id=project.id, title=f'第{i}章', file_type='draft', content=f'林风走进第{i}个院子。',
             updated_at=start + timedelta(hours=i))
        for i in range(1, 31)
    ])
    db_session.commit()
    results = FileSearchService().search(project_id=project.id, query='林风', top_k=6, session=db_session)
    assert len(results) == 6
    assert results[0].entity_id == card.id
