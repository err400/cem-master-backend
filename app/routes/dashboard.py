from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.indexer.rollups import SENSITIVE_IUCN_CATEGORIES
from app.models import (
    AnalysisJob,
    Species,
    Spot,
    SpotEnvironmentDaily,
    SpotSource,
    SpotSpeciesDaily,
    SpotSpeciesSummary,
    SpotSummary,
)


router = APIRouter(prefix="/api/v1", tags=["dashboard"])


def species_to_dict(species: Species) -> dict[str, Any]:
    metrics = dict(species.network_metrics or {})
    if species.migration_class:
        metrics.setdefault("migration", species.migration_class)
    if species.activity_hours:
        metrics.setdefault("activity_hours", species.activity_hours)
    if species.seasonality:
        metrics.setdefault("seasonality", species.seasonality)
    return {
        "id": species.id,
        "common_name": species.common_name,
        "scientific_name": species.scientific_name,
        "iucn_category": species.iucn_category,
        "image_url": species.image_url,
        "image_attribution": species.image_attribution,
        "migration_class": species.migration_class,
        "activity_hours": species.activity_hours,
        "seasonality": species.seasonality,
        "taxonomy": species.taxonomy or {},
        "network_metrics": metrics,
    }


@router.get("/species")
def list_species(
    search: str | None = Query(default=None, max_length=220),
    migration_class: str | None = Query(default=None, max_length=40),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    # Only return species with active public observations
    active_species_ids = select(SpotSpeciesSummary.species_id).distinct()
    stmt = select(Species).where(Species.id.in_(active_species_ids))

    # Exclude sensitive/endangered categories
    stmt = stmt.where(
        or_(
            Species.iucn_category.is_(None),
            func.upper(Species.iucn_category).not_in(SENSITIVE_IUCN_CATEGORIES),
        )
    )

    if search and search.strip():
        pattern = f"%{search.strip()}%"
        stmt = stmt.where(
            or_(
                Species.common_name.ilike(pattern),
                Species.scientific_name.ilike(pattern),
            )
        )
    if migration_class and migration_class.strip():
        stmt = stmt.where(
            func.lower(Species.migration_class) == migration_class.strip().lower()
        )
    species = db.scalars(stmt.order_by(Species.common_name).limit(limit)).all()
    return {"items": [species_to_dict(item) for item in species]}


@router.get("/species/{species_id}")
def get_species(species_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    species = db.get(Species, species_id)
    if species is None:
        raise HTTPException(status_code=404, detail="Species not found")
    if species.iucn_category and species.iucn_category.strip().upper() in SENSITIVE_IUCN_CATEGORIES:
        raise HTTPException(status_code=404, detail="Species not found")
    result = species_to_dict(species)
    result["spot_count"] = db.scalar(
        select(func.count()).select_from(SpotSpeciesSummary).where(
            SpotSpeciesSummary.species_id == species_id
        )
    ) or 0
    return result


@router.get("/spots/{spot_id}/summary")
def get_spot_summary(spot_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    spot = db.get(Spot, spot_id)
    if spot is None:
        raise HTTPException(status_code=404, detail="Spot not found")

    summary = db.get(SpotSummary, spot_id)
    sources = db.scalars(
        select(SpotSource).where(SpotSource.spot_id == spot_id).order_by(SpotSource.id)
    ).all()
    inventory_rows = db.execute(
        select(SpotSpeciesSummary, Species)
        .join(Species, Species.id == SpotSpeciesSummary.species_id)
        .where(SpotSpeciesSummary.spot_id == spot_id)
        .order_by(SpotSpeciesSummary.detection_count.desc())
    ).all()
    job_count = db.scalar(
        select(func.count()).select_from(AnalysisJob).where(AnalysisJob.spot_id == spot_id)
    ) or 0

    return {
        "spot": {
            "id": spot.id,
            "name": spot.name,
            "description": spot.description,
            "latitude": spot.latitude,
            "longitude": spot.longitude,
            "source_count": len(sources) or 1,
        },
        "summary": {
            "species_richness": summary.species_richness if summary else len(inventory_rows),
            "total_detections": summary.total_detections if summary else sum(row.detection_count for row, _ in inventory_rows),
            "recording_count": summary.recording_count if summary else 0,
            "active_days": summary.active_days if summary else 0,
            # Kept for the current frontend while it migrates to active_days.
            "recording_days": summary.active_days if summary else 0,
            "job_count": job_count,
            "first_recording_date": summary.first_recording_date if summary else None,
            "last_recording_date": summary.last_recording_date if summary else None,
            "acoustic_indices": summary.acoustic_indices if summary else {},
            "analysis_assets": (summary.analysis_assets or []) if summary else [],
        },
        "top_species": [
            {
                "id": species.id,
                "common_name": species.common_name,
                "scientific_name": species.scientific_name,
                "detection_count": item.detection_count,
            }
            for item, species in inventory_rows[:8]
        ],
        "bird_inventory": [
            {
                "id": species.id,
                "common_name": species.common_name,
                "scientific_name": species.scientific_name,
                "iucn_category": species.iucn_category,
                "detection_count": item.detection_count,
                "active_days": item.active_days,
                "activity_rank": item.activity_rank,
                "migration_class": item.migration_class,
                "first_occurrence": item.first_detection_date,
                "last_occurrence": item.last_detection_date,
                "monthly_counts": item.monthly_counts or [],
            }
            for item, species in inventory_rows
        ],
        "sources": [
            {
                "source_project_id": source.source_project_id,
                "source_spot_id": source.source_spot_id,
                "contributed_at": source.contributed_at,
            }
            for source in sources
        ],
    }


@router.get("/spots/{spot_id}/species/{species_id}")
def get_spot_species_summary(
    spot_id: int,
    species_id: int,
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    if start_date and end_date and start_date > end_date:
        raise HTTPException(status_code=422, detail="start_date must be on or before end_date")
    spot = db.get(Spot, spot_id)
    species = db.get(Species, species_id)
    if spot is None:
        raise HTTPException(status_code=404, detail="Spot not found")
    if species is None:
        raise HTTPException(status_code=404, detail="Species not found")

    item = db.scalar(
        select(SpotSpeciesSummary).where(
            SpotSpeciesSummary.spot_id == spot_id,
            SpotSpeciesSummary.species_id == species_id,
        )
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Species has no observations at this spot")

    detection_count = item.detection_count
    active_days = item.active_days
    first_detection_date = item.first_detection_date
    last_detection_date = item.last_detection_date
    daily_counts = item.daily_counts or []
    if start_date or end_date:
        daily_stmt = select(SpotSpeciesDaily).where(
            SpotSpeciesDaily.spot_id == spot_id,
            SpotSpeciesDaily.species_id == species_id,
            SpotSpeciesDaily.detection_count > 0,
        )
        if start_date:
            daily_stmt = daily_stmt.where(SpotSpeciesDaily.observation_date >= start_date)
        if end_date:
            daily_stmt = daily_stmt.where(SpotSpeciesDaily.observation_date <= end_date)
        daily_rows = db.scalars(daily_stmt.order_by(SpotSpeciesDaily.observation_date)).all()
        if not daily_rows:
            raise HTTPException(status_code=404, detail="No detections in the selected date range")
        detection_count = sum(row.detection_count for row in daily_rows)
        active_days = len(daily_rows)
        first_detection_date = daily_rows[0].observation_date
        last_detection_date = daily_rows[-1].observation_date
        daily_counts = [
            {"date": row.observation_date, "count": row.detection_count}
            for row in daily_rows
        ]

    jobs = db.scalars(
        select(AnalysisJob).where(
            AnalysisJob.spot_id == spot_id,
            or_(AnalysisJob.species_id == species_id, AnalysisJob.species_id.is_(None)),
        ).order_by(AnalysisJob.started_at.desc(), AnalysisJob.job_id)
    ).all()

    return {
        "spot": {
            "id": spot.id,
            "name": spot.name,
            "latitude": spot.latitude,
            "longitude": spot.longitude,
        },
        "species": species_to_dict(species),
        "observation": {
            "detection_count": detection_count,
            "active_days": active_days,
            # Kept for the current frontend while it migrates to active_days.
            "recording_days": active_days,
            "activity_rank": item.activity_rank,
            "migration_class": item.migration_class,
            "average_confidence": item.average_confidence,
            "maximum_confidence": item.maximum_confidence,
            "first_detection_date": first_detection_date,
            "last_detection_date": last_detection_date,
            "activity_regularity": item.activity_regularity,
            "hourly_counts": item.hourly_counts or [],
            "daily_counts": daily_counts,
            "monthly_counts": item.monthly_counts or [],
            "analysis_metrics": item.analysis_metrics or {},
            "analysis_assets": item.analysis_assets or [],
        },
        "jobs": [
            {
                "job_id": job.job_id,
                "analysis_type": job.analysis_type,
                "status": job.status,
                "input_file": (job.job_metadata or {}).get("input_file"),
                "input_url": job.input_url,
                "output_file": (job.job_metadata or {}).get("output_file"),
                "output_url": job.output_url,
                "started_at": job.started_at,
                "completed_at": job.completed_at,
            }
            for job in jobs
        ],
    }


@router.get("/spots/{spot_id}/environment")
def get_spot_environment(
    spot_id: int,
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    if start_date and end_date and start_date > end_date:
        raise HTTPException(status_code=422, detail="start_date must be on or before end_date")
    if db.get(Spot, spot_id) is None:
        raise HTTPException(status_code=404, detail="Spot not found")

    stmt = select(SpotEnvironmentDaily).where(SpotEnvironmentDaily.spot_id == spot_id)
    if start_date:
        stmt = stmt.where(SpotEnvironmentDaily.observation_date >= start_date)
    if end_date:
        stmt = stmt.where(SpotEnvironmentDaily.observation_date <= end_date)
    rows = db.scalars(stmt.order_by(SpotEnvironmentDaily.observation_date)).all()
    return {
        "spot_id": spot_id,
        "items": [
            {
                "date": row.observation_date,
                "sunrise_at": row.sunrise_at,
                "sunset_at": row.sunset_at,
                "rainfall_mm": row.rainfall_mm,
                "temperature_min_c": row.temperature_min_c,
                "temperature_max_c": row.temperature_max_c,
                "temperature_mean_c": row.temperature_mean_c,
                "humidity_mean": row.humidity_mean,
                "severe_weather": row.severe_weather,
            }
            for row in rows
        ],
    }


@router.get("/rankings/threatened-spots")
def threatened_spot_rankings(db: Session = Depends(get_db)) -> dict[str, Any]:
    threatened_categories = ("VU", "EN", "CR", "Vulnerable", "Endangered", "Critically Endangered")
    rows = db.execute(
        select(Spot, func.count(SpotSpeciesSummary.id).label("threatened_species_richness"))
        .join(SpotSpeciesSummary, SpotSpeciesSummary.spot_id == Spot.id)
        .join(Species, Species.id == SpotSpeciesSummary.species_id)
        .where(Species.iucn_category.in_(threatened_categories))
        .group_by(Spot.id)
        .order_by(func.count(SpotSpeciesSummary.id).desc(), Spot.name)
    ).all()
    return {
        "items": [
            {
                "rank": rank,
                "spot_id": spot.id,
                "spot_name": spot.name,
                "threatened_species_richness": richness,
            }
            for rank, (spot, richness) in enumerate(rows, start=1)
        ]
    }
