"""Helpers for consistent email account identity handling."""

from email_validator import validate_email
from sqlalchemy import func


def normalize_email_identity(email: str) -> str:
    """Normalize an email address for account identity comparisons/storage."""
    return str(email).strip().lower()


def validate_registration_email(email: str) -> None:
    """Reject ASCII TLD typos after IDNA validation, preserving valid U-/A-labels."""
    domain = validate_email(email, check_deliverability=False).ascii_domain
    tld = domain.rsplit(".", 1)[-1]
    if not (tld.isalpha() or tld.startswith("xn--")):
        raise ValueError("Invalid recipient domain")


def email_identity_matches(column, email: str):  # type: ignore[no-untyped-def]
    """Return a SQL expression matching email identity case-insensitively."""
    return func.lower(column) == normalize_email_identity(email)
