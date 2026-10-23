from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    MetaData,
    Numeric,
    String,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# Deterministic constraint names so Alembic migrations are reproducible.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class PaymentMethod(StrEnum):
    YAPE = "yape"
    CARD = "card"
    CASH = "cash"
    TRANSFER = "transfer"
    OTHER = "other"


class ExpenseSource(StrEnum):
    EMAIL = "email"
    MANUAL = "manual"


def _str_enum(enum_cls: type[StrEnum], name: str) -> Enum:
    # Stored as VARCHAR + CHECK instead of a native Postgres ENUM,
    # so adding a value later is a simple migration.
    return Enum(
        enum_cls,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=20,
        values_callable=lambda e: [member.value for member in e],
    )


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50), unique=True)


class Merchant(Base):
    """A store or person the agent already knows, with the category it learned."""

    __tablename__ = "merchants"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    default_category_id: Mapped[int | None] = mapped_column(
        ForeignKey("categories.id")
    )

    default_category: Mapped[Category | None] = relationship()


class Expense(Base):
    __tablename__ = "expenses"
    __table_args__ = (
        CheckConstraint("amount > 0", name="amount_positive"),
        CheckConstraint(
            "(source = 'email') = (source_email_id IS NOT NULL)",
            name="email_source_has_email_id",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3))
    spent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    description: Mapped[str | None] = mapped_column(String(500))
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"))
    merchant_id: Mapped[int | None] = mapped_column(ForeignKey("merchants.id"))
    payment_method: Mapped[PaymentMethod] = mapped_column(
        _str_enum(PaymentMethod, "payment_method")
    )
    source: Mapped[ExpenseSource] = mapped_column(_str_enum(ExpenseSource, "source"))
    # Gmail message id; unique so the same email can never create two expenses.
    source_email_id: Mapped[str | None] = mapped_column(String(100), unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    category: Mapped[Category | None] = relationship()
    merchant: Mapped[Merchant | None] = relationship()
