"""app_setting and job_config (admin panel)

Revision ID: a1d2e3f4b5c6
Revises: 9c3e4f5a6b71
Create Date: 2026-09-15 05:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1d2e3f4b5c6"
down_revision: str | Sequence[str] | None = "9c3e4f5a6b71"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "app_setting",
        sa.Column("key", sa.String(length=80), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("is_secret", sa.Boolean(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("key"),
    )
    op.create_table(
        "job_config",
        sa.Column("job", sa.String(length=40), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("interval_hours", sa.Float(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("job"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("job_config")
    op.drop_table("app_setting")
