"""market_site

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-09-16 02:10:00

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d4e5f6a7b8c9"
down_revision: str | Sequence[str] | None = "c3d4e5f6a7b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "market_site",
        sa.Column("host", sa.String(length=120), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("paused_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_ok_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("pages_read", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("listings_found", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "discovered_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("host"),
    )
    # the open-web reader stores what it finds under its own source
    op.execute(
        "INSERT INTO source (id, code, name, authority_rank, kind, base_url) "
        "SELECT gen_random_uuid(), 'web', 'Tiendas y anuncios web', 8, 'market', 'https://' "
        "WHERE NOT EXISTS (SELECT 1 FROM source WHERE code = 'web')"
    )


def downgrade() -> None:
    op.drop_table("market_site")
