"""estimate_history and watch_item

Revision ID: 9c3e4f5a6b71
Revises: 8b2d3c4e5f60
Create Date: 2026-09-15 03:40:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "9c3e4f5a6b71"
down_revision: str | Sequence[str] | None = "8b2d3c4e5f60"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "estimate_history",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("issue_id", sa.Uuid(), nullable=False),
        sa.Column(
            "grade",
            postgresql.ENUM(name="grade", create_type=False),
            nullable=False,
        ),
        sa.Column("basis", sa.String(length=20), nullable=False),
        sa.Column("median", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("p25", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("p75", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("n_obs", sa.Integer(), nullable=False),
        sa.Column(
            "computed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(["issue_id"], ["coin_issue.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_estimate_history_issue_at", "estimate_history", ["issue_id", "computed_at"]
    )
    op.create_table(
        "watch_item",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("type_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(["type_id"], ["coin_type.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "type_id", name="uq_watch_item"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("watch_item")
    op.drop_index("ix_estimate_history_issue_at", table_name="estimate_history")
    op.drop_table("estimate_history")
