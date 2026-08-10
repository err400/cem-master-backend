import sys
from datetime import date
from pathlib import Path

from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import SessionLocal, init_db
from app.models import Species, Spot, SpotSource, SpotSpeciesSummary, SpotSummary


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

SAMPLE_SPECIES = [
    {
        "common_name": "Indian Peafowl",
        "scientific_name": "Pavo cristatus",
        "iucn_category": "Least Concern",
        "network_metrics": {"habitat_affinity": 0.67, "migration_class": "Resident", "sci": 0.42},
    },
    {
        "common_name": "Red-whiskered Bulbul",
        "scientific_name": "Pycnonotus jocosus",
        "iucn_category": "Least Concern",
        "network_metrics": {"habitat_affinity": 0.54, "migration_class": "Resident", "sunrise_correlation": 0.52},
    },
    {
        "common_name": "Hume's Warbler",
        "scientific_name": "Phylloscopus humei",
        "iucn_category": "Least Concern",
        "network_metrics": {"habitat_affinity": 0.71, "migration_class": "Migratory", "sci": 0.98, "pmr": 76.4},
    },
    {
        "common_name": "Common Tailorbird",
        "scientific_name": "Orthotomus sutorius",
        "iucn_category": "Least Concern",
        "network_metrics": {"habitat_affinity": 0.45, "migration_class": "Resident", "sci": 0.31},
    },
]

SPOT_SUMMARIES = {
    "sanjay-van": {
        "species_richness": 91,
        "total_detections": 18420,
        "recording_days": 111,
        "acoustic_indices": {"ADI": 0.78, "ACI": 0.63, "AEI": 0.48, "NDSI": 0.72},
    },
    "yamuna-biodiversity-park": {
        "species_richness": 68,
        "total_detections": 12180,
        "recording_days": 94,
        "acoustic_indices": {"ADI": 0.69, "ACI": 0.58, "AEI": 0.55, "NDSI": 0.61},
    },
    "lodhi-garden": {
        "species_richness": 43,
        "total_detections": 7350,
        "recording_days": 76,
        "acoustic_indices": {"ADI": 0.54, "ACI": 0.57, "AEI": 0.71, "NDSI": 0.18},
    },
}


def main() -> None:
    init_db()
    created = 0
    with SessionLocal() as db:
        spots_by_project = {}
        for spot_data in SAMPLE_SPOTS:
            spot = db.scalar(
                select(Spot).where(
                    Spot.source_project_id == spot_data["source_project_id"],
                    Spot.source_spot_id == spot_data["source_spot_id"],
                )
            )
            if spot is None:
                spot = Spot(**spot_data)
                db.add(spot)
                db.flush()
                created += 1
            spots_by_project[spot_data["source_project_id"]] = spot
            source = db.scalar(select(SpotSource).where(SpotSource.spot_id == spot.id))
            if source is None:
                db.add(SpotSource(
                    spot_id=spot.id,
                    source_project_id=spot_data["source_project_id"],
                    source_spot_id=spot_data["source_spot_id"],
                ))

        species_by_name = {}
        for species_data in SAMPLE_SPECIES:
            species = db.scalar(select(Species).where(
                Species.scientific_name == species_data["scientific_name"]
            ))
            if species is None:
                species = Species(**species_data)
                db.add(species)
                db.flush()
            species_by_name[species.common_name] = species

        for project_id, values in SPOT_SUMMARIES.items():
            spot = spots_by_project[project_id]
            if db.get(SpotSummary, spot.id) is None:
                db.add(SpotSummary(
                    spot_id=spot.id,
                    first_recording_date=date(2025, 5, 1),
                    last_recording_date=date(2026, 5, 31),
                    **values,
                ))

        associations = [
            ("sanjay-van", "Indian Peafowl", 2860, 103, 0.86, 0.96, 0.72),
            ("sanjay-van", "Red-whiskered Bulbul", 2134, 98, 0.81, 0.95, 0.68),
            ("sanjay-van", "Hume's Warbler", 524, 31, 0.79, 0.93, 0.83),
            ("sanjay-van", "Common Tailorbird", 3910, 109, 0.84, 0.97, 0.76),
            ("yamuna-biodiversity-park", "Indian Peafowl", 1180, 72, 0.82, 0.94, 0.64),
            ("yamuna-biodiversity-park", "Red-whiskered Bulbul", 1620, 81, 0.80, 0.93, 0.62),
            ("yamuna-biodiversity-park", "Hume's Warbler", 310, 24, 0.77, 0.91, 0.79),
            ("lodhi-garden", "Indian Peafowl", 640, 52, 0.78, 0.91, 0.55),
            ("lodhi-garden", "Red-whiskered Bulbul", 990, 65, 0.83, 0.96, 0.66),
            ("lodhi-garden", "Common Tailorbird", 1540, 70, 0.81, 0.94, 0.71),
        ]
        for project_id, common_name, count, days, avg_conf, max_conf, regularity in associations:
            spot = spots_by_project[project_id]
            species = species_by_name[common_name]
            exists = db.scalar(select(SpotSpeciesSummary).where(
                SpotSpeciesSummary.spot_id == spot.id,
                SpotSpeciesSummary.species_id == species.id,
            ))
            if exists is not None:
                continue
            hourly = [round(count * weight / 100) for weight in [1, 1, 1, 2, 4, 7, 9, 8, 6, 5, 5, 4, 4, 4, 5, 6, 7, 8, 7, 5, 3, 2, 1, 1]]
            db.add(SpotSpeciesSummary(
                spot_id=spot.id,
                species_id=species.id,
                detection_count=count,
                recording_days=days,
                average_confidence=avg_conf,
                maximum_confidence=max_conf,
                first_detection_date=date(2025, 5, 1),
                last_detection_date=date(2026, 5, 31),
                activity_regularity=regularity,
                hourly_counts=hourly,
                analysis_metrics=species.network_metrics,
            ))
        db.commit()

    print(f"Seeded {created} new spot(s) plus dashboard sample data.")


if __name__ == "__main__":
    main()
