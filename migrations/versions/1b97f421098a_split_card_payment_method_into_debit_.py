"""split card payment method into debit and credit

Revision ID: 1b97f421098a
Revises: edac2ad4e7bf
Create Date: 2026-10-27 11:03:31.058236

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1b97f421098a'
down_revision: Union[str, Sequence[str], None] = 'edac2ad4e7bf'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# payment_method is VARCHAR + CHECK (not a native ENUM), so changing its values
# means replacing the CHECK constraint. Autogenerate does not detect this.
CONSTRAINT = "ck_expenses_payment_method"
OLD_VALUES = ("yape", "card", "cash", "transfer", "other")
NEW_VALUES = ("yape", "debit_card", "credit_card", "cash", "transfer", "other")

expenses = sa.table("expenses", sa.column("payment_method", sa.String))


def _check(values: tuple[str, ...]) -> str:
    return "payment_method IN ({})".format(", ".join(f"'{v}'" for v in values))


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_constraint(op.f(CONSTRAINT), "expenses", type_="check")
    # Existing card payments did not record the type; debit is the most common.
    op.execute(
        expenses.update()
        .where(expenses.c.payment_method == "card")
        .values(payment_method="debit_card")
    )
    op.create_check_constraint(op.f(CONSTRAINT), "expenses", _check(NEW_VALUES))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(op.f(CONSTRAINT), "expenses", type_="check")
    op.execute(
        expenses.update()
        .where(expenses.c.payment_method.in_(["debit_card", "credit_card"]))
        .values(payment_method="card")
    )
    op.create_check_constraint(op.f(CONSTRAINT), "expenses", _check(OLD_VALUES))
