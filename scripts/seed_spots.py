import sys
from pathlib import Path

from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import SessionLocal, init_db
from app.models import Spot


SAMPLE_SPOTS = [
    {
        "source_project_id": "sanjay-van",
        "source_spot_id": "s1",
        "name": "Sanjay Van Site 1",
        "description": "Sample monitoring location near Sanjay Van.",
        "latitude": 28.533,
        "longitude": 77.176,
    },
    {
        "source_project_id": "yamuna-biodiversity-park",
        "source_spot_id": "wetland-1",
        "name": "Yamuna Biodiversity Park Wetland",
        "description": "Sample wetland monitoring point in north Delhi.",
        "latitude": 28.7327,
        "longitude": 77.2011,
    },
    {
        "source_project_id": "lodhi-garden",
        "source_spot_id": "lg-central",
        "name": "Lodhi Garden Central Trail",
        "description": "Sample public park monitoring point in central Delhi.",
        "latitude": 28.5933,
        "longitude": 77.2209,
    },
]


def main() -> None:
    init_db()
    created = 0
    with SessionLocal() as db:
        for spot_data in SAMPLE_SPOTS:
            exists = db.scalar(
                select(Spot).where(
                    Spot.source_project_id == spot_data["source_project_id"],
                    Spot.source_spot_id == spot_data["source_spot_id"],
                )
            )
            if exists:
                continue
            db.add(Spot(**spot_data))
            created += 1
        db.commit()

    print(f"Seeded {created} sample spot(s).")


if __name__ == "__main__":
    main()
