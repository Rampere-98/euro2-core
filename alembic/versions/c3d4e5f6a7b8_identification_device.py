"""identification device

Revision ID: c3d4e5f6a7b8
Revises: b2e3f4a5c6d7
Create Date: 2026-09-16 01:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c3d4e5f6a7b8"
down_revision: str | Sequence[str] | None = "b2e3f4a5c6d7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Which kind of device asked (ios/android/desktop) and whether the app was installed
    # (PWA), for the admin panel's usage breakdown. Anonymous: no model, version or IP.
    op.add_column("identification", sa.Column("device", sa.String(length=16), nullable=True))
    op.add_column("identification", sa.Column("pwa", sa.Boolean(), nullable=True))


def downgrade() -> None:
    op.drop_column("identification", "pwa")
    op.drop_column("identification", "device")
