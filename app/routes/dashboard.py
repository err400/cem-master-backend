from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Species, Spot, SpotSource, SpotSpeciesSummary, SpotSummary


router = APIRouter(prefix="/api/v1", tags=["dashboard"])


def species_to_dict(species: Species) -> dict[str, Any]:
    return {
        "id": species.id,
        "common_name": species.common_name,
        "scientific_name": species.scientific_name,
        "iucn_category": species.iucn_category,
        "image_url": species.image_url,
        "image_attribution": species.image_attribution,
        "taxonomy": species.taxonomy or {},
        "network_metrics": species.network_metrics or {},
    }


@router.get("/species")
def list_species(
    search: str | None = Query(default=None, max_length=220),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    stmt = select(Species)
    if search and search.strip():
        pattern = f"%{search.strip()}%"
        stmt = stmt.where(
            or_(
                Species.common_name.ilike(pattern),
                Species.scientific_name.ilike(pattern),
            )
        )
    species = db.scalars(stmt.order_by(Species.common_name).limit(limit)).all()
    return {"items": [species_to_dict(item) for item in species]}


@router.get("/species/{species_id}")
def get_species(species_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    species = db.get(Species, species_id)
    if species is None:
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
    top_rows = db.execute(
        select(SpotSpeciesSummary, Species)
        .join(Species, Species.id == SpotSpeciesSummary.species_id)
        .where(SpotSpeciesSummary.spot_id == spot_id)
        .order_by(SpotSpeciesSummary.detection_count.desc())
        .limit(8)
    ).all()

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
            "species_richness": summary.species_richness if summary else len(top_rows),
            "total_detections": summary.total_detections if summary else sum(row.detection_count for row, _ in top_rows),
            "recording_days": summary.recording_days if summary else 0,
            "first_recording_date": summary.first_recording_date if summary else None,
            "last_recording_date": summary.last_recording_date if summary else None,
            "acoustic_indices": summary.acoustic_indices if summary else {},
            "analysis_assets": summary.analysis_assets if summary else [],
        },
        "top_species": [
            {
                "id": species.id,
                "common_name": species.common_name,
                "scientific_name": species.scientific_name,
                "detection_count": item.detection_count,
            }
            for item, species in top_rows
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
    db: Session = Depends(get_db),
) -> dict[str, Any]:
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

    return {
        "spot": {
            "id": spot.id,
            "name": spot.name,
            "latitude": spot.latitude,
            "longitude": spot.longitude,
        },
        "species": species_to_dict(species),
        "observation": {
            "detection_count": item.detection_count,
            "recording_days": item.recording_days,
            "average_confidence": item.average_confidence,
            "maximum_confidence": item.maximum_confidence,
            "first_detection_date": item.first_detection_date,
            "last_detection_date": item.last_detection_date,
            "activity_regularity": item.activity_regularity,
            "hourly_counts": item.hourly_counts or [],
            "daily_counts": item.daily_counts or [],
            "analysis_metrics": item.analysis_metrics or {},
            "analysis_assets": item.analysis_assets or [],
        },
    }
