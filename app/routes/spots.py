from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database import get_db
from app.models import Species, Spot, SpotSource, SpotSpeciesDaily, SpotSpeciesSummary
from app.schemas import SpotCreate, SpotRead

router = APIRouter(prefix="/api/v1/spots", tags=["spots"])


def require_api_key(
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
    settings: Settings = Depends(get_settings),
) -> None:
    if settings.api_key and x_api_key != settings.api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid API key",
        )


def spot_to_feature(spot: Spot) -> dict[str, Any]:
    return {
        "type": "Feature",
        "geometry": {
            "type": "Point",
            "coordinates": [spot.longitude, spot.latitude],
        },
        "properties": {
            "id": spot.id,
            "source_project_id": spot.source_project_id,
            "source_spot_id": spot.source_spot_id,
            "name": spot.name,
            "description": spot.description,
        },
    }


@router.get("")
def list_spots(
    species_id: int | None = Query(default=None, ge=1),
    migration_class: str | None = Query(default=None, max_length=40),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    if start_date and end_date and start_date > end_date:
        raise HTTPException(status_code=422, detail="start_date must be on or before end_date")
    if (start_date or end_date) and species_id is None:
        raise HTTPException(status_code=422, detail="Date filters require species_id")

    migration_class = migration_class.strip() if migration_class else None
    stmt = select(Spot).order_by(Spot.id)
    if species_id is not None:
        if db.get(Species, species_id) is None:
            raise HTTPException(status_code=404, detail="Species not found")
        summary_filter = select(SpotSpeciesSummary.spot_id).where(
            SpotSpeciesSummary.species_id == species_id
        )
        if migration_class:
            summary_filter = summary_filter.where(
                func.lower(SpotSpeciesSummary.migration_class) == migration_class.lower()
            )
        stmt = stmt.where(Spot.id.in_(summary_filter))
        if start_date or end_date:
            daily_filter = select(SpotSpeciesDaily.spot_id).where(
                SpotSpeciesDaily.species_id == species_id,
                SpotSpeciesDaily.detection_count > 0,
            )
            if start_date:
                daily_filter = daily_filter.where(SpotSpeciesDaily.observation_date >= start_date)
            if end_date:
                daily_filter = daily_filter.where(SpotSpeciesDaily.observation_date <= end_date)
            stmt = stmt.where(Spot.id.in_(daily_filter))
    elif migration_class:
        stmt = stmt.where(Spot.id.in_(
            select(SpotSpeciesSummary.spot_id).where(
                func.lower(SpotSpeciesSummary.migration_class) == migration_class.lower()
            )
        ))

    spots = db.scalars(stmt).all()
    features = []
    for spot in spots:
        feature = spot_to_feature(spot)
        feature["properties"]["source_count"] = db.scalar(
            select(func.count()).select_from(SpotSource).where(SpotSource.spot_id == spot.id)
        ) or 1
        feature["properties"]["species_count"] = db.scalar(
            select(func.count()).select_from(SpotSpeciesSummary).where(SpotSpeciesSummary.spot_id == spot.id)
        ) or 0

        if species_id is not None:
            if start_date or end_date:
                count_stmt = select(
                    func.coalesce(func.sum(SpotSpeciesDaily.detection_count), 0),
                    func.count(SpotSpeciesDaily.id),
                ).where(
                    SpotSpeciesDaily.spot_id == spot.id,
                    SpotSpeciesDaily.species_id == species_id,
                    SpotSpeciesDaily.detection_count > 0,
                )
                if start_date:
                    count_stmt = count_stmt.where(SpotSpeciesDaily.observation_date >= start_date)
                if end_date:
                    count_stmt = count_stmt.where(SpotSpeciesDaily.observation_date <= end_date)
                detection_count, active_days = db.execute(count_stmt).one()
            else:
                summary = db.scalar(select(SpotSpeciesSummary).where(
                    SpotSpeciesSummary.spot_id == spot.id,
                    SpotSpeciesSummary.species_id == species_id,
                ))
                detection_count = summary.detection_count if summary else 0
                active_days = summary.active_days if summary else 0
            feature["properties"]["detection_count"] = int(detection_count or 0)
            feature["properties"]["active_days"] = int(active_days or 0)
        features.append(feature)

    if species_id is not None:
        features.sort(key=lambda item: item["properties"]["detection_count"], reverse=True)
        for rank, feature in enumerate(features, start=1):
            feature["properties"]["activity_rank"] = rank
    else:
        ranked = sorted(
            features,
            key=lambda item: item["properties"]["species_count"],
            reverse=True,
        )
        ranks = {item["properties"]["id"]: rank for rank, item in enumerate(ranked, start=1)}
        for feature in features:
            feature["properties"]["activity_rank"] = ranks[feature["properties"]["id"]]
    return {
        "type": "FeatureCollection",
        "features": features,
    }


@router.get("/{spot_id}", response_model=SpotRead)
def get_spot(spot_id: int, db: Session = Depends(get_db)) -> Spot:
    spot = db.get(Spot, spot_id)
    if spot is None:
        raise HTTPException(status_code=404, detail="Spot not found")
    return spot


@router.post("", response_model=SpotRead, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_api_key)])
def create_spot(spot_in: SpotCreate, response: Response, db: Session = Depends(get_db)) -> Spot:
    existing_source = db.scalar(
        select(SpotSource).where(
            SpotSource.source_project_id == spot_in.source_project_id,
            SpotSource.source_spot_id == spot_in.source_spot_id,
        )
    )
    existing_legacy = db.scalar(
        select(Spot).where(
            Spot.source_project_id == spot_in.source_project_id,
            Spot.source_spot_id == spot_in.source_spot_id,
        )
    )
    if existing_source or existing_legacy:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Spot already exists")

    # Coordinates define a canonical physical spot. A new contributing project
    # at exactly the same coordinate is linked to the existing spot instead of
    # creating a duplicate map marker.
    spot = db.scalar(
        select(Spot).where(
            Spot.latitude == spot_in.latitude,
            Spot.longitude == spot_in.longitude,
        )
    )
    if spot is None:
        spot = Spot(**spot_in.model_dump())
        db.add(spot)
        db.flush()

    db.add(
        SpotSource(
            spot_id=spot.id,
            source_project_id=spot_in.source_project_id,
            source_spot_id=spot_in.source_spot_id,
        )
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Spot already exists") from exc

    db.refresh(spot)
    response.headers["Location"] = f"/api/v1/spots/{spot.id}"
    return spot
