"""Business logic for expenses, merchants and categories.

Each function receives a database session and a schema input, commits its own
changes and returns a schema output. The agent tools and the HTTP endpoints
are thin adapters over these functions.
"""

from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import Select, func, select, update
from sqlalchemy.orm import Session

from centinel.config import get_settings
from centinel.db.models import (
    Category,
    EmailStatus,
    Expense,
    ExpenseSource,
    Merchant,
    TrackedEmail,
)
from centinel.errors import UserError
from centinel.expenses.schemas import (
    CreateCategoryInput,
    ExpenseOut,
    FindMerchantInput,
    GetSpendingInput,
    ListExpensesInput,
    MerchantOut,
    SaveExpenseInput,
    SetMerchantCategoryInput,
    SetMerchantCategoryOut,
    SpendingTotal,
    UpdateExpenseInput,
)

# --- Helpers ---


def _find_category(session: Session, name: str) -> Category | None:
    return session.scalar(
        select(Category).where(func.lower(Category.name) == name.strip().lower())
    )


def _get_category(session: Session, name: str) -> Category:
    category = _find_category(session, name)
    if category is None:
        raise UserError(
            f"Unknown category '{name}'. "
            f"Valid categories: {', '.join(list_categories(session))}."
        )
    return category


def _find_merchant_exact(
    session: Session, name: str, reference: str | None
) -> Merchant | None:
    return session.scalar(
        select(Merchant).where(
            func.lower(Merchant.name) == name.strip().lower(),
            Merchant.reference.is_not_distinct_from(reference),
        )
    )


def _get_or_create_merchant(
    session: Session, name: str, reference: str | None = None
) -> Merchant:
    merchant = _find_merchant_exact(session, name, reference)
    if merchant is None:
        merchant = Merchant(name=name.strip(), reference=reference)
        session.add(merchant)
    return merchant


def _start_of_day(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=get_settings().timezone)


def _filter_expenses(
    stmt: Select,
    start_date: date | None = None,
    end_date: date | None = None,
    category: Category | None = None,
) -> Select:
    """Filter by whole days in the user's timezone, both ends inclusive."""
    if start_date is not None and end_date is not None and end_date < start_date:
        raise UserError(f"end_date {end_date} is before start_date {start_date}.")
    if start_date is not None:
        stmt = stmt.where(Expense.spent_at >= _start_of_day(start_date))
    if end_date is not None:
        # Up to the start of the next day, so the whole end_date is included.
        stmt = stmt.where(
            Expense.spent_at < _start_of_day(end_date + timedelta(days=1))
        )
    if category is not None:
        stmt = stmt.where(Expense.category_id == category.id)
    return stmt


# --- Service ---


def save_expense(session: Session, data: SaveExpenseInput) -> ExpenseOut:
    """Register a new expense."""
    if data.source_email_id is not None and session.scalar(
        select(Expense.id).where(Expense.source_email_id == data.source_email_id)
    ):
        raise UserError(f"The email {data.source_email_id} was already registered.")

    merchant = (
        _get_or_create_merchant(session, data.merchant, data.merchant_reference)
        if data.merchant
        else None
    )
    if data.category is not None:
        category = _get_category(session, data.category)
        # The first category a merchant gets is learned for its future expenses.
        if merchant is not None and merchant.default_category is None:
            merchant.default_category = category
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
    if data.source_email_id is not None:
        session.execute(
            update(TrackedEmail)
            .where(TrackedEmail.gmail_id == data.source_email_id)
            .values(status=EmailStatus.PROCESSED)
        )
    session.commit()
    return ExpenseOut.from_expense(expense)


def update_expense(session: Session, data: UpdateExpenseInput) -> ExpenseOut:
    """Change the given fields of one expense."""
    expense = session.get(Expense, data.id)
    if expense is None:
        raise UserError(f"There is no expense with id {data.id}.")

    if data.merchant is not None:
        expense.merchant = _get_or_create_merchant(
            session, data.merchant, data.merchant_reference
        )
    if data.category is not None:
        expense.category = _get_category(session, data.category)
    for field in ("amount", "currency", "spent_at", "description", "payment_method"):
        value = getattr(data, field)
        if value is not None:
            setattr(expense, field, value)
    session.commit()
    return ExpenseOut.from_expense(expense)


def get_spending(session: Session, data: GetSpendingInput) -> list[SpendingTotal]:
    """Total spent in a period, one row per currency (amounts are never mixed)."""
    category = _get_category(session, data.category) if data.category else None
    stmt = _filter_expenses(
        select(Expense.currency, func.sum(Expense.amount), func.count()).group_by(
            Expense.currency
        ),
        data.start_date,
        data.end_date,
        category,
    )
    return [
        SpendingTotal(currency=currency, total=total, count=count)
        for currency, total, count in session.execute(stmt.order_by(Expense.currency))
    ]


def list_expenses(session: Session, data: ListExpensesInput) -> list[ExpenseOut]:
    """List expenses, most recent first."""
    category = _get_category(session, data.category) if data.category else None
    stmt = _filter_expenses(select(Expense), data.start_date, data.end_date, category)
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
    merchant = _get_or_create_merchant(session, data.merchant, data.merchant_reference)
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


def list_categories(session: Session) -> list[str]:
    """Names of all categories, alphabetically."""
    return list(session.scalars(select(Category.name).order_by(Category.name)))


def create_category(session: Session, data: CreateCategoryInput) -> str:
    """Add a new category and return its name, stored in lowercase."""
    name = data.name.lower()
    if _find_category(session, name) is not None:
        raise UserError(f"The category '{name}' already exists.")
    session.add(Category(name=name))
    session.commit()
    return name
