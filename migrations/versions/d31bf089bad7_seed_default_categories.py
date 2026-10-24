"""seed default categories

Revision ID: d31bf089bad7
Revises: 09f5dcce7276
Create Date: 2026-10-24 10:34:00.910686

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd31bf089bad7'
down_revision: Union[str, Sequence[str], None] = '09f5dcce7276'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


DEFAULT_CATEGORIES = [
    "food",
    "transport",
    "home",
    "health",
    "entertainment",
    "shopping",
    "services",
    "other",
]

# Lightweight table definition so this migration does not depend on the current models.
categories = sa.table("categories", sa.column("name", sa.String))


def upgrade() -> None:
    """Upgrade schema."""
    op.bulk_insert(categories, [{"name": name} for name in DEFAULT_CATEGORIES])


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(categories.delete().where(categories.c.name.in_(DEFAULT_CATEGORIES)))
