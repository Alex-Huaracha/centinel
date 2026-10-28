from datetime import UTC, datetime

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from centinel.db.models import EmailStatus, TrackedEmail
from centinel.emails.gmail import FoundEmail, GmailError
from centinel.emails.schemas import SenderInput
from centinel.emails.service import (
    add_sender,
    list_senders,
    remove_sender,
    sync_emails,
)
from centinel.expenses.errors import ExpenseError

YAPE = "notificaciones@yape.example"
SHOP = "orders@shop.example"
OCT_1 = datetime(2026, 10, 1, tzinfo=UTC)


def _found(gmail_id: str, sender: str = YAPE) -> FoundEmail:
    return FoundEmail(gmail_id=gmail_id, sender=sender, received_at=OCT_1)


class FakeGmail:
    """Returns all its emails on every search, like Gmail's loose from: match."""

    def __init__(self, emails: list[FoundEmail] | None = None, fail: bool = False):
        self.emails = emails or []
        self.fail = fail
        self.searches: list[list[str]] = []

    def search(self, senders: list[str], days: int) -> list[FoundEmail]:
        if self.fail:
            raise GmailError("The Gmail script answered HTTP 500.")
        self.searches.append(senders)
        return self.emails

    def get_raw(self, gmail_id: str) -> bytes | None:
        return None


def _add(session: Session, email: str, gmail: FakeGmail | None = None) -> str:
    return add_sender(session, SenderInput(email=email), gmail).email


def _tracked(session: Session) -> list[tuple[str, str, EmailStatus]]:
    return [
        (email.gmail_id, email.sender.email, email.status)
        for email in session.scalars(select(TrackedEmail).order_by(TrackedEmail.id))
    ]


# --- add_sender / list_senders / remove_sender ---


def test_add_sender_stores_it_in_lowercase(session: Session):
    assert _add(session, "  Notificaciones@Yape.example ") == YAPE
    assert list_senders(session) == [YAPE]


def test_add_sender_rejects_tracked_address(session: Session):
    _add(session, YAPE)

    with pytest.raises(ExpenseError, match="already tracked"):
        _add(session, YAPE.upper())


@pytest.mark.parametrize("email", ["yape", "yape@", "a b@yape.example", ""])
def test_sender_input_rejects_invalid_address(email: str):
    with pytest.raises(ValidationError):
        SenderInput(email=email)


def test_add_sender_records_its_recent_emails(session: Session):
    gmail = FakeGmail([_found("g-1"), _found("g-2")])

    result = add_sender(session, SenderInput(email=YAPE), gmail)

    assert result.emails_found == 2
    assert _tracked(session) == [
        ("g-1", YAPE, EmailStatus.PENDING),
        ("g-2", YAPE, EmailStatus.PENDING),
    ]


def test_add_sender_finding_nothing_hints_at_a_typo(session: Session):
    gmail = FakeGmail([_found("g-1")])

    result = add_sender(session, SenderInput(email="notificaciones@yap.example"), gmail)

    assert result.emails_found == 0


def test_add_sender_without_gmail_reports_no_count(session: Session):
    assert add_sender(session, SenderInput(email=YAPE)).emails_found is None


def test_add_sender_keeps_sender_when_gmail_fails(session: Session):
    with pytest.raises(ExpenseError, match="was added, but"):
        _add(session, YAPE, FakeGmail(fail=True))

    assert list_senders(session) == [YAPE]


def test_list_senders_alphabetically(session: Session):
    _add(session, SHOP)
    _add(session, YAPE)

    assert list_senders(session) == [YAPE, SHOP]


def test_remove_sender_forgets_its_emails(session: Session):
    _add(session, YAPE, FakeGmail([_found("g-1")]))
    _add(session, SHOP)

    assert remove_sender(session, SenderInput(email=YAPE)) == YAPE

    assert list_senders(session) == [SHOP]
    assert _tracked(session) == []


def test_remove_sender_lists_tracked_ones_when_unknown(session: Session):
    _add(session, YAPE)

    with pytest.raises(ExpenseError, match=f"Tracked senders: {YAPE}"):
        remove_sender(session, SenderInput(email="notificaciones@yap.example"))


# --- sync_emails ---


def test_sync_emails_records_only_new_ones(session: Session):
    gmail = FakeGmail([_found("g-1")])
    _add(session, YAPE, gmail)
    gmail.emails.append(_found("g-2"))

    assert sync_emails(session, gmail) == 2

    assert [gmail_id for gmail_id, _, _ in _tracked(session)] == ["g-1", "g-2"]


def test_sync_emails_searches_all_tracked_senders(session: Session):
    _add(session, YAPE)
    _add(session, SHOP)
    gmail = FakeGmail([_found("g-1"), _found("s-1", SHOP)])

    sync_emails(session, gmail)

    assert sorted(gmail.searches[0]) == [YAPE, SHOP]
    assert [sender for _, sender, _ in _tracked(session)] == [YAPE, SHOP]


def test_sync_emails_ignores_similar_addresses(session: Session):
    _add(session, YAPE)
    gmail = FakeGmail([_found("g-1", "promo." + YAPE)])

    assert sync_emails(session, gmail) == 0
    assert _tracked(session) == []


def test_sync_emails_without_senders_does_not_call_gmail(session: Session):
    gmail = FakeGmail()

    assert sync_emails(session, gmail) == 0
    assert gmail.searches == []
