from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from centinel.db.models import Expense, ExpenseSource
from centinel.expenses.errors import ExpenseError
from centinel.expenses.schemas import (
    FindMerchantInput,
    GetSpendingInput,
    ListExpensesInput,
    SaveExpenseInput,
    SetMerchantCategoryInput,
)
from centinel.expenses.service import (
    find_merchant,
    get_spending,
    list_expenses,
    save_expense,
    set_merchant_category,
)

OCT_1 = datetime(2026, 10, 1, tzinfo=UTC)
OCT_15 = datetime(2026, 10, 15, tzinfo=UTC)
NOV_1 = datetime(2026, 11, 1, tzinfo=UTC)


def _save(session: Session, **fields) -> None:
    save_expense(session, SaveExpenseInput(**fields))


# --- save_expense ---


def test_save_expense_creates_merchant_and_category(session: Session):
    result = save_expense(
        session,
        SaveExpenseInput(amount=Decimal("25.50"), merchant="Tambo", category="Food"),
    )

    assert result.amount == Decimal("25.50")
    assert result.currency == "PEN"
    assert result.merchant == "Tambo"
    assert result.category == "food"


def test_save_expense_uses_learned_merchant_category(session: Session):
    set_merchant_category(
        session, SetMerchantCategoryInput(merchant="Tambo", category="food")
    )

    result = save_expense(
        session, SaveExpenseInput(amount=Decimal(10), merchant="TAMBO")
    )

    assert result.merchant == "Tambo"
    assert result.category == "food"


def test_save_expense_rejects_unknown_category(session: Session):
    with pytest.raises(
        ExpenseError, match="Valid categories: food, shopping, transport"
    ):
        save_expense(session, SaveExpenseInput(amount=Decimal(10), category="pets"))


def test_save_expense_rejects_duplicate_email(session: Session):
    _save(session, amount=Decimal(10), source_email_id="gmail-123")

    with pytest.raises(ExpenseError, match="already registered"):
        _save(session, amount=Decimal(10), source_email_id="gmail-123")


def test_save_expense_sets_source_from_email_id(session: Session):
    email = save_expense(
        session, SaveExpenseInput(amount=Decimal(10), source_email_id="g-1")
    )
    manual = save_expense(session, SaveExpenseInput(amount=Decimal(10)))

    assert session.get_one(Expense, email.id).source == ExpenseSource.EMAIL
    assert session.get_one(Expense, manual.id).source == ExpenseSource.MANUAL


@pytest.mark.parametrize(
    "fields",
    [
        {"amount": Decimal(0)},
        {"amount": Decimal("1.234")},
        {"amount": Decimal(10), "currency": "soles"},
        {"amount": Decimal(10), "spent_at": datetime(2026, 10, 1)},
    ],
    ids=["zero-amount", "three-decimals", "bad-currency", "naive-datetime"],
)
def test_save_expense_input_validation(fields: dict):
    with pytest.raises(ValidationError):
        SaveExpenseInput(**fields)


# --- get_spending ---


def test_get_spending_sums_per_currency_within_period(session: Session):
    _save(session, amount=Decimal("10.10"), spent_at=OCT_1, category="food")
    _save(session, amount=Decimal("5.20"), spent_at=OCT_15, category="transport")
    _save(session, amount=Decimal(30), currency="USD", spent_at=OCT_15)
    _save(session, amount=Decimal(99), spent_at=NOV_1)  # end is exclusive

    totals = get_spending(session, GetSpendingInput(start=OCT_1, end=NOV_1))

    assert [(t.currency, t.total, t.count) for t in totals] == [
        ("PEN", Decimal("15.30"), 2),
        ("USD", Decimal("30.00"), 1),
    ]


def test_get_spending_filters_by_category(session: Session):
    _save(session, amount=Decimal(10), spent_at=OCT_1, category="food")
    _save(session, amount=Decimal(5), spent_at=OCT_1, category="transport")

    totals = get_spending(
        session, GetSpendingInput(start=OCT_1, end=NOV_1, category="food")
    )

    assert [(t.total, t.count) for t in totals] == [(Decimal("10.00"), 1)]


def test_get_spending_returns_empty_list_without_expenses(session: Session):
    assert get_spending(session, GetSpendingInput(start=OCT_1, end=NOV_1)) == []


# --- list_expenses ---


def test_list_expenses_most_recent_first_with_limit(session: Session):
    _save(session, amount=Decimal(1), spent_at=OCT_1)
    _save(session, amount=Decimal(2), spent_at=OCT_15)
    _save(session, amount=Decimal(3), spent_at=NOV_1)

    result = list_expenses(session, ListExpensesInput(limit=2))

    assert [e.amount for e in result] == [Decimal("3.00"), Decimal("2.00")]


def test_list_expenses_filters_by_merchant_partial_name(session: Session):
    _save(session, amount=Decimal(1), merchant="Tambo+ San Isidro")
    _save(session, amount=Decimal(2), merchant="Wong")

    result = list_expenses(session, ListExpensesInput(merchant="tambo"))

    assert [e.merchant for e in result] == ["Tambo+ San Isidro"]


# --- find_merchant / set_merchant_category ---


def test_find_merchant_by_partial_name(session: Session):
    set_merchant_category(
        session, SetMerchantCategoryInput(merchant="Tambo", category="food")
    )
    _save(session, amount=Decimal(1), merchant="Wong")

    result = find_merchant(session, FindMerchantInput(query="tam"))

    assert [(m.name, m.category) for m in result] == [("Tambo", "food")]


def test_set_merchant_category_backfills_uncategorized_expenses(session: Session):
    _save(session, amount=Decimal(1), merchant="Temu")
    _save(session, amount=Decimal(2), merchant="Temu")
    _save(session, amount=Decimal(3), merchant="Temu", category="food")  # keeps its own

    result = set_merchant_category(
        session, SetMerchantCategoryInput(merchant="temu", category="shopping")
    )

    assert result.expenses_updated == 2
    assert result.merchant.category == "shopping"
    categories = {
        e.amount: e.category for e in list_expenses(session, ListExpensesInput())
    }
    assert categories == {
        Decimal("1.00"): "shopping",
        Decimal("2.00"): "shopping",
        Decimal("3.00"): "food",
    }
