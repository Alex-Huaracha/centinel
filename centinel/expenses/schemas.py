"""Inputs and outputs of the expenses service.

The input models double as the JSON schema the LLM sees, so their field
descriptions are written for the model.
"""

from datetime import datetime
from decimal import Decimal
from typing import Annotated

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from centinel.db.models import Expense, Merchant, PaymentMethod

Currency = Annotated[
    str, Field(pattern=r"^[A-Z]{3}$", description="ISO 4217 code, e.g. PEN or USD")
]


# --- Inputs ---


class SaveExpenseInput(BaseModel):
    amount: Decimal = Field(gt=Decimal(0), max_digits=12, decimal_places=2)
    currency: Currency = "PEN"
    spent_at: AwareDatetime | None = Field(
        default=None, description="When the expense happened. Defaults to now."
    )
    description: str | None = Field(default=None, max_length=500)
    merchant: str | None = Field(
        default=None, max_length=200, description="Store or person that was paid."
    )
    category: str | None = Field(
        default=None,
        description="Category name. If omitted, the merchant's learned category is used.",
    )
    payment_method: PaymentMethod = PaymentMethod.OTHER
    source_email_id: str | None = Field(
        default=None,
        max_length=100,
        description="Gmail message id, only when the expense comes from an email.",
    )


class GetSpendingInput(BaseModel):
    start: AwareDatetime = Field(description="Start of the period, inclusive.")
    end: AwareDatetime = Field(description="End of the period, exclusive.")
    category: str | None = None


class ListExpensesInput(BaseModel):
    start: AwareDatetime | None = Field(default=None, description="Inclusive.")
    end: AwareDatetime | None = Field(default=None, description="Exclusive.")
    category: str | None = None
    merchant: str | None = None
    limit: int = Field(default=20, ge=1, le=100)


class FindMerchantInput(BaseModel):
    query: str = Field(min_length=1, description="Full or partial merchant name.")


class SetMerchantCategoryInput(BaseModel):
    merchant: str = Field(min_length=1, max_length=200)
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
    category: str | None
    payment_method: PaymentMethod

    @classmethod
    def from_expense(cls, expense: Expense) -> ExpenseOut:
        return cls(
            id=expense.id,
            amount=expense.amount,
            currency=expense.currency,
            spent_at=expense.spent_at,
            description=expense.description,
            merchant=expense.merchant.name if expense.merchant else None,
            category=expense.category.name if expense.category else None,
            payment_method=expense.payment_method,
        )


class SpendingTotal(BaseModel):
    currency: str
    total: Decimal
    count: int


class MerchantOut(BaseModel):
    name: str
    category: str | None

    @classmethod
    def from_merchant(cls, merchant: Merchant) -> MerchantOut:
        category = merchant.default_category
        return cls(name=merchant.name, category=category.name if category else None)


class SetMerchantCategoryOut(BaseModel):
    merchant: MerchantOut
    expenses_updated: int = Field(
        description="Uncategorized expenses of this merchant that got the new category."
    )
