"""Business logic for the senders whose emails Centinel reads.

Same conventions as the expenses service: each function receives a session and
a schema input, and commits its own changes.
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from centinel.config import get_settings
from centinel.db.models import EmailStatus, Expense, TrackedEmail, TrackedSender
from centinel.emails.gmail import Gmail, GmailError
from centinel.emails.parsing import email_to_text
from centinel.emails.schemas import (
    AddSenderOut,
    IgnoreEmailInput,
    ListPendingEmailsInput,
    PendingEmailOut,
    PendingEmailsOut,
    SenderInput,
)
from centinel.errors import UserError


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

    ids = [email.gmail_id for email in found]
    known = set(
        session.scalars(
            select(TrackedEmail.gmail_id).where(TrackedEmail.gmail_id.in_(ids))
        )
    )
    # A sender added again may have emails that already became expenses.
    registered = set(
        session.scalars(
            select(Expense.source_email_id).where(Expense.source_email_id.in_(ids))
        )
    )
    session.add_all(
        TrackedEmail(
            gmail_id=email.gmail_id,
            sender=by_email[email.sender],
            received_at=email.received_at,
            status=EmailStatus.PROCESSED
            if email.gmail_id in registered
            else EmailStatus.PENDING,
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
        raise UserError(f"The sender {email} is already tracked.")
    sender = TrackedSender(email=email)
    session.add(sender)
    session.commit()

    if gmail is None:
        return AddSenderOut(email=email, emails_found=None)
    try:
        found = sync_emails(session, gmail, [sender])
    except GmailError as error:
        raise UserError(
            f"{email} was added, but its emails could not be searched. {error}"
        ) from error
    return AddSenderOut(email=email, emails_found=found)


def remove_sender(session: Session, data: SenderInput) -> str:
    """Stop reading emails from an address. Expenses it created are kept."""
    email = data.email.lower()
    sender = _find_sender(session, email)
    if sender is None:
        tracked = ", ".join(list_senders(session)) or "none"
        raise UserError(
            f"The sender {email} is not tracked. Tracked senders: {tracked}."
        )
    session.delete(sender)
    session.commit()
    return email


def list_pending_emails(
    session: Session, gmail: Gmail | None, data: ListPendingEmailsInput
) -> PendingEmailsOut:
    """Look for new emails, then read the pending ones, oldest first."""
    if gmail is None:
        raise UserError("Email intake is not set up, see apps_script/README.md.")
    sync_emails(session, gmail)

    pending = select(TrackedEmail).where(TrackedEmail.status == EmailStatus.PENDING)
    emails: list[PendingEmailOut] = []
    for email in session.scalars(pending.order_by(TrackedEmail.received_at)):
        if len(emails) == data.limit:
            break
        raw = gmail.get_raw(email.gmail_id)
        if raw is None:
            # Deleted from Gmail before it was read; nothing left to register.
            email.status = EmailStatus.IGNORED
            continue
        subject, text = email_to_text(raw)
        emails.append(
            PendingEmailOut(
                gmail_id=email.gmail_id,
                sender=email.sender.email,
                received_at=email.received_at,
                subject=subject,
                text=text,
            )
        )
    session.commit()

    total = session.scalar(select(func.count()).select_from(pending.subquery()))
    return PendingEmailsOut(emails=emails, remaining=(total or 0) - len(emails))


def ignore_email(session: Session, data: IgnoreEmailInput) -> str:
    """Mark a pending email as not being an expense. Returns its id."""
    email = session.scalar(
        select(TrackedEmail).where(TrackedEmail.gmail_id == data.gmail_id)
    )
    if email is None or email.status != EmailStatus.PENDING:
        raise UserError(f"There is no pending email {data.gmail_id}.")
    email.status = EmailStatus.IGNORED
    session.commit()
    return data.gmail_id
