"""add audio recordings and bird occurrences

Revision ID: 2d9f7a6c4b10
Revises: 8b3c5e2d1f9a
Create Date: 2026-09-08 12:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "2d9f7a6c4b10"
down_revision: str | None = "8b3c5e2d1f9a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "audio_recordings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_audio_id", sa.String(length=40), nullable=False),
        sa.Column("spot_id", sa.Integer(), nullable=False),
        sa.Column("source_project_id", sa.String(length=120), nullable=False),
        sa.Column("source_spot_id", sa.String(length=120), nullable=False),
        sa.Column("filename", sa.String(length=260), nullable=False),
        sa.Column("relative_path", sa.Text(), nullable=False),
        sa.Column("recorded_date", sa.Date(), nullable=True),
        sa.Column("hour", sa.Integer(), nullable=True),
        sa.Column("minute", sa.Integer(), nullable=True),
        sa.Column("second", sa.Integer(), nullable=True),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("sample_rate", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["spot_id"], ["spots.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_audio_id", name="uq_audio_recordings_source_audio_id"),
        sa.UniqueConstraint(
            "source_project_id",
            "source_spot_id",
            "filename",
            name="uq_audio_recording_source_file",
        ),
    )
    op.create_index("ix_audio_recordings_spot_date", "audio_recordings", ["spot_id", "recorded_date"])
    op.create_index(op.f("ix_audio_recordings_recorded_date"), "audio_recordings", ["recorded_date"])
    op.create_index(op.f("ix_audio_recordings_source_project_id"), "audio_recordings", ["source_project_id"])
    op.create_index(op.f("ix_audio_recordings_source_spot_id"), "audio_recordings", ["source_spot_id"])
    op.create_index(op.f("ix_audio_recordings_spot_id"), "audio_recordings", ["spot_id"])

    op.create_table(
        "bird_occurrences",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("audio_recording_id", sa.Integer(), nullable=False),
        sa.Column("spot_id", sa.Integer(), nullable=False),
        sa.Column("species_id", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("start_time_seconds", sa.Float(), nullable=True),
        sa.Column("end_time_seconds", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["audio_recording_id"], ["audio_recordings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["species_id"], ["species.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["spot_id"], ["spots.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_bird_occurrences_recording_species",
        "bird_occurrences",
        ["audio_recording_id", "species_id"],
    )
    op.create_index("ix_bird_occurrences_species_spot", "bird_occurrences", ["species_id", "spot_id"])
    op.create_index(op.f("ix_bird_occurrences_audio_recording_id"), "bird_occurrences", ["audio_recording_id"])
    op.create_index(op.f("ix_bird_occurrences_species_id"), "bird_occurrences", ["species_id"])
    op.create_index(op.f("ix_bird_occurrences_spot_id"), "bird_occurrences", ["spot_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_bird_occurrences_spot_id"), table_name="bird_occurrences")
    op.drop_index(op.f("ix_bird_occurrences_species_id"), table_name="bird_occurrences")
    op.drop_index(op.f("ix_bird_occurrences_audio_recording_id"), table_name="bird_occurrences")
    op.drop_index("ix_bird_occurrences_species_spot", table_name="bird_occurrences")
    op.drop_index("ix_bird_occurrences_recording_species", table_name="bird_occurrences")
    op.drop_table("bird_occurrences")

    op.drop_index(op.f("ix_audio_recordings_spot_id"), table_name="audio_recordings")
    op.drop_index(op.f("ix_audio_recordings_source_spot_id"), table_name="audio_recordings")
    op.drop_index(op.f("ix_audio_recordings_source_project_id"), table_name="audio_recordings")
    op.drop_index(op.f("ix_audio_recordings_recorded_date"), table_name="audio_recordings")
    op.drop_index("ix_audio_recordings_spot_date", table_name="audio_recordings")
    op.drop_table("audio_recordings")
