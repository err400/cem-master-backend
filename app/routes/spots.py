from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database import get_db
from app.models import Spot
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
def list_spots(db: Session = Depends(get_db)) -> dict[str, Any]:
    spots = db.scalars(select(Spot).order_by(Spot.id)).all()
    return {
        "type": "FeatureCollection",
        "features": [spot_to_feature(spot) for spot in spots],
    }


@router.post("", response_model=SpotRead, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_api_key)])
def create_spot(spot_in: SpotCreate, response: Response, db: Session = Depends(get_db)) -> Spot:
    existing = db.scalar(
        select(Spot).where(
            Spot.source_project_id == spot_in.source_project_id,
            Spot.source_spot_id == spot_in.source_spot_id,
        )
    )
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Spot already exists")

    spot = Spot(**spot_in.model_dump())
    db.add(spot)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Spot already exists") from exc

    db.refresh(spot)
    response.headers["Location"] = f"/api/v1/spots/{spot.id}"
    return spot
