import sys
from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy import delete, select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import SessionLocal
from app.indexer.rollups import SENSITIVE_IUCN_CATEGORIES
from app.models import (
    AnalysisJob,
    Species,
    Spot,
    SpotSource,
    SpotSpeciesDaily,
    SpotSpeciesSummary,
    SpotSummary,
)


SAMPLE_SPOTS = [
    {
        "source_project_id": "sanjay-van",
        "source_spot_id": "s1",
        "name": "Sanjay Van Spot 1",
        "description": "Sample bioacoustic monitoring spot.",
        "latitude": 28.5330,
        "longitude": 77.1760,
    },
    {
        "source_project_id": "sanjay-van",
        "source_spot_id": "s2",
        "name": "Sanjay Van Spot 2",
        "description": "Sample bioacoustic monitoring spot.",
        "latitude": 28.5352,
        "longitude": 77.1812,
    },
    {
        "source_project_id": "sanjay-van",
        "source_spot_id": "s3",
        "name": "Sanjay Van Spot 3",
        "description": "Sample bioacoustic monitoring spot.",
        "latitude": 28.5291,
        "longitude": 77.1850,
    },
    {
        "source_project_id": "sanjay-van",
        "source_spot_id": "s4",
        "name": "Sanjay Van Spot 4",
        "description": "Sample bioacoustic monitoring spot.",
        "latitude": 28.5265,
        "longitude": 77.1738,
    },
]

SAMPLE_SPECIES = [
    {
        "common_name": "Indian Peafowl",
        "scientific_name": "Pavo cristatus",
        "iucn_category": "Least Concern",
        "migration_class": "resident",
        "activity_hours": "05:00–09:00, 16:00–19:00",
        "seasonality": "Year-round",
        "network_metrics": {
            "habitat_affinity": 0.67,
            "migration": "Resident",
            "activity_hours": "05:00–09:00, 16:00–19:00",
            "seasonality": "Year-round",
            "sci": 0.42,
        },
    },
    {
        "common_name": "Red-whiskered Bulbul",
        "scientific_name": "Pycnonotus jocosus",
        "iucn_category": "Least Concern",
        "migration_class": "resident",
        "activity_hours": "05:00–10:00",
        "seasonality": "Year-round",
        "network_metrics": {
            "habitat_affinity": 0.54,
            "migration": "Resident",
            "activity_hours": "05:00–10:00",
            "seasonality": "Year-round",
            "sunrise_correlation": 0.52,
        },
    },
    {
        "common_name": "Hume's Warbler",
        "scientific_name": "Phylloscopus humei",
        "iucn_category": "Least Concern",
        "migration_class": "migratory",
        "activity_hours": "06:00–10:00",
        "seasonality": "Winter peak",
        "network_metrics": {
            "habitat_affinity": 0.71,
            "migration": "Migratory",
            "activity_hours": "06:00–10:00",
            "seasonality": "Winter peak",
            "sci": 0.98,
            "pmr": 76.4,
        },
    },
    {
        "common_name": "Common Tailorbird",
        "scientific_name": "Orthotomus sutorius",
        "iucn_category": "Least Concern",
        "migration_class": "resident",
        "activity_hours": "05:00–09:00",
        "seasonality": "Year-round",
        "network_metrics": {
            "habitat_affinity": 0.45,
            "migration": "Resident",
            "activity_hours": "05:00–09:00",
            "seasonality": "Year-round",
            "sci": 0.31,
        },
    },
    {
        "common_name": "Egyptian Vulture",
        "scientific_name": "Neophron percnopterus",
        "iucn_category": "Endangered",
        "migration_class": "partial_migrant",
        "activity_hours": "08:00–16:00",
        "seasonality": "Winter increase",
        "network_metrics": {
            "habitat_affinity": 0.36,
            "migration": "Partially migratory",
            "activity_hours": "08:00–16:00",
            "seasonality": "Winter increase",
            "sci": 0.74,
        },
    },
]

# spot, species, detections, active days, average confidence, maximum confidence, regularity
ASSOCIATIONS = [
    ("s1", "Indian Peafowl", 815, 53, 0.86, 0.96, 0.72),
    ("s1", "Red-whiskered Bulbul", 1000, 61, 0.81, 0.95, 0.68),
    ("s1", "Hume's Warbler", 1185, 37, 0.79, 0.93, 0.83),
    ("s1", "Common Tailorbird", 1370, 68, 0.84, 0.97, 0.76),
    ("s1", "Egyptian Vulture", 1555, 21, 0.78, 0.92, 0.51),
    ("s2", "Indian Peafowl", 1085, 57, 0.82, 0.94, 0.64),
    ("s2", "Red-whiskered Bulbul", 1270, 63, 0.80, 0.93, 0.62),
    ("s2", "Common Tailorbird", 1640, 71, 0.81, 0.95, 0.70),
    ("s3", "Indian Peafowl", 1355, 64, 0.84, 0.95, 0.67),
    ("s3", "Red-whiskered Bulbul", 1540, 69, 0.82, 0.94, 0.65),
    ("s3", "Hume's Warbler", 1725, 42, 0.78, 0.92, 0.79),
    ("s3", "Common Tailorbird", 1910, 76, 0.83, 0.96, 0.73),
    ("s3", "Egyptian Vulture", 2095, 28, 0.76, 0.91, 0.54),
    ("s4", "Indian Peafowl", 1625, 66, 0.81, 0.94, 0.61),
    ("s4", "Common Tailorbird", 2180, 79, 0.84, 0.97, 0.75),
]

ACOUSTIC_INDICES = {
    "s1": {"ADI": 0.58, "ACI": 0.51, "AEI": 0.64, "NDSI": 0.32},
    "s2": {"ADI": 0.62, "ACI": 0.54, "AEI": 0.61, "NDSI": 0.42},
    "s3": {"ADI": 0.66, "ACI": 0.57, "AEI": 0.59, "NDSI": 0.52},
    "s4": {"ADI": 0.70, "ACI": 0.60, "AEI": 0.56, "NDSI": 0.62},
}

DAILY_DATES = [
    date(2025, 5, 1),
    date(2025, 8, 14),
    date(2025, 12, 9),
    date(2026, 2, 18),
    date(2026, 5, 31),
]
HOURLY_WEIGHTS = [1, 1, 1, 2, 4, 7, 9, 8, 6, 5, 5, 4, 4, 4, 5, 6, 7, 8, 7, 5, 3, 2, 1, 1]


def analysis_assets(spot_id: str) -> list[dict[str, str]]:
    base = f"https://example.org/cem-integration/{spot_id}"
    return [
        {
            "analysis": "Richness time series",
            "input_file": "aggregate.csv",
            "input_url": f"{base}/input/aggregate.csv",
            "output_file": "richness-timeseries.html",
            "output_url": f"{base}/results/richness-timeseries.html",
        },
        {
            "analysis": "Acoustic-index heatmap",
            "input_file": "acoustic-indices.csv",
            "input_url": f"{base}/input/acoustic-indices.csv",
            "output_file": "acoustic-heatmap.png",
            "output_url": f"{base}/results/acoustic-heatmap.png",
        },
    ]


def main() -> None:
    created_spots = 0
    with SessionLocal() as db:
        spots_by_source: dict[str, Spot] = {}
        for spot_data in SAMPLE_SPOTS:
            spot = db.scalar(select(Spot).where(
                Spot.source_project_id == spot_data["source_project_id"],
                Spot.source_spot_id == spot_data["source_spot_id"],
            ))
            if spot is None:
                spot = Spot(**spot_data)
                db.add(spot)
                db.flush()
                created_spots += 1
            else:
                spot.name = spot_data["name"]
                spot.description = spot_data["description"]
            spots_by_source[spot_data["source_spot_id"]] = spot

            source = db.scalar(select(SpotSource).where(
                SpotSource.source_project_id == spot_data["source_project_id"],
                SpotSource.source_spot_id == spot_data["source_spot_id"],
            ))
            if source is None:
                db.add(SpotSource(
                    spot_id=spot.id,
                    source_project_id=spot_data["source_project_id"],
                    source_spot_id=spot_data["source_spot_id"],
                ))

        # Apply the indexer's privacy/conservation filter dynamically
        allowed_species_data = [
            s for s in SAMPLE_SPECIES
            if str(s.get("iucn_category") or "").strip().upper() not in SENSITIVE_IUCN_CATEGORIES
        ]

        species_by_name: dict[str, Species] = {}
        for species_data in allowed_species_data:
            species = db.scalar(select(Species).where(
                Species.scientific_name == species_data["scientific_name"]
            ))
            if species is None:
                species = Species(**species_data)
                db.add(species)
                db.flush()
            else:
                species.common_name = species_data["common_name"]
                species.iucn_category = species_data["iucn_category"]
                species.migration_class = species_data["migration_class"]
                species.activity_hours = species_data["activity_hours"]
                species.seasonality = species_data["seasonality"]
                species.network_metrics = species_data["network_metrics"]
            species_by_name[species.common_name] = species

        allowed_associations = [
            a for a in ASSOCIATIONS if a[1] in species_by_name
        ]

        associations_by_spot: dict[str, list[tuple]] = {}
        for association in allowed_associations:
            associations_by_spot.setdefault(association[0], []).append(association)

        for source_spot_id, spot in spots_by_source.items():
            local_associations = associations_by_spot.get(source_spot_id, [])
            values = {
                "recording_count": 900 + (int(source_spot_id[-1]) * 125),
                "species_richness": len(local_associations),
                "total_detections": sum(item[2] for item in local_associations),
                "active_days": 72 + (int(source_spot_id[-1]) * 8),
                "job_count": len(local_associations),
                "first_recording_date": DAILY_DATES[0],
                "last_recording_date": DAILY_DATES[-1],
                "acoustic_indices": ACOUSTIC_INDICES[source_spot_id],
                "analysis_assets": analysis_assets(source_spot_id),
            }
            summary = db.get(SpotSummary, spot.id)
            if summary is None:
                db.add(SpotSummary(spot_id=spot.id, **values))
            else:
                for key, value in values.items():
                    setattr(summary, key, value)

        for source_spot_id, common_name, count, days, avg_conf, max_conf, regularity in allowed_associations:
            spot = spots_by_source[source_spot_id]
            species = species_by_name[common_name]
            hourly = [round(count * weight / 100) for weight in HOURLY_WEIGHTS]
            metrics = {
                **(species.network_metrics or {}),
                "sunrise": "05:42",
                "sunset": "18:51",
                "peak_solar_relation": "Morning peak begins near sunrise",
                "rainfall_correlation": -0.38,
                "temperature_correlation": 0.17,
                "humidity_correlation": -0.21,
                "severe_weather_note": "Sample result: activity was lower on high-rainfall recording days.",
            }
            species_assets = [
                {
                    "analysis": "Hourly activity heatmap",
                    "input_file": "species-detections.csv",
                    "input_url": f"https://example.org/cem-integration/{source_spot_id}/input/species-detections.csv",
                    "output_file": "hourly-heatmap.png",
                    "output_url": f"https://example.org/cem-integration/{source_spot_id}/results/{species.id}-hourly-heatmap.png",
                }
            ]
            values = {
                "detection_count": count,
                "active_days": days,
                "activity_rank": 1 + sum(
                    1
                    for association in associations_by_spot[source_spot_id]
                    if association[2] > count
                ),
                "migration_class": species.migration_class,
                "average_confidence": avg_conf,
                "maximum_confidence": max_conf,
                "first_detection_date": DAILY_DATES[0],
                "last_detection_date": DAILY_DATES[-1],
                "activity_regularity": regularity,
                "hourly_counts": hourly,
                "monthly_counts": [
                    {"month": "2025-05", "count": round(count * 0.12)},
                    {"month": "2025-08", "count": round(count * 0.19)},
                    {"month": "2025-12", "count": round(count * 0.27)},
                    {"month": "2026-02", "count": round(count * 0.23)},
                    {"month": "2026-05", "count": round(count * 0.19)},
                ],
                "analysis_metrics": metrics,
                "analysis_assets": species_assets,
            }
            summary_item = db.scalar(select(SpotSpeciesSummary).where(
                SpotSpeciesSummary.spot_id == spot.id,
                SpotSpeciesSummary.species_id == species.id,
            ))
            if summary_item is None:
                db.add(SpotSpeciesSummary(
                    spot_id=spot.id,
                    species_id=species.id,
                    **values,
                ))
            else:
                for key, value in values.items():
                    setattr(summary_item, key, value)

            for index, observation_date in enumerate(DAILY_DATES, start=1):
                daily_count = max(1, round(count * index / 30))
                daily = db.scalar(select(SpotSpeciesDaily).where(
                    SpotSpeciesDaily.spot_id == spot.id,
                    SpotSpeciesDaily.species_id == species.id,
                    SpotSpeciesDaily.observation_date == observation_date,
                ))
                if daily is None:
                    db.add(SpotSpeciesDaily(
                        spot_id=spot.id,
                        species_id=species.id,
                        observation_date=observation_date,
                        detection_count=daily_count,
                    ))
                else:
                    daily.detection_count = daily_count

            job_id = f"integration-{source_spot_id}-{species.id}"
            job_values = {
                "spot_id": spot.id,
                "species_id": species.id,
                "analysis_type": "species-activity",
                "status": "completed",
                "input_url": f"https://example.org/cem-integration/{job_id}/species-detections.csv",
                "output_url": f"https://example.org/cem-integration/{job_id}/species-activity.html",
                "job_metadata": {
                    "input_file": "species-detections.csv",
                    "output_file": "species-activity.html",
                },
                "started_at": datetime(2026, 6, 1, 8, 0, tzinfo=timezone.utc),
                "completed_at": datetime(2026, 6, 1, 8, 12, tzinfo=timezone.utc),
            }
            job = db.get(AnalysisJob, job_id)
            if job is None:
                db.add(AnalysisJob(job_id=job_id, **job_values))
            else:
                for key, value in job_values.items():
                    setattr(job, key, value)

        # Purge stale/sensitive species (e.g. Egyptian Vulture) from sample spots
        allowed_species_ids = {s.id for s in species_by_name.values()}
        for spot in spots_by_source.values():
            db.execute(
                delete(SpotSpeciesSummary).where(
                    SpotSpeciesSummary.spot_id == spot.id,
                    SpotSpeciesSummary.species_id.not_in(allowed_species_ids),
                )
            )
            db.execute(
                delete(SpotSpeciesDaily).where(
                    SpotSpeciesDaily.spot_id == spot.id,
                    SpotSpeciesDaily.species_id.not_in(allowed_species_ids),
                )
            )

        db.commit()

    print(
        f"Seed complete: {created_spots} new spot(s); "
        f"{len(SAMPLE_SPOTS)} sample spots and {len(SAMPLE_SPECIES)} species are ready."
    )


if __name__ == "__main__":
    main()
