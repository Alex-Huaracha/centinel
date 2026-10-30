"""Inputs and outputs of the expenses service.

The input models double as the JSON schema the LLM sees, so their field
descriptions are written for the model.
"""

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from centinel.config import get_settings
from centinel.db.models import Expense, Merchant, PaymentMethod

Currency = Annotated[
    str, Field(pattern=r"^[A-Z]{3}$", description="ISO 4217 code, e.g. PEN or USD")
]


def _assume_user_timezone(value: datetime) -> datetime:
    # People speak in local time, so a datetime without offset is the user's.
    if value.tzinfo is None:
        return value.replace(tzinfo=get_settings().timezone)
    return value


UserDatetime = Annotated[datetime, AfterValidator(_assume_user_timezone)]

# Tells the model the offset is optional.
DATETIME_FORMAT = "ISO 8601. Without a UTC offset, it is the user's local time."

MerchantReference = Annotated[
    str,
    Field(
        max_length=20,
        description=(
            "Visible digits of the payee's number when they are named only partly, "
            "e.g. 606 from XXXXXXXXXXXX606. Tells apart people with the same name."
        ),
    ),
]


class _MerchantFields(BaseModel):
    merchant: str | None = Field(
        default=None, max_length=200, description="Store or person that was paid."
    )
    merchant_reference: MerchantReference | None = None

    @model_validator(mode="after")
    def _reference_needs_merchant(self) -> _MerchantFields:
        if self.merchant_reference is not None and self.merchant is None:
            raise ValueError("merchant_reference requires merchant.")
        return self


# --- Inputs ---


class SaveExpenseInput(_MerchantFields):
    amount: Decimal = Field(gt=Decimal(0), max_digits=12, decimal_places=2)
    currency: Currency = "PEN"
    spent_at: UserDatetime | None = Field(
        default=None,
        description=f"When the expense happened. Defaults to now. {DATETIME_FORMAT}",
    )
    description: str | None = Field(default=None, max_length=500)
    category: str | None = Field(
        default=None,
        description=(
            "Category name. If omitted, the merchant's learned category is used. "
            "A merchant without one learns this category."
        ),
    )
    payment_method: PaymentMethod = Field(
        default=PaymentMethod.OTHER,
        description=f"One of: {', '.join(PaymentMethod)}.",
    )
    source_email_id: str | None = Field(
        default=None,
        max_length=100,
        description="Gmail message id, only when the expense comes from an email.",
    )


class UpdateExpenseInput(_MerchantFields):
    """Only the fields given are changed; the rest stay as they are."""

    id: int = Field(description="Id of the expense, as list_expenses shows it.")
    amount: Decimal | None = Field(
        default=None, gt=Decimal(0), max_digits=12, decimal_places=2
    )
    currency: Currency | None = None
    spent_at: UserDatetime | None = Field(default=None, description=DATETIME_FORMAT)
    description: str | None = Field(default=None, max_length=500)
    category: str | None = None
    payment_method: PaymentMethod | None = Field(
        default=None, description=f"One of: {', '.join(PaymentMethod)}."
    )


class SpendingGroup(StrEnum):
    CATEGORY = "category"
    MERCHANT = "merchant"
    DAY = "day"
    WEEK = "week"
    MONTH = "month"


class ExpenseOrder(StrEnum):
    DATE = "date"
    AMOUNT = "amount"


class MissingField(StrEnum):
    CATEGORY = "category"
    DESCRIPTION = "description"


class ExpenseFilters(BaseModel):
    category: str | None = None
    merchant: str | None = Field(
        default=None, description="Full or partial merchant name."
    )
    payment_method: PaymentMethod | None = None


class GetSpendingInput(ExpenseFilters):
    start_date: date = Field(description="First day of the period, inclusive.")
    end_date: date = Field(description="Last day of the period, inclusive.")
    group_by: SpendingGroup | None = Field(
        default=None,
        description=(
            "Split the totals by category or merchant, largest first, or by day, "
            "week or month, in date order. Weeks start on Monday."
        ),
    )


class ListExpensesInput(ExpenseFilters):
    start_date: date | None = Field(default=None, description="First day, inclusive.")
    end_date: date | None = Field(default=None, description="Last day, inclusive.")
    missing: MissingField | None = Field(
        default=None, description="Only the expenses without this field."
    )
    order_by: ExpenseOrder = Field(
        default=ExpenseOrder.DATE,
        description="date: most recent first. amount: largest first.",
    )
    limit: int = Field(default=20, ge=1, le=100)


class FindMerchantInput(BaseModel):
    query: str = Field(min_length=1, description="Full or partial merchant name.")


class SetMerchantCategoryInput(BaseModel):
    merchant: str = Field(min_length=1, max_length=200)
    merchant_reference: MerchantReference | None = None
    category: str


class CreateCategoryInput(BaseModel):
    # Strip before validating, so "  " is rejected as empty.
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(
        min_length=1, max_length=50, description="Category name chosen by the user."
    )


# --- Outputs ---


class ExpenseOut(BaseModel):
    id: int
    amount: Decimal
    currency: str
    spent_at: datetime
    description: str | None
    merchant: str | None
    merchant_reference: str | None
    category: str | None
    payment_method: PaymentMethod

    @classmethod
    def from_expense(cls, expense: Expense) -> ExpenseOut:
        merchant = expense.merchant
        return cls(
            id=expense.id,
            amount=expense.amount,
            currency=expense.currency,
            spent_at=expense.spent_at,
            description=expense.description,
            merchant=merchant.name if merchant else None,
            merchant_reference=merchant.reference if merchant else None,
            category=expense.category.name if expense.category else None,
            payment_method=expense.payment_method,
        )


class SpendingTotal(BaseModel):
    currency: str
    total: Decimal
    count: int


class SpendingGroupTotal(SpendingTotal):
    group: str | None = Field(
        description=(
            "The category, the merchant (with its reference, if any) or the first "
            "day of the day, week or month. Null for the expenses without a "
            "category or merchant."
        ),
    )


class SpendingOut(BaseModel):
    totals: list[SpendingTotal] = Field(
        description="Total of the whole period, one per currency."
    )
    groups: list[SpendingGroupTotal] = Field(
        default=[], description="The breakdown asked with group_by."
    )


class MerchantOut(BaseModel):
    name: str
    reference: str | None
    category: str | None

    @classmethod
    def from_merchant(cls, merchant: Merchant) -> MerchantOut:
        category = merchant.default_category
        return cls(
            name=merchant.name,
            reference=merchant.reference,
            category=category.name if category else None,
        )


class SetMerchantCategoryOut(BaseModel):
    merchant: MerchantOut
    expenses_updated: int = Field(
        description="Uncategorized expenses of this merchant that got the new category."
    )
