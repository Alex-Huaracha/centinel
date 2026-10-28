"""Business logic for the senders whose emails Centinel reads.

Same conventions as the expenses service: each function receives a session and
a schema input, and commits its own changes.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from centinel.config import get_settings
from centinel.db.models import TrackedEmail, TrackedSender
from centinel.emails.gmail import Gmail, GmailError
from centinel.emails.schemas import AddSenderOut, SenderInput
from centinel.expenses.errors import ExpenseError


def _find_sender(session: Session, email: str) -> TrackedSender | None:
    return session.scalar(select(TrackedSender).where(TrackedSender.email == email))


def list_senders(session: Session) -> list[str]:
    """Tracked addresses, alphabetically."""
    return list(
        session.scalars(select(TrackedSender.email).order_by(TrackedSender.email))
    )


def sync_emails(
    session: Session, gmail: Gmail, senders: list[TrackedSender] | None = None
) -> int:
    """Record new emails of the senders (all tracked ones by default) as pending.

    Searching the last days again on every sync, instead of remembering the last
    sync, keeps no extra state; emails already recorded are skipped.
    Returns how many emails of the senders were found, new or not.
    """
    if senders is None:
        senders = list(session.scalars(select(TrackedSender)))
    if not senders:
        return 0
    by_email = {sender.email: sender for sender in senders}
    found = [
        email
        for email in gmail.search(list(by_email), get_settings().email_lookback_days)
        # Gmail's from: also matches similar addresses; keep only exact ones.
        if email.sender in by_email
    ]

    known = set(
        session.scalars(
            select(TrackedEmail.gmail_id).where(
                TrackedEmail.gmail_id.in_([email.gmail_id for email in found])
            )
        )
    )
    session.add_all(
        TrackedEmail(
            gmail_id=email.gmail_id,
            sender=by_email[email.sender],
            received_at=email.received_at,
        )
        for email in found
        if email.gmail_id not in known
    )
    session.commit()
    return len(found)


def add_sender(
    session: Session, data: SenderInput, gmail: Gmail | None = None
) -> AddSenderOut:
    """Start reading emails from an address and look for its recent ones."""
    # Email addresses are matched case-insensitively in practice.
    email = data.email.lower()
    if _find_sender(session, email) is not None:
        raise ExpenseError(f"The sender {email} is already tracked.")
    sender = TrackedSender(email=email)
    session.add(sender)
    session.commit()

    if gmail is None:
        return AddSenderOut(email=email, emails_found=None)
    try:
        found = sync_emails(session, gmail, [sender])
    except GmailError as error:
        raise ExpenseError(
            f"{email} was added, but its emails could not be searched. {error}"
        ) from error
    return AddSenderOut(email=email, emails_found=found)


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
