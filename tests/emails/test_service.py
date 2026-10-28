from datetime import UTC, datetime

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from centinel.db.models import TrackedEmail, TrackedSender
from centinel.emails.schemas import SenderInput
from centinel.emails.service import add_sender, list_senders, remove_sender
from centinel.expenses.errors import ExpenseError

YAPE = "notificaciones@yape.example"


def _add(session: Session, email: str) -> str:
    return add_sender(session, SenderInput(email=email))


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


def test_list_senders_alphabetically(session: Session):
    _add(session, "orders@shop.example")
    _add(session, YAPE)

    assert list_senders(session) == [YAPE, "orders@shop.example"]


def test_remove_sender_forgets_its_emails(session: Session):
    _add(session, YAPE)
    _add(session, "orders@shop.example")
    yape = session.scalar(select(TrackedSender).where(TrackedSender.email == YAPE))
    session.add(
        TrackedEmail(gmail_id="g-1", sender=yape, received_at=datetime.now(UTC))
    )
    session.commit()

    assert remove_sender(session, SenderInput(email=YAPE)) == YAPE

    assert list_senders(session) == ["orders@shop.example"]
    assert session.scalars(select(TrackedEmail)).all() == []


def test_remove_sender_lists_tracked_ones_when_unknown(session: Session):
    _add(session, YAPE)

    with pytest.raises(ExpenseError, match=f"Tracked senders: {YAPE}"):
        remove_sender(session, SenderInput(email="notificaciones@yap.example"))
