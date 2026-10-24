"""Business logic for expenses, merchants and categories.

Each function receives a database session and a schema input, commits its own
changes and returns a schema output. The agent tools and the HTTP endpoints
are thin adapters over these functions.
"""

from datetime import UTC, datetime

from sqlalchemy import Select, func, select, update
from sqlalchemy.orm import Session

from centinel.db.models import Category, Expense, ExpenseSource, Merchant
from centinel.expenses.errors import ExpenseError
from centinel.expenses.schemas import (
    ExpenseOut,
    FindMerchantInput,
    GetSpendingInput,
    ListExpensesInput,
    MerchantOut,
    SaveExpenseInput,
    SetMerchantCategoryInput,
    SetMerchantCategoryOut,
    SpendingTotal,
)

# --- Helpers ---


def _get_category(session: Session, name: str) -> Category:
    category = session.scalar(
        select(Category).where(func.lower(Category.name) == name.strip().lower())
    )
    if category is None:
        valid = session.scalars(select(Category.name).order_by(Category.name)).all()
        raise ExpenseError(
            f"Unknown category '{name}'. Valid categories: {', '.join(valid)}."
        )
    return category


def _find_merchant_exact(session: Session, name: str) -> Merchant | None:
    return session.scalar(
        select(Merchant).where(func.lower(Merchant.name) == name.strip().lower())
    )


def _get_or_create_merchant(session: Session, name: str) -> Merchant:
    merchant = _find_merchant_exact(session, name)
    if merchant is None:
        merchant = Merchant(name=name.strip())
        session.add(merchant)
    return merchant


def _filter_expenses(
    stmt: Select,
    start: datetime | None = None,
    end: datetime | None = None,
    category: Category | None = None,
) -> Select:
    if start is not None:
        stmt = stmt.where(Expense.spent_at >= start)
    if end is not None:
        stmt = stmt.where(Expense.spent_at < end)
    if category is not None:
        stmt = stmt.where(Expense.category_id == category.id)
    return stmt


# --- Service ---


def save_expense(session: Session, data: SaveExpenseInput) -> ExpenseOut:
    """Register a new expense."""
    if data.source_email_id is not None and session.scalar(
        select(Expense.id).where(Expense.source_email_id == data.source_email_id)
    ):
        raise ExpenseError(f"The email {data.source_email_id} was already registered.")

    merchant = (
        _get_or_create_merchant(session, data.merchant) if data.merchant else None
    )
    if data.category is not None:
        category = _get_category(session, data.category)
    else:
        category = merchant.default_category if merchant else None

    expense = Expense(
        amount=data.amount,
        currency=data.currency,
        spent_at=data.spent_at or datetime.now(UTC),
        description=data.description,
        merchant=merchant,
        category=category,
        payment_method=data.payment_method,
        source=ExpenseSource.EMAIL if data.source_email_id else ExpenseSource.MANUAL,
        source_email_id=data.source_email_id,
    )
    session.add(expense)
    session.commit()
    return ExpenseOut.from_expense(expense)


def get_spending(session: Session, data: GetSpendingInput) -> list[SpendingTotal]:
    """Total spent in a period, one row per currency (amounts are never mixed)."""
    category = _get_category(session, data.category) if data.category else None
    stmt = _filter_expenses(
        select(Expense.currency, func.sum(Expense.amount), func.count()).group_by(
            Expense.currency
        ),
        data.start,
        data.end,
        category,
    )
    return [
        SpendingTotal(currency=currency, total=total, count=count)
        for currency, total, count in session.execute(stmt.order_by(Expense.currency))
    ]


def list_expenses(session: Session, data: ListExpensesInput) -> list[ExpenseOut]:
    """List expenses, most recent first."""
    category = _get_category(session, data.category) if data.category else None
    stmt = _filter_expenses(select(Expense), data.start, data.end, category)
    if data.merchant:
        stmt = stmt.join(Expense.merchant).where(
            Merchant.name.ilike(f"%{data.merchant.strip()}%")
        )
    stmt = stmt.order_by(Expense.spent_at.desc()).limit(data.limit)
    return [ExpenseOut.from_expense(expense) for expense in session.scalars(stmt)]


def find_merchant(session: Session, data: FindMerchantInput) -> list[MerchantOut]:
    """Look up known merchants whose name contains the query."""
    stmt = (
        select(Merchant)
        .where(Merchant.name.ilike(f"%{data.query.strip()}%"))
        .order_by(Merchant.name)
        .limit(10)
    )
    return [MerchantOut.from_merchant(merchant) for merchant in session.scalars(stmt)]


def set_merchant_category(
    session: Session, data: SetMerchantCategoryInput
) -> SetMerchantCategoryOut:
    """Learn a merchant's category and apply it to its uncategorized expenses."""
    category = _get_category(session, data.category)
    merchant = _get_or_create_merchant(session, data.merchant)
    merchant.default_category = category
    session.flush()

    updated_ids = session.scalars(
        update(Expense)
        .where(Expense.merchant_id == merchant.id, Expense.category_id.is_(None))
        .values(category_id=category.id)
        .returning(Expense.id)
    ).all()
    session.commit()
    return SetMerchantCategoryOut(
        merchant=MerchantOut.from_merchant(merchant), expenses_updated=len(updated_ids)
    )
