"""allow multi-project spots at same physical location

Revision ID: 8b3c5e2d1f9a
Revises: 4a1f6c2b9d17
Create Date: 2026-09-07 11:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "8b3c5e2d1f9a"
down_revision: str | None = "4a1f6c2b9d17"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Drop the unique constraint so multiple projects can each define a spot at the same coordinates
    op.drop_constraint("uq_spot_geo_key", "spots", type_="unique")
    op.create_index("ix_spot_geo_key", "spots", ["geo_key"])


def downgrade() -> None:
    op.drop_index("ix_spot_geo_key", table_name="spots")
    op.create_unique_constraint("uq_spot_geo_key", "spots", ["geo_key"])
