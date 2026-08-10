from datetime import date, datetime, timezone

from sqlalchemy import JSON, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Spot(Base):
    __tablename__ = "spots"
    __table_args__ = (
        UniqueConstraint("source_project_id", "source_spot_id", name="uq_source_project_spot"),
        UniqueConstraint("latitude", "longitude", name="uq_spot_coordinates"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    source_project_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    source_spot_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
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
    taxonomy: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    network_metrics: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class SpotSummary(Base):
    __tablename__ = "spot_summaries"

    spot_id: Mapped[int] = mapped_column(ForeignKey("spots.id", ondelete="CASCADE"), primary_key=True)
    species_richness: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_detections: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    recording_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    first_recording_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    last_recording_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    acoustic_indices: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    analysis_assets: Mapped[list | None] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class SpotSpeciesSummary(Base):
    __tablename__ = "spot_species_summaries"
    __table_args__ = (
        UniqueConstraint("spot_id", "species_id", name="uq_spot_species_summary"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    spot_id: Mapped[int] = mapped_column(ForeignKey("spots.id", ondelete="CASCADE"), index=True)
    species_id: Mapped[int] = mapped_column(ForeignKey("species.id", ondelete="CASCADE"), index=True)
    detection_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    recording_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    average_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    maximum_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    first_detection_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    last_detection_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    activity_regularity: Mapped[float | None] = mapped_column(Float, nullable=True)
    hourly_counts: Mapped[list | None] = mapped_column(JSON, nullable=True)
    daily_counts: Mapped[list | None] = mapped_column(JSON, nullable=True)
    analysis_metrics: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    analysis_assets: Mapped[list | None] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )
