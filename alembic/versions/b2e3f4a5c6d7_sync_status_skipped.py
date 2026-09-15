"""sync_status gains 'skipped'

Revision ID: b2e3f4a5c6d7
Revises: a1d2e3f4b5c6
Create Date: 2026-09-15 05:20:00

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b2e3f4a5c6d7"
down_revision: str | Sequence[str] | None = "a1d2e3f4b5c6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE sync_status ADD VALUE IF NOT EXISTS 'skipped'")


def downgrade() -> None:
    """Downgrade schema."""
    # PostgreSQL cannot drop an enum value; leaving it is harmless.
