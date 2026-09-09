"""add species audio snippets

Revision ID: 3e8a1b5c9d20
Revises: 2d9f7a6c4b10
Create Date: 2026-09-09 10:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "3e8a1b5c9d20"
down_revision: str | None = "2d9f7a6c4b10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("species", sa.Column("best_snippet_path", sa.Text(), nullable=True))
    op.add_column("species", sa.Column("best_snippet_url", sa.Text(), nullable=True))
    op.add_column("species", sa.Column("best_snippet_confidence", sa.Float(), nullable=True))
    op.add_column("species", sa.Column("best_snippet_spot_name", sa.String(length=200), nullable=True))
    op.add_column("species", sa.Column("best_snippet_project_id", sa.String(length=120), nullable=True))
    op.add_column(
        "species",
        sa.Column("best_snippet_window", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )

    op.add_column("spot_species_summaries", sa.Column("snippet_rel_path", sa.Text(), nullable=True))
    op.add_column("spot_species_summaries", sa.Column("snippet_url", sa.Text(), nullable=True))
    op.add_column("spot_species_summaries", sa.Column("snippet_confidence", sa.Float(), nullable=True))
    op.add_column(
        "spot_species_summaries",
        sa.Column("snippet_detection_window", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "spot_species_summaries",
        sa.Column("snippet_window", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("spot_species_summaries", "snippet_window")
    op.drop_column("spot_species_summaries", "snippet_detection_window")
    op.drop_column("spot_species_summaries", "snippet_confidence")
    op.drop_column("spot_species_summaries", "snippet_url")
    op.drop_column("spot_species_summaries", "snippet_rel_path")

    op.drop_column("species", "best_snippet_window")
    op.drop_column("species", "best_snippet_project_id")
    op.drop_column("species", "best_snippet_spot_name")
    op.drop_column("species", "best_snippet_confidence")
    op.drop_column("species", "best_snippet_url")
    op.drop_column("species", "best_snippet_path")
