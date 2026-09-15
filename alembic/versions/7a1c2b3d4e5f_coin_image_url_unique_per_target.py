"""coin_image source_url unique per coin, not globally

Revision ID: 7a1c2b3d4e5f
Revises: 3cb47c584c0e
Create Date: 2026-09-15 01:10:00

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7a1c2b3d4e5f"
down_revision: str | Sequence[str] | None = "3cb47c584c0e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_constraint("coin_image_source_url_key", "coin_image", type_="unique")
    op.create_unique_constraint(
        "uq_coin_image_target_url", "coin_image", ["type_id", "issue_id", "source_url"]
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("uq_coin_image_target_url", "coin_image", type_="unique")
    op.create_unique_constraint("coin_image_source_url_key", "coin_image", ["source_url"])
