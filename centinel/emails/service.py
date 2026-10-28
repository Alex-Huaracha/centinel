"""Business logic for the senders whose emails Centinel reads.

Same conventions as the expenses service: each function receives a session and
a schema input, and commits its own changes.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from centinel.db.models import TrackedSender
from centinel.emails.schemas import SenderInput
from centinel.expenses.errors import ExpenseError


def _find_sender(session: Session, email: str) -> TrackedSender | None:
    return session.scalar(select(TrackedSender).where(TrackedSender.email == email))


def list_senders(session: Session) -> list[str]:
    """Tracked addresses, alphabetically."""
    return list(
        session.scalars(select(TrackedSender.email).order_by(TrackedSender.email))
    )


def add_sender(session: Session, data: SenderInput) -> str:
    """Start reading emails from an address. Returns it, stored in lowercase."""
    # Email addresses are matched case-insensitively in practice.
    email = data.email.lower()
    if _find_sender(session, email) is not None:
        raise ExpenseError(f"The sender {email} is already tracked.")
    session.add(TrackedSender(email=email))
    session.commit()
    return email


def remove_sender(session: Session, data: SenderInput) -> str:
    """Stop reading emails from an address. Expenses it created are kept."""
    email = data.email.lower()
    sender = _find_sender(session, email)
    if sender is None:
        tracked = ", ".join(list_senders(session)) or "none"
        raise ExpenseError(
            f"The sender {email} is not tracked. Tracked senders: {tracked}."
        )
    session.delete(sender)
    session.commit()
    return email
