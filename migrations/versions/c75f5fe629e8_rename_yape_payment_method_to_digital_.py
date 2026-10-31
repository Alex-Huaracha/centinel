"""rename yape payment method to digital_wallet

Revision ID: c75f5fe629e8
Revises: 2b92b281414a
Create Date: 2026-10-30 16:15:05.180402

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c75f5fe629e8'
down_revision: Union[str, Sequence[str], None] = '2b92b281414a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Payment methods are kinds, not brands: Yape is one digital wallet among many
# (Plin, PIX, Venmo...). payment_method is VARCHAR + CHECK, so the CHECK is
# replaced around the update; autogenerate does not detect this.
CONSTRAINT = "ck_expenses_payment_method"
OLD_VALUES = ("yape", "debit_card", "credit_card", "cash", "transfer", "other")
NEW_VALUES = ("digital_wallet", "debit_card", "credit_card", "cash", "transfer", "other")

expenses = sa.table("expenses", sa.column("payment_method", sa.String))


def _check(values: tuple[str, ...]) -> str:
    return "payment_method IN ({})".format(", ".join(f"'{v}'" for v in values))


def _rename(old: str, new: str, values: tuple[str, ...]) -> None:
    op.drop_constraint(op.f(CONSTRAINT), "expenses", type_="check")
    op.execute(
        expenses.update()
        .where(expenses.c.payment_method == old)
        .values(payment_method=new)
    )
    op.create_check_constraint(op.f(CONSTRAINT), "expenses", _check(values))


def upgrade() -> None:
    """Upgrade schema."""
    _rename("yape", "digital_wallet", NEW_VALUES)


def downgrade() -> None:
    """Downgrade schema."""
    _rename("digital_wallet", "yape", OLD_VALUES)
