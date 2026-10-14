"""Durable qualification and source relation for the first writing workspace."""
from datetime import datetime

from sqlmodel import Field, SQLModel

from config.datetime_utils import utcnow


class WorkspaceOnboarding(SQLModel, table=True):
    __tablename__ = "workspace_onboarding"

    user_id: str = Field(primary_key=True, foreign_key="user.id")
    # Only the two account creation paths insert this record. Existing accounts
    # have no record; deploying or changing a clock never enrolls them later.
    registered_at: datetime = Field(default_factory=utcnow)
    status: str = Field(default="pending", max_length=32)
    initialized_at: datetime | None = None
    # Deliberately not FKs: the original result survives permanent deletion.
    project_id: str | None = Field(default=None, index=True)
    file_id: str | None = None
    opened_at: datetime | None = None
    first_manual_write_at: datetime | None = None
    first_ai_requested_at: datetime | None = None
