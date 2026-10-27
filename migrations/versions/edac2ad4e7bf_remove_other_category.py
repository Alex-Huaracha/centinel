"""remove other category

Revision ID: edac2ad4e7bf
Revises: d31bf089bad7
Create Date: 2026-10-27 10:56:24.336000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'edac2ad4e7bf'
down_revision: Union[str, Sequence[str], None] = 'd31bf089bad7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Instead of a catch-all category, the agent asks the user to create a fitting one.

# Lightweight table definitions so this migration does not depend on the current models.
categories = sa.table("categories", sa.column("id", sa.Integer), sa.column("name", sa.String))
expenses = sa.table("expenses", sa.column("category_id", sa.Integer))
merchants = sa.table("merchants", sa.column("default_category_id", sa.Integer))


def upgrade() -> None:
    """Upgrade schema."""
    other_id = (
        sa.select(categories.c.id).where(categories.c.name == "other").scalar_subquery()
    )
    # Whatever was filed under "other" becomes uncategorized.
    op.execute(
        expenses.update().where(expenses.c.category_id == other_id).values(category_id=None)
    )
    op.execute(
        merchants.update()
        .where(merchants.c.default_category_id == other_id)
        .values(default_category_id=None)
    )
    op.execute(categories.delete().where(categories.c.name == "other"))


def downgrade() -> None:
    """Downgrade schema."""
    op.bulk_insert(categories, [{"name": "other"}])
