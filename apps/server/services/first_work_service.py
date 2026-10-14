"""One transactional, model-free starting workspace for newly registered authors."""
from __future__ import annotations

import json
from datetime import datetime

from pydantic import BaseModel
from sqlmodel import Session, col, select, update

from config.datetime_utils import utcnow
from core.error_codes import ErrorCode
from core.error_handler import APIException
from models import File, Project, User, UserPersonaProfile, WorkspaceOnboarding
from services.quota_service import quota_service

VALID_TYPES = {"novel", "short", "screenplay"}
PERSONA_TYPES = {"short_story": "short", "screenwriter": "screenplay"}


class FirstWorkState(BaseModel):
    status: str
    project_id: str | None = None
    file_id: str | None = None
    available: bool = False
    static_guidance: bool = False
    opened_at: datetime | None = None
    first_manual_write_at: datetime | None = None
    first_ai_requested_at: datetime | None = None


def enroll_new_user(session: Session, user: User) -> None:
    """Stage qualification in the same transaction as a genuinely new account."""
    session.flush()  # The new user must exist before its FK row; still one transaction.
    session.add(WorkspaceOnboarding(user_id=user.id))


def _state(session: Session, record: WorkspaceOnboarding | None) -> FirstWorkState:
    if record is None:
        return FirstWorkState(status="ineligible")
    project = session.get(Project, record.project_id) if record.project_id else None
    file = session.get(File, record.file_id) if record.file_id else None
    available = bool(project and project.owner_id == record.user_id and not project.is_deleted
                     and file and file.project_id == project.id and not file.is_deleted)
    return FirstWorkState(
        status=record.status, project_id=record.project_id, file_id=record.file_id,
        available=available, static_guidance=available and record.first_ai_requested_at is None,
        opened_at=record.opened_at, first_manual_write_at=record.first_manual_write_at,
        first_ai_requested_at=record.first_ai_requested_at,
    )


def get_first_work_state(session: Session, user_id: str) -> FirstWorkState:
    return _state(session, session.get(WorkspaceOnboarding, user_id))


def consume_for_author_project(session: Session, user_id: str | None) -> None:
    """Called inside the common owner creation gate, before the author's commit."""
    if user_id:
        session.exec(update(WorkspaceOnboarding).where(
            col(WorkspaceOnboarding.user_id) == user_id,
            col(WorkspaceOnboarding.status) == "pending",
        ).values(status="skipped_existing", initialized_at=utcnow()))


def initialize_first_work(
    session: Session, user_id: str, *, preferred_type: str | None = None, lang: str = "zh",
) -> FirstWorkState:
    from services.project_service import stage_project_with_default_folders

    try:
        # The shared creation gate also serializes manual/Agent/inspiration
        # creation. Its quota helpers use commit=False until our final commit.
        allowed, used, limit = quota_service.check_project_limit(session, user_id, for_creation=True)
        record = session.get(WorkspaceOnboarding, user_id, populate_existing=True)
        if record is None or record.status != "pending":
            result = _state(session, record)
            session.commit()
            return result
        user = session.get(User, user_id, populate_existing=True)
        if not user.email_verified:
            session.commit()
            return FirstWorkState(status="waiting_verification")
        profile = session.exec(select(UserPersonaProfile).where(UserPersonaProfile.user_id == user_id)).first()
        if profile is None:
            session.commit()
            return FirstWorkState(status="waiting_onboarding")
        # Include deleted rows, and persist the result even if those rows later
        # disappear. Zero active projects is never treated as new eligibility.
        if session.exec(select(Project.id).where(Project.owner_id == user_id)).first():
            consume_for_author_project(session, user_id)
            session.commit()
            return get_first_work_state(session, user_id)
        if not allowed:
            raise APIException(error_code=ErrorCode.QUOTA_PROJECTS_EXCEEDED, status_code=402,
                               detail=f"Project limit reached ({used}/{limit}). Please upgrade your plan.")
        project_type = preferred_type if preferred_type in VALID_TYPES else "novel"
        if preferred_type not in VALID_TYPES:
            try:
                personas = json.loads(profile.selected_personas)
            except (ValueError, TypeError):
                personas = []
            if isinstance(personas, list):
                project_type = next((PERSONA_TYPES[p] for p in personas if isinstance(p, str) and p in PERSONA_TYPES), "novel")
        english = lang == "en"
        project = Project(name="My First Work" if english else "我的首部作品",
                          owner_id=user_id, project_type=project_type)
        stage_project_with_default_folders(session, project, lang)
        script = project_type == "screenplay"
        file = File(project_id=project.id,
                    parent_id=f"{project.id}-{'script' if script else 'draft'}-folder",
                    title=("Script" if script else "Draft") if english else ("剧本" if script else "正文"),
                    file_type="script" if script else "draft", content="")
        file.set_metadata({"creation_source": "first_work"})
        session.add(file)
        session.flush()
        record.status = "created"
        record.initialized_at = utcnow()
        record.project_id, record.file_id = project.id, file.id
        session.add(record)
        session.commit()
        return get_first_work_state(session, user_id)
    except Exception:
        session.rollback()
        raise


def record_first_work_action(session: Session, user_id: str, project_id: str, action: str) -> None:
    """Persist real actions without a prompt, manuscript, synthetic chat or event."""
    fields = {"open": "opened_at", "manual_write": "first_manual_write_at", "ai_request": "first_ai_requested_at"}
    field = fields[action]
    column = getattr(WorkspaceOnboarding, field)
    session.exec(update(WorkspaceOnboarding).where(
        col(WorkspaceOnboarding.user_id) == user_id,
        col(WorkspaceOnboarding.project_id) == project_id,
        column.is_(None),
    ).values(**{field: utcnow()}))
