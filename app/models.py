from datetime import date, datetime, timezone

from sqlalchemy import Date, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Spot(Base):
    __tablename__ = "spots"
    __table_args__ = (
        UniqueConstraint("source_project_id", "source_spot_id", name="uq_source_project_spot"),
        Index("ix_spot_geo_key", "geo_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    source_project_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    source_spot_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    # Rounded-coordinate identity for a physical location: "28.54100:77.16950".
    #
    # A derived key rather than a stored comparison, because rounding inside a
    # WHERE clause cannot use an index and reintroduces float fuzziness. Nullable
    # so rows predating the column (and any created without coordinates) remain
    # valid; NULLs do not collide under a UNIQUE constraint in PostgreSQL.
    #
    # This is what makes a spot's identity survive a rename: the recorder does
    # not move, so the key does not change. See INDEXING-PLAN 6.3.
    geo_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class SpotSource(Base):
    """A contributing project/spot pair attached to one physical location."""

    __tablename__ = "spot_sources"
    __table_args__ = (
        UniqueConstraint("source_project_id", "source_spot_id", name="uq_spot_source"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    spot_id: Mapped[int] = mapped_column(ForeignKey("spots.id", ondelete="CASCADE"), index=True)
    source_project_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    source_spot_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    contributed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class Species(Base):
    __tablename__ = "species"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scientific_name: Mapped[str] = mapped_column(String(220), unique=True, nullable=False, index=True)
    common_name: Mapped[str] = mapped_column(String(220), nullable=False, index=True)
    iucn_category: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_attribution: Mapped[str | None] = mapped_column(Text, nullable=True)
    migration_class: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    activity_hours: Mapped[str | None] = mapped_column(String(160), nullable=True)
    seasonality: Mapped[str | None] = mapped_column(String(160), nullable=True)
    taxonomy: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    network_metrics: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    best_snippet_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    best_snippet_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    best_snippet_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    best_snippet_spot_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    best_snippet_project_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    best_snippet_window: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class SpotSummary(Base):
    __tablename__ = "spot_summaries"

    spot_id: Mapped[int] = mapped_column(ForeignKey("spots.id", ondelete="CASCADE"), primary_key=True)
    recording_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    species_richness: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_detections: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    active_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    job_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    first_recording_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    last_recording_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    acoustic_indices: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    analysis_assets: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class SpotSpeciesSummary(Base):
    __tablename__ = "spot_species_summaries"
    __table_args__ = (
        UniqueConstraint("spot_id", "species_id", name="uq_spot_species_summary"),
        Index("ix_spot_species_activity", "spot_id", "detection_count"),
        Index("ix_species_spot_activity", "species_id", "detection_count"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    spot_id: Mapped[int] = mapped_column(ForeignKey("spots.id", ondelete="CASCADE"), index=True)
    species_id: Mapped[int] = mapped_column(ForeignKey("species.id", ondelete="CASCADE"), index=True)
    detection_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    active_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    activity_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    migration_class: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    average_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    maximum_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    first_detection_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    last_detection_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    activity_regularity: Mapped[float | None] = mapped_column(Float, nullable=True)
    hourly_counts: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    daily_counts: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    monthly_counts: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    analysis_metrics: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    analysis_assets: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    snippet_rel_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    snippet_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    snippet_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    snippet_detection_window: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    snippet_window: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class SpotSpeciesDaily(Base):
    """Daily detection totals used for exact occurrence/date filtering."""

    __tablename__ = "spot_species_daily"
    __table_args__ = (
        UniqueConstraint(
            "spot_id", "species_id", "observation_date", name="uq_spot_species_daily"
        ),
        Index("ix_species_date_spot", "species_id", "observation_date", "spot_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    spot_id: Mapped[int] = mapped_column(ForeignKey("spots.id", ondelete="CASCADE"), index=True)
    species_id: Mapped[int] = mapped_column(ForeignKey("species.id", ondelete="CASCADE"), index=True)
    observation_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    detection_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class AudioRecording(Base):
    __tablename__ = "audio_recordings"
    __table_args__ = (
        UniqueConstraint(
            "source_audio_id",
            name="uq_audio_recordings_source_audio_id",
        ),
        UniqueConstraint(
            "source_project_id",
            "source_spot_id",
            "filename",
            name="uq_audio_recording_source_file",
        ),
        Index("ix_audio_recordings_spot_date", "spot_id", "recorded_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_audio_id: Mapped[str] = mapped_column(String(40), nullable=False)
    spot_id: Mapped[int] = mapped_column(ForeignKey("spots.id", ondelete="CASCADE"), index=True)
    source_project_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    source_spot_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    filename: Mapped[str] = mapped_column(String(260), nullable=False)
    relative_path: Mapped[str] = mapped_column(Text, nullable=False)
    recorded_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    hour: Mapped[int | None] = mapped_column(Integer, nullable=True)
    minute: Mapped[int | None] = mapped_column(Integer, nullable=True)
    second: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    sample_rate: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class BirdOccurrence(Base):
    __tablename__ = "bird_occurrences"
    __table_args__ = (
        Index("ix_bird_occurrences_species_spot", "species_id", "spot_id"),
        Index("ix_bird_occurrences_recording_species", "audio_recording_id", "species_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    audio_recording_id: Mapped[int] = mapped_column(
        ForeignKey("audio_recordings.id", ondelete="CASCADE"), index=True
    )
    spot_id: Mapped[int] = mapped_column(ForeignKey("spots.id", ondelete="CASCADE"), index=True)
    species_id: Mapped[int] = mapped_column(ForeignKey("species.id", ondelete="CASCADE"), index=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    start_time_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    end_time_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class AnalysisJob(Base):
    """Public provenance for a bioacoustic analysis run.

    input_url and output_url must be HTTP(S) API/object-storage URLs. Local DATA_DIR
    paths remain private to the backend and are never returned to the browser.
    """

    __tablename__ = "analysis_jobs"

    job_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    spot_id: Mapped[int] = mapped_column(ForeignKey("spots.id", ondelete="CASCADE"), index=True)
    species_id: Mapped[int | None] = mapped_column(
        ForeignKey("species.id", ondelete="SET NULL"), nullable=True, index=True
    )
    analysis_type: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(40), default="completed", nullable=False, index=True)
    input_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    job_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class SpotEnvironmentDaily(Base):
    """Daily solar and weather measurements used by activity correlations."""

    __tablename__ = "spot_environment_daily"
    __table_args__ = (
        UniqueConstraint("spot_id", "observation_date", name="uq_spot_environment_daily"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    spot_id: Mapped[int] = mapped_column(ForeignKey("spots.id", ondelete="CASCADE"), index=True)
    observation_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    sunrise_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sunset_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rainfall_mm: Mapped[float | None] = mapped_column(Float, nullable=True)
    temperature_min_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    temperature_max_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    temperature_mean_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    humidity_mean: Mapped[float | None] = mapped_column(Float, nullable=True)
    severe_weather: Mapped[bool | None] = mapped_column(nullable=True)
