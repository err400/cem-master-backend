"""add spots.geo_key, replacing exact-coordinate uniqueness

Identity for a physical location, rounded to ~1.1 m instead of exact float
equality. Two consequences:

* Two GPS readings of the same recorder differing in the 7th decimal used to
  produce two map markers. They now collapse to one.
* A spot's identity survives a rename, because renaming does not move the
  recorder. That is what lets the indexer update a spot's name rather than
  forking it into a second row (INDEXING-PLAN 6.3).

Existing rows are backfilled from their own coordinates, so nothing is lost.
The upgrade will FAIL LOUDLY if two existing rows round to the same key -- that
means the database already holds two spots within a metre of each other, and
which one to keep is a judgement call, not something a migration should guess.

Revision ID: 4a1f6c2b9d17
Revises: 79ea7b4cc34e
Create Date: 2026-08-18 19:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "4a1f6c2b9d17"
down_revision: str | None = "79ea7b4cc34e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Keep in step with app.indexer.source.GEO_KEY_PRECISION.
PRECISION = 5


def upgrade() -> None:
    op.add_column("spots", sa.Column("geo_key", sa.String(length=64), nullable=True))
    # No separate index: the UNIQUE constraint below creates one.

    # Backfill from the coordinates already stored.
    #
    # The format string forces exactly PRECISION decimals INCLUDING trailing
    # zeros, so this produces the same string as Python's f"{lat:.5f}". Using a
    # variable-width format here would write "28.541" where the indexer writes
    # "28.54100" -- the same place, two different keys, and the very next pass
    # would create a duplicate spot.
    decimals = "0" * PRECISION
    op.execute(
        sa.text(
            f"""
            UPDATE spots
               SET geo_key = to_char(round(latitude::numeric,  {PRECISION}), 'FM999999990.{decimals}')
                          || ':'
                          || to_char(round(longitude::numeric, {PRECISION}), 'FM999999990.{decimals}')
            """
        )
    )

    # Offline mode (`alembic upgrade --sql`) has no connection to query, so the
    # check is skipped there. It emits SQL for review rather than applying it,
    # and the real run will still catch a genuine collision.
    if not op.get_context().as_sql:
        duplicates = op.get_bind().execute(
            sa.text(
                "SELECT geo_key, count(*) FROM spots "
                "WHERE geo_key IS NOT NULL GROUP BY geo_key HAVING count(*) > 1"
            )
        ).fetchall()
        if duplicates:
            raise RuntimeError(
                "Cannot add uq_spot_geo_key: these locations round to the same "
                f"key, so two spots sit within ~1 m of each other: {duplicates}. "
                "Merge or move them by hand, then re-run this migration."
            )

    op.create_unique_constraint("uq_spot_geo_key", "spots", ["geo_key"])
    op.drop_constraint("uq_spot_coordinates", "spots", type_="unique")


def downgrade() -> None:
    # Restoring exact-coordinate uniqueness can fail where the rounded key
    # merged rows that differ in later decimals -- but at this point they are
    # distinct rows again, so the constraint holds.
    op.create_unique_constraint("uq_spot_coordinates", "spots", ["latitude", "longitude"])
    op.drop_constraint("uq_spot_geo_key", "spots", type_="unique")
    op.drop_column("spots", "geo_key")
