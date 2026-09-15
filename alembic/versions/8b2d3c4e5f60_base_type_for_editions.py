"""base_type_id allowed on special editions, not only on errors

Revision ID: 8b2d3c4e5f60
Revises: 7a1c2b3d4e5f
Create Date: 2026-09-15 02:50:00

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8b2d3c4e5f60"
down_revision: str | Sequence[str] | None = "7a1c2b3d4e5f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_constraint("ck_coin_type_error_has_base", "coin_type", type_="check")
    op.create_check_constraint(
        "ck_coin_type_error_has_base", "coin_type", "kind <> 'error' OR base_type_id IS NOT NULL"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("ck_coin_type_error_has_base", "coin_type", type_="check")
    op.create_check_constraint(
        "ck_coin_type_error_has_base", "coin_type", "(kind = 'error') = (base_type_id IS NOT NULL)"
    )
