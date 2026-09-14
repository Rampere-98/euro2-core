"""observation_kind auction_open

Revision ID: a1b2c3d4e5f6
Revises: e4780859e0af
Create Date: 2026-09-14 21:30:00

"""

from collections.abc import Sequence

from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: str | Sequence[str] | None = "e4780859e0af"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE observation_kind ADD VALUE IF NOT EXISTS 'auction_open'")


def downgrade() -> None:
    # PostgreSQL cannot drop an enum value; rows using it would have to be removed first.
    pass
