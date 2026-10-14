"""Coordinate active-chat ownership on the caller's existing transaction."""

from sqlalchemy import text
from sqlmodel import Session


def lock_active_chat_session(session: Session, *, user_id: str, project_id: str) -> None:
    """Serialize active-session reads/writes until the owner commits/rolls back.

    SQLite retains its existing write/commit behavior. PostgreSQL uses the same
    account/project key for API, agent resolution, and message-save fallbacks.
    This helper must not commit: requested-session activation may flush first.
    """
    if session.get_bind().dialect.name == "postgresql":
        session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"zenstory:active-chat:{user_id}:{project_id}"},
        )
